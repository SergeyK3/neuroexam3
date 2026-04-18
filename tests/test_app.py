"""Basic smoke tests for the NeuroExam3 FastAPI application."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


_TEST_BEARER = "test-bearer-token-value"
_AUTH_HEADERS = {"Authorization": f"Bearer {_TEST_BEARER}"}


@pytest.mark.asyncio
async def test_evaluate_text_exact_match(monkeypatch):
    monkeypatch.setattr(settings, "mvp_evaluation_mode", "similarity", raising=False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "api_bearer_token", _TEST_BEARER, raising=False)

    async def fake_sim(sa: str, ref: str) -> float:
        return 1.0 if sa.strip() == ref.strip() else 0.0

    monkeypatch.setattr("app.services.evaluation_service.evaluate_similarity", fake_sim)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/exam/evaluate-text",
            data={
                "student_answer": "The mitochondria is the powerhouse of the cell",
                "reference": "The mitochondria is the powerhouse of the cell",
            },
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "similarity"
    assert body["score"] == 1.0


@pytest.mark.asyncio
async def test_evaluate_text_no_match(monkeypatch):
    monkeypatch.setattr(settings, "mvp_evaluation_mode", "similarity", raising=False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "api_bearer_token", _TEST_BEARER, raising=False)

    async def fake_sim(_sa: str, _ref: str) -> float:
        return 0.2

    monkeypatch.setattr("app.services.evaluation_service.evaluate_similarity", fake_sim)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/exam/evaluate-text",
            data={
                "student_answer": "Wrong answer",
                "reference": "Correct answer",
            },
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "similarity"
    assert body["score"] < 0.9


@pytest.mark.asyncio
async def test_evaluate_voice_returns_transcript(monkeypatch):
    """Smoke test: the evaluate-voice endpoint returns expected keys."""
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "mvp_evaluation_mode", "similarity", raising=False)
    monkeypatch.setattr(settings, "api_bearer_token", _TEST_BEARER, raising=False)

    async def fake_sim(_sa: str, _ref: str) -> float:
        return 0.35

    monkeypatch.setattr("app.services.evaluation_service.evaluate_similarity", fake_sim)

    async def fake_transcribe(_audio: bytes, *, language: str = "ru") -> str:
        return "stub transcript"

    monkeypatch.setattr("app.services.speech_service.transcribe", fake_transcribe)
    dummy_audio = b"RIFF\x00\x00\x00\x00WAVEfmt "  # minimal fake WAV header
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/exam/evaluate-voice",
            files={"audio": ("test.wav", dummy_audio, "audio/wav")},
            data={"reference": "some reference answer"},
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 200
    body = response.json()
    assert "transcript" in body
    assert body.get("mode") == "similarity"
    assert "score" in body
    assert 0.0 <= body["score"] <= 1.0
    assert body["score"] < 1.0


@pytest.mark.asyncio
async def test_telegram_webhook_accepts_minimal_update(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    payload = {"update_id": 1, "message": {"message_id": 1, "date": 0}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_telegram_webhook_requires_secret_when_configured(monkeypatch):
    secret = "test-webhook-secret-32chars!!"
    monkeypatch.setattr(settings, "telegram_webhook_secret", secret, raising=False)
    payload = {"update_id": 42}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        no_header = await client.post("/telegram/webhook", json=payload)
        bad = await client.post(
            "/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        ok = await client.post(
            "/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        )
    assert no_header.status_code == 401
    assert bad.status_code == 401
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_telegram_webhook_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_telegram_webhook_rejects_non_object_update(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=[1, 2])
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_telegram_webhook_requires_update_id(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json={"message": {}})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_telegram_webhook_start_invokes_fsm(monkeypatch):
    """/start в теле Update вызывает FSM и sendMessage (заглушка без реального Telegram)."""
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    sent: list[tuple[int, str]] = []

    async def fake_send(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(
        "app.integrations.telegram_client.send_message",
        fake_send,
    )
    uid = 424242
    payload = {
        "update_id": 11,
        "message": {
            "message_id": 2,
            "date": 0,
            "from": {"id": uid, "is_bot": False, "first_name": "U"},
            "chat": {"id": uid, "type": "private"},
            "text": "/start",
        },
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(sent) == 2
    assert sent[0][0] == uid
    assert "вдох" in sent[0][1].lower()
    assert "язык" in sent[1][1].lower() or "language" in sent[1][1].lower() or "ru" in sent[1][1].lower()


def test_start_command_recognized_after_zwsp():
    from app.services.bot_update_handler import _is_new_command, _is_start_command

    assert _is_start_command("\u200b/start")
    assert _is_start_command("/start@SomeBot")
    assert _is_new_command("/new")
    assert _is_new_command("/new@SomeBot")


@pytest.mark.asyncio
async def test_telegram_webhook_business_message_start(monkeypatch):
    """Telegram Business: текст в business_message, не в message."""
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    sent: list[str] = []

    async def fake_send(chat_id: int, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("app.integrations.telegram_client.send_message", fake_send)
    uid = 424243
    payload = {
        "update_id": 14,
        "business_message": {
            "message_id": 5,
            "date": 0,
            "from": {"id": uid, "is_bot": False, "first_name": "U"},
            "chat": {"id": uid, "type": "private"},
            "text": "/start",
        },
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=payload)
    assert response.status_code == 200
    assert len(sent) == 2
    assert "вдох" in sent[0].lower()
    assert "язык" in sent[1].lower()


@pytest.mark.asyncio
async def test_telegram_webhook_no_session_prompts_start(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    sent: list[str] = []

    async def fake_send(chat_id: int, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("app.integrations.telegram_client.send_message", fake_send)
    uid = 777001
    payload = {
        "update_id": 12,
        "message": {
            "message_id": 3,
            "date": 0,
            "from": {"id": uid, "is_bot": False, "first_name": "U"},
            "chat": {"id": uid, "type": "private"},
            "text": "hello",
        },
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=payload)
    assert response.status_code == 200
    assert len(sent) == 1
    assert sent[0].startswith("To begin")


@pytest.mark.asyncio
async def test_telegram_webhook_new_restarts_exam(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    sent: list[str] = []

    async def fake_send(chat_id: int, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("app.integrations.telegram_client.send_message", fake_send)
    uid = 900123
    payload = {
        "update_id": 13,
        "message": {
            "message_id": 4,
            "date": 0,
            "from": {"id": uid, "is_bot": False, "first_name": "U"},
            "chat": {"id": uid, "type": "private"},
            "text": "/new",
        },
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=payload)
    assert response.status_code == 200
    assert len(sent) == 2
    assert "заново" in sent[0].lower()
    assert "язык" in sent[1].lower()


@pytest.mark.asyncio
async def test_telegram_webhook_enqueues_when_arq_pool_present(monkeypatch):
    """При наличии пула arq задача ставится в очередь, обработчик не вызывается напрямую."""
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setattr(settings, "telegram_webhook_secret", "", raising=False)
    called: list[object] = []

    async def fake_handle(_update: dict) -> None:
        called.append(True)

    monkeypatch.setattr(
        "app.api.telegram_webhook.handle_telegram_update",
        fake_handle,
    )

    mock_pool = MagicMock()
    mock_pool.enqueue_job = AsyncMock()
    app.state.arq_pool = mock_pool

    payload = {"update_id": 501, "message": {"message_id": 1, "date": 0}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert called == []
    mock_pool.enqueue_job.assert_awaited_once()
    assert mock_pool.enqueue_job.call_args[0][0] == "process_telegram_update"
