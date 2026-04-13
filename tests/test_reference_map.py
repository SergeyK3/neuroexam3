"""Тесты загрузки эталонов (mock Google)."""

import pytest

from app.core import config as cfg
from app.integrations.sheets_client import _parse_question_bank, _parse_table
from app.models.question_bank import QuestionRecord
from app.services import reference_map_service


def test_parse_ideal_table_russian_headers_skips_header_row():
    """Шапка «Ключ» + «Идеальный ответ» должна не попадать в словарь как ключ «Ключ»."""
    rows = [
        ["Ключ", "Идеальный ответ"],
        ["1-2-3", "Эталонный текст про ЭМК"],
    ]
    m = _parse_table(rows)
    assert m == {"1-2-3": "Эталонный текст про ЭМК"}
    assert "Ключ" not in m


def test_parse_ideal_table_infers_ref_col_when_only_key_header_matches():
    rows = [
        ["Ключ вопроса", "Произвольная подпись без слова эталон"],
        ["10-20-30", "Длинный эталон"],
    ]
    m = _parse_table(rows)
    assert m == {"10-20-30": "Длинный эталон"}


def test_parse_question_bank_reads_question_text():
    rows = [
        ["Ключ", "Вопрос", "Идеальный ответ"],
        ["2-7-4", "Объясните применение ИИ в роботизированной хирургии.", "ИИ повышает точность движений."],
    ]
    bank = _parse_question_bank(rows)
    assert bank == [
        QuestionRecord(
            question_key="2-7-4",
            question_text="Объясните применение ИИ в роботизированной хирургии.",
            reference_answer="ИИ повышает точность движений.",
        ),
    ]


def test_parse_ideal_table_placeholder_row_skipped_in_fallback_mode():
    """Если шапка не распознана, строка с ключом «Ключ» не должна давать запись в словаре."""
    rows = [
        ["Ключ", "Колонка2"],
        ["5-5-5", "Нормальный эталон"],
    ]
    m = _parse_table(rows)
    assert "Ключ" not in m
    assert m.get("5-5-5") == "Нормальный эталон"

@pytest.mark.asyncio
async def test_get_reference_map_uses_env_when_no_sheets(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheets_credentials", "", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_id", "", raising=False)
    monkeypatch.setattr(cfg.settings, "discipline_google_sheet_ids_json", "", raising=False)
    monkeypatch.setattr(cfg.settings, "mvp_references_json", '{"X":"refx"}', raising=False)

    m = await reference_map_service.get_reference_map(None)
    assert m == {"X": "refx"}


@pytest.mark.asyncio
async def test_get_question_bank_uses_env_when_no_sheets(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheets_credentials", "", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_id", "", raising=False)
    monkeypatch.setattr(cfg.settings, "discipline_google_sheet_ids_json", "", raising=False)
    monkeypatch.setattr(cfg.settings, "mvp_references_json", '{"X":"refx"}', raising=False)

    bank = await reference_map_service.get_question_bank(None)
    assert len(bank) == 1
    assert bank[0].question_key == "X"
    assert bank[0].reference_answer == "refx"


@pytest.mark.asyncio
async def test_get_reference_map_calls_sheet_when_configured(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheets_credentials", "/fake/path.json", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_id", "abc123", raising=False)
    monkeypatch.setattr(cfg.settings, "discipline_google_sheet_ids_json", "", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_ideal_tab", "ideal_answers", raising=False)

    async def fake_fetch(sheet_id: str, tab: str, *, credentials_path: str):
        assert sheet_id == "abc123"
        return {"Q1": "from_sheet"}

    monkeypatch.setattr(
        "app.services.reference_map_service.fetch_ideal_references",
        fake_fetch,
    )

    m = await reference_map_service.get_reference_map(None, registration_raw=None)
    assert m == {"Q1": "from_sheet"}


@pytest.mark.asyncio
async def test_get_reference_map_prefers_course_name_map(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheets_credentials", "/fake/path.json", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_id", "", raising=False)
    monkeypatch.setattr(cfg.settings, "discipline_google_sheet_ids_json", '{"x":"wrongid"}', raising=False)
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Экономика и маркетинг в сестринском деле":"sheet-from-name"}',
        raising=False,
    )
    monkeypatch.setattr(cfg.settings, "google_sheet_ideal_tab", "ideal_answers", raising=False)

    seen: list[tuple[str, str]] = []

    async def fake_fetch(sheet_id: str, tab: str, *, credentials_path: str):
        seen.append((sheet_id, tab))
        return {"Q1": "from_named_sheet"}

    monkeypatch.setattr(
        "app.services.reference_map_service.fetch_ideal_references",
        fake_fetch,
    )

    m = await reference_map_service.get_reference_map(
        "x",
        registration_raw="Экономика и маркетинг в сестринском деле\nЭкзамен\n101\nИванов",
    )
    assert m == {"Q1": "from_named_sheet"}
    assert seen == [("sheet-from-name", "ideal_answers")]
