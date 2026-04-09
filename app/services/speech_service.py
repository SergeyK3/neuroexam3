"""Распознавание речи: OpenAI Whisper (если задан OPENAI_API_KEY), иначе заглушка."""

import io
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


async def transcribe(audio_bytes: bytes, *, language: str = "ru") -> str:
    """Сырой звук (OGG/OPUS от Telegram и т.д.) → текст."""
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

    tr = await client.audio.transcriptions.create(
        model=settings.speech_model,
        file=buf,
        language=lang,
    )
    text = (tr.text or "").strip()
    if not text:
        raise RuntimeError("Whisper вернул пустой текст.")
    return text
