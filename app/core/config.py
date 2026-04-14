"""Application configuration loaded from environment variables / .env file."""

import difflib
import json
import logging
import os
import unicodedata

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
    # Оценка: coverage (покрытие смысловых элементов, чат LLM) | similarity (семантика по эмбеддингам 0–1)
    mvp_evaluation_mode: str = "coverage"
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
    # Имя вкладки с эталонами (как в UI таблицы) — по умолчанию для всех дисциплин
    google_sheet_ideal_tab: str = "ideal_answers"
    # Лист для append результатов (без эталонов) — по умолчанию для всех дисциплин
    google_sheet_results_tab: str = "students_answers"
    # Если в разных книгах вкладки названы иначе: JSON slug → имя листа (только отличия от строк выше).
    discipline_ideal_tabs_json: str = ""
    discipline_results_tabs_json: str = ""
    # Полное название дисциплины (как в 1-й строке регистрации) → id таблицы. Имеет приоритет над slug-картой.
    discipline_course_name_sheet_ids_json: str = ""
    # Порог нечёткого совпадения (0…1): ниже — больше опечаток/сокращений допускается, выше — строже.
    discipline_course_name_match_threshold: float = 0.52

    # Очередь: при непустом REDIS_URL вебхук Telegram ставит задачу в Redis (нужен процесс arq)
    redis_url: str = ""

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator(
        "mvp_references_json",
        "discipline_google_sheet_ids_json",
        "discipline_ideal_tabs_json",
        "discipline_results_tabs_json",
        "discipline_course_name_sheet_ids_json",
        mode="before",
    )
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

    def _slug_to_tab_overrides(self, raw: str) -> dict[str, str]:
        raw = (raw or "").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("JSON вкладок по дисциплинам не разобран: %s", e)
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                ks, vs = k.strip(), v.strip()
                if ks and vs:
                    out[ks] = vs
        return out

    def ideal_worksheet_for_discipline(self, discipline_id: str | None) -> str:
        """Имя листа эталонов: переопределение из DISCIPLINE_IDEAL_TABS_JSON или GOOGLE_SHEET_IDEAL_TAB."""
        default = (self.google_sheet_ideal_tab or "ideal_answers").strip() or "ideal_answers"
        key = (discipline_id or self.default_discipline or "").strip()
        m = self._slug_to_tab_overrides(self.discipline_ideal_tabs_json)
        if key and key in m:
            return m[key]
        return default

    def results_worksheet_for_discipline(self, discipline_id: str | None) -> str:
        """Имя листа результатов: переопределение из DISCIPLINE_RESULTS_TABS_JSON или GOOGLE_SHEET_RESULTS_TAB."""
        default = (self.google_sheet_results_tab or "students_answers").strip() or "students_answers"
        key = (discipline_id or self.default_discipline or "").strip()
        m = self._slug_to_tab_overrides(self.discipline_results_tabs_json)
        if key and key in m:
            return m[key]
        return default

    @staticmethod
    def registration_course_first_line(raw: str | None) -> str:
        """Первая непустая строка регистрации — обычно название дисциплины/курса."""
        if not raw or not str(raw).strip():
            return ""
        for ln in str(raw).splitlines():
            s = ln.strip()
            if s:
                return s
        return ""

    @staticmethod
    def _normalize_course_label(s: str) -> str:
        t = unicodedata.normalize("NFC", (s or "").strip().lower())
        t = " ".join(t.split())
        # Частое сокращение в регистрационных данных: «ИИ» вместо «искусственный интеллект».
        t = t.replace("ии в здравоохранении", "искусственный интеллект в здравоохранении")
        t = t.replace("ии в медицине", "искусственный интеллект в медицине")
        return t

    def spreadsheet_id_for_registration_course(self, registration_raw: str | None) -> str | None:
        """
        Id таблицы по DISCIPLINE_COURSE_NAME_SHEET_IDS_JSON и первой строке регистрации.
        Порядок: точное совпадение (нормализация пробелов/регистра) → подстрока (самый длинный ключ) →
        нечёткое сравнение (difflib: опечатки, перестановка слов, сокращённые формулировки «по смыслу» в разумных пределах).
        Порог: DISCIPLINE_COURSE_NAME_MATCH_THRESHOLD (по умолчанию 0.52).
        """
        raw_j = (self.discipline_course_name_sheet_ids_json or "").strip()
        if not raw_j:
            return None
        course = self.registration_course_first_line(registration_raw)
        if not course:
            return None
        try:
            data = json.loads(raw_j)
        except json.JSONDecodeError as e:
            logger.error("DISCIPLINE_COURSE_NAME_SHEET_IDS_JSON: %s", e)
            return None
        if not isinstance(data, dict):
            return None
        norm_map: dict[str, str] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                nk = self._normalize_course_label(k)
                vs = v.strip()
                if nk and vs:
                    norm_map[nk] = vs
        cn = self._normalize_course_label(course)
        if cn in norm_map:
            return norm_map[cn]
        best_sid: str | None = None
        best_klen = 0
        for nk, sid in norm_map.items():
            if not nk:
                continue
            if nk in cn or cn in nk:
                kl = len(nk)
                if kl > best_klen:
                    best_klen = kl
                    best_sid = sid
        if best_sid is not None:
            return best_sid

        thr = float(self.discipline_course_name_match_threshold)
        if not (0.0 < thr <= 1.0):
            thr = 0.52
        cn_sorted_words = " ".join(sorted(cn.split()))
        best_ratio = 0.0
        fuzzy_sid: str | None = None
        fuzzy_klen = 0
        for nk, sid in norm_map.items():
            if not nk:
                continue
            nk_sorted_words = " ".join(sorted(nk.split()))
            r = max(
                difflib.SequenceMatcher(None, cn, nk).ratio(),
                difflib.SequenceMatcher(None, cn_sorted_words, nk_sorted_words).ratio(),
            )
            if r > best_ratio or (abs(r - best_ratio) < 1e-6 and len(nk) > fuzzy_klen):
                best_ratio = r
                fuzzy_sid = sid
                fuzzy_klen = len(nk)
        if fuzzy_sid is not None and best_ratio >= thr:
            return fuzzy_sid
        return None


settings = Settings()
