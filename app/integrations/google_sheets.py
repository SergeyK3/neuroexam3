"""Google Sheets: подключение сервисным аккаунтом и запись строк ответов студента."""

from __future__ import annotations

import os
from typing import Any

from app.core.config import settings


def results_worksheet_title(discipline_id: str | None = None) -> str:
    """Имя листа с ответами: ``GOOGLE_SHEET_RESULTS_TAB`` или переопределение из ``DISCIPLINE_RESULTS_TABS_JSON``."""
    return settings.results_worksheet_for_discipline(discipline_id)


def resolve_credentials_path(explicit: str | None = None) -> str:
    """
    Путь к JSON ключа: явный аргумент, иначе GOOGLE_SHEETS_CREDENTIALS / GOOGLE_APPLICATION_CREDENTIALS из настроек.
    """
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    return settings.google_creds_path()


def _require_existing_json(path: str) -> str:
    p = path.strip()
    if not p:
        raise RuntimeError(
            "Не задан путь к JSON сервисного аккаунта: "
            "GOOGLE_SHEETS_CREDENTIALS или GOOGLE_APPLICATION_CREDENTIALS",
        )
    if not os.path.isfile(p):
        raise FileNotFoundError(f"Файл ключа не найден: {p}")
    return p


def open_gspread_client(*, credentials_path: str | None = None) -> Any:
    """Клиент gspread (service account)."""
    try:
        import gspread
    except ImportError as e:
        raise RuntimeError("Установите пакеты: gspread google-auth") from e

    path = _require_existing_json(resolve_credentials_path(credentials_path))
    return gspread.service_account(filename=path)


def open_spreadsheet_by_id(spreadsheet_id: str, *, credentials_path: str | None = None) -> Any:
    """Открыть таблицу по id (фрагмент из URL между /d/ и /edit)."""
    gc = open_gspread_client(credentials_path=credentials_path)
    return gc.open_by_key(spreadsheet_id)


def open_spreadsheet_by_url(url: str, *, credentials_path: str | None = None) -> Any:
    """Открыть таблицу по полному URL (как в браузере)."""
    gc = open_gspread_client(credentials_path=credentials_path)
    return gc.open_by_url(url)


def get_worksheet(
    spreadsheet_id: str,
    worksheet_title: str,
    *,
    credentials_path: str | None = None,
) -> Any:
    """Лист по названию; при отсутствии — понятная ошибка со списком листов."""
    try:
        from gspread.exceptions import WorksheetNotFound
    except ImportError as e:
        raise RuntimeError("Установите пакеты: gspread google-auth") from e

    sh = open_spreadsheet_by_id(spreadsheet_id, credentials_path=credentials_path)
    try:
        return sh.worksheet(worksheet_title)
    except WorksheetNotFound as e:
        titles = [w.title for w in sh.worksheets()]
        raise RuntimeError(
            f"Лист «{worksheet_title}» не найден. Доступные: {titles}",
        ) from e


def append_student_answer_row(
    spreadsheet_id: str,
    worksheet_title: str,
    row: list[Any],
    *,
    credentials_path: str | None = None,
) -> None:
    """
    Дописать одну строку на лист результатов (заголовок при пустом листе — как в sheets_client).

    Готовую строку можно собрать через ``build_student_answer_row`` (те же поля, что в экспорте бота).
    """
    from app.integrations import sheets_client

    creds = resolve_credentials_path(credentials_path)
    sheets_client.append_student_result_row_sync(
        spreadsheet_id,
        worksheet_title,
        credentials_path=creds,
        row=row,
    )


def build_student_answer_row(
    *,
    telegram_user_id: int,
    session_id: str,
    discipline_slug: str,
    course_name: str,
    control_type: str,
    group_number: str = "",
    student_fio: str,
    question_key: str,
    score_display: str,
    full_transcript: str,
    answer_excerpt: str,
    rationale: str,
    telegram_message_id: int | None = None,
    ticket_number: str = "",
) -> list[Any]:
    """Собрать список ячеек одной строки (обёртка над sheets_client.build_result_row)."""
    from app.integrations.sheets_client import build_result_row

    return build_result_row(
        telegram_user_id=telegram_user_id,
        session_id=session_id,
        discipline_slug=discipline_slug,
        course_name=course_name,
        control_type=control_type,
        group_number=group_number,
        student_fio=student_fio,
        question_key=question_key,
        score_display=score_display,
        full_transcript=full_transcript,
        answer_excerpt=answer_excerpt,
        rationale=rationale,
        telegram_message_id=telegram_message_id,
        ticket_number=ticket_number,
    )


def first_empty_row_in_column_a(worksheet: Any, *, min_row: int = 2) -> int:
    """Номер первой пустой строки в колонке A (1-based), не ниже ``min_row``."""
    col = worksheet.col_values(1)
    last = len(col)
    return max(min_row, last + 1)


def write_range(
    worksheet: Any,
    range_a1: str,
    values: list[list[Any]],
) -> None:
    """Записать значения в диапазон A1-нотация (обёртка над worksheet.update)."""
    worksheet.update(range_name=range_a1, values=values)
