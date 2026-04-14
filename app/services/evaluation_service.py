"""Оценка ответа: покрытие смысловых элементов или семантическая близость 0–1."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings

logger = logging.getLogger(__name__)


def normalized_evaluation_mode() -> str:
    """Нормализует режим оценки, сохраняя обратную совместимость старых значений .env."""
    mode = (settings.mvp_evaluation_mode or "coverage").strip().lower()
    if mode in {"coverage", "rubric"}:
        return "coverage"
    return "similarity"


def use_coverage_scoring() -> bool:
    """Покрытие смысловых элементов включается режимом и наличием ключа OpenAI."""
    return normalized_evaluation_mode() == "coverage" and bool((settings.openai_api_key or "").strip())


def cosine_similarity_vec(a: list[float], b: list[float]) -> float:
    """Косинусная близость векторов; результат в [0, 1] (для неотрицательных смысловых эмбеддингов)."""
    if len(a) != len(b):
        raise ValueError("Размерность эмбеддингов не совпадает.")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    cos = dot / (na * nb)
    return max(0.0, min(1.0, cos))


class CoverageElementJson(BaseModel):
    element: str = Field(description="Один смысловой элемент эталонного ответа")
    coverage: str = Field(description="covered | partial | missing")
    rationale: str = Field(default="", description="Краткое пояснение статуса элемента")

    @field_validator("element", "coverage", "rationale", mode="before")
    @classmethod
    def _coerce_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("coverage")
    @classmethod
    def _validate_coverage(cls, v: str) -> str:
        low = v.strip().lower()
        if low in {"covered", "full", "1", "1.0"}:
            return "covered"
        if low in {"partial", "partially_covered", "0.5", "half"}:
            return "partial"
        return "missing"


class CoverageJson(BaseModel):
    elements: list[CoverageElementJson] = Field(default_factory=list)
    general_comment: str = ""

    @field_validator("general_comment", mode="before")
    @classmethod
    def _coerce_comment(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()


@dataclass(frozen=True)
class CoverageElementScore:
    element: str
    coverage: str
    rationale: str = ""

    @property
    def weight(self) -> float:
        if self.coverage == "covered":
            return 1.0
        if self.coverage == "partial":
            return 0.5
        return 0.0


@dataclass(frozen=True)
class CoverageScores:
    score: int
    total_elements: int
    covered_elements: list[str]
    partial_elements: list[str]
    missing_elements: list[str]
    elements: list[CoverageElementScore]
    general_comment: str = ""


COVERAGE_SYSTEM = """Ты — эксперт по проверке экзаменационных ответов по модели покрытия смысловых элементов.

Задача:
1. Разбей эталонный ответ на 3-8 самостоятельных смысловых элементов.
2. Для каждого элемента определи статус относительно ответа студента:
   - covered: смысл раскрыт достаточно полно;
   - partial: смысл затронут частично или слишком расплывчато;
   - missing: смысл не раскрыт.
3. Для каждого элемента дай очень короткое пояснение на русском языке.
4. Верни ТОЛЬКО JSON-объект:
{
  "elements": [
    {"element":"...", "coverage":"covered|partial|missing", "rationale":"..."}
  ],
  "general_comment":"краткий общий вывод"
}

Правила:
- Не оценивай стиль, орфографию и воду отдельно.
- Если студент сказал то же другими словами, это covered.
- Если в ответе есть нерелевантные детали, они не повышают статус элемента.
- Не придумывай элементы, которых нет в эталоне."""


def _coverage_json_to_scores(data: CoverageJson) -> CoverageScores:
    elements = [
        CoverageElementScore(
            element=item.element,
            coverage=item.coverage,
            rationale=item.rationale[:400],
        )
        for item in data.elements
        if item.element
    ]
    if not elements:
        return CoverageScores(
            score=50,
            total_elements=0,
            covered_elements=[],
            partial_elements=[],
            missing_elements=[],
            elements=[],
            general_comment=(data.general_comment or "")[:1200],
        )
    total = len(elements)
    weighted = sum(item.weight for item in elements)
    score = int(round(50 + (weighted / total) * 50))
    if any(item.coverage in {"covered", "partial"} for item in elements):
        score = max(score, 65)
    covered = [item.element for item in elements if item.coverage == "covered"]
    partial = [item.element for item in elements if item.coverage == "partial"]
    missing = [item.element for item in elements if item.coverage == "missing"]
    return CoverageScores(
        score=score,
        total_elements=total,
        covered_elements=covered,
        partial_elements=partial,
        missing_elements=missing,
        elements=elements,
        general_comment=(data.general_comment or "")[:1200],
    )


async def evaluate_similarity(student_answer: str, reference_answer: str) -> float:
    """
    Семантическая близость в [0, 1]: косинус между эмбеддингами ответа и эталона.
    Нужен OPENAI_API_KEY (модель — MVP_EMBEDDING_MODEL).
    """
    if not student_answer or not reference_answer:
        raise ValueError("Both student_answer and reference_answer must be non-empty.")
    if not (settings.openai_api_key or "").strip():
        raise ValueError("OPENAI_API_KEY required for embedding-based similarity.")

    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise RuntimeError("openai package required for embedding similarity") from e

    ref_t = reference_answer.strip()
    st_t = student_answer.strip()
    if not ref_t or not st_t:
        raise ValueError("Both student_answer and reference_answer must be non-empty.")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    emb_model = (settings.mvp_embedding_model or "text-embedding-3-small").strip() or "text-embedding-3-small"

    resp = await client.embeddings.create(model=emb_model, input=[ref_t, st_t])
    items = resp.data
    if len(items) < 2:
        raise ValueError("Embeddings API returned fewer than 2 vectors")
    e_ref = items[0].embedding
    e_st = items[1].embedding
    score = round(cosine_similarity_vec(list(e_ref), list(e_st)), 4)
    logger.debug("evaluate_similarity (embeddings): score=%s model=%s", score, emb_model)
    return score


async def evaluate_coverage(student_answer: str, reference_answer: str) -> CoverageScores:
    """Оценка по покрытию смысловых элементов через chat completion."""
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY required for coverage scoring.")

    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise RuntimeError("openai package required for coverage scoring") from e

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    model = (settings.mvp_evaluation_model or "gpt-4o-mini").strip() or "gpt-4o-mini"

    user_msg = (
        "Эталонный ответ (для сравнения):\n"
        f"{reference_answer.strip()}\n\n"
        "Ответ экзаменуемого:\n"
        f"{student_answer.strip()}"
    )

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": COVERAGE_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM returned non-object JSON")
    parsed = CoverageJson.model_validate(data)
    return _coverage_json_to_scores(parsed)


async def evaluate(student_answer: str, reference_answer: str) -> float:
    return await evaluate_similarity(student_answer, reference_answer)
