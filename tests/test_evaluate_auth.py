"""Авторизация /exam/* эндпоинтов."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from main import app


@pytest.mark.asyncio
async def test_evaluate_text_without_bearer_returns_503_when_token_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "api_bearer_token", "", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/exam/evaluate-text",
            data={"student_answer": "x", "reference": "y"},
        )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_evaluate_text_rejects_missing_authorization(monkeypatch):
    monkeypatch.setattr(settings, "api_bearer_token", "secret-abc", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/exam/evaluate-text",
            data={"student_answer": "x", "reference": "y"},
        )
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").lower().startswith("bearer")


@pytest.mark.asyncio
async def test_evaluate_text_rejects_wrong_bearer(monkeypatch):
    monkeypatch.setattr(settings, "api_bearer_token", "secret-abc", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/exam/evaluate-text",
            data={"student_answer": "x", "reference": "y"},
            headers={"Authorization": "Bearer wrong"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_evaluate_text_rejects_oversize_text(monkeypatch):
    monkeypatch.setattr(settings, "api_bearer_token", "secret-abc", raising=False)
    monkeypatch.setattr(settings, "max_text_chars", 100, raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/exam/evaluate-text",
            data={"student_answer": "x" * 200, "reference": "y"},
            headers={"Authorization": "Bearer secret-abc"},
        )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_evaluate_voice_rejects_oversize_audio(monkeypatch):
    monkeypatch.setattr(settings, "api_bearer_token", "secret-abc", raising=False)
    monkeypatch.setattr(settings, "max_audio_bytes", 512, raising=False)
    big_audio = b"\0" * 2048
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/exam/evaluate-voice",
            files={"audio": ("big.wav", big_audio, "audio/wav")},
            data={"reference": "ref"},
            headers={"Authorization": "Bearer secret-abc"},
        )
    assert r.status_code in (413,)
