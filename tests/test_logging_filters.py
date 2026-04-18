"""Маскирование токенов и ПДн в логах."""

from __future__ import annotations

import logging

from app.core.logging_filters import BotTokenFilter, PiiMaskFilter


def _make_record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args or None,
        exc_info=None,
    )


def test_bot_token_filter_masks_url():
    rec = _make_record(
        "error at https://api.telegram.org/bot1234567890:ABC-def_XYZ/sendMessage",
    )
    BotTokenFilter().filter(rec)
    assert "bot-token" in rec.getMessage()
    assert "ABC-def_XYZ" not in rec.getMessage()


def test_bot_token_filter_masks_bare_token_in_args():
    rec = _make_record("token=%s", "1234567890:ABCDEFGHIJabcdefghij0123456789XY")
    BotTokenFilter().filter(rec)
    assert "<bot-token>" in rec.getMessage()


def test_bot_token_filter_masks_bare_token_in_msg():
    rec = _make_record("token=1234567890:ABCDEFGHIJabcdefghij0123456789XY done")
    BotTokenFilter().filter(rec)
    assert "<bot-token>" in rec.getMessage()


def test_bot_token_filter_masks_openai_api_key():
    rec = _make_record("using key=sk-1234567890ABCDEFabcdef for call")
    BotTokenFilter().filter(rec)
    assert "<api-key>" in rec.getMessage()
    assert "sk-1234567890ABCDEFabcdef" not in rec.getMessage()


def test_pii_filter_masks_fio_short():
    rec = _make_record("student=Иванов И.И. group=23-А")
    PiiMaskFilter(enabled=True).filter(rec)
    assert "Иванов" not in rec.getMessage()
    assert "И***" in rec.getMessage() or "*" in rec.getMessage()


def test_pii_filter_masks_fio_full():
    rec = _make_record("ФИО: Иванова Ирина Петровна, группа 101-Б")
    PiiMaskFilter(enabled=True).filter(rec)
    msg = rec.getMessage()
    assert "Иванова" not in msg
    assert "Ирина" not in msg
    assert "Петровна" not in msg


def test_pii_filter_masks_group_code():
    rec = _make_record("registration: группа 2301-А и др.")
    PiiMaskFilter(enabled=True).filter(rec)
    assert "2301" not in rec.getMessage()
    assert "**" in rec.getMessage()


def test_pii_filter_disabled_when_debug():
    rec = _make_record("student=Иванов И.И.")
    PiiMaskFilter(enabled=False).filter(rec)
    assert "Иванов" in rec.getMessage()
