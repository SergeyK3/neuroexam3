"""Telegram Bot API webhook: receive `Update` JSON and validate secret token."""

import hmac
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.api.deps import enforce_max_body
from app.core.config import settings
from app.models.telegram import TgUpdate
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
    enforce_max_body(request, settings.max_update_bytes)

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

    # Строгая валидация входа: отсеиваем битые/посторонние payload'ы до постановки в очередь.
    try:
        validated = TgUpdate.from_raw(update)
    except ValidationError as e:
        logger.warning("Telegram webhook: schema validation failed (%d issues)", len(e.errors()))
        raise HTTPException(status_code=400, detail="Invalid Telegram Update schema") from None

    logger.debug("Telegram update_id=%s", validated.update_id)

    pool = getattr(request.app.state, "arq_pool", None)
    if pool is not None:
        await pool.enqueue_job(JOB_NAME, update, _job_id=f"tg-{validated.update_id}")
        logger.info(
            "Telegram webhook: задача в очереди (%s), update_id=%s",
            JOB_NAME,
            validated.update_id,
        )
    else:
        await handle_telegram_update(update)
    return {"ok": True}
