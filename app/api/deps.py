"""FastAPI-зависимости: аутентификация и проверка размера payload."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request, status

from app.core.config import settings


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    """Bearer-аутентификация публичных /exam/* эндпоинтов.

    Пустой API_BEARER_TOKEN → 503 (эндпоинты отключены).
    """
    expected = (settings.api_bearer_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API disabled: API_BEARER_TOKEN is not configured.",
        )
    received = (authorization or "").strip()
    if not received.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = received[len("bearer "):].strip()
    if len(token) != len(expected) or not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def enforce_max_body(request: Request, limit: int) -> None:
    """Жёсткий cap по Content-Length до чтения тела."""
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        size = int(raw)
    except ValueError:
        return
    if size > limit:
        raise HTTPException(
            status_code=413,
            detail=f"Payload too large: {size} > {limit} bytes",
        )


async def read_upload_capped(upload, limit: int) -> bytes:
    """Чтение UploadFile по чанкам с жёстким пределом (защита от «бомбы»)."""
    buf = bytearray()
    chunk_size = 64 * 1024
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"Audio payload exceeds limit: >{limit} bytes",
            )
    return bytes(buf)
