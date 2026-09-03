"""Выгрузка строк оценки в Google Sheets (лист GOOGLE_SHEET_RESULTS_TAB), без эталонов."""

from __future__ import annotations

import asyncio
import logging
import re

from app.core.config import settings
from app.integrations import sheets_client
from app.integrations.google_sheets import results_worksheet_title
from app.services import reference_map_service

logger = logging.getLogger(__name__)

_REGISTRATION_NUMBER_RE = re.compile(r"^\s*[1-4](?:[).:;\-]|\s+)\s*(.+?)\s*$")
_TRANSLATION_UNAVAILABLE = "[Перевод временно недоступен. Исходный ответ сохранён в колонке J.]"
_TRANSLATION_TRUNCATED = "[перевод сокращён из-за размера ячейки]"


def _clean_registration_line(line: str) -> str:
    match = _REGISTRATION_NUMBER_RE.match(line or "")
    return (match.group(1) if match else line).strip()


def parse_registration_lines(raw: str | None) -> tuple[str, str, str, str]:
    """Четыре поля регистрации: дисциплина/курс, вид контроля, номер группы, ФИО (как в FSM).

    Три строки без номера группы (старый формат) трактуются как: курс, контроль, ФИО; группа пустая.
    """
    if not raw or not str(raw).strip():
        return ("", "", "", "")
    lines = [_clean_registration_line(ln) for ln in str(raw).splitlines() if ln.strip()]
    if len(lines) >= 4:
        return (lines[0], lines[1], lines[2], lines[3])
    if len(lines) == 3:
        return (lines[0], lines[1], "", lines[2])
    if len(lines) == 2:
        return (lines[0], lines[1], "", "")
    if len(lines) == 1:
        return (lines[0], "", "", "")
    return ("", "", "", "")


_parse_registration_lines = parse_registration_lines


def _documented_transcript(
    *,
    course_name: str,
    control_type: str,
    group_number: str,
    student_fio: str,
    ticket_number: str,
    transcript: str,
) -> str:
    lines = [
        f"Дисциплина: {course_name}" if course_name else "",
        f"Вид контроля: {control_type}" if control_type else "",
        f"Группа: {group_number}" if group_number else "",
        f"Студент: {student_fio}" if student_fio else "",
        f"Билет: {ticket_number}" if ticket_number else "",
    ]
    header = "\n".join(line for line in lines if line).strip()
    body = (transcript or "").strip()
    if header and body:
        return f"{header}\n\nТранскрипт ответа:\n{body}"
    return header or body


def _parse_score_value(score_display: str) -> float | None:
    raw = (score_display or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _aggregate_score_display(scored_rows: list[tuple[str, str, str, str]]) -> str:
    items: list[str] = []
    values: list[float] = []
    has_fraction = False
    for idx, (_question_key, score_display, _excerpt, _rationale) in enumerate(scored_rows, start=1):
        items.append(f"В{idx}: {score_display}")
        numeric = _parse_score_value(score_display)
        if numeric is not None:
            values.append(numeric)
            if not numeric.is_integer():
                has_fraction = True
    if values:
        mean = sum(values) / len(values)
        mean_display = f"{mean:.4f}" if has_fraction else f"{mean:.1f}"
        items.append(f"Средняя: {mean_display}")
    return "; ".join(items)


def _aggregate_rationale(
    scored_rows: list[tuple[str, str, str, str]],
) -> str:
    blocks: list[str] = []
    for idx, (question_key, score_display, _excerpt, rationale) in enumerate(scored_rows, start=1):
        parts = [f"Вопрос {idx}: {score_display}"]
        if question_key:
            parts.append(f"Ключ: {question_key}")
        if rationale.strip():
            parts.append(rationale.strip())
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks).strip()


def _compose_comment(
    evaluation_text: str,
    *,
    translation_ru: str | None,
    translation_attempted: bool,
    max_chars: int | None = None,
) -> str:
    """Собрать K, сохранив оценивание приоритетно в пределах прежних 4000 символов."""
    evaluation = (evaluation_text or "").strip()
    if not translation_attempted:
        return evaluation

    limit = sheets_client.RESULT_COMMENT_MAX_CHARS if max_chars is None else max(0, max_chars)
    # Если прежний rationale уже занимает лимит, сохраняем прежнее поведение:
    # build_result_row обрежет только его, без добавления перевода и новых заголовков.
    if len(evaluation) >= limit:
        return evaluation

    translation = (translation_ru or "").strip() or _TRANSLATION_UNAVAILABLE
    prefix = "Перевод на русский:\n"
    suffix = f"\n\nОценивание:\n{evaluation}"
    available = limit - len(prefix) - len(suffix)

    if available <= 0:
        return evaluation
    if len(translation) <= available:
        return f"{prefix}{translation}{suffix}"

    marker = _TRANSLATION_TRUNCATED
    if available < len(marker):
        return evaluation
    content_budget = available - len(marker) - 1
    shortened = translation[: max(0, content_budget)].rstrip()
    translation_block = f"{shortened}\n{marker}" if shortened else marker
    return f"{prefix}{translation_block}{suffix}"


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
    translation_ru: str | None = None,
    translation_attempted: bool = False,
) -> None:
    """
    Для всего ответа студента формирует одну агрегированную строку в Sheets.
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

    course_name, control_type, group_number, student_fio = parse_registration_lines(registration_raw)
    slug = (discipline_id or settings.default_discipline or "").strip() or "-"
    route_label = course_name or slug
    metadata_block = "\n".join(
        value
        for value in (
            f"Маршрут дисциплины (бот): {route_label}" if route_label else "",
            f"session: {session_id}" if session_id else "",
        )
        if value
    )
    rationale_budget = max(
        0,
        sheets_client.RESULT_COMMENT_MAX_CHARS
        - len(metadata_block)
        - (1 if metadata_block else 0),
    )
    row = sheets_client.build_result_row(
        telegram_user_id=telegram_user_id,
        session_id=session_id,
        discipline_slug=route_label,
        course_name=course_name,
        control_type=control_type,
        group_number=group_number,
        student_fio=student_fio,
        question_key="",
        score_display=_aggregate_score_display(scored_rows),
        full_transcript=full_transcript,
        answer_excerpt=_documented_transcript(
            course_name=course_name,
            control_type=control_type,
            group_number=group_number,
            student_fio=student_fio,
            ticket_number=ticket_number or "",
            transcript=full_transcript,
        ),
        rationale=_compose_comment(
            _aggregate_rationale(scored_rows),
            translation_ru=translation_ru,
            translation_attempted=translation_attempted,
            max_chars=rationale_budget,
        ),
        telegram_message_id=telegram_message_id,
        ticket_number=ticket_number or "",
    )
    # Итоговая строка уникальна на пользователя и экзаменационную сессию.
    # message_id намеренно не участвует: продолжение/повторная отправка в той
    # же сессии не должна создавать ещё один итог.
    dedup_key = f"{telegram_user_id}:{session_id or '-'}"
    try:
        appended = await asyncio.to_thread(
            sheets_client.append_with_retries,
            sheet_id,
            tab,
            credentials_path=creds,
            row=row,
            dedup_key=dedup_key,
        )
        if not appended:
            logger.info(
                "Sheets: пропущена запись по dedup_key=%s (уже есть в листе %s/%s)",
                dedup_key,
                sheet_id,
                tab,
            )
    except Exception:
        logger.exception(
            "Не удалось записать результат в Sheets %s / %s",
            sheet_id,
            tab,
        )
