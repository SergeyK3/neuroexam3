"""Semantic similarity module (placeholder).

Replace the body of `compute_similarity` with an embedding-based or
LLM-based implementation when ready.
"""


def compute_similarity(text_a: str, text_b: str) -> float:
    """Return a semantic similarity score between 0.0 and 1.0.

    Currently delegates to a simple word-overlap heuristic.
    Integrate sentence-transformers, OpenAI embeddings, etc. here.
    """
    # TODO: integrate a real embedding / LLM similarity model
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))
