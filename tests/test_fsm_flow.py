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


def test_registration_accumulates_over_messages():
    s = ExamSession(user_id=5, state=ExamState.REGISTRATION, language="ru")
    out = fsm_service.process_message(s, text="Информатика в медицине", has_voice=False, is_start_command=False)
    assert out.session.state == ExamState.REGISTRATION
    assert "(1/3)" in "\n".join(out.messages)
    assert len(out.session.registration_parts) == 1

    out2 = fsm_service.process_message(out.session, text="Экзамен", has_voice=False, is_start_command=False)
    assert out2.session.state == ExamState.REGISTRATION
    assert "(2/3)" in "\n".join(out2.messages)

    out3 = fsm_service.process_message(out2.session, text="Иванов Иван Иванович", has_voice=False, is_start_command=False)
    assert out3.session.state == ExamState.ANSWERING
    raw = out3.session.registration_raw or ""
    assert "Информатика" in raw and "Экзамен" in raw and "Иванов" in raw


def test_registration_one_message_three_lines():
    s = ExamSession(user_id=55, state=ExamState.REGISTRATION, language="ru")
    out = fsm_service.process_message(
        s,
        text="Информатика\nЭкзамен\nИванов Иван Иванович",
        has_voice=False,
        is_start_command=False,
    )
    assert out.session.state == ExamState.ANSWERING
    assert "Информатика" in (out.session.registration_raw or "")


def test_registration_three_parts_semicolon():
    s = ExamSession(user_id=6, state=ExamState.REGISTRATION, language="ru")
    out = fsm_service.process_message(
        s,
        text="Информатика; рубежный контроль; Иванов Иван Иванович",
        has_voice=False,
        is_start_command=False,
    )
    assert out.session.state == ExamState.ANSWERING
