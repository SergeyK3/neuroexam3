"""Точечные тесты форматирования отчета в Telegram."""

from app.models.question_bank import QuestionRecord
from app.services import bot_update_handler


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
