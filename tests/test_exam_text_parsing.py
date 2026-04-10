"""Парсинг номера билета из ответа."""

from app.services.exam_text_parsing import extract_ticket_number


def test_extract_ticket_bilet_number():
    assert extract_ticket_number("Билет 14, первый вопрос ключ 146") == "14"


def test_extract_ticket_nomber():
    assert extract_ticket_number("Номер билета: 3. Ответ …") == "3"


def test_extract_ticket_none():
    assert extract_ticket_number("Только текст без номера") is None
