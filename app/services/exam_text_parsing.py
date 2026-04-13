"""Извлечение служебных полей из ответа студента (текст / транскрипт)."""

from __future__ import annotations

import re
import unicodedata

# Фразы, которыми студент помечает конец ответа (устно/в конце текста); в оценку и Sheets не должны попадать.
# Только устойчивые многословные шаблоны (без коротких «оцени» и т.п., чтобы не резать обычный текст).
_COMPLETION_PHRASES = (
    r"ответ\s+закончен",
    r"закончен\s+ответ",
    r"ответ\s+окончен",
    r"окончен\s+ответ",
    r"конец\s+ответа",
    r"the\s+answer\s+is\s+over",
    r"answer\s+is\s+over",
    r"the\s+answer\s+is\s+complete",
    r"answer\s+is\s+complete",
    r"the\s+answer\s+is\s+finished",
    r"answer\s+is\s+finished",
    r"answer\s+finished",
    r"my\s+answer\s+is\s+finished",
    r"my\s+answer\s+is\s+complete",
    r"finished\s+my\s+answer",
    r"i\s+finished\s+my\s+answer",
    r"i\x27m\s+done\s+with\s+my\s+answer",
    r"end\s+of\s+answer",
    r"that\x27s\s+the\s+end\s+of\s+my\s+answer",
    r"that\s+is\s+the\s+end\s+of\s+my\s+answer",
    r"жауап\s+аяқталды",
    r"жауап\s+бітті",
    r"жауапымды\s+аяқтадым",
    r"менің\s+жауабым\s+аяқталды",
)
_COMPLETION_RE = re.compile(
    r"(?iu)(?<!\w)(?:" + "|".join(_COMPLETION_PHRASES) + r")(?!\w)\s*[\.,!?;:…]*",
)
_LEGACY_BOT_OUTPUT_START_RE = re.compile(
    r"(?is)(?:^|\n|\s)(?:•\s*)?Вопрос\s+1\b.*",
)
_LEGACY_BOT_TAIL_RE = re.compile(
    r"(?is)\b(?:ошибк[аи]|примечани[ея])\b.*",
)


_TICKET_PATTERNS = (
    # «билет 14», «билет № 14», «билет номер 14»
    re.compile(r"(?i)билет(?:а|у)?\s*(?:номер|№)?\s*[:.;]?\s*(\d{1,6})\b"),
    re.compile(r"(?i)номер\s+билета\s*[:.;]?\s*(\d{1,6})\b"),
    re.compile(r"(?i)№\s*билета\s*[:.;]?\s*(\d{1,6})\b"),
    # «экзаменационный билет 12»
    re.compile(r"(?i)экзаменационн(?:ый|ого)\s+билет\s*[:.;]?\s*(\d{1,6})\b"),
)


def extract_ticket_number(text: str | None) -> str | None:
    """
    Номер билета из устной/письменной формулировки (билет 14, номер билета 3, …).
    Возвращает строку цифр или None.
    """
    if not text or not str(text).strip():
        return None
    t = str(text)
    for rx in _TICKET_PATTERNS:
        m = rx.search(t)
        if m:
            return m.group(1).strip()
    return None


_OTVET_MARKER = re.compile(r"(?is)\bОтвет\s*[.:]\s*")


def split_at_otvet_marker(text: str | None) -> tuple[str, str]:
    """
    Разделить фрагмент на (текст до «Ответ.», текст после маркера).
    Если маркера нет — («», весь текст): для вывода в Telegram в хронологии билет → вопрос → ключ → ответ.
    """
    t = unicodedata.normalize("NFC", (text or "").strip())
    if not t:
        return ("", "")
    m = _OTVET_MARKER.search(t)
    if not m:
        return ("", t)
    return (t[: m.start()].strip(), t[m.end() :].strip())


def extract_answer_body_for_evaluation(text: str | None) -> str:
    """
    Устный экзамен: после «Билет … / первый вопрос …» студент говорит «Ответ. <суть>».
    Рубрику нужно строить по части после «Ответ.», иначе низкая полнота из‑за отсутствия «данных в ЭМК»
    при том, что суть сказана ниже в том же фрагменте.
    """
    t = unicodedata.normalize("NFC", (text or "").strip())
    if not t:
        return ""
    m = _OTVET_MARKER.search(t)
    if not m:
        return t
    head = t[: m.start()].strip()
    if len(head) > 900:
        return t
    # Только если до «Ответ.» похоже на инструкцию экзаменатора, а не на сам ответ.
    if not re.search(r"(?i)билет|номер\s+билета|экзаменационн", head):
        return t
    if not re.search(r"(?i)вопрос|ключ\b|шифр|код\s*вопроса|обозначение", head):
        return t
    tail = t[m.end() :].strip()
    return tail if tail else t


def strip_answer_completion_markers(text: str | None) -> str:
    """
    Убрать типовые фразы «ответ окончен» / answer is over / жауап аяқталды и т.п.
    Студент произносит их как сигнал конца записи; в рубрику и таблицу они не должны попадать.
    """
    if not text or not str(text).strip():
        return ""
    t = unicodedata.normalize("NFC", str(text))
    prev = None
    while prev != t:
        prev = t
        t = _COMPLETION_RE.sub(" ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def strip_embedded_bot_output(text: str | None) -> str:
    """
    Убрать хвосты, которые попали в транскрипт из старого вывода бота:
    «• Вопрос 1 Обоснование ...», «Среднее по рубрике ...», «Ошибка ...».
    """
    if not text or not str(text).strip():
        return ""
    t = unicodedata.normalize("NFC", str(text)).strip()
    m = _LEGACY_BOT_OUTPUT_START_RE.search(t)
    if m:
        t = t[: m.start()].strip()
    m2 = _LEGACY_BOT_TAIL_RE.search(t)
    if m2:
        t = t[: m2.start()].strip()
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
