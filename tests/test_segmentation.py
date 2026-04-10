"""Тесты сегментации транскрипта по ключам."""

import pytest

from app.services import segmentation_service


def test_one_key_returns_whole_transcript():
    t = "Полный ответ студента."
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, ["Q1"])
    assert err is None
    assert try_llm is False
    assert parts == {"Q1": t}


def test_three_paragraphs_three_keys():
    t = "Ответ один.\n\nВторой блок.\n\nТретий блок."
    keys = ["Q1", "Q2", "Q3"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert parts["Q1"] == "Ответ один."
    assert "Второй" in parts["Q2"]


def test_separator_triple_dash():
    t = "A\n---\nB\n---\nC"
    keys = ["Q1", "Q2", "Q3"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert parts["Q1"].strip() == "A"
    assert parts["Q3"].strip() == "C"


def test_fallback_puts_all_in_first_key_and_flags_llm():
    t = "Один сплошной текст без разбиения на три части."
    keys = ["Q1", "Q2", "Q3"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is True
    assert parts["Q1"] == t
    assert parts["Q2"] == ""


def test_russian_question_markers_two_blocks():
    t = (
        "Билет номер 11, вопрос 1, ключ 121. Первый ответ по сути. "
        "Вопрос номер 2, ключ 157, какие проблемы помогает решать библиотека. Второй ответ. Ответ закончен."
    )
    keys = ["Q1", "Q2", "Q3"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert "Первый ответ" in parts["Q1"]
    assert "Второй ответ" in parts["Q2"]
    assert parts["Q3"] == ""


def test_russian_only_question_two_marker():
    t = "Сначала ответ на первый вопрос без явного «вопрос 1». Вопрос номер 2, ключ 99, продолжение."
    keys = ["Q1", "Q2"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert "Сначала" in parts["Q1"]
    assert "продолжение" in parts["Q2"]


def test_russian_question_number_sign_marker():
    t = "Первый блок текста. Вопрос № 2, ключ 42, второй блок."
    keys = ["Q1", "Q2"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert "Первый" in parts["Q1"]
    assert "второй" in parts["Q2"]


def test_russian_ordinal_key_markers():
    """Порядковые «первый ключ / второй ключ» без кодов из таблицы в паттернах."""
    t = (
        "Вступление. Первый ключ. Ответ про А. "
        "Второй ключ. Ответ про Б и В."
    )
    keys = ["Q1", "Q2"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert "про А" in parts["Q1"]
    assert "про Б" in parts["Q2"]


def test_transition_speech_markers():
    t = "Начало ответа по первому. Следующий вопрос. Продолжение по второму."
    keys = ["Q1", "Q2"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert "первому" in parts["Q1"]
    assert "второму" in parts["Q2"]


def test_russian_ordinal_first_second_question_exam_style():
    """Как в устном ответе: «первый вопрос, ключ …» и отдельно «Второй вопрос.» без «вопрос 2»."""
    t = (
        "Информационные технологии в медицине, РК №1, Кожеева Амина, билет 14, "
        "первый вопрос, ключ 146. Объясните значение реального времени. "
        "Ответ про мониторинг и визуализацию. "
        "Второй вопрос. Ключ 1, 2, 8. Какие методы сбора данных для регистров. "
        "Ответ про регистры и сбор данных."
    )
    keys = ["146", "1, 2, 8"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert "реального времени" in parts["146"] or "мониторинг" in parts["146"]
    assert "регистр" in parts["1, 2, 8"].lower() or "сбор" in parts["1, 2, 8"].lower()


@pytest.mark.asyncio
async def test_mvp_reference_map_json(monkeypatch):
    from app.core import config as cfg

    monkeypatch.setattr(
        cfg.settings,
        "mvp_references_json",
        '{"A":"ra","B":"rb"}',
        raising=False,
    )
    monkeypatch.setattr(cfg.settings, "mvp_question_key", "Q1", raising=False)
    monkeypatch.setattr(cfg.settings, "mvp_reference_answer", "x", raising=False)
    m = cfg.settings.mvp_reference_map()
    assert m == {"A": "ra", "B": "rb"}
