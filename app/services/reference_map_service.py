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


def spreadsheet_id_for_discipline(
    discipline_id: str | None,
    registration_raw: str | None = None,
) -> str | None:
    """Публичный доступ к id таблицы (эталоны и результаты): см. _sheet_id_for_session."""
    return _sheet_id_for_session(discipline_id, registration_raw)


def _sheet_id_for_session(
    discipline_id: str | None,
    registration_raw: str | None = None,
) -> str | None:
    """Spreadsheet id: приоритет — карта по полному названию из регистрации, иначе slug-карта или GOOGLE_SHEET_ID."""
    sid = settings.spreadsheet_id_for_registration_course(registration_raw)
    if sid:
        logger.info("Таблица выбрана по 1-й строке регистрации (название дисциплины)")
        return sid

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


async def get_reference_map(
    discipline_id: str | None,
    registration_raw: str | None = None,
) -> dict[str, str]:
    """
    Загрузить эталоны. Если заданы credentials и id таблицы — читаем лист эталонов
    (имя задаётся в GOOGLE_SHEET_IDEAL_TAB, по умолчанию ``ideal_answers``). Иначе — MVP_REFERENCES_JSON / пара Q1+REFERENCE.
    """
    creds = settings.google_creds_path()
    sheet_id = _sheet_id_for_session(discipline_id, registration_raw)
    tab = settings.ideal_worksheet_for_discipline(discipline_id)

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
