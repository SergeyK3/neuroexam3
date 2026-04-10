"""Тесты загрузки эталонов (mock Google)."""

import pytest

from app.core import config as cfg
from app.services import reference_map_service


@pytest.mark.asyncio
async def test_get_reference_map_uses_env_when_no_sheets(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheets_credentials", "", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_id", "", raising=False)
    monkeypatch.setattr(cfg.settings, "discipline_google_sheet_ids_json", "", raising=False)
    monkeypatch.setattr(cfg.settings, "mvp_references_json", '{"X":"refx"}', raising=False)

    m = await reference_map_service.get_reference_map(None)
    assert m == {"X": "refx"}


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

    m = await reference_map_service.get_reference_map(None)
    assert m == {"Q1": "from_sheet"}
