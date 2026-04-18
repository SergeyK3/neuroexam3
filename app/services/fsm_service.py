"""FSM logic for the exam scenario."""

from dataclasses import dataclass
import re

from app.core.config import settings
from app.models.session import ExamSession, ExamState
from app.services.bot_texts import normalize_lang, t


_HINT_PATTERNS = (
    r"(?i)\bподска(?:жи|жите|зка)\b",
    r"(?i)\bправильн\w*\s+ответ\b",
    r"(?i)\bкорректн\w*\s+ответ\b",
    r"(?i)\bформулиров\w*\b",
    r"(?i)\bдай\s+ответ\b",
    r"(?i)\bhint\b",
    r"(?i)\bcorrect answer\b",
    r"(?i)\bhelp me answer\b",
    r"(?i)\bwording\b",
    r"(?i)\bдұрыс\s+жауап\b",
    r"(?i)\bкөмек\b",
    r"(?i)\bжауапты\s+айт\b",
)

_LANG_ALIASES = {
    "ru": "ru",
    "rus": "ru",
    "ру": "ru",
    "русский": "ru",
    "1": "ru",
    "kk": "kk",
    "каз": "kk",
    "казахский": "kk",
    "қазақ": "kk",
    "қазақша": "kk",
    "2": "kk",
    "en": "en",
    "eng": "en",
    "english": "en",
    "английский": "en",
    "3": "en",
}


def _fragments_from_message(text: str) -> list[str]:
    """Фрагменты из одного сообщения: строки, либо одна строка с разделителями ; | , либо одна фраза."""
    t = text.strip()
    if not t:
        return []
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if len(lines) > 1:
        return lines
    single = lines[0] if lines else t
    for sep in (";", "|"):
        if sep in single:
            parts = [p.strip() for p in single.split(sep) if p.strip()]
            return parts
    return [single]


@dataclass
class FsmOutcome:
    """Результат шага FSM: ответы пользователю и опционально текст для оценки."""

    session: ExamSession
    messages: list[str]
    evaluate_text: str | None = None


def process_message(
    session: ExamSession,
    *,
    text: str,
    has_voice: bool,
    is_start_command: bool,
    reply_language: str | None = None,
    include_welcome: bool = False,
) -> FsmOutcome:
    t = text.strip() if text else ""
    lower = t.lower()
    lang = normalize_lang(reply_language or session.language or "ru")

    if has_voice:
        if session.state == ExamState.START:
            return FsmOutcome(session, [t_("send_start_first", lang)])
        if session.state in (ExamState.LANGUAGE, ExamState.DISCIPLINE, ExamState.REGISTRATION):
            return FsmOutcome(session, [t_("text_not_voice", lang)])

    if is_start_command:
        session.state = ExamState.LANGUAGE
        messages = [t_("choose_language", lang)]
        if include_welcome:
            messages.insert(0, t_("welcome_start", lang))
        return FsmOutcome(session, messages)

    if session.state == ExamState.START:
        return FsmOutcome(session, [t_("send_start", lang)])

    if session.state == ExamState.LANGUAGE:
        key = _LANG_ALIASES.get(lower)
        if not key:
            return FsmOutcome(
                session,
                [
                    t_("need_choose_language", lang),
                ],
            )
        session.language = key
        lang = key
        slugs = settings.ordered_discipline_slugs()
        if len(slugs) > 1:
            session.state = ExamState.DISCIPLINE
            lines = [
                t_("choose_discipline_intro", lang),
                *[f"{i}. {s}" for i, s in enumerate(slugs, start=1)],
            ]
            return FsmOutcome(session, ["\n".join(lines)])
        if len(slugs) == 1:
            session.discipline_id = slugs[0]
        else:
            session.discipline_id = None
        session.registration_parts = []
        session.state = ExamState.REGISTRATION
        return FsmOutcome(session, [t_("registration_prompt", lang)])

    if session.state == ExamState.DISCIPLINE:
        slugs = settings.ordered_discipline_slugs()
        if len(slugs) < 2:
            session.registration_parts = []
            session.state = ExamState.REGISTRATION
            return FsmOutcome(session, [t_("registration_prompt", lang)])
        raw = t.strip()
        if not raw:
            return FsmOutcome(
                session,
                [t_("discipline_prompt_number", lang, count=len(slugs), example=slugs[0])],
            )
        chosen: str | None = None
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(slugs):
                chosen = slugs[n - 1]
        if chosen is None:
            low = raw.lower()
            for s in slugs:
                if s.lower() == low:
                    chosen = s
                    break
        if chosen is None:
            return FsmOutcome(
                session,
                [
                    t_("discipline_not_matched", lang, count=len(slugs)),
                ],
            )
        session.discipline_id = chosen
        session.registration_parts = []
        session.state = ExamState.REGISTRATION
        return FsmOutcome(session, [t_("registration_prompt", lang)])

    if session.state == ExamState.REGISTRATION:
        if not t:
            return FsmOutcome(session, [t_("registration_text_only", lang)])
        frags = _fragments_from_message(t)
        if not frags:
            return FsmOutcome(session, [t_("send_nonempty_text", lang)])
        buf = list(session.registration_parts)
        for f in frags:
            if len(buf) >= 4:
                break
            buf.append(f)
        session.registration_parts = buf
        if len(session.registration_parts) < 4:
            n = len(session.registration_parts)
            nxt = _registration_label(n, lang)
            return FsmOutcome(
                session,
                [
                    t_("registration_progress", lang, n=n, field=nxt, remaining=4 - n),
                ],
            )
        session.registration_raw = "\n".join(session.registration_parts[:4])
        session.registration_parts = []
        session.state = ExamState.ANSWERING
        return FsmOutcome(
            session,
            [
                t_("answering_prompt", lang),
            ],
        )

    if session.state == ExamState.ANSWERING:
        if has_voice:
            return FsmOutcome(session, [], evaluate_text=None)
        if not t:
            return FsmOutcome(session, [t_("send_text_or_voice", lang)])
        if _looks_like_hint_request(t):
            return FsmOutcome(session, [t_("hint_refusal", lang)])
        finish_phrases = (
            "ответ закончен",
            "дай оценку",
            "закончен ответ",
            "оцени",
        )
        if any(p in lower for p in finish_phrases) and len(t) < 120:
            return FsmOutcome(
                session,
                [
                    t_("finish_phrase_only", lang),
                ],
            )
        return FsmOutcome(session, [], evaluate_text=t)

    if session.state == ExamState.FINISH:
        return FsmOutcome(
            session,
            [t_("exam_finished_restart", lang)],
        )

    return FsmOutcome(session, [t_("unknown_state_restart", lang)])


def t_(key: str, lang: str, **kwargs: object) -> str:
    return t(key, lang, **kwargs)


def _registration_label(index: int, lang: str) -> str:
    keys = (
        "registration_field_course",
        "registration_field_control",
        "registration_field_group",
        "registration_field_name",
    )
    return t_(keys[index], lang)


def _looks_like_hint_request(text: str) -> bool:
    sample = (text or "").strip()
    if len(sample) < 3:
        return False
    return any(re.search(pattern, sample) for pattern in _HINT_PATTERNS)
