"""Банк вопросов и эталонов: Google Sheets (приоритет) или fallback на .env."""

from __future__ import annotations

import json
import logging
import re
import time
from difflib import SequenceMatcher

from app.core.config import settings
from app.integrations.sheets_client import fetch_ideal_references, fetch_question_bank
from app.models.question_bank import QuestionRecord

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, dict[str, str]]] = {}
_bank_cache: dict[str, tuple[float, list[QuestionRecord]]] = {}
_TTL_SEC = 120.0
_STOPWORDS = {
    "и",
    "в",
    "во",
    "на",
    "по",
    "с",
    "со",
    "для",
    "к",
    "ко",
    "это",
    "как",
    "что",
    "его",
    "ее",
    "её",
    "или",
    "а",
    "но",
    "из",
    "под",
    "при",
    "от",
    "до",
    "о",
    "об",
    "про",
    "вопрос",
    "ответ",
    "ключ",
    "вопроса",
    "билет",
    "номер",
}
_RU_SPOKEN_NUMBER_WORDS = {
    "ноль": "0",
    "один": "1",
    "раз": "1",
    "два": "2",
    "три": "3",
    "четыре": "4",
    "пять": "5",
    "шесть": "6",
    "семь": "7",
    "восемь": "8",
    "девять": "9",
    "десять": "10",
}
_SPOKEN_KEY_TOKEN_RE = r"(?:\d+|ноль|один|раз|два|три|четыре|пять|шесть|семь|восемь|девять|десять)"
_ORDINAL_QUESTION_INSERT_RE = (
    r"(?:перв(?:ого|ый)|втор(?:ого|ой)|трет(?:ьего|ий)|"
    r"четв[её]рт(?:ого|ый)|пят(?:ого|ый)|шест(?:ого|ой)|"
    r"седьм(?:ого|ой)|восьм(?:ого|ой)|девят(?:ого|ый)|десят(?:ого|ый))\s+вопроса?"
)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def normalize_question_key(key: str | None) -> str:
    raw = (key or "").strip().lower()
    if not raw:
        return ""
    nums = re.findall(r"\d+", raw)
    if len(nums) >= 2:
        return "-".join(nums)
    raw = re.sub(r"[‐‑–—.,;/\\]+", "-", raw)
    raw = re.sub(r"\s+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    return raw


def _digits_of(key: str) -> str:
    """Только цифры ключа: для сопоставления «114» ↔ «1-1-4» (STT склеивает цифры)."""
    return re.sub(r"\D", "", key)


def parse_spoken_key_fragment(fragment: str | None) -> str:
    """Нормализует цифровой или словесный ключ: «один четыре два» -> «1-4-2»."""
    raw = (fragment or "").strip().lower()
    if not raw:
        return ""

    numeric_groups = re.findall(r"\d+", raw)
    if len(numeric_groups) >= 2:
        return "-".join(numeric_groups)
    if len(numeric_groups) == 1 and re.fullmatch(r"[0-9\s,./-]+", raw):
        return numeric_groups[0]

    tokens = re.findall(r"[a-zа-яё0-9]+", raw)
    out: list[str] = []
    for tok in tokens:
        if tok.isdigit():
            out.append(tok)
            continue
        mapped = _RU_SPOKEN_NUMBER_WORDS.get(tok)
        if mapped is None:
            break
        out.append(mapped)
    if len(out) >= 2:
        return "-".join(out)
    if len(out) == 1:
        return out[0]
    return normalize_question_key(raw)


def _is_explicit_match(normalized_bank_key: str, explicit_keys: set[str]) -> bool:
    """Точное или digits-only совпадение (STT часто склеивает цифры ключа без разделителей)."""
    if normalized_bank_key in explicit_keys:
        return True
    d = _digits_of(normalized_bank_key)
    return bool(d) and len(d) >= 2 and any(_digits_of(ek) == d for ek in explicit_keys)


def _tokenize(text: str | None) -> set[str]:
    return {
        tok
        for tok in re.findall(r"[a-zа-яё0-9]+", (text or "").lower())
        if len(tok) > 2 and tok not in _STOPWORDS
    }


def _question_overlap_score(transcript_tokens: set[str], q: QuestionRecord) -> float:
    q_tokens = _tokenize(q.question_text)
    r_tokens = _tokenize(q.reference_answer)
    if not transcript_tokens or not (q_tokens or r_tokens):
        return 0.0
    return 2.0 * len(transcript_tokens & q_tokens) + 1.0 * len(transcript_tokens & r_tokens)


def _extract_spoken_question_texts(transcript: str | None) -> list[str]:
    """Формулировки вопросов, которые студент/бот проговорил в транскрипте."""
    text = (transcript or "").strip()
    if not text:
        return []
    patterns = [
        re.compile(
            r"(?is)\bвопрос\s*(?:номер\s*|№\s*)?\d+\s*[:.,;]?\s*(.+?)(?=\b(?:ключ(?:\s*вопроса)?|шифр|код(?:\s*вопроса)?|ответ)\b|$)",
        ),
        re.compile(
            r"(?is)\b(?:первый|второй|третий|четвертый|четвёртый|пятый)\s+вопрос\s*[:.,;]?\s*(.+?)(?=\b(?:ключ(?:\s*вопроса)?|шифр|код(?:\s*вопроса)?|ответ)\b|$)",
        ),
        re.compile(
            rf"(?is)\b(?:ключ(?:\s+(?:{_ORDINAL_QUESTION_INSERT_RE}))?(?:\s*вопроса)?(?:\s+номер)?|"
            rf"шифр(?:\s+(?:{_ORDINAL_QUESTION_INSERT_RE}))?(?:\s+номер)?|"
            rf"код(?:\s+(?:{_ORDINAL_QUESTION_INSERT_RE}))?(?:\s*вопроса)?(?:\s+номер)?)\b"
            rf"\s*[:.;,]?\s*{_SPOKEN_KEY_TOKEN_RE}(?:[\s,./-]+{_SPOKEN_KEY_TOKEN_RE}){{0,5}}\s*[:.;,]?\s*"
            r"(.+?)(?=\bответ\b|$)",
        ),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for rx in patterns:
        for m in rx.finditer(text):
            candidate = re.sub(r"\s+", " ", (m.group(1) or "").strip(" \n\t-:.;,?")).strip()
            if len(candidate) < 8:
                continue
            norm = candidate.lower()
            if norm in seen:
                continue
            seen.add(norm)
            out.append(candidate)
    return out


def _question_text_similarity(spoken_text: str, question_text: str) -> float:
    if not spoken_text or not question_text:
        return 0.0
    spoken_norm = " ".join(_tokenize(spoken_text))
    question_norm = " ".join(_tokenize(question_text))
    if not spoken_norm or not question_norm:
        return 0.0
    s_tokens = set(spoken_norm.split())
    q_tokens = set(question_norm.split())
    overlap = len(s_tokens & q_tokens) / max(1, len(q_tokens))
    ratio = SequenceMatcher(a=spoken_norm, b=question_norm).ratio()
    return max(overlap, ratio)


def _select_questions_by_spoken_question_text(
    transcript: str,
    bank: list[QuestionRecord],
    *,
    limit: int,
) -> list[tuple[QuestionRecord, float]]:
    """Приоритетный выбор по названной формулировке вопроса из транскрипта."""
    spoken_questions = _extract_spoken_question_texts(transcript)
    if not spoken_questions:
        return []
    selected: list[tuple[QuestionRecord, float]] = []
    seen_bank_keys: set[str] = set()
    for spoken in spoken_questions:
        best_q: QuestionRecord | None = None
        best_score = 0.0
        for q in bank:
            nk = normalize_question_key(q.question_key)
            if nk in seen_bank_keys:
                continue
            score = _question_text_similarity(spoken, q.question_text)
            if score > best_score:
                best_score = score
                best_q = q
        if best_q is not None and best_score >= 0.55:
            selected.append((best_q, best_score))
            seen_bank_keys.add(normalize_question_key(best_q.question_key))
        if len(selected) >= limit:
            break
    return selected[:limit]


def _rank_questions_by_signal(
    transcript: str,
    bank: list[QuestionRecord],
) -> list[tuple[QuestionRecord, float, bool]]:
    t_tokens = _tokenize(transcript)
    explicit_keys = _extract_explicit_keys(transcript)
    ranked = [
        (
            q,
            _question_overlap_score(t_tokens, q),
            _is_explicit_match(normalize_question_key(q.question_key), explicit_keys),
        )
        for q in bank
    ]
    ranked.sort(
        key=lambda item: (
            item[1] + (6.0 if item[2] else 0.0),
            len(item[0].question_text),
            len(item[0].reference_answer),
        ),
        reverse=True,
    )
    return ranked


def _extract_explicit_keys(transcript: str | None) -> set[str]:
    text = transcript or ""
    hits: set[str] = set()
    for m in re.finditer(
        rf"(?is)\b(?:ключ(?:\s+(?:{_ORDINAL_QUESTION_INSERT_RE}))?(?:\s*вопроса)?(?:\s+номер)?|"
        rf"шифр(?:\s+(?:{_ORDINAL_QUESTION_INSERT_RE}))?(?:\s+номер)?|"
        rf"код(?:\s+(?:{_ORDINAL_QUESTION_INSERT_RE}))?(?:\s*вопроса)?(?:\s+номер)?|"
        rf"по\s+(?:шифру|коду|ключу))\b\s*[:.;,]?\s*({_SPOKEN_KEY_TOKEN_RE}(?:[\s,./-]+{_SPOKEN_KEY_TOKEN_RE}){{0,5}})",
        text,
    ):
        norm = parse_spoken_key_fragment(m.group(1))
        if norm:
            hits.add(norm)
    return hits


def _extract_explicit_keys_in_order(transcript: str | None) -> list[str]:
    """Явно произнесённые ключи в порядке появления, без потери дублей до дедупликации."""
    text = transcript or ""
    ordered: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        rf"(?is)\b(?:ключ(?:\s+(?:{_ORDINAL_QUESTION_INSERT_RE}))?(?:\s*вопроса)?(?:\s+номер)?|"
        rf"шифр(?:\s+(?:{_ORDINAL_QUESTION_INSERT_RE}))?(?:\s+номер)?|"
        rf"код(?:\s+(?:{_ORDINAL_QUESTION_INSERT_RE}))?(?:\s*вопроса)?(?:\s+номер)?|"
        rf"по\s+(?:шифру|коду|ключу))\b\s*[:.;,]?\s*({_SPOKEN_KEY_TOKEN_RE}(?:[\s,./-]+{_SPOKEN_KEY_TOKEN_RE}){{0,5}})",
        text,
    ):
        norm = parse_spoken_key_fragment(m.group(1))
        if norm and norm not in seen:
            ordered.append(norm)
            seen.add(norm)
    return ordered


def _select_questions_by_text_then_key(
    transcript: str,
    bank: list[QuestionRecord],
    *,
    limit: int,
) -> list[QuestionRecord]:
    """Сначала сопоставление по question_text, затем key только валидирует/уточняет."""
    spoken_selected = _select_questions_by_spoken_question_text(transcript, bank, limit=limit)
    explicit_keys = _extract_explicit_keys_in_order(transcript)
    if not spoken_selected and not explicit_keys:
        return []

    selected: list[QuestionRecord] = []
    seen_keys: set[str] = set()

    for idx, (text_q, text_score) in enumerate(spoken_selected):
        chosen = text_q
        explicit = explicit_keys[idx] if idx < len(explicit_keys) else ""
        if explicit and text_score < 0.72:
            for candidate in bank:
                nk = normalize_question_key(candidate.question_key)
                if nk in seen_keys:
                    continue
                if _is_explicit_match(nk, {explicit}):
                    chosen = candidate
                    break
        chosen_key = normalize_question_key(chosen.question_key)
        if chosen_key in seen_keys:
            continue
        selected.append(chosen)
        seen_keys.add(chosen_key)
        if len(selected) >= limit:
            return selected[:limit]

    if len(selected) < limit:
        for q in _select_questions_by_explicit_keys(transcript, bank, limit=limit):
            nk = normalize_question_key(q.question_key)
            if nk in seen_keys:
                continue
            selected.append(q)
            seen_keys.add(nk)
            if len(selected) >= limit:
                return selected[:limit]

    return selected[:limit]


def _select_questions_by_explicit_keys(
    transcript: str,
    bank: list[QuestionRecord],
    *,
    limit: int,
) -> list[QuestionRecord]:
    """Приоритетный выбор по явно произнесённым ключам из всего банка, а не из shortlist."""
    explicit_keys = _extract_explicit_keys_in_order(transcript)
    if not explicit_keys:
        return []
    selected: list[QuestionRecord] = []
    seen_bank_keys: set[str] = set()
    for explicit in explicit_keys:
        for q in bank:
            normalized_bank_key = normalize_question_key(q.question_key)
            if normalized_bank_key in seen_bank_keys:
                continue
            if _is_explicit_match(normalized_bank_key, {explicit}):
                selected.append(q)
                seen_bank_keys.add(normalized_bank_key)
                break
        if len(selected) >= limit:
            break
    return selected[:limit]


def infer_expected_question_count(transcript: str | None) -> int:
    text = (transcript or "").strip()
    if not text:
        return 1
    count = 1
    numeric = [int(n) for n in re.findall(r"(?i)\bвопрос\s*(?:номер\s*|№\s*)?(\d+)\b", text)]
    if numeric:
        count = max(count, max(numeric))
    low = text.lower()
    if "второй вопрос" in low:
        count = max(count, 2)
    if "третий вопрос" in low:
        count = max(count, 3)
    if "четвертый вопрос" in low or "четвёртый вопрос" in low:
        count = max(count, 4)
    key_mentions = len(re.findall(r"(?i)\b(?:ключ(?:\s*вопроса)?|шифр|код(?:\s*вопроса)?)\b", text))
    if key_mentions:
        count = max(count, min(key_mentions, 4))
    return min(max(count, 1), 4)


def spreadsheet_id_for_discipline(
    discipline_id: str | None,
    registration_raw: str | None = None,
) -> str | None:
    """Публичный доступ к id таблицы (эталоны и результаты): см. _sheet_id_for_session."""
    return _sheet_id_for_session(discipline_id, registration_raw)


def _sheet_id_for_session(
    discipline_id: str | None,
    registration_raw: str | None = None,
) -> str | None:
    """Spreadsheet id: приоритет — карта по полному названию из регистрации, иначе slug-карта или GOOGLE_SHEET_ID."""
    sid = settings.spreadsheet_id_for_registration_course(registration_raw)
    if sid:
        logger.info("Таблица выбрана по 1-й строке регистрации (название дисциплины)")
        return sid

    raw = (settings.discipline_google_sheet_ids_json or "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("DISCIPLINE_GOOGLE_SHEET_IDS_JSON: %s", e)
            raise ValueError("DISCIPLINE_GOOGLE_SHEET_IDS_JSON: неверный JSON") from e
        if not isinstance(data, dict):
            raise ValueError("DISCIPLINE_GOOGLE_SHEET_IDS_JSON должен быть объектом")
        key = (discipline_id or settings.default_discipline or "").strip()
        if not key:
            key = next(iter(data.keys()), "")
        sid = data.get(key) if key else None
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
        single = (settings.google_sheet_id or "").strip()
        if single:
            logger.warning(
                "Дисциплина «%s» не найдена в карте таблиц — используется GOOGLE_SHEET_ID",
                key,
            )
            return single
        raise ValueError(
            f"Нет таблицы для дисциплины «{key}»: проверьте DISCIPLINE_GOOGLE_SHEET_IDS_JSON",
        )

    single = (settings.google_sheet_id or "").strip()
    return single or None


def _env_question_bank() -> list[QuestionRecord]:
    return [
        QuestionRecord(
            question_key=key,
            question_text="",
            reference_answer=ref,
        )
        for key, ref in settings.mvp_reference_map().items()
    ]


async def get_reference_map(
    discipline_id: str | None,
    registration_raw: str | None = None,
) -> dict[str, str]:
    """
    Загрузить эталоны. Если заданы credentials и id таблицы — читаем лист эталонов
    (имя задаётся в GOOGLE_SHEET_IDEAL_TAB, по умолчанию ``ideal_answers``). Иначе — MVP_REFERENCES_JSON / пара Q1+REFERENCE.
    """
    creds = settings.google_creds_path()
    sheet_id = _sheet_id_for_session(discipline_id, registration_raw)
    tab = settings.ideal_worksheet_for_discipline(discipline_id)

    if creds and sheet_id:
        cache_key = f"{sheet_id}|{tab}"
        now = time.monotonic()
        ent = _cache.get(cache_key)
        if ent is not None:
            ts, data = ent
            if now - ts < _TTL_SEC and data:
                return dict(data)

        try:
            data = await fetch_ideal_references(sheet_id, tab, credentials_path=creds)
        except Exception:
            logger.exception("Не удалось прочитать Google Sheet %s", sheet_id)
            logger.info("Fallback на эталоны из .env")
            return settings.mvp_reference_map()

        _cache[cache_key] = (now, data)
        if data:
            return dict(data)
        logger.warning("Таблица %s: пусто, fallback на .env", sheet_id)

    return settings.mvp_reference_map()


async def get_question_bank(
    discipline_id: str | None,
    registration_raw: str | None = None,
) -> list[QuestionRecord]:
    creds = settings.google_creds_path()
    sheet_id = _sheet_id_for_session(discipline_id, registration_raw)
    tab = settings.ideal_worksheet_for_discipline(discipline_id)

    if creds and sheet_id:
        cache_key = f"{sheet_id}|{tab}"
        now = time.monotonic()
        ent = _bank_cache.get(cache_key)
        if ent is not None:
            ts, data = ent
            if now - ts < _TTL_SEC and data:
                return list(data)

        try:
            data = await fetch_question_bank(sheet_id, tab, credentials_path=creds)
        except Exception:
            logger.exception("Не удалось прочитать банк вопросов Google Sheet %s", sheet_id)
            logger.info("Fallback на эталоны из .env")
            return _env_question_bank()

        _bank_cache[cache_key] = (now, data)
        if data:
            return list(data)
        logger.warning("Таблица %s: пусто, fallback на .env", sheet_id)

    return _env_question_bank()


def select_relevant_questions(
    transcript: str,
    bank: list[QuestionRecord],
    *,
    limit: int | None = None,
) -> list[QuestionRecord]:
    if not bank:
        return []
    take = limit if limit is not None else infer_expected_question_count(transcript)
    take = min(max(take, 1), len(bank))
    selected = _select_questions_by_text_then_key(transcript, bank, limit=take)
    if len(selected) >= take:
        return selected[:take]
    seen = {normalize_question_key(q.question_key) for q in selected}
    ranked = _rank_questions_by_signal(transcript, bank)
    for q, _score, _is_explicit in ranked:
        nk = normalize_question_key(q.question_key)
        if nk in seen:
            continue
        selected.append(q)
        seen.add(nk)
        if len(selected) >= take:
            break
    return selected[:take]


async def select_relevant_questions_async(
    transcript: str,
    bank: list[QuestionRecord],
    *,
    limit: int | None = None,
) -> list[QuestionRecord]:
    if not bank:
        return []
    take = limit if limit is not None else infer_expected_question_count(transcript)
    take = min(max(take, 1), len(bank))
    selected = _select_questions_by_text_then_key(transcript, bank, limit=take)
    if len(selected) >= take:
        return selected[:take]
    seen: set[str] = {normalize_question_key(q.question_key) for q in selected}
    lexical_ranked = _rank_questions_by_signal(transcript, bank)
    lexical_shortlist = [q for q, _score, _is_explicit in lexical_ranked[: min(max(take * 4, 8), len(bank))]]
    if not (settings.openai_api_key or "").strip() or len(lexical_shortlist) <= take:
        for q in lexical_shortlist:
            nk = normalize_question_key(q.question_key)
            if nk in seen:
                continue
            selected.append(q)
            seen.add(nk)
            if len(selected) >= take:
                break
        return selected[:take]
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return lexical_shortlist[:take]

    explicit_keys = _extract_explicit_keys(transcript)
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=30.0,
        max_retries=2,
    )
    model = (settings.mvp_embedding_model or "text-embedding-3-small").strip() or "text-embedding-3-small"
    payload = [transcript.strip()] + [
        f"{q.question_text}\n{q.reference_answer[:700]}".strip() for q in lexical_shortlist
    ]
    try:
        resp = await client.embeddings.create(model=model, input=payload)
    except Exception:
        logger.exception("Question selection embeddings failed")
        return lexical_shortlist[:take]

    vectors = [list(item.embedding) for item in resp.data]
    if len(vectors) != len(payload):
        return lexical_shortlist[:take]
    t_vec = vectors[0]
    scored = [
        (
            q,
            _cosine_similarity(t_vec, vec),
            _is_explicit_match(normalize_question_key(q.question_key), explicit_keys),
        )
        for q, vec in zip(lexical_shortlist, vectors[1:], strict=True)
    ]
    scored.sort(
        key=lambda item: (
            item[1] + (0.2 if item[2] else 0.0),
            len(item[0].question_text),
        ),
        reverse=True,
    )
    best_sim = scored[0][1] if scored else 0.0
    for q, _sim, _is_explicit in scored:
        nk = normalize_question_key(q.question_key)
        if nk in seen:
            continue
        selected.append(q)
        seen.add(nk)
        if len(selected) >= take:
            break
    return selected[:take]
