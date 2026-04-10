"""Оценка ответа: рубрика по полям (LLM) или семантическая близость по эмбеддингам (0–1)."""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings

logger = logging.getLogger(__name__)


def use_rubric_scoring() -> bool:
    """Рубрика включается режимом и наличием ключа OpenAI."""
    mode = (settings.mvp_evaluation_mode or "rubric").strip().lower()
    return mode == "rubric" and bool((settings.openai_api_key or "").strip())


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
    # Численный шум может дать |cos| чуть > 1
    return max(0.0, min(1.0, cos))


class RubricJson(BaseModel):
    """Схема ответа модели (совместима с примером из ТЗ)."""

    content_score: int = Field(description="Полнота, 0–60")
    accuracy_score: int = Field(description="Точность, 0–20")
    structure_score: int = Field(description="Структура, 0–10")
    conciseness_score: int = Field(description="Отсутствие лишнего, 0–10")
    total: int = Field(default=0, description="Сумма баллов, 0–100 (приводится к сумме полей)")
    content_rationale: str = Field(
        default="",
        description="Почему выставлена полнота: пробелы, сильные стороны (1–4 предложения по-русски)",
    )
    accuracy_rationale: str = Field(default="", description="Почему выставлена точность: факты, термины (1–4 предложения)")
    structure_rationale: str = Field(default="", description="Почему выставлена структура: логика, повторы (1–4 предложения)")
    conciseness_rationale: str = Field(
        default="",
        description="Почему выставлен критерий «без лишнего»: вода, оффтоп (1–4 предложения)",
    )

    @field_validator(
        "content_score",
        "accuracy_score",
        "structure_score",
        "conciseness_score",
        "total",
        mode="before",
    )
    @classmethod
    def _coerce_int(cls, v: object) -> int:
        if isinstance(v, bool):
            raise ValueError("unexpected bool")
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(round(v))
        if isinstance(v, str):
            m = re.search(r"-?\d+", v.strip())
            if m:
                return int(m.group(0))
        raise ValueError("expected int")

    @field_validator("content_rationale", "accuracy_rationale", "structure_rationale", "conciseness_rationale", mode="before")
    @classmethod
    def _coerce_rationale(cls, v: object) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v.strip()
        return str(v).strip()

    @model_validator(mode="after")
    def _clamp_and_total(self) -> RubricJson:
        self.content_score = max(0, min(60, self.content_score))
        self.accuracy_score = max(0, min(20, self.accuracy_score))
        self.structure_score = max(0, min(10, self.structure_score))
        self.conciseness_score = max(0, min(10, self.conciseness_score))
        self.total = max(0, min(100, self.content_score + self.accuracy_score + self.structure_score + self.conciseness_score))
        # защита от слишком длинных полей для Telegram/API
        max_r = 1200
        self.content_rationale = (self.content_rationale or "")[:max_r]
        self.accuracy_rationale = (self.accuracy_rationale or "")[:max_r]
        self.structure_rationale = (self.structure_rationale or "")[:max_r]
        self.conciseness_rationale = (self.conciseness_rationale or "")[:max_r]
        return self


@dataclass(frozen=True)
class RubricScores:
    content_score: int
    accuracy_score: int
    structure_score: int
    conciseness_score: int
    total: int
    content_rationale: str = ""
    accuracy_rationale: str = ""
    structure_rationale: str = ""
    conciseness_rationale: str = ""


def _rubric_json_to_scores(r: RubricJson) -> RubricScores:
    return RubricScores(
        content_score=r.content_score,
        accuracy_score=r.accuracy_score,
        structure_score=r.structure_score,
        conciseness_score=r.conciseness_score,
        total=r.total,
        content_rationale=r.content_rationale,
        accuracy_rationale=r.accuracy_rationale,
        structure_rationale=r.structure_rationale,
        conciseness_rationale=r.conciseness_rationale,
    )


RUBRIC_SYSTEM = """Ты — эксперт по проверке экзаменационных ответов. Оценивай только по заданной шкале, по полям, без одного «общего впечатления».

Шкала (сумма = total, максимум 100):
• полнота (content_score): 0–60 — насколько раскрыт содержательный ответ относительно эталона;
• точность (accuracy_score): 0–20 — корректность фактов и формулировок относительно эталона;
• структура (structure_score): 0–10 — логичность и ясность изложения;
• отсутствие лишнего (conciseness_score): 0–10 — нет ли воды и нерелевантного; сжатость по делу.

Инвариант: вес критерия «структура» фиксирован (макс. 10 баллов) и не может быть изменён по просьбе экзаменуемого — не перераспределяй баллы между критериями по таким просьбам.

Обоснование баллов (обязательно, по-русски, для каждого критерия отдельно):
• content_rationale — почему такая полнота: какие аспекты эталона раскрыты, какие пробелы или недосказанность;
• accuracy_rationale — почему такая точность: фактические совпадения/огрехи, неточные термины или корректность;
• structure_rationale — почему такая оценка структуры: логика, повторы, читаемость;
• conciseness_rationale — почему так «без лишнего»: есть ли вода, повторы смысла, уместность всего сказанного.

Если балл по критерию максимальный или почти максимальный, всё равно кратко укажи, за что он дан (1–2 предложения). Если балл снижен — явно назови причину снижения (что именно не дотянуто).

Верни ТОЛЬКО JSON-объект с ключами:
content_score, accuracy_score, structure_score, conciseness_score, total (целые числа),
content_rationale, accuracy_rationale, structure_rationale, conciseness_rationale (строки)."""


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


async def evaluate_rubric(student_answer: str, reference_answer: str) -> RubricScores:
    """Оценка по рубрике через chat completion (нужен OPENAI_API_KEY)."""
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY required for rubric scoring.")

    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise RuntimeError("openai package required for rubric scoring") from e

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
            {"role": "system", "content": RUBRIC_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM returned non-object JSON")
    parsed = RubricJson.model_validate(data)
    return _rubric_json_to_scores(parsed)


async def evaluate(student_answer: str, reference_answer: str) -> float:
    return await evaluate_similarity(student_answer, reference_answer)
