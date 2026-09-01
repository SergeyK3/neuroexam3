"""Фильтры логирования: маскировка токена Telegram и ПДн студента.

Фильтры применяются на корневом логгере в `main.py` (uvicorn) и
`app/workers/worker_settings.py` (arq). Маскируют значения в `record.msg`,
`record.args` и готовом `record.message`.
"""

from __future__ import annotations

import logging
import re
import threading
import traceback
import types
from typing import Any

_RE_BOT_IN_URL = re.compile(
    r"(https://api\.telegram\.org/(?:file/)?bot)([A-Za-z0-9:_-]+)(/)",
    re.IGNORECASE,
)
_RE_BOT_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])\d{5,16}:[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])",
)
_RE_SK = re.compile(r"\bsk-[A-Za-z0-9-]{16,}\b")

_FACTORY_MARKER = "_neuroexam_secure_log_record_factory_v1"
_MAKE_RECORD_MARKER = "_neuroexam_secure_logger_make_record_v1"
_FILTER_MARKER = "_neuroexam_secure_logging_filter_v1"
_INSTALL_LOCK = getattr(logging, "_neuroexam_logging_install_lock", None)
if _INSTALL_LOCK is None:
    _INSTALL_LOCK = threading.RLock()
    setattr(logging, "_neuroexam_logging_install_lock", _INSTALL_LOCK)

# ФИО русское: «Иванов И.И.», «Иванова Ирина Петровна» и т.п.
_RE_FIO_RU_SHORT = re.compile(
    r"\b([А-ЯЁ][а-яё]{1,30})\s+([А-ЯЁ])\.\s*([А-ЯЁ])\.",
)
_RE_FIO_RU_FULL = re.compile(
    r"\b([А-ЯЁ][а-яё]{1,30})\s+([А-ЯЁ][а-яё]{1,30})\s+([А-ЯЁ][а-яё]{1,30})\b",
)
# Группа: «Группа 23-02», «Гр. 101», «101" , «гр 23-Б»
_RE_GROUP = re.compile(
    r"\b(группа|гр\.?|group)\s*[:№]?\s*([0-9]{2,4}[A-Za-zА-Яа-я-]*)",
    re.IGNORECASE,
)


def _redact_tokens(s: str) -> str:
    s = _RE_BOT_IN_URL.sub(r"\1[REDACTED]\3", s)
    s = _RE_BOT_TOKEN.sub("[REDACTED]", s)
    s = _RE_SK.sub("[REDACTED]", s)
    return s


def _redact_value(value: Any, seen: set[int] | None = None) -> Any:
    """Redact secrets recursively without retaining raw string containers."""
    if isinstance(value, str):
        return _redact_tokens(value)
    if isinstance(value, BaseException):
        return _redact_tokens(
            "".join(traceback.format_exception(type(value), value, value.__traceback__))
        )
    if isinstance(value, types.TracebackType):
        return _redact_tokens("".join(traceback.format_tb(value)))
    if not isinstance(value, (tuple, list, dict, set, frozenset)):
        return value

    seen = set() if seen is None else seen
    identity = id(value)
    if identity in seen:
        return "[REDACTED RECURSIVE VALUE]"
    seen.add(identity)
    try:
        if isinstance(value, tuple):
            return tuple(_redact_value(item, seen) for item in value)
        if isinstance(value, list):
            return [_redact_value(item, seen) for item in value]
        if isinstance(value, dict):
            return {
                _redact_value(key, seen): _redact_value(item, seen)
                for key, item in value.items()
            }
        if isinstance(value, set):
            return {_redact_value(item, seen) for item in value}
        return frozenset(_redact_value(item, seen) for item in value)
    finally:
        seen.remove(identity)


def _sanitize_record(record: logging.LogRecord) -> logging.LogRecord:
    """Remove raw tokens and exception objects before handlers see the record."""
    if record.exc_info:
        safe_traceback = _redact_tokens("".join(traceback.format_exception(*record.exc_info)))
        record.exc_text = safe_traceback
        record.exc_info = None

    try:
        rendered = record.getMessage()
    except Exception:  # pragma: no cover - defensive fallback for broken third-party args
        rendered = str(record.msg)
    record.msg = _redact_tokens(rendered)
    record.args = ()

    for key, value in tuple(record.__dict__.items()):
        if key in {"msg", "args", "exc_info", "exc_text"}:
            continue
        record.__dict__[key] = _redact_value(value)
    if record.exc_text:
        record.exc_text = _redact_tokens(record.exc_text)
    return record


def _mask_fio(s: str) -> str:
    s = _RE_FIO_RU_SHORT.sub(lambda m: f"{m.group(1)[0]}*** {m.group(2)}.{m.group(3)}.", s)
    s = _RE_FIO_RU_FULL.sub(
        lambda m: f"{m.group(1)[0]}*** {m.group(2)[0]}. {m.group(3)[0]}.",
        s,
    )
    return s


def _mask_group(s: str) -> str:
    def _repl(m: re.Match[str]) -> str:
        code = m.group(2)
        if len(code) <= 2:
            masked = code
        else:
            masked = code[:2] + "*" * (len(code) - 2)
        return f"{m.group(1)} {masked}"

    return _RE_GROUP.sub(_repl, s)


class BotTokenFilter(logging.Filter):
    """Вырезает из сообщения токены ботов/OpenAI API и URL api.telegram.org/bot…/."""

    _neuroexam_filter_marker = _FILTER_MARKER

    def filter(self, record: logging.LogRecord) -> bool:
        _sanitize_record(record)
        return True


class PiiMaskFilter(logging.Filter):
    """Маскирует ФИО и номер группы. Включать только в production (debug=False)."""

    _neuroexam_filter_marker = "_neuroexam_pii_filter_v1"

    def __init__(self, *, enabled: bool = True) -> None:
        super().__init__()
        self._enabled = enabled

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._enabled:
            return True
        if isinstance(record.msg, str):
            record.msg = _mask_group(_mask_fio(record.msg))
        if record.args and isinstance(record.args, tuple):
            record.args = tuple(
                _mask_group(_mask_fio(a)) if isinstance(a, str) else a for a in record.args
            )
        return True


def install_filters(*, debug: bool) -> None:
    """Install process-wide, reload-idempotent secret redaction."""
    with _INSTALL_LOCK:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

        current_factory = logging.getLogRecordFactory()
        if not getattr(current_factory, _FACTORY_MARKER, False):
            base_factory = current_factory

            def secure_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
                return _sanitize_record(base_factory(*args, **kwargs))

            setattr(secure_factory, _FACTORY_MARKER, True)
            logging.setLogRecordFactory(secure_factory)

        current_make_record = logging.Logger.makeRecord
        if not getattr(current_make_record, _MAKE_RECORD_MARKER, False):
            base_make_record = current_make_record

            def secure_make_record(
                self: logging.Logger,
                *args: Any,
                **kwargs: Any,
            ) -> logging.LogRecord:
                record = base_make_record(self, *args, **kwargs)
                return _sanitize_record(record)

            setattr(secure_make_record, _MAKE_RECORD_MARKER, True)
            logging.Logger.makeRecord = secure_make_record

        root = logging.getLogger()
        if not any(getattr(f, "_neuroexam_filter_marker", None) == _FILTER_MARKER for f in root.filters):
            root.addFilter(BotTokenFilter())
        if not any(
            getattr(f, "_neuroexam_filter_marker", None) == "_neuroexam_pii_filter_v1"
            for f in root.filters
        ):
            root.addFilter(PiiMaskFilter(enabled=not debug))

        for handler in root.handlers:
            if not any(
                getattr(f, "_neuroexam_filter_marker", None) == _FILTER_MARKER
                for f in handler.filters
            ):
                handler.addFilter(BotTokenFilter())
