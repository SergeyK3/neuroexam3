"""Логика переходов FSM (без сети). Сообщения — как в прежнем сценарии бота."""

from dataclasses import dataclass

from app.core.config import settings
from app.models.session import ExamSession, ExamState

_LANG_ALIASES = {
    "ru": "ru",
    "rus": "ru",
    "ру": "ru",
    "русский": "ru",
    "1": "ru",
    "kk": "kk",
    "каз": "kk",
    "казахский": "kk",
    "қазақша": "kk",
    "2": "kk",
    "en": "en",
    "eng": "en",
    "english": "en",
    "английский": "en",
    "3": "en",
}


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
                "Пожалуйста, выберите язык экзамена: Русский, Казахский или Английский "
                "(можно: Русский / Казахский / English или 1 / 2 / 3).",
            ],
        )

    if session.state == ExamState.START:
        return FsmOutcome(session, ["Чтобы начать, отправьте команду /start."])

    if session.state == ExamState.LANGUAGE:
        key = _LANG_ALIASES.get(lower)
        if not key:
            return FsmOutcome(
                session,
                ["Нужно выбрать язык: Русский или Казахский (или 1 / 2)."],
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
        session.state = ExamState.REGISTRATION
        return FsmOutcome(
            session,
            [
                "Пожалуйста, предоставьте следующие регистрационные данные одним сообщением:\n"
                "• Название дисциплины или курса\n"
                "• Название контроля (рубежный контроль или экзамен)\n"
                "• ФИО полностью",
            ],
        )

    if session.state == ExamState.DISCIPLINE:
        slugs = settings.ordered_discipline_slugs()
        if len(slugs) < 2:
            session.state = ExamState.REGISTRATION
            return FsmOutcome(
                session,
                [
                    "Пожалуйста, предоставьте следующие регистрационные данные одним сообщением:\n"
                    "• Название дисциплины или курса\n"
                    "• Название контроля (рубежный контроль или экзамен)\n"
                    "• ФИО полностью",
                ],
            )
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
        session.state = ExamState.REGISTRATION
        return FsmOutcome(
            session,
            [
                "Пожалуйста, предоставьте следующие регистрационные данные одним сообщением:\n"
                "• Название дисциплины или курса\n"
                "• Название контроля (рубежный контроль или экзамен)\n"
                "• ФИО полностью",
            ],
        )

    if session.state == ExamState.REGISTRATION:
        if not t:
            return FsmOutcome(session, ["Отправьте регистрационные данные текстом (см. список выше)."])
        session.registration_raw = t
        session.state = ExamState.ANSWERING
        return FsmOutcome(
            session,
            [
                "Спасибо. Теперь предоставьте данные для экзамена (при необходимости — отдельным сообщением):\n"
                "• Номер экзаменационного билета\n"
                "• Ключ вопроса\n"
                "• Ответ на вопрос\n"
                "• Ключ следующего вопроса и ответ (если есть)\n\n"
                "Затем отправьте ответ **текстом или голосом**. "
                "Несколько ответов: разделяйте блоки пустой строкой, строкой «---» или подписями «Q1: …», «Q2: …». "
                "Эталоны задаются на сервере (MVP); эталон в чате не показывается.",
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
