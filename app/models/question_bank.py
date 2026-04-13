from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionRecord:
    """One question from the bank: key, wording, and ideal answer."""

    question_key: str
    question_text: str
    reference_answer: str
