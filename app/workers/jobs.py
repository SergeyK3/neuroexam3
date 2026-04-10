"""Задачи воркера arq (имя функции — строка в enqueue_job)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def process_telegram_update(ctx: Any, update: dict[str, Any]) -> None:
    """Обработка Telegram Update вне процесса uvicorn (тяжёлые STT/оценка)."""
    from app.services.bot_update_handler import handle_telegram_update

    uid = update.get("update_id")
    logger.info(
        "Задача process_telegram_update: update_id=%s keys=%s",
        uid,
        list(update.keys()) if isinstance(update, dict) else None,
    )
    try:
        await handle_telegram_update(update)
    except Exception:
        logger.exception(
            "Ошибка обработки update_id=%s keys=%s",
            update.get("update_id"),
            list(update.keys()) if isinstance(update, dict) else None,
        )
        raise
