"""Парсинг номера билета из ответа."""

from app.services.exam_text_parsing import (
    extract_answer_body_for_evaluation,
    extract_ticket_number,
    split_at_otvet_marker,
    strip_answer_completion_markers,
)


def test_extract_ticket_bilet_number():
    assert extract_ticket_number("Билет 14, первый вопрос ключ 146") == "14"


def test_extract_ticket_nomber():
    assert extract_ticket_number("Номер билета: 3. Ответ …") == "3"


def test_extract_ticket_none():
    assert extract_ticket_number("Только текст без номера") is None


def test_strip_completion_russian():
    t = "Билет 5. Синапс передаёт сигнал.\nОтвет закончен."
    assert strip_answer_completion_markers(t) == "Билет 5. Синапс передаёт сигнал."


def test_strip_completion_english():
    t = "The neuron fires. Answer is over."
    assert strip_answer_completion_markers(t) == "The neuron fires."


def test_strip_completion_kazakh():
    t = "Мәтін. Жауап аяқталды."
    assert strip_answer_completion_markers(t) == "Мәтін."


def test_strip_completion_only_marker():
    assert strip_answer_completion_markers("Ответ закончен.") == ""


def test_extract_answer_after_otvet_oral_exam():
    raw = (
        "Билет номер 17. Первый вопрос. Какие данные включаются в электронные медицинские карты\n\n"
        "Ответ. Электронные медицинские карты - это систематизированный сборник."
    )
    out = extract_answer_body_for_evaluation(raw)
    assert "Электронные медицинские карты - это" in out
    assert "Билет номер 17" not in out


def test_extract_answer_no_strip_without_bilet():
    t = "Ключ 1-5-9. Ответ. Только суть."
    assert extract_answer_body_for_evaluation(t) == t


def test_split_at_otvet_marker_no_marker_all_in_tail():
    head, tail = split_at_otvet_marker("Только текст без маркера ответа")
    assert head == ""
    assert tail == "Только текст без маркера ответа"


def test_split_at_otvet_marker_splits():
    raw = "Билет 3. Первый вопрос. Ответ. Суть здесь."
    head, tail = split_at_otvet_marker(raw)
    assert "Билет 3" in head
    assert tail == "Суть здесь."


def test_extract_answer_shifr_in_instruction_head():
    raw = (
        "Билет 2. Шифр 1-5-9. Краткая вводная перед ответом.\n\n"
        "Ответ. Электронные медицинские карты включают данные пациента."
    )
    out = extract_answer_body_for_evaluation(raw)
    assert "Электронные медицинские карты" in out
    assert "Билет 2" not in out
