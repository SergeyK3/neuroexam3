"""Тесты SessionStore: InMemory и Redis (через fakeredis)."""

from __future__ import annotations

import pytest

from app.models.session import ExamSession, ExamState
from app.services.session_store import (
    InMemorySessionStore,
    RedisSessionStore,
    _session_from_json,
    _session_to_json,
    is_timed_out,
)


def _make_session(user_id: int = 1) -> ExamSession:
    return ExamSession(
        user_id=user_id,
        session_id="s-1",
        discipline_id="med",
        state=ExamState.ANSWERING,
        start_time=100.0,
        language="ru",
        registration_parts=["Иванов И.И.", "Группа 101", "Билет 7"],
        registration_raw="Иванов И.И.\nГруппа 101\nБилет 7",
        ticket_number="7",
        last_transcript="lorem ipsum",
        pending_transcript=None,
    )


def test_session_roundtrip_json():
    s = _make_session()
    restored = _session_from_json(_session_to_json(s))
    assert restored == s


@pytest.mark.asyncio
async def test_in_memory_store_upsert_get_reset():
    store = InMemorySessionStore()
    s = _make_session(42)
    assert await store.get(42) is None
    await store.upsert(s)
    got = await store.get(42)
    assert got is not None and got.user_id == 42
    assert got.state is ExamState.ANSWERING

    fresh = await store.reset(42)
    assert fresh.state is ExamState.START
    assert fresh.registration_parts == []


@pytest.mark.asyncio
async def test_redis_store_with_fakeredis(monkeypatch):
    """RedisSessionStore должен читать/писать JSON через любой совместимый клиент."""
    import fakeredis.aioredis  # type: ignore[import-not-found]

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    store = RedisSessionStore("redis://ignored")
    store._client = fake  # подмена реального клиента

    s = _make_session(7)
    await store.upsert(s)

    got = await store.get(7)
    assert got is not None
    assert got.user_id == 7
    assert got.state is ExamState.ANSWERING
    assert got.ticket_number == "7"

    fresh = await store.reset(7)
    assert fresh.state is ExamState.START

    raw = await fake.get(store._key(7))
    assert raw is not None
    assert '"state": "START"' in raw


def test_is_timed_out_semantics():
    s = _make_session()
    s.start_time = 0.0
    assert not is_timed_out(s, now=10**9)

    s.start_time = 1_000.0
    assert not is_timed_out(s, now=1_000.0 + 60)
    # 2h 15m > 2h limit
    assert is_timed_out(s, now=1_000.0 + 2 * 3600 + 900)


@pytest.mark.asyncio
async def test_redis_store_corrupt_payload_returns_none(monkeypatch):
    import fakeredis.aioredis  # type: ignore[import-not-found]

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = RedisSessionStore("redis://ignored")
    store._client = fake

    await fake.set(store._key(99), "not a json")
    assert await store.get(99) is None
