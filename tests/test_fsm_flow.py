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
