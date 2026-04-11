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


def test_bilet_preamble_merges_to_first_spoken_key_not_first_sheet_row():
    """Преамбула с билетом — к первому произнесённому шифру, не к первой строке эталонов."""
    t = (
        "Билет номер 17. Первый вопрос. Кратко про формулировку. "
        "Ключ вопроса 1-1-10. Ответ. Электронные медицинские карты — это система."
    )
    keys = ["1-1-1", "1-1-10"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert not (parts.get("1-1-1") or "").strip()
    assert "Билет" in (parts.get("1-1-10") or "")
    assert "Электронные" in (parts.get("1-1-10") or "")


def test_preamble_before_klyuch_goes_to_first_table_key():
    """Текст до первого «Ключ …» — первый вопрос (первая строка эталонов), не теряется."""
    t = (
        "Краткий ответ про МИС и регистры. Затем второй блок. "
        "Как структурирована библиотека? Ключ 1-5-9. Ответ. Корпоративная библиотека — это система."
    )
    keys = ["MIS_KEY", "1-5-9"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert "МИС" in parts["MIS_KEY"] or "регистр" in parts["MIS_KEY"].lower()
    assert "Корпоративная" in parts["1-5-9"] or "библиотек" in parts["1-5-9"].lower()


def test_key_speech_klyuch_voprosa_before_digit_code():
    """«Ключ вопроса 1-5-9» — между словом «ключ» и шифром может быть «вопроса» (раньше ломало разметку)."""
    t = (
        "Вступление про МИС. Ключ вопроса 1-5-9. Корпоративная библиотека — это система. "
        "Шифр 2-2-2. Второй фрагмент."
    )
    keys = ["MIS_KEY", "1-5-9", "2-2-2"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert "МИС" in parts["MIS_KEY"] or "Вступление" in parts["MIS_KEY"]
    assert "Корпоративная" in parts["1-5-9"] or "библиотек" in parts["1-5-9"].lower()
    assert "Второй" in parts["2-2-2"]


def test_key_speech_shifr_and_po_shifru():
    t = "По шифру 9-9-9, рассказываю про регистры. Ключ 8-8-8. Про библиотеку."
    keys = ["9-9-9", "8-8-8"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert "регистр" in parts["9-9-9"].lower()
    assert "библиотек" in parts["8-8-8"].lower()


def test_inline_klyuch_typo_digit_key_maps_to_sheet():
    """Вопрос в тексте, затем «Ключ 1-5-8.» — в эталоне 1-5-9; не привязывать ко второму ключу таблицы."""
    t = (
        "Как структурирована корпоративная библиотека в медучреждениях? Ключ 1-5-8. Ответ. "
        "Корпоративная библиотека — это структурированная система."
    )
    keys = ["1-5-9", "OTHER_KEY"]
    parts, err, try_llm = segmentation_service.segment_transcript_to_keys(t, keys)
    assert err is None
    assert try_llm is False
    assert "Корпоративная библиотека" in parts["1-5-9"]
    assert parts.get("OTHER_KEY", "") == ""


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
