"""Нечёткое сопоставление названия дисциплины из регистрации с ключами в .env."""

from app.core import config as cfg


def test_fuzzy_typo_in_course_name(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Экономика и маркетинг в сестринском деле":"id-econ"}',
        raising=False,
    )
    monkeypatch.setattr(cfg.settings, "discipline_course_name_match_threshold", 0.48, raising=False)
    raw = "Эканомика и маркетинг в сестринском деле\nЭкзамен\n1\nИванов"
    assert cfg.settings.spreadsheet_id_for_registration_course(raw) == "id-econ"


def test_fuzzy_word_order_abbreviation(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Информационные технологии в здравоохранении":"id-it"}',
        raising=False,
    )
    monkeypatch.setattr(cfg.settings, "discipline_course_name_match_threshold", 0.45, raising=False)
    raw = "технологии информационные здравоохранение"
    assert cfg.settings.spreadsheet_id_for_registration_course(raw) == "id-it"
