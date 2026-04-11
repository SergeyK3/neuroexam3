"""Выгрузка строк оценки в Google Sheets (лист GOOGLE_SHEET_RESULTS_TAB), без эталонов."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.integrations import sheets_client
from app.integrations.google_sheets import results_worksheet_title
from app.services import reference_map_service

logger = logging.getLogger(__name__)


def _parse_registration_lines(raw: str | None) -> tuple[str, str, str, str]:
    """Четыре поля регистрации: дисциплина/курс, вид контроля, номер группы, ФИО (как в FSM).

    Три строки без номера группы (старый формат) трактуются как: курс, контроль, ФИО; группа пустая.
    """
    if not raw or not str(raw).strip():
        return ("", "", "", "")
    lines = [ln.strip() for ln in str(raw).splitlines() if ln.strip()]
    if len(lines) >= 4:
        return (lines[0], lines[1], lines[2], lines[3])
    if len(lines) == 3:
        return (lines[0], lines[1], "", lines[2])
    if len(lines) == 2:
        return (lines[0], lines[1], "", "")
    if len(lines) == 1:
        return (lines[0], "", "", "")
    return ("", "", "", "")


async def export_question_scores(
    *,
    discipline_id: str | None,
    telegram_user_id: int,
    session_id: str,
    registration_raw: str | None,
    full_transcript: str,
    scored_rows: list[tuple[str, str, str, str]],
    telegram_message_id: int | None = None,
    ticket_number: str | None = None,
) -> None:
    """
    Для каждой оценённой строки (ключ, score_display, фрагмент, обоснование) — append в Sheets.
    При отсутствии credentials / id таблицы — no-op.
    """
    creds = settings.google_creds_path()
    sheet_id = reference_map_service.spreadsheet_id_for_discipline(
        discipline_id,
        registration_raw=registration_raw,
    )
    tab = results_worksheet_title(discipline_id)
    if not creds or not sheet_id:
        if not creds:
            logger.warning(
                "Результаты в Google Sheets не записаны: не задан путь к ключу сервисного аккаунта "
                "(GOOGLE_SHEETS_CREDENTIALS или GOOGLE_APPLICATION_CREDENTIALS). "
                "Строк для экспорта: %s.",
                len(scored_rows),
            )
        if not sheet_id:
            logger.warning(
                "Результаты в Google Sheets не записаны: не задан id таблицы "
                "(GOOGLE_SHEET_ID или DISCIPLINE_GOOGLE_SHEET_IDS_JSON для дисциплины). "
                "Строк для экспорта: %s.",
                len(scored_rows),
            )
        return

    slug = (discipline_id or settings.default_discipline or "").strip() or "-"
    course_name, control_type, group_number, student_fio = _parse_registration_lines(registration_raw)

    for question_key, score_display, excerpt, rationale in scored_rows:
        row = sheets_client.build_result_row(
            telegram_user_id=telegram_user_id,
            session_id=session_id,
            discipline_slug=slug,
            course_name=course_name,
            control_type=control_type,
            group_number=group_number,
            student_fio=student_fio,
            question_key=question_key,
            score_display=score_display,
            full_transcript=full_transcript,
            answer_excerpt=excerpt,
            rationale=rationale or "",
            telegram_message_id=telegram_message_id,
            ticket_number=ticket_number or "",
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
