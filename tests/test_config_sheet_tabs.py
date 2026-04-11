"""Имена листов: общие и переопределения по дисциплине."""

from app.core import config as cfg


def test_ideal_tab_default(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheet_ideal_tab", "ideal_answers", raising=False)
    monkeypatch.setattr(cfg.settings, "discipline_ideal_tabs_json", "", raising=False)
    monkeypatch.setattr(cfg.settings, "default_discipline", "x", raising=False)
    assert cfg.settings.ideal_worksheet_for_discipline("any") == "ideal_answers"


def test_ideal_tab_override_per_slug(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheet_ideal_tab", "ideal_answers", raising=False)
    monkeypatch.setattr(
        cfg.settings,
        "discipline_ideal_tabs_json",
        '{"aizdrav":"Sheet_Ai_Ideal"}',
        raising=False,
    )
    assert cfg.settings.ideal_worksheet_for_discipline("aizdrav") == "Sheet_Ai_Ideal"
    assert cfg.settings.ideal_worksheet_for_discipline("sample") == "ideal_answers"


def test_results_tab_override(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheet_results_tab", "students_answers", raising=False)
    monkeypatch.setattr(
        cfg.settings,
        "discipline_results_tabs_json",
        '{"econ":"Econ_results_tab"}',
        raising=False,
    )
    assert cfg.settings.results_worksheet_for_discipline("econ") == "Econ_results_tab"
    assert cfg.settings.results_worksheet_for_discipline("sample") == "students_answers"
