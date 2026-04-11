"""Логика переходов FSM (без сети). Сообщения — как в прежнем сценарии бота."""

from dataclasses import dataclass

from app.core.config import settings
from app.models.session import ExamSession, ExamState

_REGISTRATION_LABELS = (
    "название дисциплины или курса",
    "вид контроля (рубежный контроль или экзамен)",
    "номер группы",
    "ФИО полностью",
)

_REGISTRATION_PROMPT = (
    "Нужны **четыре сведения по порядку**:\n"
    "1) Название дисциплины или курса\n"
    "2) Вид контроля (рубежный контроль или экзамен)\n"
    "3) Номер группы\n"
    "4) ФИО полностью\n\n"
    "Можно отправить **одним сообщением** (несколько строк или через `;` / `|`), "
    "или **несколькими сообщениями подряд** — если случайно нажали Enter, просто допишите в следующих сообщениях."
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
) -> FsmOutcome:
    t = text.strip() if text else ""
    lower = t.lower()

    if has_voice:
        if session.state == ExamState.START:
            return FsmOutcome(session, ["Сначала отправьте команду /start."])
        if session.state in (ExamState.LANGUAGE, ExamState.DISCIPLINE, ExamState.REGISTRATION):
            return FsmOutcome(session, ["На этом шаге нужен текст, а не голосовое сообщение."])

    if is_start_command:
        session.state = ExamState.LANGUAGE
        return FsmOutcome(
            session,
            [
                "Пожалуйста, выберите язык экзамена: Русский (1), Қазақ (2) или English (3).",
            ],
        )

    if session.state == ExamState.START:
        return FsmOutcome(session, ["Чтобы начать, отправьте команду /start."])

    if session.state == ExamState.LANGUAGE:
        key = _LANG_ALIASES.get(lower)
        if not key:
            return FsmOutcome(
                session,
                [
                    "Нужно выбрать язык: Русский (1), Қазақ (2) или English (3) "
                    "(можно написать словом или цифрой).",
                ],
            )
        session.language = key
        slugs = settings.ordered_discipline_slugs()
        if len(slugs) > 1:
            session.state = ExamState.DISCIPLINE
            lines = [
                "Выберите дисциплину (ответьте номером или кодом из списка):",
                *[f"{i}. {s}" for i, s in enumerate(slugs, start=1)],
            ]
            return FsmOutcome(session, ["\n".join(lines)])
        if len(slugs) == 1:
            session.discipline_id = slugs[0]
        else:
            session.discipline_id = None
        session.registration_parts = []
        session.state = ExamState.REGISTRATION
        return FsmOutcome(session, [_REGISTRATION_PROMPT])

    if session.state == ExamState.DISCIPLINE:
        slugs = settings.ordered_discipline_slugs()
        if len(slugs) < 2:
            session.registration_parts = []
            session.state = ExamState.REGISTRATION
            return FsmOutcome(session, [_REGISTRATION_PROMPT])
        raw = t.strip()
        if not raw:
            return FsmOutcome(
                session,
                ["Укажите номер дисциплины (1…{}) или код (например «{}»).".format(len(slugs), slugs[0])],
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
                    "Не удалось сопоставить ответ с дисциплиной. "
                    "Отправьте номер из списка (1…{}) или точный код дисциплины.".format(len(slugs)),
                ],
            )
        session.discipline_id = chosen
        session.registration_parts = []
        session.state = ExamState.REGISTRATION
        return FsmOutcome(session, [_REGISTRATION_PROMPT])

    if session.state == ExamState.REGISTRATION:
        if not t:
            return FsmOutcome(session, ["Отправьте регистрационные данные текстом (см. список выше)."])
        frags = _fragments_from_message(t)
        if not frags:
            return FsmOutcome(session, ["Отправьте непустой текст."])
        buf = list(session.registration_parts)
        for f in frags:
            if len(buf) >= 4:
                break
            buf.append(f)
        session.registration_parts = buf
        if len(session.registration_parts) < 4:
            n = len(session.registration_parts)
            nxt = _REGISTRATION_LABELS[n]
            return FsmOutcome(
                session,
                [
                    f"Принято ({n}/4). Дальше пришлите: **{nxt}** "
                    f"(отдельным сообщением или вместе с остальным — как удобно). "
                    f"Осталось полей: {4 - n}.",
                ],
            )
        session.registration_raw = "\n".join(session.registration_parts[:4])
        session.registration_parts = []
        session.state = ExamState.ANSWERING
        return FsmOutcome(
            session,
            [
                "Спасибо. Теперь предоставьте данные для экзамена (при необходимости — отдельным сообщением):\n"
                "• Номер экзаменационного билета\n"
                "• Ключ вопроса\n"
                "• Ответ на вопрос\n"
                "• Ключ следующего вопроса и ответ (если есть)\n",
            ],
        )

    if session.state == ExamState.ANSWERING:
        if has_voice:
            return FsmOutcome(session, [], evaluate_text=None)
        if not t:
            return FsmOutcome(session, ["Отправьте текстовый ответ или голосовое сообщение."])
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
                    "Голосовые ответы оцениваются автоматически после распознавания речи. "
                    "Текстовый ответ оценивается по сообщению с содержанием (не только по этой фразе).",
                ],
            )
        return FsmOutcome(session, [], evaluate_text=t)

    if session.state == ExamState.FINISH:
        return FsmOutcome(
            session,
            ["Экзамен завершён. Чтобы начать снова, отправьте /start."],
        )

    return FsmOutcome(session, ["Неизвестное состояние. Попробуйте /start."])
