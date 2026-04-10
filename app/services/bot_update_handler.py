"""Связка webhook → сессия → FSM → Telegram; голос/текст: Whisper → сегментация по ключам → оценка."""

import logging
import re
import time
import unicodedata
from typing import Any

from app.core.config import settings
from app.integrations import telegram_client
from app.models.session import ExamSession, ExamState
from app.services import (
    evaluation_service,
    fsm_service,
    reference_map_service,
    results_export_service,
    segmentation_service,
    session_service,
    speech_service,
)
from app.services.evaluation_service import RubricScores
from app.services.exam_text_parsing import extract_ticket_number

logger = logging.getLogger(__name__)

_START_RE = re.compile(r"^/start(?:@\w+)?(?:\s|$)", re.IGNORECASE)


def _normalize_user_text(text: str) -> str:
    """NFC + убрать невидимые символы (ZWSP и т.д.), мешающие распознать /start."""
    t = unicodedata.normalize("NFC", text).strip()
    return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", t)
def _rubric_rationale_for_sheet(r: RubricScores) -> str:
    """Текст для колонки rationale в Google Sheets (рубрика)."""
    parts: list[str] = []
    if (r.content_rationale or "").strip():
        parts.append(f"Полнота: {_truncate_block(r.content_rationale, 900)}")
    if (r.accuracy_rationale or "").strip():
        parts.append(f"Точность: {_truncate_block(r.accuracy_rationale, 900)}")
    if (r.structure_rationale or "").strip():
        parts.append(f"Структура: {_truncate_block(r.structure_rationale, 900)}")
    if (r.conciseness_rationale or "").strip():
        parts.append(f"Без лишнего: {_truncate_block(r.conciseness_rationale, 900)}")
    return "\n\n".join(parts)


def _rubric_lines(question_ordinal: int, r: RubricScores) -> list[str]:
    """Текст для Telegram: без кодов ключей из таблицы — только порядковый «Вопрос N»."""
    lines = [
        f"• Вопрос {question_ordinal}",
        f"  — полнота: {r.content_score}/60",
        f"  — точность: {r.accuracy_score}/20",
        f"  — структура: {r.structure_score}/10",
        f"  — отсутствие лишнего: {r.conciseness_score}/10",
        f"  — итого: {r.total}/100",
    ]
    rationale_parts: list[str] = []
    if (r.content_rationale or "").strip():
        rationale_parts.append(f"  — Полнота: {_truncate_block(r.content_rationale, 900)}")
    if (r.accuracy_rationale or "").strip():
        rationale_parts.append(f"  — Точность: {_truncate_block(r.accuracy_rationale, 900)}")
    if (r.structure_rationale or "").strip():
        rationale_parts.append(f"  — Структура: {_truncate_block(r.structure_rationale, 900)}")
    if (r.conciseness_rationale or "").strip():
        rationale_parts.append(f"  — Без лишнего: {_truncate_block(r.conciseness_rationale, 900)}")
    if rationale_parts:
        lines.append("  Обоснование:")
        lines.extend(rationale_parts)
    return lines


def _truncate_block(text: str, max_len: int = 2000) -> str:
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + "…"


def _mean_formula_rubric(totals: list[int], mean: float) -> str:
    if not totals:
        return ""
    parts = " + ".join(str(t) for t in totals)
    n = len(totals)
    return f"({parts}) / {n} = {mean:.1f}"


def _mean_formula_similarity(scores: list[float], mean: float) -> str:
    if not scores:
        return ""
    parts = " + ".join(f"{s:.4f}" for s in scores)
    n = len(scores)
    return f"({parts}) / {n} = {mean:.4f}"


def _preview_recognized_text(
    transcript: str,
    parts: dict[str, str],
    keys: list[str],
    *,
    max_len: int = 1200,
) -> str:
    """Для нескольких фрагментов — пустая строка между блоками; иначе исходный транскрипт."""
    chunks: list[str] = []
    for k in keys:
        seg = (parts.get(k) or "").strip()
        if seg:
            chunks.append(seg)
    text = "\n\n".join(chunks) if len(chunks) >= 2 else transcript.strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def _is_start_command(text: str | None) -> bool:
    if not text:
        return False
    t = _normalize_user_text(text)
    if _START_RE.match(t):
        return True
    parts = t.split()
    if not parts:
        return False
    head = parts[0].lower()
    return head == "/start" or head.startswith("/start@")


async def _evaluate_and_reply(
    chat_id: int,
    transcript: str,
    *,
    telegram_user_id: int,
    session_id: str,
    discipline_id: str | None = None,
    registration_raw: str | None = None,
    telegram_message_id: int | None = None,
    ticket_number: str | None = None,
) -> None:
    """Сегментация по ключам (Google Sheets или .env), оценка каждого непустого фрагмента."""
    try:
        ref_map = await reference_map_service.get_reference_map(discipline_id)
    except ValueError as e:
        await telegram_client.send_message(
            chat_id,
            f"Ошибка настроек таблиц/эталонов: {telegram_client.redact_secrets(str(e))}",
        )
        return

    if not ref_map:
        await telegram_client.send_message(
            chat_id,
            "Нет эталонов: настройте Google Sheet и ключ, либо MVP_REFERENCES_JSON / MVP_REFERENCE_ANSWER в .env.",
        )
        return

    keys = list(ref_map.keys())
    parts, notes = await segmentation_service.segment_with_fallback(
        transcript,
        keys,
        use_llm=settings.mvp_segmentation_use_llm,
    )

    has_openai = bool((settings.openai_api_key or "").strip())
    if not has_openai:
        lines = [
            "Оценка недоступна: в .env задайте OPENAI_API_KEY.",
            "Без ключа нельзя ни рубрику по полям, ни семантическое сравнение по эмбеддингам.",
        ]
        if notes:
            lines.append("")
            lines.append("Примечание:")
            lines.extend(notes)
        preview = _preview_recognized_text(transcript, parts, keys)
        lines.append("")
        lines.append(preview)
        await telegram_client.send_message(chat_id, "\n".join(lines))
        return

    use_rubric = evaluation_service.use_rubric_scoring()

    scored: list[tuple[str, str, str, str]] = []
    rubric_totals: list[int] = []
    sim_scores: list[float] = []

    lines: list[str] = []

    first_answer = True
    question_ordinal = 0
    for key in keys:
        seg = (parts.get(key) or "").strip()
        ref = ref_map[key]
        if not seg:
            continue
        question_ordinal += 1
        if not first_answer:
            lines.append("")
        lines.append(_truncate_block(seg))
        lines.append("")

        if use_rubric:
            try:
                r = await evaluation_service.evaluate_rubric(seg, ref)
            except (ValueError, RuntimeError) as e:
                lines.append(f"• Вопрос {question_ordinal}: ошибка оценки: {e}")
                first_answer = False
                continue
            lines.extend(_rubric_lines(question_ordinal, r))
            rubric_totals.append(r.total)
            scored.append((key, str(r.total), seg, _rubric_rationale_for_sheet(r)))
        else:
            try:
                sim = await evaluation_service.evaluate_similarity(seg, ref)
            except ValueError as e:
                lines.append(f"• Вопрос {question_ordinal}: ошибка оценки: {e}")
                first_answer = False
                continue
            lines.append(f"• Вопрос {question_ordinal}")
            lines.append(f"  — сходство: {sim:.4f}")
            sim_scores.append(sim)
            scored.append((key, f"{sim:.4f}", seg, ""))

        first_answer = False

    if use_rubric and rubric_totals:
        mean_r = sum(rubric_totals) / len(rubric_totals)
        lines.append("")
        lines.append("Среднее по рубрике (итого):")
        lines.append(_mean_formula_rubric(rubric_totals, mean_r))
    elif not use_rubric and len(sim_scores) >= 1:
        mean = sum(sim_scores) / len(sim_scores)
        lines.append("")
        lines.append(_mean_formula_similarity(sim_scores, mean))

    if notes:
        lines.append("")
        lines.append("Примечание:")
        lines.extend(notes)

    await telegram_client.send_message(chat_id, "\n".join(lines))

    if scored:
        await results_export_service.export_question_scores(
            discipline_id=discipline_id,
            telegram_user_id=telegram_user_id,
            session_id=session_id,
            registration_raw=registration_raw,
            full_transcript=transcript,
            scored_rows=scored,
            telegram_message_id=telegram_message_id,
            ticket_number=ticket_number,
        )


async def _handle_voice_answering(
    sess: ExamSession,
    chat_id: int,
    user_id: int,
    message: dict[str, Any],
) -> None:
    voice = message.get("voice")
    if not isinstance(voice, dict):
        await telegram_client.send_message(chat_id, "Нет голосового вложения.")
        return
    file_id = voice.get("file_id")
    if not isinstance(file_id, str):
        await telegram_client.send_message(chat_id, "Не удалось получить file_id голосового.")
        return

    try:
        audio = await telegram_client.download_file_bytes(file_id)
        lang = sess.language or "ru"
        transcript = await speech_service.transcribe(audio, language=lang)
        sess.last_transcript = transcript
        tn = extract_ticket_number(transcript)
        if tn:
            sess.ticket_number = tn
        mid_raw = message.get("message_id")
        msg_id = mid_raw if isinstance(mid_raw, int) else None
        await _evaluate_and_reply(
            chat_id,
            transcript,
            telegram_user_id=user_id,
            session_id=sess.session_id,
            discipline_id=sess.discipline_id,
            registration_raw=sess.registration_raw,
            telegram_message_id=msg_id,
            ticket_number=sess.ticket_number,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Ошибка конвейера голоса")
        await telegram_client.send_message(
            chat_id,
            f"Ошибка обработки голоса: {telegram_client.redact_secrets(str(e))}",
        )


def _message_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    """Обычный чат, канал или Telegram Business (business_message)."""
    for key in (
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "business_message",
        "edited_business_message",
    ):
        m = update.get(key)
        if isinstance(m, dict):
            return m
    return None


async def handle_telegram_update(update: dict[str, Any]) -> None:
    message = _message_from_update(update)
    if not isinstance(message, dict):
        return

    from_user = message.get("from")
    chat = message.get("chat")
    if not isinstance(from_user, dict) or not isinstance(chat, dict):
        return

    user_id = from_user.get("id")
    chat_id = chat.get("id")
    if not isinstance(user_id, int) or not isinstance(chat_id, int):
        return

    text = message.get("text") or message.get("caption")
    if text is not None and not isinstance(text, str):
        text = str(text)
    text = _normalize_user_text(text or "")
    has_voice = bool(message.get("voice"))
    start_cmd = _is_start_command(text)

    if start_cmd:
        logger.info("Команда /start: user_id=%s chat_id=%s", user_id, chat_id)
        sess = await session_service.reset_session(user_id)
        sess.start_time = time.monotonic()
        out = fsm_service.process_message(
            sess,
            text=text,
            has_voice=has_voice,
            is_start_command=True,
        )
        await session_service.upsert_session(out.session)
        for line in out.messages:
            await telegram_client.send_message(chat_id, line)
        return

    sess = await session_service.get_session(user_id)
    if sess is None:
        sess = ExamSession(user_id=user_id)

    if session_service.is_timed_out(sess) and sess.state != ExamState.FINISH:
        await telegram_client.send_message(
            chat_id,
            "Время экзамена истекло (2 часа с команды /start). Отправьте /start, чтобы начать заново.",
        )
        sess.state = ExamState.FINISH
        await session_service.upsert_session(sess)
        return

    if has_voice and sess.state == ExamState.ANSWERING:
        await _handle_voice_answering(sess, chat_id, user_id, message)
        await session_service.upsert_session(sess)
        return

    out = fsm_service.process_message(
        sess,
        text=text,
        has_voice=has_voice,
        is_start_command=False,
    )

    for line in out.messages:
        await telegram_client.send_message(chat_id, line)

    if out.evaluate_text:
        out.session.last_transcript = out.evaluate_text.strip()
        tn = extract_ticket_number(out.evaluate_text)
        if tn:
            out.session.ticket_number = tn
        mid_raw = message.get("message_id")
        msg_id = mid_raw if isinstance(mid_raw, int) else None
        await _evaluate_and_reply(
            chat_id,
            out.evaluate_text,
            telegram_user_id=user_id,
            session_id=out.session.session_id,
            discipline_id=out.session.discipline_id,
            registration_raw=out.session.registration_raw,
            telegram_message_id=msg_id,
            ticket_number=out.session.ticket_number,
        )

    await session_service.upsert_session(out.session)
