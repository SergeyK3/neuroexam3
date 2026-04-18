"""Точечные тесты форматирования отчета в Telegram."""

import pytest

from app.models.session import ExamSession
from app.models.question_bank import QuestionRecord
from app.services import bot_update_handler
from app.services.evaluation_service import CoverageScores


def test_telegram_answer_chrono_block_does_not_invent_key_title():
    question = QuestionRecord(question_key="Q3", question_text="", reference_answer="Эталон")

    text = bot_update_handler._telegram_answer_chrono_block(
        question,
        "Билет №3. Первый вопрос. Ответ. Основной текст ответа.",
    )

    assert "Ключ вопроса: Q3" not in text
    assert "Основной текст ответа." in text


def test_telegram_answer_chrono_block_shows_real_key():
    question = QuestionRecord(question_key="1.1.5", question_text="", reference_answer="Эталон")

    text = bot_update_handler._telegram_answer_chrono_block(
        question,
        "Билет №5. Ответ. Основной текст ответа.",
    )

    assert "Ключ вопроса: 1.1.5" in text


def test_telegram_answer_chrono_block_keeps_plain_segment_without_question_text():
    question = QuestionRecord(question_key="Q3", question_text="", reference_answer="Эталон")

    text = bot_update_handler._telegram_answer_chrono_block(
        question,
        "Просто сегмент ответа без маркера.",
    )

    assert text == "Просто сегмент ответа без маркера."


def test_expected_question_count_treats_current_control_as_rubezh():
    count = bot_update_handler._expected_question_count_from_registration(
        "Дисциплина\nТекущий контроль\n101\nИванов Иван",
        "Краткий транскрипт",
    )
    assert count == 2


@pytest.mark.parametrize(
    ("control_type", "expected"),
    [
        ("Текуший контроль", 2),
        ("тек. контроль", 2),
        ("ТК", 2),
    ],
)
def test_expected_question_count_accepts_current_control_variants(control_type, expected):
    count = bot_update_handler._expected_question_count_from_registration(
        f"Дисциплина\n{control_type}\n101\nИванов Иван",
        "Краткий транскрипт",
    )
    assert count == expected


def test_repair_segments_keeps_second_explicit_question_segment():
    questions = [
        QuestionRecord(question_key="2-9-2", question_text="Первый", reference_answer="Эталон 1"),
        QuestionRecord(question_key="2-10-2", question_text="Второй", reference_answer="Эталон 2"),
    ]
    transcript = (
        "Билет номер 10. Вопрос 1. Перечислите основные методы обезличивания данных. "
        "Ответ. Длинный ответ про обезличивание данных. "
        "Вопрос номер 2. Ключ 2.10.2. Перечислить основные принципы ответственного использования данных. "
        "Ответ. Достижение ответственного использования данных является одной из главных задач. "
        "Второе. Конфиденциальность. Пятый. Принцип информированного согласия."
    )
    parts = {
        "2-9-2": "Билет номер 10. Вопрос 1. Ответ. Длинный ответ про обезличивание данных.",
        "2-10-2": (
            "Вопрос номер 2. Ключ 2.10.2. Перечислить основные принципы ответственного использования данных. "
            "Ответ. Достижение ответственного использования данных является одной из главных задач. "
            "Второе. Конфиденциальность. Пятый. Принцип информированного согласия."
        ),
    }

    fixed = bot_update_handler._repair_segments(transcript, questions, parts)

    assert "Конфиденциальность" in fixed["2-10-2"]
    assert "информированного согласия" in fixed["2-10-2"]


def test_repair_segments_keeps_multiple_substantial_segments():
    questions = [
        QuestionRecord(question_key="Q1", question_text="Первый", reference_answer="Эталон 1"),
        QuestionRecord(question_key="Q2", question_text="Второй", reference_answer="Эталон 2"),
    ]
    transcript = "Первый длинный сегмент. " * 30 + "\n\n" + "Второй длинный сегмент. " * 20
    parts = {
        "Q1": "Первый длинный сегмент. " * 30,
        "Q2": "Второй длинный сегмент. " * 20,
    }

    fixed = bot_update_handler._repair_segments(transcript, questions, parts)

    assert fixed["Q1"] == parts["Q1"].strip()
    assert fixed["Q2"] == parts["Q2"].strip()


@pytest.mark.asyncio
async def test_handle_answer_payload_waits_for_second_answer(monkeypatch):
    sent: list[str] = []

    async def fake_send(_chat_id: int, text: str) -> None:
        sent.append(text)

    async def fake_bank(_discipline_id, registration_raw=None):
        return [
            QuestionRecord(question_key="Q1", question_text="Первый", reference_answer="Эталон 1"),
            QuestionRecord(question_key="Q2", question_text="Второй", reference_answer="Эталон 2"),
        ]

    async def fake_segment(_transcript: str, questions: list[QuestionRecord], *, use_llm: bool):
        return ({questions[0].question_key: "Развернутый ответ по первому вопросу.", questions[1].question_key: ""}, [])

    monkeypatch.setattr("app.integrations.telegram_client.send_message", fake_send)
    monkeypatch.setattr("app.services.reference_map_service.get_question_bank", fake_bank)
    monkeypatch.setattr("app.services.segmentation_service.segment_with_fallback", fake_segment)

    sess = ExamSession(
        user_id=1,
        registration_raw="Дисциплина\nРубежный контроль\n101\nИванов Иван",
    )

    await bot_update_handler._handle_answer_payload(
        sess,
        chat_id=1,
        user_id=1,
        raw_text="Развернутый ответ по первому вопросу. Ответ закончен.",
        telegram_message_id=11,
    )

    assert sess.pending_transcript
    assert "1 из 2" in sent[-1]
    assert "Ответ закончен" in sent[-1]


@pytest.mark.asyncio
async def test_handle_answer_payload_reports_too_short_transcription(monkeypatch):
    sent: list[str] = []

    async def fake_send(_chat_id: int, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("app.integrations.telegram_client.send_message", fake_send)

    sess = ExamSession(
        user_id=1,
        registration_raw="Дисциплина\nТекущий контроль\n101\nИванов Иван",
    )

    await bot_update_handler._handle_answer_payload(
        sess,
        chat_id=1,
        user_id=1,
        raw_text="Короткий фрагм",
        telegram_message_id=11,
    )

    assert sent
    assert "слишком мало текста" in sent[-1]
    assert sess.pending_transcript is None


@pytest.mark.asyncio
async def test_handle_answer_payload_evaluates_after_enough_parts(monkeypatch):
    sent: list[str] = []
    evaluated: list[tuple[str, int | None]] = []

    async def fake_send(_chat_id: int, text: str) -> None:
        sent.append(text)

    async def fake_bank(_discipline_id, registration_raw=None):
        return [
            QuestionRecord(question_key="Q1", question_text="Первый", reference_answer="Эталон 1"),
            QuestionRecord(question_key="Q2", question_text="Второй", reference_answer="Эталон 2"),
        ]

    async def fake_segment(transcript: str, questions: list[QuestionRecord], *, use_llm: bool):
        parts = {
            questions[0].question_key: "Развернутый ответ по первому вопросу.",
            questions[1].question_key: "",
        }
        if "второму" in transcript:
            parts[questions[1].question_key] = "Развернутый ответ по второму вопросу."
        return (parts, [])

    async def fake_evaluate_and_reply(chat_id: int, transcript: str, **kwargs) -> None:
        evaluated.append((transcript, kwargs.get("expected_question_count")))

    monkeypatch.setattr("app.integrations.telegram_client.send_message", fake_send)
    monkeypatch.setattr("app.services.reference_map_service.get_question_bank", fake_bank)
    monkeypatch.setattr("app.services.segmentation_service.segment_with_fallback", fake_segment)
    monkeypatch.setattr("app.services.bot_update_handler._evaluate_and_reply", fake_evaluate_and_reply)

    sess = ExamSession(
        user_id=1,
        registration_raw="Дисциплина\nРубежный контроль\n101\nИванов Иван",
    )

    await bot_update_handler._handle_answer_payload(
        sess,
        chat_id=1,
        user_id=1,
        raw_text="Развернутый ответ по первому вопросу.",
        telegram_message_id=11,
    )
    await bot_update_handler._handle_answer_payload(
        sess,
        chat_id=1,
        user_id=1,
        raw_text="Развернутый ответ по второму вопросу.",
        telegram_message_id=12,
    )

    assert evaluated
    assert "первому" in evaluated[0][0]
    assert "второму" in evaluated[0][0]
    assert evaluated[0][1] == 2
    assert sess.pending_transcript is None


@pytest.mark.asyncio
async def test_evaluate_and_reply_shows_full_transcript_without_key_lines(monkeypatch):
    sent: list[str] = []
    exported: list[dict] = []

    async def fake_send(_chat_id: int, text: str) -> None:
        sent.append(text)

    async def fake_bank(_discipline_id, registration_raw=None):
        return [
            QuestionRecord(question_key="1.1.1", question_text="Первый", reference_answer="Эталон 1"),
            QuestionRecord(question_key="1.1.2", question_text="Второй", reference_answer="Эталон 2"),
        ]

    async def fake_segment(_transcript: str, questions: list[QuestionRecord], *, use_llm: bool):
        return (
            {
                questions[0].question_key: "Ответ. Полный развернутый ответ по первому вопросу.",
                questions[1].question_key: "Ответ. Полный развернутый ответ по второму вопросу.",
            },
            [],
        )

    async def fake_coverage(_student_answer: str, _reference: str) -> CoverageScores:
        return CoverageScores(
            score=80,
            total_elements=2,
            covered_elements=["элемент 1"],
            partial_elements=["элемент 2"],
            missing_elements=[],
            elements=[],
            general_comment="Нормальный ответ",
        )

    async def fake_export(**kwargs) -> None:
        exported.append(kwargs)

    monkeypatch.setattr("app.integrations.telegram_client.send_message", fake_send)
    monkeypatch.setattr("app.services.reference_map_service.get_question_bank", fake_bank)
    monkeypatch.setattr("app.services.segmentation_service.segment_with_fallback", fake_segment)
    monkeypatch.setattr("app.services.evaluation_service.use_coverage_scoring", lambda: True)
    monkeypatch.setattr("app.services.evaluation_service.evaluate_coverage", fake_coverage)
    monkeypatch.setattr("app.services.results_export_service.export_question_scores", fake_export)
    # Без OPENAI_API_KEY хендлер уходит в ветку «Оценка недоступна».
    # Сам ключ не используется (evaluate_coverage уже замокан), нужен только непустой флаг.
    monkeypatch.setattr(bot_update_handler.settings, "openai_api_key", "test-key")

    await bot_update_handler._evaluate_and_reply(
        1,
        "Полный транскрибированный ответ студента.",
        telegram_user_id=1,
        session_id="sess-1",
        registration_raw="Дисциплина\nЭкзамен\n101\nИванов Иван",
        expected_question_count=2,
    )

    assert sent
    assert "Полный транскрибированный ответ:" in sent[0]
    assert "Ключ вопроса:" not in sent[0]
    assert "Средняя оценка по вопросам:" in sent[0]
    assert "Это предварительная оценка." in sent[0]
    assert "Окончательную оценку выставляет преподаватель." in sent[0]
    assert exported
