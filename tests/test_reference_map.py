"""Тесты загрузки эталонов (mock Google)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import config as cfg
from app.integrations.sheets_client import _parse_question_bank, _parse_table
from app.models.question_bank import QuestionRecord
from app.services import reference_map_service


def test_parse_ideal_table_russian_headers_skips_header_row():
    """Шапка «Ключ» + «Идеальный ответ» должна не попадать в словарь как ключ «Ключ»."""
    rows = [
        ["Ключ", "Идеальный ответ"],
        ["1-2-3", "Эталонный текст про ЭМК"],
    ]
    m = _parse_table(rows)
    assert m == {"1-2-3": "Эталонный текст про ЭМК"}
    assert "Ключ" not in m


def test_parse_ideal_table_infers_ref_col_when_only_key_header_matches():
    rows = [
        ["Ключ вопроса", "Произвольная подпись без слова эталон"],
        ["10-20-30", "Длинный эталон"],
    ]
    m = _parse_table(rows)
    assert m == {"10-20-30": "Длинный эталон"}


def test_parse_question_bank_reads_question_text():
    rows = [
        ["Ключ", "Вопрос", "Идеальный ответ"],
        ["2-7-4", "Объясните применение ИИ в роботизированной хирургии.", "ИИ повышает точность движений."],
    ]
    bank = _parse_question_bank(rows)
    assert bank == [
        QuestionRecord(
            question_key="2-7-4",
            question_text="Объясните применение ИИ в роботизированной хирургии.",
            reference_answer="ИИ повышает точность движений.",
        ),
    ]


def test_parse_ideal_table_placeholder_row_skipped_in_fallback_mode():
    """Если шапка не распознана, строка с ключом «Ключ» не должна давать запись в словаре."""
    rows = [
        ["Ключ", "Колонка2"],
        ["5-5-5", "Нормальный эталон"],
    ]
    m = _parse_table(rows)
    assert "Ключ" not in m
    assert m.get("5-5-5") == "Нормальный эталон"


def test_select_relevant_questions_matches_concat_digit_key():
    """STT пишет «ключ 114», а банк содержит ключ «1-1-4» — должен найти через digits-only."""
    bank = [
        QuestionRecord(question_key="1-1-4", question_text="Передача сигнала", reference_answer="Нейрон"),
        QuestionRecord(question_key="2-1-4", question_text="Модели обучения", reference_answer="Перцептрон"),
    ]

    selected = reference_map_service.select_relevant_questions(
        "Ключ 114. Ответ про нейроны. Ключ 214. Ответ про модели.",
        bank,
        limit=2,
    )

    keys = {q.question_key for q in selected}
    assert "1-1-4" in keys
    assert "2-1-4" in keys


def test_select_relevant_questions_matches_spoken_digit_key():
    bank = [
        QuestionRecord(question_key="1-4-2", question_text="LLM в здравоохранении", reference_answer="Ответ 1"),
        QuestionRecord(question_key="2-10-6", question_text="Защита данных", reference_answer="Ответ 2"),
    ]

    selected = reference_map_service.select_relevant_questions(
        "Второй вопрос, ключ один четыре два, какие основные задачи решает ЛЛМ здравоохранения?",
        bank,
        limit=1,
    )

    assert [q.question_key for q in selected] == ["1-4-2"]


def test_select_relevant_questions_matches_spoken_mixed_key_with_ten():
    bank = [
        QuestionRecord(question_key="1-4-2", question_text="LLM в здравоохранении", reference_answer="Ответ 1"),
        QuestionRecord(question_key="2-10-6", question_text="Защита данных", reference_answer="Ответ 2"),
    ]

    selected = reference_map_service.select_relevant_questions(
        "Второй вопрос, ключ два десять шесть, какие меры принимаются для защиты данных?",
        bank,
        limit=1,
    )

    assert [q.question_key for q in selected] == ["2-10-6"]


def test_select_relevant_questions_falls_back_to_top_ranked():
    bank = [
        QuestionRecord(question_key="1-1-1", question_text="Безопасность данных пациентов", reference_answer="Шифрование и аудит"),
        QuestionRecord(question_key="2-2-2", question_text="Электронные медицинские карты", reference_answer="МИС и ЭМК"),
    ]

    selected = reference_map_service.select_relevant_questions(
        "Совершенно другой текст без совпадающих терминов.",
        bank,
        limit=1,
    )

    assert len(selected) == 1


def test_select_relevant_questions_prefers_explicit_key_over_semantic_ranking():
    bank = [
        QuestionRecord(question_key="292", question_text="Методы обезличивания данных", reference_answer="Удаление идентификаторов"),
        QuestionRecord(question_key="2-10-2", question_text="Принципы ответственного использования данных", reference_answer="Конфиденциальность"),
        QuestionRecord(question_key="2-9-2", question_text="Безопасность хранения", reference_answer="Шифрование"),
    ]

    selected = reference_map_service.select_relevant_questions(
        "Билет номер 10. Вопрос 1. Ключ 292. Ответ про обезличивание данных.",
        bank,
        limit=1,
    )

    assert [q.question_key for q in selected] == ["292"]


def test_select_relevant_questions_prefers_spoken_question_text_over_wrong_key():
    bank = [
        QuestionRecord(
            question_key="292",
            question_text="Перечислите основные методы обезличивания данных",
            reference_answer="Удаление идентификаторов",
        ),
        QuestionRecord(
            question_key="2-10-2",
            question_text="Перечислите основные принципы ответственного использования данных",
            reference_answer="Конфиденциальность",
        ),
    ]

    selected = reference_map_service.select_relevant_questions(
        "Билет номер 10. Вопрос 1. Перечислите основные методы обезличивания данных. Ключ 2.10.2. Ответ про обезличивание.",
        bank,
        limit=1,
    )

    assert [q.question_key for q in selected] == ["292"]


def test_select_relevant_questions_reads_question_text_after_key_phrase():
    bank = [
        QuestionRecord(
            question_key="1-1-2",
            question_text="Какое строение имеет биологический нейрон",
            reference_answer="Тело, дендриты, аксон",
        ),
        QuestionRecord(
            question_key="1-5-7",
            question_text="Как технология доверенного ИИ снижает риски",
            reference_answer="Контроль, прозрачность, аудит",
        ),
    ]

    selected = reference_map_service.select_relevant_questions(
        "Ключ первого вопроса 1.1.2. Какое строение имеет биологический нейрон. "
        "Ключ второго вопроса 1.5.7. Как технология доверенного ИИ снижает риски.",
        bank,
        limit=2,
    )

    assert [q.question_key for q in selected] == ["1-1-2", "1-5-7"]

@pytest.mark.asyncio
async def test_get_reference_map_uses_env_when_no_sheets(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheets_credentials", "", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_id", "", raising=False)
    monkeypatch.setattr(cfg.settings, "discipline_google_sheet_ids_json", "", raising=False)
    monkeypatch.setattr(cfg.settings, "mvp_references_json", '{"X":"refx"}', raising=False)

    m = await reference_map_service.get_reference_map(None)
    assert m == {"X": "refx"}


@pytest.mark.asyncio
async def test_get_question_bank_uses_env_when_no_sheets(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheets_credentials", "", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_id", "", raising=False)
    monkeypatch.setattr(cfg.settings, "discipline_google_sheet_ids_json", "", raising=False)
    monkeypatch.setattr(cfg.settings, "mvp_references_json", '{"X":"refx"}', raising=False)

    bank = await reference_map_service.get_question_bank(None)
    assert len(bank) == 1
    assert bank[0].question_key == "X"
    assert bank[0].reference_answer == "refx"


@pytest.mark.asyncio
async def test_get_reference_map_calls_sheet_when_configured(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheets_credentials", "/fake/path.json", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_id", "abc123", raising=False)
    monkeypatch.setattr(cfg.settings, "discipline_google_sheet_ids_json", "", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_ideal_tab", "ideal_answers", raising=False)

    async def fake_fetch(sheet_id: str, tab: str, *, credentials_path: str):
        assert sheet_id == "abc123"
        return {"Q1": "from_sheet"}

    monkeypatch.setattr(
        "app.services.reference_map_service.fetch_ideal_references",
        fake_fetch,
    )

    m = await reference_map_service.get_reference_map(None, registration_raw=None)
    assert m == {"Q1": "from_sheet"}


@pytest.mark.asyncio
async def test_get_reference_map_prefers_course_name_map(monkeypatch):
    monkeypatch.setattr(cfg.settings, "google_sheets_credentials", "/fake/path.json", raising=False)
    monkeypatch.setattr(cfg.settings, "google_sheet_id", "", raising=False)
    monkeypatch.setattr(cfg.settings, "discipline_google_sheet_ids_json", '{"x":"wrongid"}', raising=False)
    monkeypatch.setattr(
        cfg.settings,
        "discipline_course_name_sheet_ids_json",
        '{"Экономика и маркетинг в сестринском деле":"sheet-from-name"}',
        raising=False,
    )
    monkeypatch.setattr(cfg.settings, "google_sheet_ideal_tab", "ideal_answers", raising=False)

    seen: list[tuple[str, str]] = []

    async def fake_fetch(sheet_id: str, tab: str, *, credentials_path: str):
        seen.append((sheet_id, tab))
        return {"Q1": "from_named_sheet"}

    monkeypatch.setattr(
        "app.services.reference_map_service.fetch_ideal_references",
        fake_fetch,
    )

    m = await reference_map_service.get_reference_map(
        "x",
        registration_raw="Экономика и маркетинг в сестринском деле\nЭкзамен\n101\nИванов",
    )
    assert m == {"Q1": "from_named_sheet"}
    assert seen == [("sheet-from-name", "ideal_answers")]


@pytest.mark.asyncio
async def test_select_relevant_questions_async_trusts_explicit_key(monkeypatch):
    """Если студент явно назвал ключ, он должен быть включён даже при слабой семантике."""
    monkeypatch.setattr(cfg.settings, "openai_api_key", "sk-test", raising=False)
    bank = [
        QuestionRecord(question_key="1-1-1", question_text="Тема А", reference_answer="A"),
        QuestionRecord(question_key="2-2-2", question_text="Тема Б", reference_answer="B"),
    ]

    def emb(vec: list[float]):
        item = MagicMock()
        item.embedding = vec
        return item

    resp = MagicMock()
    resp.data = [emb([1.0, 0.0]), emb([0.0, 1.0]), emb([1.0, 0.0])]
    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=resp)
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: mock_client)

    selected = await reference_map_service.select_relevant_questions_async(
        "Ключ вопроса 2-2-2. Краткий ответ.",
        bank,
        limit=1,
    )

    assert [q.question_key for q in selected] == ["2-2-2"]


@pytest.mark.asyncio
async def test_select_relevant_questions_async_both_explicit_keys_selected(monkeypatch):
    """Два явных ключа из транскрипта попадают в результат, даже если
    один из них семантически далёк от общего эмбеддинга."""
    monkeypatch.setattr(cfg.settings, "openai_api_key", "sk-test", raising=False)
    bank = [
        QuestionRecord(question_key="1-1-4", question_text="Передача сигнала", reference_answer="Нейроны"),
        QuestionRecord(question_key="1-2-4", question_text="Подходы к ИИ", reference_answer="Машинное обучение"),
        QuestionRecord(question_key="9-9-9", question_text="Не тот", reference_answer="Другой"),
    ]

    def emb(vec: list[float]):
        item = MagicMock()
        item.embedding = vec
        return item

    resp = MagicMock()
    resp.data = [
        emb([0.9, 0.1, 0.0]),   # transcript — ближе к 1-1-4
        emb([1.0, 0.0, 0.0]),   # 1-1-4
        emb([0.0, 1.0, 0.0]),   # 1-2-4 — далеко от транскрипта
        emb([0.0, 0.0, 1.0]),   # 9-9-9
    ]
    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=resp)
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: mock_client)

    selected = await reference_map_service.select_relevant_questions_async(
        "Ключ 114. Ответ про нейроны. Ключ номер 1, 2, 4. Ответ про ИИ.",
        bank,
        limit=2,
    )

    keys = {q.question_key for q in selected}
    assert keys == {"1-1-4", "1-2-4"}


@pytest.mark.asyncio
async def test_select_relevant_questions_async_explicit_key_can_bypass_shortlist(monkeypatch):
    """Явный ключ должен выбираться по всему банку, даже если семантически не попал бы в shortlist."""
    monkeypatch.setattr(cfg.settings, "openai_api_key", "", raising=False)
    bank = [
        QuestionRecord(question_key="292", question_text="Методы обезличивания данных", reference_answer="Удаление идентификаторов"),
        QuestionRecord(question_key="2-10-2", question_text="Принципы ответственного использования данных", reference_answer="Конфиденциальность"),
        QuestionRecord(question_key="2-9-2", question_text="Безопасность хранения", reference_answer="Шифрование"),
        QuestionRecord(question_key="8-8-8", question_text="Совсем другой вопрос", reference_answer="Другое"),
    ]

    selected = await reference_map_service.select_relevant_questions_async(
        "Билет номер 10. Вопрос 1. Ключ 292. Ответ про обезличивание данных.",
        bank,
        limit=1,
    )

    assert [q.question_key for q in selected] == ["292"]


@pytest.mark.asyncio
async def test_select_relevant_questions_async_prefers_spoken_question_text_over_wrong_key(monkeypatch):
    monkeypatch.setattr(cfg.settings, "openai_api_key", "", raising=False)
    bank = [
        QuestionRecord(
            question_key="292",
            question_text="Перечислите основные методы обезличивания данных",
            reference_answer="Удаление идентификаторов",
        ),
        QuestionRecord(
            question_key="2-10-2",
            question_text="Перечислите основные принципы ответственного использования данных",
            reference_answer="Конфиденциальность",
        ),
        QuestionRecord(
            question_key="8-8-8",
            question_text="Совсем другой вопрос",
            reference_answer="Другое",
        ),
    ]

    selected = await reference_map_service.select_relevant_questions_async(
        "Билет номер 10. Вопрос 1. Перечислите основные методы обезличивания данных. Ключ 2.10.2. Ответ про обезличивание.",
        bank,
        limit=1,
    )

    assert [q.question_key for q in selected] == ["292"]


@pytest.mark.asyncio
async def test_select_relevant_questions_async_reads_question_text_after_key_phrase(monkeypatch):
    monkeypatch.setattr(cfg.settings, "openai_api_key", "", raising=False)
    bank = [
        QuestionRecord(
            question_key="1-1-2",
            question_text="Какое строение имеет биологический нейрон",
            reference_answer="Тело, дендриты, аксон",
        ),
        QuestionRecord(
            question_key="1-5-7",
            question_text="Как технология доверенного ИИ снижает риски",
            reference_answer="Контроль, прозрачность, аудит",
        ),
        QuestionRecord(
            question_key="8-8-8",
            question_text="Совсем другой вопрос",
            reference_answer="Другое",
        ),
    ]

    selected = await reference_map_service.select_relevant_questions_async(
        "Ключ первого вопроса 1.1.2. Какое строение имеет биологический нейрон. "
        "Ключ второго вопроса 1.5.7. Как технология доверенного ИИ снижает риски.",
        bank,
        limit=2,
    )

    assert [q.question_key for q in selected] == ["1-1-2", "1-5-7"]


@pytest.mark.asyncio
async def test_select_relevant_questions_async_falls_back_without_signal(monkeypatch):
    monkeypatch.setattr(cfg.settings, "openai_api_key", "", raising=False)
    bank = [
        QuestionRecord(question_key="1-1-1", question_text="Безопасность данных пациентов", reference_answer="Шифрование и аудит"),
        QuestionRecord(question_key="2-2-2", question_text="Электронные медицинские карты", reference_answer="МИС и ЭМК"),
    ]

    selected = await reference_map_service.select_relevant_questions_async(
        "Совершенно другой текст без совпадающих терминов.",
        bank,
        limit=1,
    )

    assert len(selected) == 1
