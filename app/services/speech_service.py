"""Speech recognition service.

Placeholder implementation that converts audio bytes to text.
Replace the body of ``transcribe`` with a real STT backend
(e.g. OpenAI Whisper, Google Speech-to-Text, Vosk, etc.).
"""

import logging

logger = logging.getLogger(__name__)


async def transcribe(audio_bytes: bytes, *, language: str = "ru") -> str:
    """Convert raw audio bytes to a text transcript.

    Args:
        audio_bytes: Raw audio data (OGG/OPUS as received from Telegram).
        language: BCP-47 language code for the expected language.

    Returns:
        Recognized text string.

    Raises:
        RuntimeError: When the underlying STT call fails.
    """
    # TODO: replace with a real speech-to-text implementation.
    logger.warning(
        "transcribe() is a placeholder — received %d bytes of audio (language=%s)",
        len(audio_bytes),
        language,
    )
    return "placeholder transcript"
