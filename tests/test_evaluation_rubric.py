"""Покрытие смысловых элементов, косинус эмбеддингов, мок API."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.services.evaluation_service import (
    CoverageJson,
    _coverage_json_to_scores,
    cosine_similarity_vec,
    evaluate_coverage,
    evaluate_similarity,
)


def test_coverage_json_to_scores_counts_weights():
    parsed = CoverageJson.model_validate(
        {
            "elements": [
                {"element": "A", "coverage": "covered"},
                {"element": "B", "coverage": "partial"},
                {"element": "C", "coverage": "missing"},
            ],
            "general_comment": "Краткий вывод",
        }
    )
    s = _coverage_json_to_scores(parsed)
    assert s.score == 75
    assert s.covered_elements == ["A"]
    assert s.partial_elements == ["B"]
    assert s.missing_elements == ["C"]
    assert "вывод" in s.general_comment.lower()


def test_coverage_json_to_scores_partial_answer_not_below_65():
    parsed = CoverageJson.model_validate(
        {
            "elements": [
                {"element": "A", "coverage": "partial"},
                {"element": "B", "coverage": "missing"},
                {"element": "C", "coverage": "missing"},
            ],
        }
    )
    s = _coverage_json_to_scores(parsed)
    assert s.score == 65


def test_cosine_same_and_orthogonal():
    assert cosine_similarity_vec([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0
    assert cosine_similarity_vec([1.0, 0.0], [0.0, 1.0]) == 0.0


@pytest.mark.asyncio
async def test_evaluate_similarity_embeddings_mocked(monkeypatch):
    """Без реального вызова OpenAI: два одинаковых вектора → 1.0."""
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)

    vec = [0.6, 0.8, 0.0]
    emb = MagicMock()
    emb.embedding = vec
    resp = MagicMock()
    resp.data = [emb, emb]
    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=resp)

    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: mock_client)

    s = await evaluate_similarity("ответ студента", "эталон другой текст")
    assert s == 1.0


@pytest.mark.asyncio
async def test_evaluate_similarity_requires_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        await evaluate_similarity("a", "b")


@pytest.mark.asyncio
async def test_evaluate_coverage_returns_elements(monkeypatch):
    """Без реального OpenAI: проверяем разбор JSON по смысловым элементам."""
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "mvp_evaluation_mode", "coverage", raising=False)

    payload = {
        "elements": [
            {"element": "ведение данных пациентов", "coverage": "covered", "rationale": "Элемент назван явно"},
            {"element": "поддержка принятия решений", "coverage": "partial", "rationale": "Смысл затронут кратко"},
            {"element": "безопасность данных", "coverage": "missing", "rationale": "Элемент не упомянут"},
        ],
        "general_comment": "Ответ знает основу, но часть элементов пропущена.",
    }
    msg = MagicMock()
    msg.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: mock_client)

    r = await evaluate_coverage("ответ студента", "эталонный текст эталон")
    assert r.score == 75
    assert "ведение данных" in r.covered_elements[0]
    assert "поддержка" in r.partial_elements[0]
    assert "безопасность" in r.missing_elements[0]
