"""Чтение эталонов с листа Google Sheets (сервисный аккаунт)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_KEY_HEADER = frozenset(
    {
        "question_key",
        "key",
        "ключ",
        "код",
        "код вопроса",
    },
)
_REF_HEADER = frozenset(
    {
        "reference",
        "ideal",
        "ideal_answer",
        "etalon",
        "эталон",
        "reference_answer",
    },
)


def _resolve_credentials_path(explicit: str) -> str:
    if explicit.strip():
        return explicit.strip()
    return os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()


def _normalize_header(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.strip().lower())


def _find_col(headers: list[str], aliases: frozenset[str]) -> int | None:
    for i, h in enumerate(headers):
        n = _normalize_header(h)
        if n in aliases:
            return i
        for a in aliases:
            if a in n or n in a:
                return i
    return None


def _parse_table(rows: list[list[Any]]) -> dict[str, str]:
    if not rows:
        return {}
    headers = [_normalize_header(str(c or "")) for c in rows[0]]
    idx_k = _find_col(headers, _KEY_HEADER)
    idx_r = _find_col(headers, _REF_HEADER)
    if idx_k is not None and idx_r is not None:
        data_rows = rows[1:]
    else:
        idx_k, idx_r = 0, 1
        data_rows = rows

    out: dict[str, str] = {}
    for row in data_rows:
        if len(row) <= max(idx_k, idx_r):
            continue
        k = str(row[idx_k] or "").strip()
        v = str(row[idx_r] or "").strip()
        if k and v:
            out[k] = v
    return out


def fetch_ideal_references_sync(
    spreadsheet_id: str,
    worksheet_title: str,
    *,
    credentials_path: str,
) -> dict[str, str]:
    """Синхронное чтение (вызывать через asyncio.to_thread)."""
    from app.integrations import google_sheets

    cred_path = _resolve_credentials_path(credentials_path)
    if not cred_path:
        raise RuntimeError(
            "Не задан путь к JSON сервисного аккаунта: "
            "GOOGLE_SHEETS_CREDENTIALS или GOOGLE_APPLICATION_CREDENTIALS",
        )
    if not os.path.isfile(cred_path):
        raise FileNotFoundError(f"Файл ключа не найден: {cred_path}")

    ws = google_sheets.get_worksheet(
        spreadsheet_id,
        worksheet_title,
        credentials_path=credentials_path,
    )
    rows = ws.get_all_values()
    return _parse_table(rows)


async def fetch_ideal_references(
    spreadsheet_id: str,
    worksheet_title: str,
    *,
    credentials_path: str,
) -> dict[str, str]:
    return await asyncio.to_thread(
        fetch_ideal_references_sync,
        spreadsheet_id,
        worksheet_title,
        credentials_path=credentials_path,
    )


# Лист результатов: шапка как в операционной таблице кафедры (A–J). Одна строка = один оценённый ключ вопроса.
_RESULT_HEADER = (
    "ID сообщения",
    "ID в Telegram",
    "Название дисциплины",
    "Название контроля",
    "Дата и время начала ответа",
    "ФИО студента",
    "Оценка",
    "Номер билета",
    "Ответ на билет",
    "Комментарий",
)


def append_student_result_row_sync(
    spreadsheet_id: str,
    worksheet_title: str,
    *,
    credentials_path: str,
    row: list[Any],
) -> None:
    """Добавить строку на лист результатов; при пустом листе — записать заголовок."""
    from app.integrations import google_sheets

    cred_path = _resolve_credentials_path(credentials_path)
    if not cred_path:
        raise RuntimeError(
            "Не задан путь к JSON сервисного аккаунта: "
            "GOOGLE_SHEETS_CREDENTIALS или GOOGLE_APPLICATION_CREDENTIALS",
        )
    if not os.path.isfile(cred_path):
        raise FileNotFoundError(f"Файл ключа не найден: {cred_path}")

    ws = google_sheets.get_worksheet(
        spreadsheet_id,
        worksheet_title,
        credentials_path=credentials_path,
    )

    existing = ws.get_all_values()
    if not existing:
        ws.append_row(list(_RESULT_HEADER))
    elif existing[0] != list(_RESULT_HEADER):
        logger.warning(
            "Первая строка листа %s не совпадает с ожидаемым заголовком — строка всё равно будет добавлена",
            worksheet_title,
        )
    ws.append_row(row)


async def append_student_result_row(
    spreadsheet_id: str,
    worksheet_title: str,
    *,
    credentials_path: str,
    row: list[Any],
) -> None:
    await asyncio.to_thread(
        append_student_result_row_sync,
        spreadsheet_id,
        worksheet_title,
        credentials_path=credentials_path,
        row=row,
    )


def _clip(text: str, max_len: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + "…"


def build_result_row(
    *,
    telegram_user_id: int,
    session_id: str,
    discipline_slug: str,
    course_name: str,
    control_type: str,
    student_fio: str,
    question_key: str,
    score_display: str,
    full_transcript: str,
    answer_excerpt: str,
    rationale: str,
    telegram_message_id: int | None = None,
    ticket_number: str = "",
) -> list[Any]:
    """
    Одна строка листа students_answers. Оценка — балл 0–100 или сходство 0–1 как строка.
    Колонка «Ответ на билет» — фрагмент по данному ключу; при пустом фрагменте — обрезанный полный транскрипт.
    """
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    answer_cell = (answer_excerpt or "").strip() or (full_transcript or "").strip()
    answer_cell = _clip(answer_cell, 8000)
    comment = _clip(
        "\n".join(
            p
            for p in (
                (rationale or "").strip(),
                f"Ключ вопроса: {question_key}" if question_key else "",
                f"Код дисциплины (бот): {discipline_slug}" if discipline_slug else "",
                f"session: {session_id}" if session_id else "",
            )
            if p
        ),
        4000,
    )
    msg_id = str(telegram_message_id) if telegram_message_id is not None else ""
    return [
        msg_id,
        str(telegram_user_id),
        _clip(course_name, 500),
        _clip(control_type, 300),
        ts,
        _clip(student_fio, 300),
        score_display,
        _clip(ticket_number, 200),
        answer_cell,
        comment,
    ]


def append_with_retries(
    spreadsheet_id: str,
    worksheet_title: str,
    *,
    credentials_path: str,
    row: list[Any],
    max_attempts: int = 3,
) -> None:
    """Синхронная запись с коротким retry (идемпотентность — на стороне вызывающего)."""
    last: Exception | None = None
    for attempt in range(max_attempts):
        try:
            append_student_result_row_sync(
                spreadsheet_id,
                worksheet_title,
                credentials_path=credentials_path,
                row=row,
            )
            return
        except Exception as e:
            last = e
            logger.warning("append_student_result attempt %s/%s: %s", attempt + 1, max_attempts, e)
            time.sleep(0.4 * (attempt + 1))
    if last:
        raise last
