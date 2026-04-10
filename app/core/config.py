"""Application configuration loaded from environment variables / .env file."""

import json
import logging
import os

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    speech_model: str = "whisper-1"
    openai_api_key: str = ""

    # Эталоны из .env (если Google Sheets не заданы или пустой ответ)
    mvp_question_key: str = "Q1"
    mvp_reference_answer: str = "Укажите эталонный ответ для проверки в .env (MVP_REFERENCE_ANSWER)."
    mvp_references_json: str = ""
    mvp_segmentation_use_llm: bool = True
    # Оценка: rubric (по полям, чат LLM) | similarity (семантика по эмбеддингам 0–1); нужен OPENAI_API_KEY
    mvp_evaluation_mode: str = "rubric"
    mvp_evaluation_model: str = "gpt-4o-mini"
    mvp_embedding_model: str = "text-embedding-3-small"

    # Google Sheets: путь к JSON сервисного аккаунта (или переменная окружения GOOGLE_APPLICATION_CREDENTIALS)
    google_sheets_credentials: str = ""
    # Одна таблица на всё приложение (если не используете карту дисциплин)
    google_sheet_id: str = ""
    # Карта slug дисциплины → id таблицы: {"it_med":"1abc...","math":"2def..."}
    discipline_google_sheet_ids_json: str = ""
    # Какой slug использовать, пока в боте нет выбора дисциплины
    default_discipline: str = "default"
    # Имя вкладки с эталонами (как в UI таблицы)
    google_sheet_ideal_tab: str = "ideal_answers"
    # Лист для append результатов (без эталонов)
    google_sheet_results_tab: str = "students_answers"

    # Очередь: при непустом REDIS_URL вебхук Telegram ставит задачу в Redis (нужен процесс arq)
    redis_url: str = ""

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("mvp_references_json", "discipline_google_sheet_ids_json", mode="before")
    @classmethod
    def _strip_json(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    def google_creds_path(self) -> str:
        if self.google_sheets_credentials.strip():
            return self.google_sheets_credentials.strip()
        return os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

    def mvp_reference_map(self) -> dict[str, str]:
        """Только эталоны из .env (fallback)."""
        raw = self.mvp_references_json
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.error("MVP_REFERENCES_JSON не JSON: %s", e)
                raise ValueError("MVP_REFERENCES_JSON: неверный JSON") from e
            if not isinstance(data, dict):
                raise ValueError("MVP_REFERENCES_JSON должен быть JSON-объектом")
            out: dict[str, str] = {}
            for k, v in data.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                ks, vs = k.strip(), v.strip()
                if ks and vs:
                    out[ks] = vs
            if not out:
                raise ValueError("MVP_REFERENCES_JSON: нет ни одной пары ключ–эталон")
            return out

        k = (self.mvp_question_key or "Q1").strip()
        v = (self.mvp_reference_answer or "").strip()
        if not v:
            return {}
        return {k: v}

    def ordered_discipline_slugs(self) -> list[str]:
        """Стабильный порядок slug из DISCIPLINE_GOOGLE_SHEET_IDS_JSON (для шага выбора в боте)."""
        raw = (self.discipline_google_sheet_ids_json or "").strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, dict):
            return []
        return sorted(data.keys())


settings = Settings()
