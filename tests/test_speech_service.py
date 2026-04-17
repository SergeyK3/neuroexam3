"""Тесты улучшенного STT-пайплайна для экзаменационных аудио."""

import pytest

from app.services import speech_service


@pytest.mark.asyncio
async def test_transcribe_exam_answer_single_question_uses_one_pass(monkeypatch):
    calls: list[str | None] = []

    async def fake_once(_audio: bytes, *, language: str = "ru", prompt: str | None = None) -> str:
        calls.append(prompt)
        return "Один полный ответ."

    monkeypatch.setattr("app.services.speech_service._transcribe_once", fake_once)

    out = await speech_service.transcribe_exam_answer(
        b"audio",
        language="ru",
        expected_question_count=1,
    )

    assert out == "Один полный ответ."
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_transcribe_exam_answer_retries_when_expected_two_questions(monkeypatch):
    responses = iter(
        [
            "Билет 6. Первый вопрос. Ключ 296. Ответ только по первому вопросу.",
            "Билет 6. Первый вопрос. Ключ 296. Ответ только по первому вопросу. "
            "Второй вопрос. Ключ 2-10-6. Ответ по второму вопросу.",
        ],
    )
    calls: list[str | None] = []

    async def fake_once(_audio: bytes, *, language: str = "ru", prompt: str | None = None) -> str:
        calls.append(prompt)
        return next(responses)

    monkeypatch.setattr("app.services.speech_service._transcribe_once", fake_once)

    out = await speech_service.transcribe_exam_answer(
        b"audio",
        language="ru",
        expected_question_count=2,
    )

    assert "Второй вопрос" in out
    assert len(calls) == 2
    assert calls[0]
    assert calls[1]


def test_prefer_retry_transcript_when_retry_has_more_question_signal():
    primary = "Билет 6. Первый вопрос. Ответ только по первому вопросу."
    retry = (
        "Билет 6. Первый вопрос. Ответ только по первому вопросу. "
        "Второй вопрос. Ключ 2-10-6. Ответ по второму вопросу."
    )

    chosen = speech_service._prefer_retry_transcript(
        primary,
        retry,
        expected_question_count=2,
    )

    assert chosen == retry
