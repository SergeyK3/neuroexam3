"""Telegram bot entry point.

Placeholder implementation that wires together the Telegram bot with the
speech recognition and evaluation services.

Replace the handler bodies with real logic once the STT and evaluation
services are implemented.

Usage:
    python -m app.bot.bot
"""

import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _handle_voice(bot_token: str) -> None:  # pragma: no cover
    """Placeholder coroutine — set up python-telegram-bot handlers here."""
    # TODO: Implement with python-telegram-bot or aiogram.
    #
    # Example sketch (python-telegram-bot v20+):
    #
    #   from telegram.ext import Application, MessageHandler, filters
    #
    #   async def voice_handler(update, context):
    #       voice = update.message.voice
    #       file = await context.bot.get_file(voice.file_id)
    #       audio_bytes = await file.download_as_bytearray()
    #       transcript = await speech_service.transcribe(bytes(audio_bytes))
    #       score = await evaluation_service.evaluate(transcript, REFERENCE)
    #       await update.message.reply_text(f"Score: {score:.2f}\n{transcript}")
    #
    #   app = Application.builder().token(bot_token).build()
    #   app.add_handler(MessageHandler(filters.VOICE, voice_handler))
    #   await app.run_polling()

    logger.warning(
        "Telegram bot is a placeholder. "
        "Set TELEGRAM_BOT_TOKEN in .env and implement _handle_voice()."
    )
    await asyncio.sleep(0)


def main() -> None:  # pragma: no cover
    """Start the Telegram bot."""
    logging.basicConfig(level=logging.INFO)
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Bot cannot start.")
        return
    asyncio.run(_handle_voice(settings.telegram_bot_token))


if __name__ == "__main__":
    main()
