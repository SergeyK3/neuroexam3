"""Telegram Bot API webhook: receive `Update` JSON and validate secret token."""

import hmac
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.services.bot_update_handler import handle_telegram_update

JOB_NAME = "process_telegram_update"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])

# Header Telegram sends when `secret_token` was set via setWebhook (Bot API).
_TELEGRAM_SECRET_HEADER = "x-telegram-bot-api-secret-token"


def _secret_matches(expected: str, received: str | None) -> bool:
    if received is None:
        return False
    if len(expected) != len(received):
        return False
    return hmac.compare_digest(expected, received)


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Accept a Telegram `Update` (JSON). Validates webhook secret when configured."""
    if settings.telegram_webhook_secret:
        received = request.headers.get(_TELEGRAM_SECRET_HEADER)
        if not _secret_matches(settings.telegram_webhook_secret, received):
            logger.warning("Telegram webhook: invalid or missing secret token")
            raise HTTPException(
                status_code=401,
                detail=(
                    "Invalid webhook secret. If TELEGRAM_WEBHOOK_SECRET is set in .env, "
                    "call setWebhook with the same secret_token=..., or leave .env empty for testing."
                ),
            )

    try:
        update: dict[str, Any] = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Body must be valid JSON") from None

    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="Update must be a JSON object")

    update_id = update.get("update_id")
    if update_id is None:
        raise HTTPException(status_code=400, detail="Missing update_id")

    logger.debug("Telegram update_id=%s keys=%s", update_id, list(update.keys()))

    pool = getattr(request.app.state, "arq_pool", None)
    if pool is not None:
        await pool.enqueue_job(JOB_NAME, update)
    else:
        await handle_telegram_update(update)
    return {"ok": True}
