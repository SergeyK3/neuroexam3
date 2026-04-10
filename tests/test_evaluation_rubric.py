"""Парсинг рубрики, косинус эмбеддингов, мок API."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.services.evaluation_service import (
    RubricJson,
    cosine_similarity_vec,
    evaluate_rubric,
    evaluate_similarity,
)


def test_rubric_json_clamps_and_total():
    r = RubricJson.model_validate(
        {
            "content_score": 70,
            "accuracy_score": 25,
            "structure_score": 15,
            "conciseness_score": 15,
            "total": 999,
        }
    )
    assert r.content_score == 60
    assert r.accuracy_score == 20
    assert r.structure_score == 10
    assert r.conciseness_score == 10
    assert r.total == 100
    assert r.content_rationale == ""


def test_rubric_json_rationales_optional():
    r = RubricJson.model_validate(
        {
            "content_score": 40,
            "accuracy_score": 15,
            "structure_score": 7,
            "conciseness_score": 5,
            "content_rationale": "  Не хватает пунктов А и Б. ",
            "accuracy_rationale": "Термин X употреблён неточно.",
        }
    )
    assert r.content_rationale.startswith("Не хватает")
    assert "Термин X" in r.accuracy_rationale
    assert r.structure_rationale == ""


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
async def test_evaluate_rubric_returns_rationales(monkeypatch):
    """Без реального OpenAI: проверяем разбор JSON с обоснованиями."""
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)

    payload = {
        "content_score": 40,
        "accuracy_score": 15,
        "structure_score": 7,
        "conciseness_score": 5,
        "total": 67,
        "content_rationale": "Раскрыта общая идея, не названы типичные KPI учреждения.",
        "accuracy_rationale": "Без грубых ошибок; спорная формулировка в конце.",
        "structure_rationale": "Есть повторы одной мысли.",
        "conciseness_rationale": "Много общих слов без новой информации.",
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

    r = await evaluate_rubric("ответ студента", "эталонный текст эталон")
    assert r.total == 67
    assert r.content_score == 40
    assert "KPI" in r.content_rationale
    assert "повторы" in r.structure_rationale.lower()
