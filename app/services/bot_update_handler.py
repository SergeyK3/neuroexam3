"""Связка webhook → сессия → FSM → Telegram; голос/текст: Whisper → сегментация по ключам → оценка."""

import logging
import re
import time
from typing import Any

from app.core.config import settings
from app.integrations import telegram_client
from app.models.session import ExamSession, ExamState
from app.services import (
    evaluation_service,
    fsm_service,
    results_export_service,
    segmentation_service,
    session_service,
    speech_service,
)

logger = logging.getLogger(__name__)

_START_RE = re.compile(r"^/start(?:@\w+)?(?:\s|$)", re.IGNORECASE)


def _is_start_command(text: str | None) -> bool:
    if not text:
        return False
    return bool(_START_RE.match(text.strip()))


async def _evaluate_and_reply(
    chat_id: int,
    transcript: str,
    *,
    telegram_user_id: int,
    session_id: str,
    discipline_id: str | None = None,
    preview_heading: str = "Распознано / ответ:",
) -> None:
    """Сегментация по ключам (Google Sheets или .env), оценка каждого непустого фрагмента."""
    try:
        ref_map = await reference_map_service.get_reference_map(discipline_id)
    except ValueError as e:
        await telegram_client.send_message(chat_id, f"Ошибка настроек таблиц/эталонов: {e}")
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

    lines: list[str] = ["Оценка по ключам (MVP, 0…1):"]
    scored: list[tuple[str, float, str]] = []
    for key in keys:
        seg = (parts.get(key) or "").strip()
        ref = ref_map[key]
        if not seg:
            lines.append(f"• {key}: нет фрагмента — пропуск")
            continue
        try:
            score = await evaluation_service.evaluate(seg, ref)
        except ValueError as e:
            lines.append(f"• {key}: ошибка оценки: {e}")
            continue
        lines.append(f"• {key}: {score:.4f}")
        scored.append((key, score, seg))

    if notes:
        lines.append("")
        lines.append("Примечание:")
        lines.extend(notes)

    preview = transcript.strip()
    if len(preview) > 1200:
        preview = preview[:1200] + "…"
    lines.append("")
    lines.append(f"{preview_heading}\n{preview}")

    await telegram_client.send_message(chat_id, "\n".join(lines))

    if scored:
        await results_export_service.export_question_scores(
            discipline_id=discipline_id,
            telegram_user_id=telegram_user_id,
            session_id=session_id,
            scored_rows=scored,
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
        await _evaluate_and_reply(
            chat_id,
            transcript,
            telegram_user_id=user_id,
            session_id=sess.session_id,
            discipline_id=sess.discipline_id,
            preview_heading="Распознано:",
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Ошибка конвейера голоса")
        await telegram_client.send_message(chat_id, f"Ошибка обработки голоса: {e}")


async def handle_telegram_update(update: dict[str, Any]) -> None:
    message = update.get("message") or update.get("edited_message")
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

    text = message.get("text")
    if text is not None and not isinstance(text, str):
        text = str(text)
    text = text or ""
    has_voice = bool(message.get("voice"))
    start_cmd = _is_start_command(text)

    if start_cmd:
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
        sess.last_transcript = out.evaluate_text.strip()
        await _evaluate_and_reply(
            chat_id,
            out.evaluate_text,
            telegram_user_id=user_id,
            session_id=out.session.session_id,
            discipline_id=out.session.discipline_id,
            preview_heading="Текст ответа:",
        )

    await session_service.upsert_session(out.session)
