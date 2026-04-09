"""Выгрузка строк оценки в Google Sheets (лист student_answers), без эталонов."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.integrations import sheets_client
from app.services import reference_map_service

logger = logging.getLogger(__name__)


async def export_question_scores(
    *,
    discipline_id: str | None,
    telegram_user_id: int,
    session_id: str,
    scored_rows: list[tuple[str, float, str]],
) -> None:
    """
    Для каждой оценённой пары (ключ, score, фрагмент ответа) — append строки.
    При отсутствии credentials / id таблицы — no-op.
    """
    creds = settings.google_creds_path()
    sheet_id = reference_map_service.spreadsheet_id_for_discipline(discipline_id)
    tab = (settings.google_sheet_results_tab or "student_answers").strip() or "student_answers"
    if not creds or not sheet_id:
        return

    slug = (discipline_id or settings.default_discipline or "").strip() or "-"

    for question_key, score, excerpt in scored_rows:
        row = sheets_client.build_result_row(
            telegram_user_id=telegram_user_id,
            session_id=session_id,
            discipline_slug=slug,
            question_key=question_key,
            score=score,
            answer_excerpt=excerpt,
        )
        try:
            await asyncio.to_thread(
                sheets_client.append_with_retries,
                sheet_id,
                tab,
                credentials_path=creds,
                row=row,
            )
        except Exception:
            logger.exception(
                "Не удалось записать результат в Sheets %s / %s",
                sheet_id,
                tab,
            )
