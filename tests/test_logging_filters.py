"""Маскирование токенов и ПДн в логах."""

from __future__ import annotations

import logging

from uvicorn.logging import AccessFormatter

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
    token = "1234567890:" + "TESTONLY" * 5
    rec = _make_record(
        f"error at https://api.telegram.org/bot{token}/sendMessage",
    )
    BotTokenFilter().filter(rec)
    assert "[REDACTED]" in rec.getMessage()
    assert token not in rec.getMessage()


def test_bot_token_filter_masks_bare_token_in_args():
    token = "1234567890:" + "TESTONLY" * 5
    rec = _make_record("token=%s", token)
    BotTokenFilter().filter(rec)
    assert "[REDACTED]" in rec.getMessage()


def test_bot_token_filter_masks_bare_token_in_msg():
    token = "1234567890:" + "TESTONLY" * 5
    rec = _make_record(f"token={token} done")
    BotTokenFilter().filter(rec)
    assert "[REDACTED]" in rec.getMessage()


def test_bot_token_filter_masks_openai_api_key():
    key = "sk-" + "TESTONLY" * 3
    rec = _make_record(f"using key={key} for call")
    BotTokenFilter().filter(rec)
    assert "[REDACTED]" in rec.getMessage()
    assert key not in rec.getMessage()


def test_bot_token_filter_preserves_uvicorn_access_log_arguments():
    rec = _make_record(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:12345",
        "GET",
        "/health",
        "1.1",
        200,
    )

    BotTokenFilter().filter(rec)

    assert rec.args == (
        "127.0.0.1:12345",
        "GET",
        "/health",
        "1.1",
        200,
    )
    formatter = AccessFormatter(
        "%(levelprefix)s %(client_addr)s - %(request_line)s %(status_code)s"
    )
    rendered = formatter.format(rec)
    assert "GET /health HTTP/1.1" in rendered
    assert "200" in rendered


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
