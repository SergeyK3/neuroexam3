"""Evaluation service: compares a student answer with a reference answer."""


def evaluate_answer(student_answer: str, reference_answer: str) -> float:
    """Return a similarity score between 0.0 and 1.0.

    This is a simple word-overlap implementation used as a placeholder until
    a proper NLP/embedding-based model is integrated.
    """
    if not student_answer or not reference_answer:
        return 0.0

    student_words = set(student_answer.lower().split())
    reference_words = set(reference_answer.lower().split())

    if not reference_words:
        return 0.0

    intersection = student_words & reference_words
    score = len(intersection) / len(reference_words)
    return round(min(score, 1.0), 4)
