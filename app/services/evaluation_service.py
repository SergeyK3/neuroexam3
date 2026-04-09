"""Оценка близости ответа студента к эталону (MVP — без LLM)."""

import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def _normalize(s: str) -> str:
    return " ".join(s.strip().lower().split())


async def evaluate(student_answer: str, reference_answer: str) -> float:
    """Сходство в диапазоне [0, 1]: 1.0 — совпадение после нормализации, иначе ratio по символам."""
    if not student_answer or not reference_answer:
        raise ValueError("Both student_answer and reference_answer must be non-empty.")

    a, b = _normalize(student_answer), _normalize(reference_answer)
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    score = round(ratio, 4)
    logger.debug("evaluate: score=%s (student_len=%s ref_len=%s)", score, len(a), len(b))
    return score
