"""Извлечение служебных полей из ответа студента (текст / транскрипт)."""

from __future__ import annotations

import re


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
