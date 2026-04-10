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
    cred_path = _resolve_credentials_path(credentials_path)
    if not cred_path:
        raise RuntimeError(
            "Не задан путь к JSON сервисного аккаунта: "
            "GOOGLE_SHEETS_CREDENTIALS или GOOGLE_APPLICATION_CREDENTIALS",
        )
    if not os.path.isfile(cred_path):
        raise FileNotFoundError(f"Файл ключа не найден: {cred_path}")

    try:
        import gspread
    except ImportError as e:
        raise RuntimeError("Установите пакеты: gspread google-auth") from e

    gc = gspread.service_account(filename=cred_path)
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_title)
    except Exception as e:
        raise RuntimeError(
            f"Лист «{worksheet_title}» не найден. Доступные: {[w.title for w in sh.worksheets()]}",
        ) from e
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


_RESULT_HEADER = (
    "timestamp_utc",
    "telegram_user_id",
    "session_id",
    "discipline_slug",
    "question_key",
    "score",
    "answer_excerpt",
)


def append_student_result_row_sync(
    spreadsheet_id: str,
    worksheet_title: str,
    *,
    credentials_path: str,
    row: list[Any],
) -> None:
    """Добавить строку на лист результатов; при пустом листе — записать заголовок."""
    cred_path = _resolve_credentials_path(credentials_path)
    if not cred_path:
        raise RuntimeError(
            "Не задан путь к JSON сервисного аккаунта: "
            "GOOGLE_SHEETS_CREDENTIALS или GOOGLE_APPLICATION_CREDENTIALS",
        )
    if not os.path.isfile(cred_path):
        raise FileNotFoundError(f"Файл ключа не найден: {cred_path}")

    try:
        import gspread
    except ImportError as e:
        raise RuntimeError("Установите пакеты: gspread google-auth") from e

    gc = gspread.service_account(filename=cred_path)
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_title)
    except Exception as e:
        raise RuntimeError(
            f"Лист «{worksheet_title}» не найден. Доступные: {[w.title for w in sh.worksheets()]}",
        ) from e

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


def build_result_row(
    *,
    telegram_user_id: int,
    session_id: str,
    discipline_slug: str,
    question_key: str,
    score_display: str,
    answer_excerpt: str,
) -> list[Any]:
    """Одна строка для student_answers (без эталонов). score_display — балл 0–100 или сходство 0–1 как строка."""
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    excerpt = (answer_excerpt or "").strip()
    if len(excerpt) > 2000:
        excerpt = excerpt[:2000] + "…"
    return [ts, str(telegram_user_id), session_id, discipline_slug, question_key, score_display, excerpt]


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
