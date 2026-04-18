"""Фильтры логирования: маскировка токена Telegram и ПДн студента.

Фильтры применяются на корневом логгере в `main.py` (uvicorn) и
`app/workers/worker_settings.py` (arq). Маскируют значения в `record.msg`,
`record.args` и готовом `record.message`.
"""

from __future__ import annotations

import logging
import re

_RE_BOT_IN_URL = re.compile(
    r"(https://api\.telegram\.org/(?:file/)?bot)([A-Za-z0-9:_-]+)(/)",
    re.IGNORECASE,
)
_RE_BOT_TOKEN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
_RE_SK = re.compile(r"\bsk-[A-Za-z0-9-]{16,}\b")

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
    s = _RE_BOT_IN_URL.sub(r"\1<bot-token>\3", s)
    s = _RE_BOT_TOKEN.sub("<bot-token>", s)
    s = _RE_SK.sub("<api-key>", s)
    return s


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

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_tokens(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    _redact_tokens(a) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (_redact_tokens(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
        return True


class PiiMaskFilter(logging.Filter):
    """Маскирует ФИО и номер группы. Включать только в production (debug=False)."""

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
    """Регистрирует фильтры на корневом логгере. Идемпотентно."""
    root = logging.getLogger()
    names = {type(f).__name__ for f in root.filters}
    if "BotTokenFilter" not in names:
        root.addFilter(BotTokenFilter())
    if "PiiMaskFilter" not in names:
        root.addFilter(PiiMaskFilter(enabled=not debug))
