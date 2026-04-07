"""Answer evaluation service.

Placeholder implementation that computes a similarity score between a
student's answer and a reference answer.

Replace the body of ``evaluate`` with a real NLP / embedding-based
approach (e.g. cosine similarity of sentence embeddings, an LLM judge,
difflib SequenceMatcher, etc.).
"""

import logging

logger = logging.getLogger(__name__)


async def evaluate(student_answer: str, reference_answer: str) -> float:
    """Compute a similarity score between a student answer and a reference.

    Args:
        student_answer: The text produced by the speech recognition step.
        reference_answer: The expected correct answer.

    Returns:
        A float in the range [0.0, 1.0] where 1.0 means a perfect match.

    Raises:
        ValueError: If either argument is an empty string.
    """
    if not student_answer or not reference_answer:
        raise ValueError("Both student_answer and reference_answer must be non-empty.")

    # TODO: replace with a real similarity / evaluation implementation.
    logger.warning(
        "evaluate() is a placeholder — student=%r, reference=%r",
        student_answer[:80],
        reference_answer[:80],
    )

    # Trivial baseline: exact-match returns 1.0, anything else returns 0.0.
    score = 1.0 if student_answer.strip() == reference_answer.strip() else 0.0
    return score
