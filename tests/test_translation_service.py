"""Перевод полного казахского/смешанного транскрипта для экспорта."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.services import translation_service


@pytest.mark.asyncio
async def test_translate_to_russian_sends_full_mixed_transcript(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "mvp_evaluation_model", "gpt-4o-mini", raising=False)

    source = ("Қазақша жауап. Русский фрагмент. " * 300) + "Соңғы бөлік."
    message = MagicMock()
    message.content = "Полный связный перевод на русский."
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **_kwargs: client)

    translated = await translation_service.translate_to_russian(source)

    assert translated == "Полный связный перевод на русский."
    call = client.chat.completions.create.await_args.kwargs
    assert call["model"] == "gpt-4o-mini"
    assert source in call["messages"][1]["content"]
    assert "Соңғы бөлік." in call["messages"][1]["content"]


@pytest.mark.asyncio
async def test_translate_to_russian_rejects_empty_model_response(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)
    message = MagicMock()
    message.content = ""
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **_kwargs: client)

    with pytest.raises(RuntimeError, match="пустой перевод"):
        await translation_service.translate_to_russian("Қазақша жауап")
