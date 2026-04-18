"""Фасад над SessionStore (in-memory по умолчанию, Redis при заданном REDIS_URL).

Публичный API (get_session/upsert_session/reset_session/is_timed_out) сохранён — чтобы
не ломать существующий код бота.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.models.session import ExamSession
from app.services.session_store import (
    EXAM_TIME_LIMIT_SEC,
    InMemorySessionStore,
    RedisSessionStore,
    SessionStore,
    is_timed_out as _store_is_timed_out,
)

logger = logging.getLogger(__name__)

__all__ = [
    "EXAM_TIME_LIMIT_SEC",
    "get_session",
    "upsert_session",
    "reset_session",
    "is_timed_out",
    "get_store",
    "reset_store_for_tests",
]

_store: SessionStore | None = None
_store_lock = asyncio.Lock()


def _build_store() -> SessionStore:
    url = (getattr(settings, "redis_url", "") or "").strip()
    if url:
        logger.info("Session store: Redis (url configured)")
        return RedisSessionStore(url)
    logger.info("Session store: in-memory (REDIS_URL empty)")
    return InMemorySessionStore()


async def get_store() -> SessionStore:
    global _store
    if _store is not None:
        return _store
    async with _store_lock:
        if _store is None:
            _store = _build_store()
    return _store


def reset_store_for_tests(store: Any | None = None) -> None:
    """Сбросить (или принудительно задать) глобальный store — нужно для тестов."""
    global _store
    _store = store


async def get_session(user_id: int) -> ExamSession | None:
    store = await get_store()
    return await store.get(user_id)


async def upsert_session(session: ExamSession) -> None:
    store = await get_store()
    await store.upsert(session)


async def reset_session(user_id: int) -> ExamSession:
    store = await get_store()
    return await store.reset(user_id)


def is_timed_out(session: ExamSession, now: float | None = None) -> bool:
    return _store_is_timed_out(session, now)
