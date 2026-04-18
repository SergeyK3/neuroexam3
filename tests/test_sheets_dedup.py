"""Идемпотентная запись в Google Sheets: колонка Dedup Key и повторный вызов."""

from __future__ import annotations

from typing import Any

import pytest

from app.integrations import sheets_client


class _FakeWorksheet:
    def __init__(self, rows: list[list[str]] | None = None) -> None:
        self.rows: list[list[str]] = list(rows or [])

    def get_all_values(self) -> list[list[str]]:
        return [list(r) for r in self.rows]

    def append_row(self, row: list[Any]) -> None:
        self.rows.append([str(c) if c is not None else "" for c in row])


def _patch_worksheet(monkeypatch, ws: _FakeWorksheet) -> None:
    def _fake_get_worksheet(_spreadsheet_id, _title, *, credentials_path):  # noqa: ARG001
        return ws

    import app.integrations.google_sheets as google_sheets

    monkeypatch.setattr(google_sheets, "get_worksheet", _fake_get_worksheet)
    monkeypatch.setattr(
        sheets_client,
        "_resolve_credentials_path",
        lambda explicit: explicit or "fake.json",
    )
    monkeypatch.setattr("os.path.isfile", lambda _p: True)


def _make_row(key_value: str = "demo") -> list[Any]:
    # 11 колонок "основной" шапки, порядок значений не принципиален для теста.
    return ["msg1", "42", "Курс", "Контроль", "2025-01-01", "Гр-1", "ФИО", "80", "Билет 1", f"ответ {key_value}", "комм."]


def test_empty_sheet_creates_header_with_dedup_column(monkeypatch):
    ws = _FakeWorksheet()
    _patch_worksheet(monkeypatch, ws)

    appended = sheets_client.append_student_result_row_sync(
        "sid", "tab", credentials_path="k", row=_make_row(), dedup_key="U1:S1:M1",
    )
    assert appended is True
    assert len(ws.rows) == 2
    assert ws.rows[0][-1] == "Dedup Key"
    assert ws.rows[1][-1] == "U1:S1:M1"


def test_duplicate_dedup_key_is_skipped(monkeypatch):
    ws = _FakeWorksheet()
    _patch_worksheet(monkeypatch, ws)

    first = sheets_client.append_with_retries(
        "sid", "tab", credentials_path="k", row=_make_row("first"), dedup_key="U1:S1:M1",
    )
    second = sheets_client.append_with_retries(
        "sid", "tab", credentials_path="k", row=_make_row("second"), dedup_key="U1:S1:M1",
    )
    third = sheets_client.append_with_retries(
        "sid", "tab", credentials_path="k", row=_make_row("third"), dedup_key="U1:S1:M2",
    )
    assert first is True
    assert second is False, "повторный вызов с тем же dedup_key должен быть no-op"
    assert third is True

    # строка шапки + две уникальные записи
    assert len(ws.rows) == 3


def test_legacy_11_column_sheet_still_accepts_writes(monkeypatch):
    """Существующие листы без колонки Dedup Key продолжают работать (обратная совместимость)."""
    ws = _FakeWorksheet([list(sheets_client._RESULT_HEADER)])
    _patch_worksheet(monkeypatch, ws)

    appended = sheets_client.append_student_result_row_sync(
        "sid", "tab", credentials_path="k", row=_make_row(), dedup_key="U1:S1:M1",
    )
    assert appended is True
    assert len(ws.rows) == 2
    # В старой шапке колонки Dedup Key нет → в строке её тоже не должно появиться.
    assert len(ws.rows[1]) == len(sheets_client._RESULT_HEADER)


def test_legacy_sheet_without_dedup_key_does_not_dedup(monkeypatch):
    """Лист без колонки Dedup Key — проверки дубликатов нет, оба вызова добавляют строку."""
    ws = _FakeWorksheet([list(sheets_client._RESULT_HEADER)])
    _patch_worksheet(monkeypatch, ws)

    sheets_client.append_with_retries("sid", "tab", credentials_path="k", row=_make_row(), dedup_key="X")
    sheets_client.append_with_retries("sid", "tab", credentials_path="k", row=_make_row(), dedup_key="X")
    assert len(ws.rows) == 3


@pytest.mark.asyncio
async def test_async_wrapper_returns_flag(monkeypatch):
    ws = _FakeWorksheet()
    _patch_worksheet(monkeypatch, ws)

    r1 = await sheets_client.append_student_result_row(
        "sid", "tab", credentials_path="k", row=_make_row(), dedup_key="U1:S1:M1",
    )
    r2 = await sheets_client.append_student_result_row(
        "sid", "tab", credentials_path="k", row=_make_row(), dedup_key="U1:S1:M1",
    )
    assert r1 is True
    assert r2 is False
