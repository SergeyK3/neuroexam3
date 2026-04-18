"""Абстракция хранилища сессий экзамена.

Две реализации:
- InMemorySessionStore — процессная память (MVP, работает, пока процесс не перезапущен);
- RedisSessionStore — JSON-сериализация сессии в Redis (переживает рестарт процесса и
  разделяется между uvicorn и arq-воркером, если оба смотрят на один Redis).

Выбирается автоматически в `session_service.get_store()` по наличию `settings.redis_url`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from typing import Any, Protocol

from app.models.session import ExamSession, ExamState

logger = logging.getLogger(__name__)

EXAM_TIME_LIMIT_SEC = 2 * 60 * 60
_REDIS_TTL_SEC = EXAM_TIME_LIMIT_SEC + 15 * 60
_REDIS_KEY_PREFIX = "neuroexam:session:"


def _session_to_json(session: ExamSession) -> str:
    data: dict[str, Any] = asdict(session)
    data["state"] = session.state.value
    return json.dumps(data, ensure_ascii=False)


def _session_from_json(raw: str) -> ExamSession:
    data = json.loads(raw)
    state_value = data.get("state") or ExamState.START.value
    try:
        state = ExamState(state_value)
    except ValueError:
        state = ExamState.START
    return ExamSession(
        user_id=int(data["user_id"]),
        session_id=str(data.get("session_id") or ""),
        discipline_id=data.get("discipline_id"),
        state=state,
        start_time=float(data.get("start_time") or 0.0),
        language=data.get("language"),
        registration_parts=list(data.get("registration_parts") or []),
        registration_raw=data.get("registration_raw"),
        ticket_number=data.get("ticket_number"),
        last_transcript=data.get("last_transcript"),
        pending_transcript=data.get("pending_transcript"),
    )


class SessionStore(Protocol):
    async def get(self, user_id: int) -> ExamSession | None: ...
    async def upsert(self, session: ExamSession) -> None: ...
    async def reset(self, user_id: int) -> ExamSession: ...


class InMemorySessionStore:
    """Хранит сессии в памяти процесса. Теряются при рестарте — только для MVP/тестов."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[int, ExamSession] = {}

    async def get(self, user_id: int) -> ExamSession | None:
        async with self._lock:
            return self._sessions.get(user_id)

    async def upsert(self, session: ExamSession) -> None:
        async with self._lock:
            self._sessions[session.user_id] = session

    async def reset(self, user_id: int) -> ExamSession:
        s = ExamSession(user_id=user_id, state=ExamState.START, start_time=0.0)
        async with self._lock:
            self._sessions[user_id] = s
        return s


class RedisSessionStore:
    """Персистентное хранение в Redis (JSON, TTL = лимит экзамена + запас)."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Any = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is not None:
                return self._client
            try:
                import redis.asyncio as redis_asyncio  # type: ignore[import-not-found]
            except ImportError as e:
                raise RuntimeError(
                    "Установите redis>=5.0 (async): pip install 'redis>=5.0'",
                ) from e
            self._client = redis_asyncio.from_url(self._url, decode_responses=True)
            return self._client

    @staticmethod
    def _key(user_id: int) -> str:
        return f"{_REDIS_KEY_PREFIX}{user_id}"

    async def get(self, user_id: int) -> ExamSession | None:
        client = await self._get_client()
        raw = await client.get(self._key(user_id))
        if not raw:
            return None
        try:
            return _session_from_json(raw)
        except (ValueError, KeyError, json.JSONDecodeError):
            logger.exception("RedisSessionStore.get: cannot decode session user_id=%s", user_id)
            return None

    async def upsert(self, session: ExamSession) -> None:
        client = await self._get_client()
        await client.set(self._key(session.user_id), _session_to_json(session), ex=_REDIS_TTL_SEC)

    async def reset(self, user_id: int) -> ExamSession:
        s = ExamSession(user_id=user_id, state=ExamState.START, start_time=0.0)
        client = await self._get_client()
        await client.set(self._key(user_id), _session_to_json(s), ex=_REDIS_TTL_SEC)
        return s

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except AttributeError:
                await self._client.close()
            self._client = None


def is_timed_out(session: ExamSession, now: float | None = None) -> bool:
    if session.start_time <= 0:
        return False
    t = now if now is not None else time.monotonic()
    return (t - session.start_time) > EXAM_TIME_LIMIT_SEC
