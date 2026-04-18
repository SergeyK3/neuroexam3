"""Связка webhook → сессия → FSM → Telegram; голос/текст: Whisper → сегментация по ключам → оценка."""

import logging
import re
import time
import unicodedata
from typing import Any

from app.core.config import settings
from app.integrations import telegram_client
from app.models.question_bank import QuestionRecord
from app.models.session import ExamSession, ExamState
from app.services import (
    bot_texts,
    evaluation_service,
    fsm_service,
    reference_map_service,
    results_export_service,
    segmentation_service,
    session_service,
    speech_service,
)
from app.services.bot_texts import detect_message_language, t
from app.services.evaluation_service import CoverageScores
from app.services.exam_text_parsing import (
    contains_answer_completion_marker,
    extract_answer_body_for_evaluation,
    extract_ticket_number,
    split_at_otvet_marker,
    strip_embedded_bot_output,
    strip_answer_completion_markers,
)

logger = logging.getLogger(__name__)

_START_RE = re.compile(r"^/start(?:@\w+)?(?:\s|$)", re.IGNORECASE)
_NEW_RE = re.compile(r"^/new(?:@\w+)?(?:\s|$)", re.IGNORECASE)
# Текст начинается с реквизитов билета — в чате сначала вводная, потом строка ключа (не наоборот).
_BILLET_OR_EXAM_LEAD = re.compile(
    r"(?is)^\s*(?:билет|номер\s+билета|экзаменационн(?:ый|ого)\s+билет|№\s*билета)",
)


def _display_question_key(question_key: str | None) -> str:
    key = (question_key or "").strip()
    if not key or re.fullmatch(r"Q\d+", key, flags=re.IGNORECASE):
        return ""
    return f"Ключ вопроса: {key}"


def _normalize_user_text(text: str) -> str:
    """NFC + убрать невидимые символы (ZWSP и т.д.), мешающие распознать /start."""
    t = unicodedata.normalize("NFC", text).strip()
    return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", t)


def _coverage_rationale_for_sheet(r: CoverageScores) -> str:
    """Текст для колонки rationale в Google Sheets (покрытие смысловых элементов)."""
    parts: list[str] = []
    if r.covered_elements:
        parts.append(f"Покрыто: {_truncate_block('; '.join(r.covered_elements), 1200)}")
    if r.partial_elements:
        parts.append(f"Частично: {_truncate_block('; '.join(r.partial_elements), 1200)}")
    if r.missing_elements:
        parts.append(f"Пропущено: {_truncate_block('; '.join(r.missing_elements), 1200)}")
    if (r.general_comment or "").strip():
        parts.append(f"Комментарий: {_truncate_block(r.general_comment, 900)}")
    return "\n\n".join(parts)


def _coverage_lines_localized(question_ordinal: int, r: CoverageScores, lang: str) -> list[str]:
    lines: list[str] = [
        f"• {t('question_label', lang, n=question_ordinal)}",
        f"  — {t('coverage_score_label', lang, score=r.score)}",
    ]
    if r.covered_elements:
        lines.append(f"  — {t('covered_label', lang)}: {_truncate_block('; '.join(r.covered_elements), 1000)}")
    if r.partial_elements:
        lines.append(f"  — {t('partial_label', lang)}: {_truncate_block('; '.join(r.partial_elements), 1000)}")
    if r.missing_elements:
        lines.append(f"  — {t('missing_label', lang)}: {_truncate_block('; '.join(r.missing_elements), 1000)}")
    if (r.general_comment or "").strip():
        lines.append(f"  — {t('conclusion_label', lang)}: {_truncate_block(r.general_comment, 900)}")
    return lines


def _telegram_answer_chrono_block(question: QuestionRecord, seg: str) -> str:
    """
    Порядок для чата: вводная (билет, формулировка вопроса) → суть ответа.
    Оценка добавляется вызывающим кодом только после этого блока.
    """
    head, tail = split_at_otvet_marker(seg)
    title = (question.question_text or "").strip()
    key_line = _display_question_key(question.question_key)
    parts: list[str] = []
    if head:
        parts.append(head.strip())
        if key_line:
            parts.append(key_line)
        if title:
            parts.append(title)
        if tail:
            parts.append(tail.strip())
        return "\n\n".join(p for p in parts if p).strip()
    t = (tail or "").strip()
    if not t:
        return "\n\n".join(p for p in (key_line, title) if p).strip()
    if _BILLET_OR_EXAM_LEAD.match(t) and title:
        return "\n\n".join(p for p in (t, key_line, title) if p).strip()
    if title or key_line:
        return "\n\n".join(p for p in (key_line, title, t) if p).strip()
    return t


def _truncate_block(text: str, max_len: int = 2000) -> str:
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + "…"


def _mean_formula_100(totals: list[int], mean: float) -> str:
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


def _reply_language(text: str | None, fallback: str | None = None) -> str:
    return detect_message_language(text, fallback=fallback or "ru")


def _expected_question_count_from_registration(
    registration_raw: str | None,
    transcript: str,
) -> int:
    _course_name, control_type, _group_number, _student_fio = results_export_service.parse_registration_lines(
        registration_raw,
    )
    low = (control_type or "").strip().lower()
    if "рубеж" in low or re.search(r"\bрк\b", low):
        return 2
    if (
        "текущ" in low
        or "текуш" in low
        or re.search(r"\bтек\.\s*контрол", low)
        or re.search(r"\bтк\b", low)
    ):
        return 2
    if "экзам" in low or "итог" in low:
        return 3
    return reference_map_service.infer_expected_question_count(transcript)


def _merge_transcripts(existing: str | None, incoming: str) -> str:
    cur = (existing or "").strip()
    new = incoming.strip()
    if not cur:
        return new
    if not new:
        return cur
    return f"{cur}\n\n{new}"


def _count_answered_questions(
    questions: list[QuestionRecord],
    parts: dict[str, str],
) -> int:
    count = 0
    for question in questions:
        seg = strip_answer_completion_markers((parts.get(question.question_key) or "").strip())
        seg_eval = extract_answer_body_for_evaluation(seg).strip() or seg.strip()
        if not seg_eval or _is_metadata_only(seg_eval):
            continue
        tokens = re.findall(r"[a-zа-яё0-9]+", seg_eval.lower())
        if len(tokens) >= 4 or len(seg_eval) >= 30:
            count += 1
    return count


def _has_meaningful_answer_text(text: str | None) -> bool:
    cleaned = strip_answer_completion_markers(strip_embedded_bot_output((text or "").strip()))
    if not cleaned or _is_metadata_only(cleaned):
        return False
    tokens = re.findall(r"[a-zа-яё0-9]+", cleaned.lower())
    return len(tokens) >= 6 or len(cleaned) >= 30


def _pending_progress_message(answered_count: int, target_count: int, completion_seen: bool, lang: str) -> str:
    if completion_seen:
        return t("pending_progress_completion", lang, answered=answered_count, target=target_count)
    return t("pending_progress_wait", lang, answered=answered_count, target=target_count)


def _transcription_too_short_message(lang: str) -> str:
    return t("transcription_too_short", lang)


def _preliminary_disclaimer(lang: str) -> str:
    return t("preliminary_disclaimer", lang)


async def _candidate_questions_for_transcript(
    transcript: str,
    bank: list[QuestionRecord],
    *,
    expected_count: int | None = None,
) -> list[QuestionRecord]:
    take = expected_count or reference_map_service.infer_expected_question_count(transcript)
    logger.info(
        "infer_expected_question_count=%d bank_size=%d",
        take, len(bank),
    )
    if len(bank) <= take:
        return list(bank)
    return await reference_map_service.select_relevant_questions_async(transcript, bank, limit=take)


def _question_semantic_tokens(question: QuestionRecord) -> set[str]:
    text = f"{question.question_text}".lower()
    return {
        tok
        for tok in re.findall(r"[a-zа-яё0-9]+", text)
        if len(tok) > 2 and tok not in {"это", "как", "что", "для", "при", "или", "его", "ее", "её"}
    }


def _is_metadata_only(segment: str) -> bool:
    s = (segment or "").strip().lower()
    if not s:
        return True
    if len(s) <= 80 and re.fullmatch(r"(?:номер\s+экзаменационного\s+билета|билет|номер\s+билета)\s*\d+", s):
        return True
    return False


def _has_explicit_segment_markers(segment: str) -> bool:
    s = (segment or "").strip().lower()
    if not s:
        return False
    return bool(
        re.search(
            r"(?i)\b(?:вопрос\s*(?:номер\s*|№\s*)?\d+|"
            r"перв(?:ый|ая|ое|ого|ой|ом)\s+вопрос|"
            r"втор(?:ой|ая|ое|ого|ом)\s+вопрос|"
            r"трет(?:ий|ья|ье|ьего|ьей|ьем)\s+вопрос|"
            r"ключ(?:\s*вопроса)?|шифр|код(?:\s*вопроса)?)\b",
            s,
        ),
    )


def _repair_segments(
    transcript: str,
    questions: list[QuestionRecord],
    parts: dict[str, str],
) -> dict[str, str]:
    fixed = {q.question_key: (parts.get(q.question_key) or "").strip() for q in questions}
    ordered_keys = [q.question_key for q in questions]

    prev_key: str | None = None
    for key in ordered_keys:
        seg = fixed.get(key, "")
        if not seg:
            continue
        low = seg.lower()
        if _is_metadata_only(seg):
            fixed[key] = ""
            continue
        if (
            prev_key
            and len(seg) < 220
            and not re.search(r"(?i)\b(?:вопрос|ключ|шифр|код|ответ)\b", seg)
            and re.match(r"(?i)^(?:он|она|оно|они|также|и|а|но|при этом|кроме того)\b", low)
        ):
            fixed[prev_key] = (fixed.get(prev_key, "") + " " + seg).strip()
            fixed[key] = ""
            continue
        prev_key = key

    nonempty = [k for k in ordered_keys if fixed.get(k, "").strip()]
    if len(nonempty) >= 2 and sum(1 for k in nonempty if _has_explicit_segment_markers(fixed.get(k, ""))) >= 2:
        return fixed
    substantial_segments = [k for k in nonempty if len(fixed.get(k, "").strip()) >= 200]
    if len(substantial_segments) >= 2:
        return fixed
    if len(questions) >= 2 and nonempty:
        token_map = {q.question_key: _question_semantic_tokens(q) for q in questions}
        rebuilt = {q.question_key: [] for q in questions}
        source_segments = [fixed[k] for k in nonempty if len(fixed.get(k, "")) > 350]
        if source_segments:
            sentences = re.split(r"(?<=[.!?])\s+|\n+", " ".join(source_segments))
            for sent in sentences:
                s = sent.strip()
                if not s:
                    continue
                s_tokens = {
                    tok
                    for tok in re.findall(r"[a-zа-яё0-9]+", s.lower())
                    if len(tok) > 2
                }
                best_key = nonempty[0]
                best_score = -1
                for q in questions:
                    score = len(s_tokens & token_map[q.question_key])
                    if score > best_score:
                        best_score = score
                        best_key = q.question_key
                rebuilt[best_key].append(s)
            if sum(1 for chunks in rebuilt.values() if chunks) >= 2:
                for key in ordered_keys:
                    fixed[key] = " ".join(rebuilt[key]).strip()

    if not any(v.strip() for v in fixed.values()):
        fixed[ordered_keys[0]] = transcript.strip()
    return fixed


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


def _is_new_command(text: str | None) -> bool:
    if not text:
        return False
    t_norm = _normalize_user_text(text)
    if _NEW_RE.match(t_norm):
        return True
    parts = t_norm.split()
    if not parts:
        return False
    head = parts[0].lower()
    return head == "/new" or head.startswith("/new@")


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
    expected_question_count: int | None = None,
    reply_language: str = "ru",
) -> None:
    """Сегментация по кандидатным вопросам и оценка каждого непустого фрагмента."""
    cleaned = strip_embedded_bot_output((transcript or "").strip())
    if not cleaned:
        await telegram_client.send_message(
            chat_id,
            t("cant_get_text_for_scoring", reply_language),
        )
        return
    transcript = cleaned
    transcript_for_scoring = strip_answer_completion_markers(transcript)
    if not transcript_for_scoring.strip():
        await telegram_client.send_message(
            chat_id,
            t("only_completion_phrase", reply_language),
        )
        return

    try:
        bank = await reference_map_service.get_question_bank(
            discipline_id,
            registration_raw=registration_raw,
        )
    except ValueError as e:
        await telegram_client.send_message(
            chat_id,
            t("config_error", reply_language, details=telegram_client.redact_secrets(str(e))),
        )
        return

    if not bank:
        await telegram_client.send_message(
            chat_id,
            t("no_references", reply_language),
        )
        return

    questions = await _candidate_questions_for_transcript(
        transcript,
        bank,
        expected_count=expected_question_count,
    )
    logger.info(
        "Кандидатные вопросы (%d): %s | transcript_len=%d",
        len(questions),
        [q.question_key for q in questions],
        len(transcript or ""),
    )
    logger.debug("Транскрипт (полный): %s", transcript)
    if not questions:
        await telegram_client.send_message(chat_id, t("no_questions_match", reply_language))
        return

    parts, notes = await segmentation_service.segment_with_fallback(
        transcript,
        questions,
        use_llm=settings.mvp_segmentation_use_llm,
    )
    parts = _repair_segments(transcript, questions, parts)
    logger.info(
        "Сегментация: ключи=%s непустых=%d",
        list(parts.keys()),
        sum(1 for v in parts.values() if (v or "").strip()),
    )

    has_openai = bool((settings.openai_api_key or "").strip())
    if not has_openai:
        lines = [
            t("scoring_unavailable_1", reply_language),
            t("scoring_unavailable_2", reply_language),
        ]
        if notes:
            lines.append("")
            lines.append(t("note_label", reply_language))
            lines.extend(notes)
        lines.append("")
        lines.append(t("full_transcript_label", reply_language))
        lines.append(_truncate_block(transcript, 3500))
        await telegram_client.send_message(chat_id, "\n".join(lines))
        return

    use_coverage = evaluation_service.use_coverage_scoring()

    scored: list[tuple[str, str, str, str]] = []
    totals_100: list[int] = []
    sim_scores: list[float] = []

    lines: list[str] = []

    lines.append(t("full_transcript_label", reply_language))
    lines.append(_truncate_block(transcript, max_len=3500))
    lines.append("")

    question_ordinal = 0
    for question in questions:
        key = question.question_key
        seg = (parts.get(key) or "").strip()
        ref = question.reference_answer
        if not seg:
            continue
        seg_eval = extract_answer_body_for_evaluation(strip_answer_completion_markers(seg))
        if not seg_eval.strip():
            seg_eval = strip_answer_completion_markers(seg)
        question_ordinal += 1
        if question_ordinal > 1:
            lines.append("")

        if use_coverage:
            try:
                r = await evaluation_service.evaluate_coverage(seg_eval, ref)
            except (ValueError, RuntimeError) as e:
                lines.append(
                    t(
                        "question_error",
                        reply_language,
                        question=t("question_label", reply_language, n=question_ordinal),
                        details=str(e),
                    ),
                )
                continue
            lines.extend(_coverage_lines_localized(question_ordinal, r, reply_language))
            totals_100.append(r.score)
            scored.append((key, str(r.score), seg, _coverage_rationale_for_sheet(r)))
        else:
            try:
                sim = await evaluation_service.evaluate_similarity(seg_eval, ref)
            except ValueError as e:
                lines.append(
                    t(
                        "question_error",
                        reply_language,
                        question=t("question_label", reply_language, n=question_ordinal),
                        details=str(e),
                    ),
                )
                continue
            lines.append(f"• {t('question_label', reply_language, n=question_ordinal)}")
            lines.append(f"  — {t('similarity_label', reply_language, score=f'{sim:.4f}')}")
            sim_scores.append(sim)
            scored.append((key, f"{sim:.4f}", seg, ""))

    if use_coverage and totals_100:
        mean_r = sum(totals_100) / len(totals_100)
        lines.append("")
        lines.append(t("average_label", reply_language))
        lines.append(_mean_formula_100(totals_100, mean_r))
    elif not use_coverage and len(sim_scores) >= 1:
        mean = sum(sim_scores) / len(sim_scores)
        lines.append("")
        lines.append(t("average_label", reply_language))
        lines.append(_mean_formula_similarity(sim_scores, mean))

    if notes:
        lines.append("")
        lines.append(t("note_label", reply_language))
        lines.extend(notes)
    if scored:
        lines.append("")
        lines.append(_preliminary_disclaimer(reply_language))

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


async def _handle_answer_payload(
    sess: ExamSession,
    chat_id: int,
    user_id: int,
    raw_text: str,
    *,
    telegram_message_id: int | None = None,
    reply_language: str = "ru",
) -> None:
    previous_pending = sess.pending_transcript
    normalized = strip_embedded_bot_output((raw_text or "").strip())
    if not normalized:
        await telegram_client.send_message(chat_id, t("cant_get_text_again", reply_language))
        return
    logger.info("incoming transcript: len=%d", len(normalized))
    logger.debug("incoming transcript (полный): %r", normalized)
    if not _has_meaningful_answer_text(normalized):
        sess.pending_transcript = previous_pending
        sess.last_transcript = previous_pending
        await telegram_client.send_message(chat_id, _transcription_too_short_message(reply_language))
        return

    tn = extract_ticket_number(normalized)
    if tn:
        sess.ticket_number = tn

    sess.pending_transcript = _merge_transcripts(sess.pending_transcript, normalized)
    sess.last_transcript = sess.pending_transcript

    try:
        bank = await reference_map_service.get_question_bank(
            sess.discipline_id,
            registration_raw=sess.registration_raw,
        )
    except ValueError as e:
        await telegram_client.send_message(
            chat_id,
            t("config_error", reply_language, details=telegram_client.redact_secrets(str(e))),
        )
        return

    if not bank:
        await telegram_client.send_message(
            chat_id,
            t("no_references", reply_language),
        )
        return

    expected_count = _expected_question_count_from_registration(
        sess.registration_raw,
        sess.pending_transcript,
    )
    questions = await _candidate_questions_for_transcript(
        sess.pending_transcript,
        bank,
        expected_count=expected_count,
    )
    target_count = min(expected_count, len(questions)) if questions else expected_count
    parts, _notes = await segmentation_service.segment_with_fallback(
        sess.pending_transcript,
        questions,
        use_llm=settings.mvp_segmentation_use_llm,
    )
    parts = _repair_segments(sess.pending_transcript, questions, parts)
    answered_count = _count_answered_questions(questions, parts)
    completion_seen = contains_answer_completion_marker(normalized)
    if answered_count == 0 and target_count <= 1 and _has_meaningful_answer_text(sess.pending_transcript):
        answered_count = 1
    logger.info(
        "answer readiness: expected=%d target=%d answered=%d completion_seen=%s transcript_len=%d",
        expected_count,
        target_count,
        answered_count,
        completion_seen,
        len(sess.pending_transcript or ""),
    )

    if answered_count < target_count:
        await telegram_client.send_message(
            chat_id,
            _pending_progress_message(answered_count, target_count, completion_seen, reply_language),
        )
        return

    await _evaluate_and_reply(
        chat_id,
        sess.pending_transcript,
        telegram_user_id=user_id,
        session_id=sess.session_id,
        discipline_id=sess.discipline_id,
        registration_raw=sess.registration_raw,
        telegram_message_id=telegram_message_id,
        ticket_number=sess.ticket_number,
        expected_question_count=expected_count,
        reply_language=reply_language,
    )
    sess.pending_transcript = None


async def _handle_voice_answering(
    sess: ExamSession,
    chat_id: int,
    user_id: int,
    message: dict[str, Any],
) -> None:
    reply_language = bot_texts.normalize_lang(sess.language or "ru")
    voice = message.get("voice")
    if not isinstance(voice, dict):
        await telegram_client.send_message(chat_id, t("no_voice_attachment", reply_language))
        return
    file_id = voice.get("file_id")
    if not isinstance(file_id, str):
        await telegram_client.send_message(chat_id, t("no_voice_file_id", reply_language))
        return

    try:
        audio = await telegram_client.download_file_bytes(file_id)
        lang = sess.language or "ru"
        expected_question_count = _expected_question_count_from_registration(sess.registration_raw, "")
        transcript = await speech_service.transcribe_exam_answer(
            audio,
            language=lang,
            expected_question_count=expected_question_count,
        )
        raw_tr = (transcript or "").strip()
        mid_raw = message.get("message_id")
        msg_id = mid_raw if isinstance(mid_raw, int) else None
        await _handle_answer_payload(
            sess,
            chat_id,
            user_id,
            raw_tr,
            telegram_message_id=msg_id,
            reply_language=reply_language,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Ошибка конвейера голоса")
        await telegram_client.send_message(
            chat_id,
            t("voice_processing_error", reply_language, details=telegram_client.redact_secrets(str(e))),
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
    new_cmd = _is_new_command(text)
    existing_session = await session_service.get_session(user_id)
    reply_language = _reply_language(text, fallback=(existing_session.language if existing_session else "ru"))

    if start_cmd or new_cmd:
        logger.info("Команда reset (%s): user_id=%s chat_id=%s", "/start" if start_cmd else "/new", user_id, chat_id)
        sess = await session_service.reset_session(user_id)
        sess.start_time = time.monotonic()
        out = fsm_service.process_message(
            sess,
            text=text,
            has_voice=has_voice,
            is_start_command=True,
            reply_language=reply_language,
            include_welcome=True,
        )
        await session_service.upsert_session(out.session)
        for line in out.messages:
            await telegram_client.send_message(chat_id, line)
        return

    sess = existing_session
    if sess is None:
        sess = ExamSession(user_id=user_id)
        logger.info("Новая сессия (не было в памяти): user_id=%s state=%s", user_id, sess.state.value)
    else:
        logger.info(
            "Сессия из памяти: user_id=%s state=%s text_len=%d",
            user_id, sess.state.value, len(text or ""),
        )
        logger.debug("Сессия из памяти: user_id=%s text=%r", user_id, text)

    if session_service.is_timed_out(sess) and sess.state != ExamState.FINISH:
        await telegram_client.send_message(
            chat_id,
            t("timeout_restart", reply_language),
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
        reply_language=reply_language,
    )
    logger.info(
        "FSM → state=%s msgs=%d evaluate=%s user_id=%s",
        out.session.state.value,
        len(out.messages),
        bool(out.evaluate_text),
        user_id,
    )

    for line in out.messages:
        await telegram_client.send_message(chat_id, line)

    if out.evaluate_text:
        raw_eval = out.evaluate_text.strip()
        mid_raw = message.get("message_id")
        msg_id = mid_raw if isinstance(mid_raw, int) else None
        await _handle_answer_payload(
            out.session,
            chat_id,
            user_id,
            raw_eval,
            telegram_message_id=msg_id,
            reply_language=reply_language,
        )

    await session_service.upsert_session(out.session)
