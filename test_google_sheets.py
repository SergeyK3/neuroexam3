"""Ручная проверка модуля app.integrations.google_sheets.

Запуск из корня проекта (PowerShell):
  python .\\test_google_sheets.py

Нужен .env с GOOGLE_SHEETS_CREDENTIALS и доступ к таблице у сервисного аккаунта.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

from gspread.exceptions import APIError

from app.integrations.google_sheets import (
    append_student_answer_row,
    build_student_answer_row,
    first_empty_row_in_column_a,
    open_spreadsheet_by_url,
    results_worksheet_title,
    write_range,
)


SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1V7S6MgpF0uGNR5zNbhCoUgY5GhjR8383Ce6cWX0LrKY/edit"


def main() -> None:
    tab = results_worksheet_title()
    try:
        spreadsheet = open_spreadsheet_by_url(SPREADSHEET_URL)
    except APIError as e:
        err = str(e)
        if "403" in err or "has not been used" in err or "disabled" in err.lower():
            print(
                "Включите Google Sheets API в проекте GCP ключа:\n"
                "https://console.developers.google.com/apis/api/sheets.googleapis.com/overview",
                file=sys.stderr,
            )
            sys.exit(1)
        raise
    except PermissionError as e:
        detail = str(e.__cause__) if e.__cause__ else str(e)
        if "403" in detail or "has not been used" in detail:
            print(
                "Включите Google Sheets API (и при необходимости Drive API) для проекта ключа.",
                file=sys.stderr,
            )
            sys.exit(1)
        raise

    print("Таблица открыта:", spreadsheet.title)
    print("Лист результатов (GOOGLE_SHEET_RESULTS_TAB):", tab)

    try:
        worksheet = spreadsheet.worksheet(tab)
    except Exception:
        print(
            f"Лист «{tab}» не найден. Создайте вкладку с этим именем или задайте GOOGLE_SHEET_RESULTS_TAB. "
            f"Доступные: {[w.title for w in spreadsheet.worksheets()]}",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Лист:", worksheet.title)

    target_row = first_empty_row_in_column_a(worksheet, min_row=2)
    print("Первая свободная строка (колонка A):", target_row)

    test_range = f"A{target_row}:B{target_row}"
    write_range(worksheet, test_range, [["test_student", "test_answer"]])
    print(f"Тестовая запись в {test_range}")

    row = build_student_answer_row(
        telegram_user_id=0,
        session_id="manual-test",
        discipline_slug="test",
        course_name="Курс",
        control_type="Экзамен",
        student_fio="Тестов Т.Т.",
        question_key="Q1",
        score_display="100",
        full_transcript="полный текст ответа",
        answer_excerpt="фрагмент",
        rationale="обоснование тест",
    )
    sid = spreadsheet.id
    append_student_answer_row(
        sid,
        tab,
        row,
    )
    print("Строка результата добавлена через append_student_answer_row (формат как у бота).")


if __name__ == "__main__":
    main()
