"""Хранение сессий экзамена в памяти процесса (MVP)."""

import asyncio
import time

from app.models.session import ExamSession, ExamState

# Лимит из брифа: 2 часа с момента /start
EXAM_TIME_LIMIT_SEC = 2 * 60 * 60

_lock = asyncio.Lock()
_sessions: dict[int, ExamSession] = {}


async def get_session(user_id: int) -> ExamSession | None:
    async with _lock:
        return _sessions.get(user_id)


async def upsert_session(session: ExamSession) -> None:
    async with _lock:
        _sessions[session.user_id] = session


async def reset_session(user_id: int) -> ExamSession:
    """Новая попытка после /start."""
    s = ExamSession(user_id=user_id, state=ExamState.START, start_time=0.0)
    async with _lock:
        _sessions[user_id] = s
    return s


def is_timed_out(session: ExamSession, now: float | None = None) -> bool:
    if session.start_time <= 0:
        return False
    t = now if now is not None else time.monotonic()
    return (t - session.start_time) > EXAM_TIME_LIMIT_SEC
