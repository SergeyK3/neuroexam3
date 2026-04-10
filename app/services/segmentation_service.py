"""Разбиение одного транскрипта на фрагменты по ключам вопросов (эвристики + опционально LLM)."""

from __future__ import annotations

import json
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def _try_key_headers(transcript: str, keys: list[str]) -> dict[str, str] | None:
    """Ищет блоки вида «Q1: текст» или «Q1 — текст» по строкам."""
    if not keys:
        return None
    pattern = "|".join(re.escape(k) for k in keys)
    rx = re.compile(
        rf"(?mis)^\s*({pattern})\s*[:\-–]\s*(.+?)(?=^\s*(?:{pattern})\s*[:\-–]|\Z)",
    )
    matches = list(rx.finditer(transcript))
    if len(matches) < 2:
        return None
    out: dict[str, str] = {k: "" for k in keys}
    for m in matches:
        key, body = m.group(1).strip(), m.group(2).strip()
        if key in out:
            out[key] = body
    if sum(1 for v in out.values() if v.strip()) >= 2:
        return out
    return None


# «вопрос 1», «вопрос номер 2», «вопрос № 2» (часто в STT)
_RU_QNUM = re.compile(r"(?i)\bвопрос\s*(?:номер\s*|№\s*)?(\d+)\b")

# «1-й вопрос», «2-й вопрос» (Whisper и др.)
_RU_Q_NUM_ORD = re.compile(r"(?is)(?<![\w\d])(10|[1-9])\s*[-‑]?\s*й\s+вопрос\b")

# «первый вопрос», «второй вопрос», … (устная речь, без привязки к номерам из таблицы)
_RU_Q_ORDINAL: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"(?is)(?<![\w\d])перв(?:ый|ая|ое|ого|ой|ом)\s+вопрос\b"), 1),
    (re.compile(r"(?is)(?<![\w\d])втор(?:ой|ая|ое|ого|ом)\s+вопрос\b"), 2),
    (re.compile(r"(?is)(?<![\w\d])трет(?:ий|ья|ье|ьего|ьей|ьем)\s+вопрос\b"), 3),
    (re.compile(r"(?is)(?<![\w\d])четв[её]рт(?:ый|ая|ое|ого|ом)\s+вопрос\b"), 4),
    (re.compile(r"(?is)(?<![\w\d])пят(?:ый|ая|ое|ого|ом)\s+вопрос\b"), 5),
    (re.compile(r"(?is)(?<![\w\d])шест(?:ой|ая|ое|ого|ом)\s+вопрос\b"), 6),
    (re.compile(r"(?is)(?<![\w\d])седьм(?:ой|ая|ое|ого|ом)\s+вопрос\b"), 7),
    (re.compile(r"(?is)(?<![\w\d])восьм(?:ой|ая|ое|ого|ом)\s+вопрос\b"), 8),
    (re.compile(r"(?is)(?<![\w\d])девят(?:ый|ая|ое|ого|ом)\s+вопрос\b"), 9),
    (re.compile(r"(?is)(?<![\w\d])десят(?:ый|ая|ое|ого|ом)\s+вопрос\b"), 10),
]

# «первый ключ», «второй ключ», … — то же по смыслу, слово «ключ» без значения из эталона
_RU_K_ORDINAL: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"(?is)(?<![\w\d])перв(?:ый|ого)\s+ключ\b"), 1),
    (re.compile(r"(?is)(?<![\w\d])втор(?:ой|ого)\s+ключ\b"), 2),
    (re.compile(r"(?is)(?<![\w\d])трет(?:ий|ьего)\s+ключ\b"), 3),
    (re.compile(r"(?is)(?<![\w\d])четв[её]рт(?:ый|ого)\s+ключ\b"), 4),
    (re.compile(r"(?is)(?<![\w\d])пят(?:ый|ого)\s+ключ\b"), 5),
    (re.compile(r"(?is)(?<![\w\d])шест(?:ой|ого)\s+ключ\b"), 6),
    (re.compile(r"(?is)(?<![\w\d])седьм(?:ой|ого)\s+ключ\b"), 7),
    (re.compile(r"(?is)(?<![\w\d])восьм(?:ой|ого)\s+ключ\b"), 8),
    (re.compile(r"(?is)(?<![\w\d])девят(?:ый|ого)\s+ключ\b"), 9),
    (re.compile(r"(?is)(?<![\w\d])десят(?:ый|ого)\s+ключ\b"), 10),
]

# Переход к следующему ответу без номера из бланка
_RX_TRANSITION = re.compile(
    r"(?is)(?<![\w\d])(?:"
    r"следующий\s+вопрос|следующий\s+ключ|"
    r"ещё\s+вопрос|еще\s+вопрос|"
    r"другой\s+вопрос"
    r")\b",
)


def _trim_leading_question_key_phrase(segment: str) -> str:
    """Убирает в начале фрагмента устные вводные (порядковые «вопрос»/«ключ», переходы) — без привязки к кодам из таблицы."""
    s = segment.strip()
    s = re.sub(
        r"(?is)^\s*(?:перв(?:ый|ая|ое|ого|ой|ом)|втор(?:ой|ая|ое|ого|ом)|трет(?:ий|ья|ье|ьего|ьей|ьем)|"
        r"четв[её]рт(?:ый|ая|ое|ого|ом)|пят(?:ый|ая|ое|ого|ом)|шест(?:ой|ая|ое|ого|ом)|"
        r"седьм(?:ой|ая|ое|ого|ом)|восьм(?:ой|ая|ое|ого|ом)|девят(?:ый|ая|ое|ого|ом)|"
        r"десят(?:ый|ая|ое|ого|ом))\s+вопрос\s*[.,;]?\s*",
        "",
        s,
        count=1,
    )
    s = re.sub(
        r"(?is)^\s*(?:перв(?:ый|ого)|втор(?:ой|ого)|трет(?:ий|ьего)|четв[её]рт(?:ый|ого)|"
        r"пят(?:ый|ого)|шест(?:ой|ого)|седьм(?:ой|ого)|восьм(?:ой|ого)|девят(?:ый|ого)|десят(?:ый|ого))\s+ключ\s*[.,;]?\s*",
        "",
        s,
        count=1,
    )
    # строка-ярлык «ключ …» до конца предложения (любой текст, не значения из конфига)
    s = re.sub(r"(?is)^\s*ключ\s*[^\n.]*[.\n]\s*", "", s, count=1)
    s = re.sub(
        r"(?is)^\s*вопрос\s*(?:номер\s*|№\s*)?\d+\s*[,;]?\s*(?:ключ\s*\d+\s*[,;]?\s*)?",
        "",
        s,
        count=1,
    )
    s = re.sub(r"(?is)^\s*(?:10|[1-9])\s*[-‑]?\s*й\s+вопрос\s*[.,;]?\s*", "", s, count=1)
    s = re.sub(
        r"(?is)^\s*(?:следующий\s+вопрос|следующий\s+ключ|ещё\s+вопрос|еще\s+вопрос|другой\s+вопрос)\s*[.,;]?\s*",
        "",
        s,
        count=1,
    )
    return s.strip()


def _try_transition_markers(transcript: str, keys: list[str]) -> dict[str, str] | None:
    """«Следующий вопрос», «ещё вопрос», «другой вопрос» — границы без номеров из бланка."""
    if len(keys) < 2:
        return None
    text = transcript.strip()
    positions = sorted(m.start() for m in _RX_TRANSITION.finditer(text))
    need = len(keys) - 1
    if len(positions) < need:
        return None
    cuts = positions[:need]
    boundaries = [0] + cuts + [len(text)]
    out: dict[str, str] = {k: "" for k in keys}
    for i, k in enumerate(keys):
        chunk = text[boundaries[i] : boundaries[i + 1]].strip()
        if i > 0:
            chunk = _trim_leading_question_key_phrase(chunk)
        out[k] = chunk
    if sum(1 for v in out.values() if v.strip()) >= 2:
        return out
    return None


def _try_russian_question_markers(transcript: str, keys: list[str]) -> dict[str, str] | None:
    """
    Устная речь: «вопрос номер N», «первый/второй вопрос», «первый/второй ключ», «N-й вопрос».
    Номера N относятся только к порядку ответов (1…K), не к кодам вопросов в таблице.
    """
    if len(keys) < 2:
        return None
    text = transcript.strip()
    raw: list[tuple[int, int]] = []
    for m in _RU_QNUM.finditer(text):
        n = int(m.group(1))
        if 1 <= n <= len(keys):
            raw.append((m.start(), n))
    for m in _RU_Q_NUM_ORD.finditer(text):
        n = int(m.group(1))
        if 1 <= n <= len(keys):
            raw.append((m.start(), n))
    for rx, n in _RU_Q_ORDINAL:
        if n > len(keys):
            continue
        for m in rx.finditer(text):
            raw.append((m.start(), n))
    for rx, n in _RU_K_ORDINAL:
        if n > len(keys):
            continue
        for m in rx.finditer(text):
            raw.append((m.start(), n))
    if not raw:
        return None
    raw.sort(key=lambda x: x[0])
    seen: set[int] = set()
    marks: list[tuple[int, int]] = []
    for pos, n in raw:
        if n not in seen:
            seen.add(n)
            marks.append((pos, n))

    if len(marks) == 1:
        pos, num = marks[0]
        if num < 2:
            return None
        out: dict[str, str] = {k: "" for k in keys}
        head = text[:pos].strip()
        tail = _trim_leading_question_key_phrase(text[pos:])
        out[keys[0]] = head
        if num - 1 < len(keys):
            out[keys[num - 1]] = tail
        if sum(1 for v in out.values() if v.strip()) >= 2:
            return out
        return None

    out = {k: "" for k in keys}
    first_pos, first_num = marks[0]
    if first_num >= 2:
        out[keys[0]] = text[:first_pos].strip()

    for i, (pos, num) in enumerate(marks):
        if not (1 <= num <= len(keys)):
            continue
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        # «Вопрос 1» в середине фразы: весь текст от начала до следующей границы — первый ответ (включая билет).
        start = 0 if (first_num == 1 and i == 0 and num == 1) else pos
        chunk = text[start:end].strip()
        if num > 1:
            chunk = _trim_leading_question_key_phrase(chunk)
        out[keys[num - 1]] = chunk

    if sum(1 for v in out.values() if v.strip()) >= 2:
        return out
    return None


def segment_transcript_to_keys(
    transcript: str,
    keys: list[str],
) -> tuple[dict[str, str], str | None, bool]:
    """
    Вернуть словарь «ключ → фрагмент ответа», опциональную ошибку конфигурации,
    и флаг «эвристики не разбили много ключей — имеет смысл попробовать LLM».

    Если разбить не удалось, весь текст кладётся в первый ключ, остальные пустые
    (без пользовательского предупреждения в чате — см. segment_with_fallback).
    """
    t = unicodedata.normalize("NFC", (transcript or "").strip())
    if not keys:
        return {}, "Нет ключей в настройках (MVP_REFERENCES_JSON / MVP_QUESTION_KEY).", False

    if len(keys) == 1:
        return {keys[0]: t}, None, False

    hdr = _try_key_headers(t, keys)
    if hdr:
        return hdr, None, False

    ru = _try_russian_question_markers(t, keys)
    if ru:
        return ru, None, False

    tr = _try_transition_markers(t, keys)
    if tr:
        return tr, None, False

    for sep in ("\n---\n", "\r\n---\r\n", "\n###\n", "\n***\n"):
        parts = t.split(sep)
        if len(parts) == len(keys):
            return {k: p.strip() for k, p in zip(keys, parts, strict=True)}, None, False

    paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    if len(paras) == len(keys):
        return {k: p for k, p in zip(keys, paras, strict=True)}, None, False

    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if len(lines) == len(keys):
        return {k: p for k, p in zip(keys, lines, strict=True)}, None, False

    out = {keys[0]: t}
    for k in keys[1:]:
        out[k] = ""
    return out, None, True


async def segment_transcript_llm(transcript: str, keys: list[str]) -> dict[str, str] | None:
    """Разбиение через chat completion (JSON). Нужен OPENAI_API_KEY."""
    from app.core.config import settings

    if not settings.openai_api_key or len(keys) < 2:
        return None

    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    keys_json = json.dumps(keys, ensure_ascii=False)
    prompt = (
        "Ты помогаешь разобрать ответы студента на экзамене. "
        f"Даны ключи вопросов (в таком порядке): {keys_json}.\n"
        "Ниже единый транскрипт (возможно несколько ответов подряд). "
        "Раздели текст на фрагменты по смыслу для каждого ключа. Если для ключа ничего нет — пустая строка.\n"
        "Верни ТОЛЬКО JSON-объект: ключи — те же строки, значения — фрагменты ответа.\n\n"
        f"Транскрипт:\n{transcript}"
    )

    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None
    out: dict[str, str] = {}
    for k in keys:
        v = data.get(k)
        out[k] = v.strip() if isinstance(v, str) else ""
    return out


async def segment_with_fallback(
    transcript: str,
    keys: list[str],
    *,
    use_llm: bool,
) -> tuple[dict[str, str], list[str]]:
    """Эвристики и явные разделители; при неудаче и включённом флаге — разбиение через LLM по списку ключей (без привязки к тексту бланка)."""
    from app.core.config import settings

    notes: list[str] = []
    parts, config_err, try_llm_refinement = segment_transcript_to_keys(transcript, keys)
    if config_err:
        notes.append(config_err)

    if (
        use_llm
        and (settings.openai_api_key or "").strip()
        and len(keys) > 1
        and len(transcript.strip()) > 30
        and try_llm_refinement
    ):
        try:
            llm_parts = await segment_transcript_llm(transcript, keys)
            if llm_parts and sum(1 for v in llm_parts.values() if v.strip()) >= 2:
                return llm_parts, []
        except Exception:
            logger.exception("segment_transcript_llm failed")

    return parts, notes
