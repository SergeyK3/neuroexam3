"""Доменная модель сессии экзамена (MVP: память процесса; ~25–30 пользователей — по user_id)."""

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class ExamState(str, Enum):
    """Сценарий: язык → дисциплина (если в конфиге несколько) → регистрация → ответы."""

    START = "START"
    LANGUAGE = "LANGUAGE"
    DISCIPLINE = "DISCIPLINE"
    REGISTRATION = "REGISTRATION"
    ANSWERING = "ANSWERING"
    FINISH = "FINISH"


@dataclass
class ExamSession:
    """Сессия одного пользователя Telegram."""

    user_id: int
    session_id: str = field(default_factory=lambda: str(uuid4()))
    discipline_id: str | None = None  # slug дисциплины для выбора Google Sheet (карта в .env)
    state: ExamState = ExamState.START
    start_time: float = 0.0
    language: str | None = None  # ru | kk | en
    # По порядку: дисциплина → вид контроля → ФИО (накапливается из одного или нескольких сообщений)
    registration_parts: list[str] = field(default_factory=list)
    registration_raw: str | None = None
    last_transcript: str | None = None
