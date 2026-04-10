"""Клиент Telegram Bot API: исходящие сообщения и загрузка файлов."""

import logging
import re

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
# https://core.telegram.org/bots/api#sendmessage
_TELEGRAM_MAX_MESSAGE_CHARS = 4096

# Любой токен в URL api.telegram.org/bot…/ или …/file/bot…/
_RE_BOT_IN_URL = re.compile(
    r"(https://api\.telegram\.org/(?:file/)?bot)([A-Za-z0-9:_-]+)(/)",
    re.IGNORECASE,
)


def redact_secrets(text: str) -> str:
    """Убрать из строки токен бота и типичные URL с токеном (для сообщений пользователю и логов)."""
    if not text:
        return text
    out = text
    tok = (settings.telegram_bot_token or "").strip()
    if len(tok) >= 12:
        out = out.replace(tok, "<bot-token>")
    return _RE_BOT_IN_URL.sub(r"\1<bot-token>\3", out)


def _chunk_text_for_telegram(text: str, max_chars: int = _TELEGRAM_MAX_MESSAGE_CHARS) -> list[str]:
    """Разбить текст на части не длиннее max_chars (по возможности по переводу строки)."""
    t = text if text is not None else ""
    if not t.strip():
        return ["…"]
    if len(t) <= max_chars:
        return [t]
    chunks: list[str] = []
    rest = t
    while rest:
        if len(rest) <= max_chars:
            chunks.append(rest)
            break
        window = rest[:max_chars]
        br = window.rfind("\n")
        if br >= max_chars // 4:
            take = br + 1
        else:
            take = max_chars
        chunks.append(rest[:take])
        rest = rest[take:].lstrip("\n")
    return chunks


async def send_message(chat_id: int, text: str) -> None:
    """Отправить текст в чат (длинные ответы режутся на несколько сообщений по лимиту Telegram 4096)."""
    if not settings.telegram_bot_token:
        logger.error(
            "TELEGRAM_BOT_TOKEN пустой — ответ пользователю не отправлен (chat_id=%s). "
            "Проверьте .env у процесса uvicorn и arq.",
            chat_id,
        )
        return

    parts = _chunk_text_for_telegram(text)
    url = f"{_TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, chunk in enumerate(parts):
            payload = {"chat_id": chat_id, "text": chunk}
            response = await client.post(url, json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = redact_secrets((e.response.text or "")[:500])
                logger.exception(
                    "sendMessage failed (chunk %s/%s): HTTP %s %s",
                    i + 1,
                    len(parts),
                    e.response.status_code,
                    body,
                )
                raise RuntimeError(
                    f"Telegram sendMessage: HTTP {e.response.status_code}",
                ) from None


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
