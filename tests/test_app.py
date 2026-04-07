"""Basic smoke tests for the NeuroExam3 FastAPI application."""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_evaluate_text_exact_match():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/exam/evaluate-text",
            data={
                "student_answer": "The mitochondria is the powerhouse of the cell",
                "reference": "The mitochondria is the powerhouse of the cell",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 1.0


@pytest.mark.asyncio
async def test_evaluate_text_no_match():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/exam/evaluate-text",
            data={
                "student_answer": "Wrong answer",
                "reference": "Correct answer",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 0.0


@pytest.mark.asyncio
async def test_evaluate_voice_returns_transcript():
    """Smoke test: the evaluate-voice endpoint returns expected keys."""
    dummy_audio = b"RIFF\x00\x00\x00\x00WAVEfmt "  # minimal fake WAV header
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/exam/evaluate-voice",
            files={"audio": ("test.wav", dummy_audio, "audio/wav")},
            data={"reference": "some reference answer"},
        )
    assert response.status_code == 200
    body = response.json()
    assert "transcript" in body
    assert "score" in body
    assert 0.0 <= body["score"] <= 1.0
