"""Задачи воркера arq (имя функции — строка в enqueue_job)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def process_telegram_update(ctx: Any, update: dict[str, Any]) -> None:
    """Обработка Telegram Update вне процесса uvicorn (тяжёлые STT/оценка)."""
    from app.services.bot_update_handler import handle_telegram_update

    await handle_telegram_update(update)
