"""Формат строки экспорта в Google Sheets (без реального API)."""

import pytest

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


def test_parse_registration_removes_numbered_prefixes():
    raw = "1) Медицина\n2) Текущий контроль\n3) 402\n4) Петров П.П."

    assert results_export_service.parse_registration_lines(raw) == (
        "Медицина",
        "Текущий контроль",
        "402",
        "Петров П.П.",
    )


def test_aggregate_score_display_includes_mean():
    value = results_export_service._aggregate_score_display(
        [
            ("Q1", "80", "фрагмент 1", "обоснование 1"),
            ("Q2", "90", "фрагмент 2", "обоснование 2"),
        ],
    )
    assert "В1: 80" in value
    assert "В2: 90" in value
    assert "Средняя: 85.0" in value


def test_result_comment_uses_real_route_label_once():
    row = sheets_client.build_result_row(
        telegram_user_id=1,
        session_id="session-1",
        discipline_slug="Информационные технологии в здравоохранении",
        course_name="Информационные технологии в здравоохранении",
        control_type="Текущий контроль",
        student_fio="Студент",
        question_key="",
        score_display="50",
        full_transcript="ответ",
        answer_excerpt="ответ",
        rationale="Вопрос 1: 50",
    )

    assert row[10].count("Маршрут дисциплины (бот):") == 1
    assert "sample" not in row[10]


@pytest.mark.asyncio
async def test_export_deduplicates_by_session_not_message(monkeypatch):
    calls: list[tuple[str, list[object]]] = []

    monkeypatch.setattr(type(results_export_service.settings), "google_creds_path", lambda _self: "creds.json")
    monkeypatch.setattr(
        results_export_service.reference_map_service,
        "spreadsheet_id_for_discipline",
        lambda _discipline_id, registration_raw=None: "sheet-id",
    )
    monkeypatch.setattr(results_export_service, "results_worksheet_title", lambda _discipline_id: "students_answers")

    def fake_append(_sheet_id, _tab, *, credentials_path, row, dedup_key):
        calls.append((dedup_key, row))
        return True

    monkeypatch.setattr(results_export_service.sheets_client, "append_with_retries", fake_append)

    await results_export_service.export_question_scores(
        discipline_id="sample",
        telegram_user_id=42,
        session_id="session-1",
        registration_raw="Информационные технологии в здравоохранении\nТекущий контроль\n402\nСтудент",
        full_transcript="Ответ",
        scored_rows=[("1-1-1", "80", "Ответ", "Комментарий")],
        telegram_message_id=123,
    )

    assert calls[0][0] == "42:session-1"
    comment = str(calls[0][1][10])
    assert "Маршрут дисциплины (бот): Информационные технологии в здравоохранении" in comment
    assert comment.count("session: session-1") == 1
    assert "sample" not in comment


def test_documented_transcript_duplicates_registration_data():
    documented = results_export_service._documented_transcript(
        course_name="Медицина",
        control_type="Экзамен",
        group_number="Гр-12",
        student_fio="Петров П.П.",
        ticket_number="17",
        transcript="Полный ответ студента",
    )
    assert "Дисциплина: Медицина" in documented
    assert "Вид контроля: Экзамен" in documented
    assert "Группа: Гр-12" in documented
    assert "Студент: Петров П.П." in documented
    assert "Билет: 17" in documented
    assert documented.endswith("Полный ответ студента")


def test_compose_comment_for_kk_contains_translation_before_evaluation():
    comment = results_export_service._compose_comment(
        "Вопрос 1: 80\nКомментарий: оценивание",
        translation_ru="Связный русский перевод.",
        translation_attempted=True,
    )

    assert comment == (
        "Перевод на русский:\nСвязный русский перевод.\n\n"
        "Оценивание:\nВопрос 1: 80\nКомментарий: оценивание"
    )


def test_compose_comment_for_ru_keeps_previous_format():
    evaluation = "Вопрос 1: 80\nКомментарий: оценивание"
    comment = results_export_service._compose_comment(
        evaluation,
        translation_ru=None,
        translation_attempted=False,
    )
    assert comment == evaluation
    assert "Перевод на русский" not in comment


def test_compose_comment_uses_fallback_when_translation_failed():
    comment = results_export_service._compose_comment(
        "Вопрос 1: 80",
        translation_ru=None,
        translation_attempted=True,
    )
    assert "Перевод временно недоступен" in comment
    assert comment.endswith("Оценивание:\nВопрос 1: 80")


def test_long_translation_never_displaces_evaluation():
    evaluation = "Вопрос 1: 80\n" + ("Оценивание сохранено. " * 80)
    comment = results_export_service._compose_comment(
        evaluation,
        translation_ru="Очень длинный перевод. " * 1000,
        translation_attempted=True,
    )

    assert len(comment) <= sheets_client.RESULT_COMMENT_MAX_CHARS
    assert "[перевод сокращён из-за размера ячейки]" in comment
    assert comment.endswith(f"Оценивание:\n{evaluation.strip()}")


def test_oversized_evaluation_keeps_previous_clipping_behavior():
    evaluation = "О" * (sheets_client.RESULT_COMMENT_MAX_CHARS + 100)
    comment = results_export_service._compose_comment(
        evaluation,
        translation_ru="Перевод",
        translation_attempted=True,
    )
    row = sheets_client.build_result_row(
        telegram_user_id=1,
        session_id="s",
        discipline_slug="d",
        course_name="Курс",
        control_type="Экзамен",
        student_fio="Иванов И.И.",
        question_key="",
        score_display="80",
        full_transcript="исходный текст",
        answer_excerpt="исходный текст",
        rationale=comment,
    )

    assert comment == evaluation
    assert row[10].startswith("Маршрут дисциплины (бот): d\nsession: s\n")
    assert "О" * 100 in row[10]
    assert row[10].endswith("…")
    assert "Перевод" not in row[10]


@pytest.mark.asyncio
async def test_export_keeps_original_in_j_and_translation_only_in_k(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(type(results_export_service.settings), "google_creds_path", lambda _self: "fake.json")
    monkeypatch.setattr(
        results_export_service.reference_map_service,
        "spreadsheet_id_for_discipline",
        lambda *_args, **_kwargs: "sheet-id",
    )
    monkeypatch.setattr(results_export_service, "results_worksheet_title", lambda _discipline_id: "students_answers")

    def fake_append(_sheet_id, _tab, *, credentials_path, row, dedup_key):
        captured["row"] = row
        return True

    monkeypatch.setattr(results_export_service.sheets_client, "append_with_retries", fake_append)

    source = "Қазақша бастапқы жауап және русский фрагмент."
    translation = "Очень длинный перевод. " * 1000
    await results_export_service.export_question_scores(
        discipline_id="management",
        telegram_user_id=1,
        session_id="sess-1",
        registration_raw="Менеджмент\nЭкзамен\n101\nИванов Иван",
        full_transcript=source,
        scored_rows=[("Q1", "80", source, "Комментарий оценки")],
        translation_ru=translation,
        translation_attempted=True,
    )

    row = captured["row"]
    assert source in row[9]
    assert translation not in row[9]
    assert row[10].startswith("Маршрут дисциплины (бот): Менеджмент\nsession: sess-1\n")
    assert row[10].index("Перевод на русский:") < row[10].index("Оценивание:")
    assert "[перевод сокращён из-за размера ячейки]" in row[10]
    assert "Оценивание:\nВопрос 1: 80" in row[10]
    assert row[10].endswith("Комментарий оценки")
    assert len(row[10]) <= sheets_client.RESULT_COMMENT_MAX_CHARS
