"""FSM: язык, выбор дисциплины, регистрация."""

import pytest

from app.core import config as cfg
from app.models.session import ExamSession, ExamState
from app.services import fsm_service


def test_language_then_discipline_when_multiple_sheets(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_google_sheet_ids_json",
        '{"b":"id1","a":"id2"}',
        raising=False,
    )
    s = ExamSession(user_id=1)
    s.state = ExamState.LANGUAGE
    out = fsm_service.process_message(s, text="1", has_voice=False, is_start_command=False)
    assert out.session.language == "ru"
    assert out.session.state == ExamState.DISCIPLINE
    assert "a" in "\n".join(out.messages) and "b" in "\n".join(out.messages)

    out2 = fsm_service.process_message(out.session, text="2", has_voice=False, is_start_command=False)
    assert out2.session.discipline_id == "b"
    assert out2.session.state == ExamState.REGISTRATION


def test_discipline_pick_by_slug(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_google_sheet_ids_json",
        '{"neuro":"x","bio":"y"}',
        raising=False,
    )
    s = ExamSession(user_id=2, state=ExamState.DISCIPLINE, language="ru")
    out = fsm_service.process_message(s, text="NEURO", has_voice=False, is_start_command=False)
    assert out.session.discipline_id == "neuro"
    assert out.session.state == ExamState.REGISTRATION


def test_single_discipline_skips_step(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_google_sheet_ids_json",
        '{"only":"sheet1"}',
        raising=False,
    )
    s = ExamSession(user_id=3, state=ExamState.LANGUAGE)
    out = fsm_service.process_message(s, text="ru", has_voice=False, is_start_command=False)
    assert out.session.discipline_id == "only"
    assert out.session.state == ExamState.REGISTRATION


def test_english_language_alias():
    s = ExamSession(user_id=4, state=ExamState.LANGUAGE)
    out = fsm_service.process_message(s, text="English", has_voice=False, is_start_command=False)
    assert out.session.language == "en"


def test_start_returns_welcome_and_language_prompt_in_english():
    s = ExamSession(user_id=40)
    out = fsm_service.process_message(
        s,
        text="/start",
        has_voice=False,
        is_start_command=True,
        reply_language="en",
        include_welcome=True,
    )
    assert len(out.messages) == 2
    assert "deep breaths" in out.messages[0]
    assert "choose the exam language" in out.messages[1].lower()


def test_hint_request_gets_refusal_in_answering():
    s = ExamSession(user_id=41, state=ExamState.ANSWERING, language="ru")
    out = fsm_service.process_message(
        s,
        text="Подскажи правильный ответ, пожалуйста",
        has_voice=False,
        is_start_command=False,
    )
    assert out.evaluate_text is None
    assert "не могу" in out.messages[0].lower()


def test_registration_accumulates_over_messages(monkeypatch):
    monkeypatch.setattr(cfg.settings, "discipline_course_name_sheet_ids_json", "", raising=False)
    s = ExamSession(user_id=5, state=ExamState.REGISTRATION, language="ru")
    out = fsm_service.process_message(s, text="Информатика в медицине", has_voice=False, is_start_command=False)
    assert out.session.state == ExamState.REGISTRATION
    assert "(1/4)" in "\n".join(out.messages)
    assert len(out.session.registration_parts) == 1

    out2 = fsm_service.process_message(out.session, text="Экзамен", has_voice=False, is_start_command=False)
    assert out2.session.state == ExamState.REGISTRATION
    assert "(2/4)" in "\n".join(out2.messages)

    out_g = fsm_service.process_message(out2.session, text="Гр-5", has_voice=False, is_start_command=False)
    assert out_g.session.state == ExamState.REGISTRATION
    assert "(3/4)" in "\n".join(out_g.messages)

    out3 = fsm_service.process_message(out_g.session, text="Иванов Иван Иванович", has_voice=False, is_start_command=False)
    assert out3.session.state == ExamState.ANSWERING
    raw = out3.session.registration_raw or ""
    assert "Информатика" in raw and "Экзамен" in raw and "Гр-5" in raw and "Иванов" in raw


def test_registration_one_message_four_lines(monkeypatch):
    monkeypatch.setattr(cfg.settings, "discipline_course_name_sheet_ids_json", "", raising=False)
    s = ExamSession(user_id=55, state=ExamState.REGISTRATION, language="ru")
    out = fsm_service.process_message(
        s,
        text="Информатика\nЭкзамен\n101\nИванов Иван Иванович",
        has_voice=False,
        is_start_command=False,
    )
    assert out.session.state == ExamState.ANSWERING
    assert "Информатика" in (out.session.registration_raw or "")
    assert "101" in (out.session.registration_raw or "")


def test_registration_four_parts_semicolon(monkeypatch):
    monkeypatch.setattr(cfg.settings, "discipline_course_name_sheet_ids_json", "", raising=False)
    s = ExamSession(user_id=6, state=ExamState.REGISTRATION, language="ru")
    out = fsm_service.process_message(
        s,
        text="Информатика; рубежный контроль; Гр-2; Иванов Иван Иванович",
        has_voice=False,
        is_start_command=False,
    )
    assert out.session.state == ExamState.ANSWERING


def test_full_numbered_registration_replaces_partial_input_without_shift():
    s = ExamSession(user_id=7, state=ExamState.REGISTRATION, language="ru")
    partial = fsm_service.process_message(
        s,
        text="Инф технологии в здрав",
        has_voice=False,
        is_start_command=False,
    )

    out = fsm_service.process_message(
        partial.session,
        text=(
            "1) Информационные технологии в здравоохранении\n"
            "2) Текущий контроль\n"
            "3) 402\n"
            "4) Иванов Иван Иванович"
        ),
        has_voice=False,
        is_start_command=False,
    )

    assert out.session.state == ExamState.ANSWERING
    assert out.session.registration_raw == (
        "Информационные технологии в здравоохранении\n"
        "Текущий контроль\n"
        "402\n"
        "Иванов Иван Иванович"
    )


def test_numbered_registration_prefixes_are_not_saved_as_field_values(monkeypatch):
    monkeypatch.setattr(cfg.settings, "discipline_course_name_sheet_ids_json", "", raising=False)
    s = ExamSession(user_id=8, state=ExamState.REGISTRATION, language="ru")

    out = fsm_service.process_message(
        s,
        text="1 Курс\n2 Контроль\n3 402\n4 Студент",
        has_voice=False,
        is_start_command=False,
    )

    assert out.session.registration_raw == "Курс\nКонтроль\n402\nСтудент"


def test_unknown_course_is_rejected_before_answering(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        (
            '{"Информационные технологии в здравоохранении":"it",'
            '"Искусственный интеллект в здравоохранении":"ai"}'
        ),
        raising=False,
    )
    s = ExamSession(user_id=9, state=ExamState.REGISTRATION, language="ru")

    out = fsm_service.process_message(
        s,
        text="Цифровые технологии в здравоохранении\nТекущий контроль\n402\nСтудент",
        has_voice=False,
        is_start_command=False,
    )

    assert out.session.state == ExamState.REGISTRATION
    assert out.session.registration_raw is None
    assert out.session.registration_parts == ["", "Текущий контроль", "402", "Студент"]
    assert "не распознано" in out.messages[0]
    assert "Информационные технологии в здравоохранении" in out.messages[0]


def test_medical_statistics_alias_in_four_fields_message_routes_to_answering(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Медицинская статистика (Статистические методы анализа данных)":"id-medstat"}',
        raising=False,
    )
    s = ExamSession(user_id=10, state=ExamState.REGISTRATION, language="ru")

    out = fsm_service.process_message(
        s,
        text="Мед статистика, Рубежный 1, 12 группа, Тестов Тест Тестович",
        has_voice=False,
        is_start_command=False,
    )

    assert out.session.state == ExamState.ANSWERING
    assert out.session.registration_raw == (
        "Мед статистика\nРубежный 1\n12 группа\nТестов Тест Тестович"
    )
    assert cfg.settings.spreadsheet_id_for_registration_course(out.session.registration_raw) == "id-medstat"


def test_medical_statistics_alias_in_separate_messages_routes_to_answering(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Медицинская статистика (Статистические методы анализа данных)":"id-medstat"}',
        raising=False,
    )
    s = ExamSession(user_id=11, state=ExamState.REGISTRATION, language="ru")

    for text in ("Медицинская статистика", "Рубежный 1", "12", "Тестов Тест"):
        out = fsm_service.process_message(
            s,
            text=text,
            has_voice=False,
            is_start_command=False,
        )
        s = out.session

    assert s.state == ExamState.ANSWERING
    assert cfg.settings.spreadsheet_id_for_registration_course(s.registration_raw) == "id-medstat"


def test_unknown_course_retry_preserves_other_registration_fields(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Медицинская статистика (Статистические методы анализа данных)":"id-medstat"}',
        raising=False,
    )
    s = ExamSession(user_id=12, state=ExamState.REGISTRATION, language="ru")

    rejected = fsm_service.process_message(
        s,
        text="Неизвестный курс; Рубежный 1; 12 группа; Тестов Тест Тестович",
        has_voice=False,
        is_start_command=False,
    )

    assert rejected.session.registration_parts == ["", "Рубежный 1", "12 группа", "Тестов Тест Тестович"]
    assert "только название дисциплины" in rejected.messages[0]

    accepted = fsm_service.process_message(
        rejected.session,
        text="Медстатистика",
        has_voice=False,
        is_start_command=False,
    )

    assert accepted.session.state == ExamState.ANSWERING
    assert accepted.session.registration_raw == (
        "Медстатистика\nРубежный 1\n12 группа\nТестов Тест Тестович"
    )
