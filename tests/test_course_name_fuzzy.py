"""Нечёткое сопоставление названия дисциплины из регистрации с ключами в .env."""

from app.core import config as cfg
import pytest


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


def test_ai_abbreviation_matches_full_course_name(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Искусственный интеллект в здравоохранении":"id-ai"}',
        raising=False,
    )
    raw = "ИИ в здравоохранении\nЭкзамен\n1\nИванов"
    assert cfg.settings.spreadsheet_id_for_registration_course(raw) == "id-ai"


@pytest.mark.parametrize(
    "entered",
    [
        "Мед статистика",
        "  МЕДИЦИНСКАЯ   СТАТИСТИКА  ",
        "Медстатистика",
    ],
)
def test_medical_statistics_aliases_match_only_configured_full_course(monkeypatch, entered):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        (
            '{"Медицинская статистика (Статистические методы анализа данных)":"id-medstat",'
            '"Медицинская информатика":"id-medinfo"}'
        ),
        raising=False,
    )

    assert cfg.settings.spreadsheet_id_for_registration_course(entered) == "id-medstat"


def test_medical_statistics_alias_does_not_match_without_its_full_course(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Медицинская информатика":"id-medinfo"}',
        raising=False,
    )

    assert cfg.settings.spreadsheet_id_for_registration_course("Мед статистика") is None


def test_generic_course_words_do_not_select_another_discipline(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        (
            '{"Информационные технологии в здравоохранении":"id-it",'
            '"Искусственный интеллект в здравоохранении":"id-ai"}'
        ),
        raising=False,
    )
    monkeypatch.setattr(cfg.settings, "discipline_course_name_match_threshold", 0.45, raising=False)

    raw = "Цифровые технологии в здравоохранении\nТекущий контроль\n402\nСтудент"

    assert cfg.settings.spreadsheet_id_for_registration_course(raw) is None


def test_short_generic_substring_does_not_select_information_technology(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Информационные технологии в здравоохранении":"id-it"}',
        raising=False,
    )

    assert cfg.settings.spreadsheet_id_for_registration_course("Технологии в здравоохранении") is None


def test_abbreviated_information_technology_course_is_still_recognized(monkeypatch):
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Информационные технологии в здравоохранении":"id-it"}',
        raising=False,
    )
    monkeypatch.setattr(cfg.settings, "discipline_course_name_match_threshold", 0.45, raising=False)

    raw = "Инф технологии в здрав\nТекущий контроль\n402\nСтудент"

    assert cfg.settings.spreadsheet_id_for_registration_course(raw) == "id-it"
