"""Тесты сегментации транскрипта по ключам."""

import pytest

from app.services import segmentation_service


def test_one_key_returns_whole_transcript():
    t = "Полный ответ студента."
    parts, warn = segmentation_service.segment_transcript_to_keys(t, ["Q1"])
    assert warn is None
    assert parts == {"Q1": t}


def test_three_paragraphs_three_keys():
    t = "Ответ один.\n\nВторой блок.\n\nТретий блок."
    keys = ["Q1", "Q2", "Q3"]
    parts, warn = segmentation_service.segment_transcript_to_keys(t, keys)
    assert warn is None
    assert parts["Q1"] == "Ответ один."
    assert "Второй" in parts["Q2"]


def test_separator_triple_dash():
    t = "A\n---\nB\n---\nC"
    keys = ["Q1", "Q2", "Q3"]
    parts, warn = segmentation_service.segment_transcript_to_keys(t, keys)
    assert warn is None
    assert parts["Q1"].strip() == "A"
    assert parts["Q3"].strip() == "C"


def test_fallback_fills_warning():
    t = "Один сплошной текст без разбиения на три части."
    keys = ["Q1", "Q2", "Q3"]
    parts, warn = segmentation_service.segment_transcript_to_keys(t, keys)
    assert warn is not None
    assert parts["Q1"] == t
    assert parts["Q2"] == ""


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
