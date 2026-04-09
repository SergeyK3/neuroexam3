"""Клиент Telegram Bot API: исходящие сообщения и загрузка файлов."""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"


async def send_message(chat_id: int, text: str) -> None:
    """Отправить текст в чат."""
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — сообщение не отправлено: %s", text[:200])
        return

    url = f"{_TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.exception(
                "sendMessage failed: %s %s",
                response.status_code,
                response.text[:500],
            )
            raise


async def download_file_bytes(file_id: str) -> bytes:
    """Скачать файл по file_id (getFile + HTTPS)."""
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан.")

    base = f"{_TELEGRAM_API}/bot{settings.telegram_bot_token}"
    async with httpx.AsyncClient(timeout=180.0) as client:
        gr = await client.get(f"{base}/getFile", params={"file_id": file_id})
        gr.raise_for_status()
        data = gr.json()
        if not data.get("ok") or "result" not in data:
            raise RuntimeError(f"getFile: {data}")
        path = data["result"].get("file_path")
        if not path:
            raise RuntimeError("getFile: нет file_path")

        file_url = f"{_TELEGRAM_API}/file/bot{settings.telegram_bot_token}/{path}"
        fr = await client.get(file_url)
        fr.raise_for_status()
        return fr.content
