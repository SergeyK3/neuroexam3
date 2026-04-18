"""Валидация Telegram Update pydantic-схемой."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.models.telegram import TgUpdate
from main import app


def test_tgupdate_parses_from_alias():
    raw = {
        "update_id": 1,
        "message": {
            "message_id": 7,
            "date": 0,
            "from": {"id": 42, "is_bot": False, "first_name": "U"},
            "chat": {"id": 42, "type": "private"},
            "text": "/start",
        },
    }
    u = TgUpdate.from_raw(raw)
    assert u.update_id == 1
    msg = u.primary_message()
    assert msg is not None
    assert msg.message_id == 7
    assert msg.from_user is not None
    assert msg.from_user.id == 42
    assert msg.text == "/start"


def test_tgupdate_accepts_business_message_and_ignores_unknown_fields():
    raw = {
        "update_id": 2,
        "business_message": {
            "message_id": 8,
            "date": 0,
            "chat": {"id": 1, "type": "private", "some_extra": "x"},
            "text": "hi",
            "absolutely_new_future_field": {"a": 1},
        },
        "absolutely_new_top_level_field": 123,
    }
    u = TgUpdate.from_raw(raw)
    assert u.primary_message() is not None
    assert u.primary_message().text == "hi"


def test_tgupdate_requires_update_id():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        TgUpdate.from_raw({"message": {"message_id": 1, "date": 0}})


@pytest.mark.asyncio
async def test_webhook_returns_400_on_invalid_schema(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/telegram/webhook", json={"update_id": "not-int"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_webhook_rejects_oversized_payload(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    monkeypatch.setattr(settings, "max_update_bytes", 1024, raising=False)
    big = "x" * 5000
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/telegram/webhook",
            content=f'{{"update_id": 1, "pad": "{big}"}}'.encode(),
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 413
