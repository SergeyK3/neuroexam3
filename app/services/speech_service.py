"""Распознавание речи: OpenAI Whisper (если задан OPENAI_API_KEY), иначе заглушка."""

import io
import logging
import re

from app.core.config import settings

logger = logging.getLogger(__name__)


_DEFAULT_EXAM_PROMPT = (
    "В аудио может быть несколько ответов подряд по билету. "
    "Точно распознавай фразы 'первый вопрос', 'второй вопрос', 'третий вопрос', "
    "'ключ', 'ключ вопроса', 'шифр', 'код вопроса', номера билета и ключей."
)


def _strong_exam_prompt(expected_question_count: int) -> str:
    return (
        "Это устный экзамен. В записи может быть несколько ответов подряд. "
        f"Ожидаемое число вопросов: {expected_question_count}. "
        "Особенно внимательно распознавай переходы между вопросами, формулировки вопросов, "
        "фразы 'второй вопрос', 'третий вопрос', а также ключи вида '2-10-6', '2106', '2 10 6'. "
        "Не пропускай короткие фразы-переходы между ответами."
    )


def _transcript_signal(transcript: str) -> tuple[int, int]:
    from app.services import reference_map_service

    inferred = reference_map_service.infer_expected_question_count(transcript)
    explicit_transitions = len(
        re.findall(
            r"(?i)\b(?:второй\s+вопрос|третий\s+вопрос|вопрос\s*(?:номер\s*|№\s*)?[23]|ключ(?:\s*вопроса)?|шифр|код(?:\s*вопроса)?)\b",
            transcript,
        ),
    )
    return inferred, explicit_transitions


def _prefer_retry_transcript(
    primary: str,
    retry: str,
    *,
    expected_question_count: int,
) -> str:
    primary_inferred, primary_transitions = _transcript_signal(primary)
    retry_inferred, retry_transitions = _transcript_signal(retry)

    primary_meets = primary_inferred >= expected_question_count
    retry_meets = retry_inferred >= expected_question_count
    if retry_meets and not primary_meets:
        return retry
    if retry_inferred > primary_inferred:
        return retry
    if retry_transitions > primary_transitions and len(retry) > len(primary):
        return retry
    if retry_meets and len(retry) > len(primary):
        return retry
    return primary


async def _transcribe_once(
    audio_bytes: bytes,
    *,
    language: str = "ru",
    prompt: str | None = None,
) -> str:
    """Один вызов Whisper/OpenAI без fallback-логики."""
    if not audio_bytes:
        raise ValueError("Пустой аудиофайл.")

    if not settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY не задан — транскрипция-заглушка (%s байт, lang=%s)",
            len(audio_bytes),
            language,
        )
        return "[Нет ключа OpenAI: задайте OPENAI_API_KEY в .env для Whisper]"

    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise RuntimeError("Установите пакет openai: pip install openai") from e

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    buf = io.BytesIO(audio_bytes)
    buf.name = "voice.ogg"

    lang = language if language in ("ru", "kk", "en") else "ru"
    kwargs: dict[str, str | io.BytesIO] = {
        "model": settings.speech_model,
        "file": buf,
        "language": lang,
    }
    if prompt and prompt.strip():
        kwargs["prompt"] = prompt.strip()

    tr = await client.audio.transcriptions.create(**kwargs)
    text = (tr.text or "").strip()
    if not text:
        raise RuntimeError("Whisper вернул пустой текст.")
    return text


async def transcribe(audio_bytes: bytes, *, language: str = "ru", prompt: str | None = None) -> str:
    """Сырой звук (OGG/OPUS от Telegram и т.д.) → текст."""
    return await _transcribe_once(audio_bytes, language=language, prompt=prompt)


async def transcribe_exam_answer(
    audio_bytes: bytes,
    *,
    language: str = "ru",
    expected_question_count: int = 1,
) -> str:
    """Транскрипция экзаменационного ответа: мягкий prompt + условный fallback с жёстким prompt."""
    primary = await _transcribe_once(
        audio_bytes,
        language=language,
        prompt=_DEFAULT_EXAM_PROMPT,
    )
    if expected_question_count <= 1:
        return primary

    primary_inferred, _primary_transitions = _transcript_signal(primary)
    if primary_inferred >= expected_question_count:
        return primary

    retry = await _transcribe_once(
        audio_bytes,
        language=language,
        prompt=_strong_exam_prompt(expected_question_count),
    )
    chosen = _prefer_retry_transcript(
        primary,
        retry,
        expected_question_count=expected_question_count,
    )
    logger.info(
        "transcribe_exam_answer: expected=%d primary_len=%d retry_len=%d chosen_len=%d",
        expected_question_count,
        len(primary),
        len(retry),
        len(chosen),
    )
    return chosen
