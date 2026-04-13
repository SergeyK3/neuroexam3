"""Формат строки экспорта в Google Sheets (без реального API)."""

from app.integrations import sheets_client
from app.services import results_export_service


def test_build_result_row_matches_header_len():
    row = sheets_client.build_result_row(
        telegram_user_id=1,
        session_id="s",
        discipline_slug="d",
        course_name="Курс",
        control_type="Экзамен",
        student_fio="Иванов И.И.",
        question_key="Q1",
        score_display="85",
        full_transcript="полный текст",
        answer_excerpt="фрагмент",
        rationale="обоснование",
    )
    assert len(row) == len(sheets_client._RESULT_HEADER)
    assert row[9] == "фрагмент"


def test_parse_registration_three_lines_legacy_no_group():
    raw = "Медицина\nЭкзамен\nПетров П.П."
    a, b, g, c = results_export_service._parse_registration_lines(raw)
    assert a == "Медицина"
    assert b == "Экзамен"
    assert g == ""
    assert c == "Петров П.П."


def test_parse_registration_four_lines():
    raw = "Медицина\nЭкзамен\nГр-12\nПетров П.П."
    a, b, g, c = results_export_service._parse_registration_lines(raw)
    assert a == "Медицина"
    assert b == "Экзамен"
    assert g == "Гр-12"
    assert c == "Петров П.П."
