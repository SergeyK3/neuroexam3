"""Словарь «ключ вопроса → эталон»: Google Sheets (приоритет) или fallback на .env."""

from __future__ import annotations

import json
import logging
import time
from app.core.config import settings
from app.integrations.sheets_client import fetch_ideal_references

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, dict[str, str]]] = {}
_TTL_SEC = 120.0


def spreadsheet_id_for_discipline(discipline_id: str | None) -> str | None:
    """Публичный доступ к id таблицы для дисциплины (та же логика, что для эталонов)."""
    return _sheet_id_for_session(discipline_id)


def _sheet_id_for_session(discipline_id: str | None) -> str | None:
    """Определить spreadsheet id: карта дисциплин, иначе один GOOGLE_SHEET_ID."""
    raw = (settings.discipline_google_sheet_ids_json or "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("DISCIPLINE_GOOGLE_SHEET_IDS_JSON: %s", e)
            raise ValueError("DISCIPLINE_GOOGLE_SHEET_IDS_JSON: неверный JSON") from e
        if not isinstance(data, dict):
            raise ValueError("DISCIPLINE_GOOGLE_SHEET_IDS_JSON должен быть объектом")
        key = (discipline_id or settings.default_discipline or "").strip()
        if not key:
            key = next(iter(data.keys()), "")
        sid = data.get(key) if key else None
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
        single = (settings.google_sheet_id or "").strip()
        if single:
            logger.warning(
                "Дисциплина «%s» не найдена в карте таблиц — используется GOOGLE_SHEET_ID",
                key,
            )
            return single
        raise ValueError(
            f"Нет таблицы для дисциплины «{key}»: проверьте DISCIPLINE_GOOGLE_SHEET_IDS_JSON",
        )

    single = (settings.google_sheet_id or "").strip()
    return single or None


async def get_reference_map(discipline_id: str | None) -> dict[str, str]:
    """
    Загрузить эталоны. Если заданы credentials и id таблицы — читаем лист ``ideal answers``
    (имя задаётся в GOOGLE_SHEET_IDEAL_TAB). Иначе — MVP_REFERENCES_JSON / пара Q1+REFERENCE.
    """
    creds = settings.google_creds_path()
    sheet_id = _sheet_id_for_session(discipline_id)
    tab = (settings.google_sheet_ideal_tab or "ideal answers").strip() or "ideal answers"

    if creds and sheet_id:
        cache_key = f"{sheet_id}|{tab}"
        now = time.monotonic()
        ent = _cache.get(cache_key)
        if ent is not None:
            ts, data = ent
            if now - ts < _TTL_SEC and data:
                return dict(data)

        try:
            data = await fetch_ideal_references(sheet_id, tab, credentials_path=creds)
        except Exception:
            logger.exception("Не удалось прочитать Google Sheet %s", sheet_id)
            logger.info("Fallback на эталоны из .env")
            return settings.mvp_reference_map()

        _cache[cache_key] = (now, data)
        if data:
            return dict(data)
        logger.warning("Таблица %s: пусто, fallback на .env", sheet_id)

    return settings.mvp_reference_map()
