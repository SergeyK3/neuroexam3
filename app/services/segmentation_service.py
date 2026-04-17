"""Разбиение одного транскрипта на фрагменты по ключам вопросов (эвристики + опционально LLM)."""

from __future__ import annotations

import difflib
import json
import logging
import re
import unicodedata

from app.models.question_bank import QuestionRecord
from app.services.exam_text_parsing import COMPLETION_MARKER_RE
from app.services.reference_map_service import (
    _SPOKEN_KEY_TOKEN_RE,
    normalize_question_key,
    parse_spoken_key_fragment,
)

logger = logging.getLogger(__name__)


def _unify_hyphens(s: str) -> str:
    """Нормализация разделителей внутри текста без схлопывания всех цифр строки в один ключ."""
    raw = unicodedata.normalize("NFC", (s or ""))
    raw = re.sub(r"[‑–—]", "-", raw)
    raw = re.sub(r"(?<=\d)\s*[,./]\s*(?=\d)", "-", raw)
    return raw


def _canon_key(s: str) -> str:
    return normalize_question_key(_unify_hyphens(s))


def _typo_correct_digit_triple_tokens(transcript: str, keys: list[str]) -> str:
    """
    Подмена в тексте кодов N-N-N на ближайший ключ из эталона (1-5-8 → 1-5-9),
    если в таблице нет точного совпадения (опечатка / STT).
    """
    keys_u = [_canon_key(k) for k in keys]
    digit_keys = [k for k in keys_u if re.fullmatch(r"\d+-\d+-\d+", k)]
    if not digit_keys:
        return transcript

    def repl(m: re.Match[str]) -> str:
        raw = m.group(0)
        tok = _canon_key(raw)
        if tok in digit_keys:
            return tok
        # 1-5-8 vs 1-5-9 даёт ratio ≈ 0.8 — cutoff 0.82 был слишком строгим.
        cm = difflib.get_close_matches(tok, digit_keys, n=1, cutoff=0.75)
        return cm[0] if cm else raw

    return re.sub(r"\d+(?:\s*[‑–—\-.,/]\s*\d+){2}", repl, transcript)


def _expand_stt_concat_keys(text: str, canon_keys: list[str]) -> str:
    """
    STT часто пишет «ключ 114» вместо «ключ 1-1-4»,
    либо словесно «ключ один четыре два».
    Подменяем цифровые/словесные ключи после «ключ/шифр/код» на канонический ключ,
    если цифровое содержание совпадает с одним из ключей банка.
    """
    digit_map: dict[str, str] = {}
    for ck in canon_keys:
        d = re.sub(r"\D", "", ck)
        if d and d != ck and len(d) >= 2:
            digit_map[d] = ck
    if not digit_map:
        return text

    _intro = (
        r"(?:ключ(?:\s*вопроса)?(?:\s+номер)?|шифр(?:\s*вопроса)?(?:\s+номер)?|"
        r"код(?:\s*вопроса)?(?:\s+номер)?|номер\s*(?:вопроса|ключа)?|обозначение|"
        r"по\s+(?:шифру|коду|ключу)|вопрос\s+с\s+(?:кодом|шифром|ключом))"
    )

    def repl(m: re.Match[str]) -> str:
        prefix = m.group(1)
        raw_num = m.group(2)
        parsed = parse_spoken_key_fragment(raw_num)
        digits = re.sub(r"\D", "", parsed)
        canon = digit_map.get(digits)
        return prefix + canon if canon else m.group(0)

    return re.sub(
        rf"(?i)({_intro}\s*[:.;,]?\s*)({_SPOKEN_KEY_TOKEN_RE}(?:[\s,./-]+{_SPOKEN_KEY_TOKEN_RE}){{0,5}})\b",
        repl,
        text,
    )


def _try_key_headers(transcript: str, keys: list[str]) -> dict[str, str] | None:
    """
    Блоки «КЛЮЧ: тело» / «КЛЮЧ — тело» / «КЛЮЧ. тело» по всему тексту.
    Допускает «? Ключ 1-5-9. Ответ…» (не только с начала строки), исправляет опечатки 1-5-8→1-5-9.
    """
    if not keys:
        return None
    t = unicodedata.normalize("NFC", (transcript or "").strip())
    t = _unify_hyphens(t)
    t = _typo_correct_digit_triple_tokens(t, keys)
    norm_keys = [_canon_key(k) for k in keys]
    t = _expand_stt_concat_keys(t, norm_keys)
    # Длинные ключи первыми, чтобы «1-5-10» не резалось как «1-5-1» + «0…»
    pattern = "|".join(sorted((re.escape(k) for k in norm_keys), key=len, reverse=True))
    # Устные вводные перед шифром из бланка: не только «ключ …», но и «ключ вопроса …»,
    # «шифр», «код вопроса», «по шифру …» и т.д. (STT и привычки экзаменуемых различаются).
    _key_speech_intro = (
        r"(?:"
        r"ключ(?:\s*вопроса)?(?:\s+номер)?|"
        r"шифр(?:\s*вопроса)?(?:\s+номер)?|"
        r"код(?:\s*вопроса)?(?:\s+номер)?|"
        r"номер\s*(?:вопроса|ключа)?|"
        r"обозначение|"
        r"по\s+(?:шифру|коду|ключу)|"
        r"вопрос\s+с\s+(?:кодом|шифром|ключом)"
        r")\s*[:.;,]?\s*"
    )
    # После кода: двоеточие/тире/точка или запятая («1-5-9, далее…»).
    pat = re.compile(
        rf"(?is)(?:^|[,.;:!?]\s+|\n\s*)(?:{_key_speech_intro})?({pattern})\s*(?:[:\-–.;]|,\s+|\s+)",
    )
    matches = list(pat.finditer(t))
    if not matches:
        return None
    out: dict[str, str] = {k: "" for k in keys}
    unify_map = {_canon_key(k): k for k in keys}
    for i, m in enumerate(matches):
        uk = _canon_key(m.group(1).strip())
        canon = unify_map.get(uk)
        if canon is None:
            continue
        start_body = m.end()
        end_body = matches[i + 1].start() if i + 1 < len(matches) else len(t)
        body = t[start_body:end_body].strip()
        out[canon] = body
    # Текст до первого явного шифра: по умолчанию — к первой строке эталонов (ввод без «билета»).
    # Если во вводной есть номер билета — тот же устной связкой идёт первый произнесённый ключ (mk),
    # иначе преамбула ошибочно попадает в keys[0] и даёт лишнюю «оценку» без ответа (другой шифр в речи).
    _pre_has_bilet = re.compile(
        r"(?i)билет|номер\s+билета|экзаменационн(?:ый|ого)\s+билет|№\s*билета",
    )
    if matches and matches[0].start() > 0:
        pre = t[: matches[0].start()].strip()
        if pre:
            m0 = matches[0]
            mk = unify_map.get(_canon_key(m0.group(1).strip()))
            if mk is not None:
                fk = keys[0]
                if _pre_has_bilet.search(pre):
                    target = mk
                else:
                    target = fk if mk != fk else mk
                cur = (out.get(target) or "").strip()
                out[target] = (pre + ("\n\n" + cur if cur else "")).strip()
    nonempty = sum(1 for v in out.values() if v.strip())
    if nonempty >= min(2, len(keys)):
        return out
    if nonempty == 1 and len(matches) == 1:
        tail = t[matches[0].end() :]
        if not re.search(r"(?i)\b(?:второй|третий|четвертый|четвёртый|следующий|другой)\s+вопрос\b", tail):
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

_RX_COMPLETION_TRANSITION = COMPLETION_MARKER_RE


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
    # Строка-ярлык «ключ / ключ вопроса / шифр / код …» до точки или переноса
    s = re.sub(
        r"(?is)^\s*(?:"
        r"ключ(?:\s*вопроса)?|шифр(?:\s*вопроса)?|код(?:\s*вопроса)?|"
        r"номер\s*(?:вопроса|ключа)?|обозначение|по\s+(?:шифру|коду|ключу)"
        r")\s*[^\n.]*[.\n]\s*",
        "",
        s,
        count=1,
    )
    # Тот же смысл, но без точки: «Ключ вопроса:» / «Шифр:» в начале фрагмента
    s = re.sub(
        r"(?is)^\s*(?:"
        r"ключ(?:\s*вопроса)?|шифр(?:\s*вопроса)?|код(?:\s*вопроса)?|"
        r"номер\s*(?:вопроса|ключа)?|обозначение"
        r")\s*[:.;]+\s*",
        "",
        s,
        count=1,
    )
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


def _try_completion_markers(transcript: str, keys: list[str]) -> dict[str, str] | None:
    """Фразы завершения ответа могут разделять части одного билета, но не должны обрезать весь ответ."""
    if len(keys) < 2:
        return None
    text = transcript.strip()
    marks = list(_RX_COMPLETION_TRANSITION.finditer(text))
    need = len(keys) - 1
    if len(marks) < need:
        return None
    cuts = [m.end() for m in marks[:need]]
    boundaries = [0] + cuts + [len(text)]
    out: dict[str, str] = {k: "" for k in keys}
    for i, k in enumerate(keys):
        chunk = text[boundaries[i] : boundaries[i + 1]].strip()
        out[k] = _trim_leading_question_key_phrase(chunk) if i > 0 else chunk
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

    compl = _try_completion_markers(t, keys)
    if compl:
        return compl, None, False

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


def _question_prompt_lines(questions: list[QuestionRecord]) -> str:
    lines: list[str] = []
    for i, q in enumerate(questions, start=1):
        q_text = (q.question_text or "").strip()
        if q_text:
            lines.append(f"{i}. {q.question_key}: {q_text}")
        else:
            lines.append(f"{i}. {q.question_key}")
    return "\n".join(lines)


async def segment_transcript_llm(
    transcript: str,
    questions: list[QuestionRecord],
) -> dict[str, str] | None:
    """Разбиение через chat completion (JSON). Нужен OPENAI_API_KEY."""
    from app.core.config import settings

    if not settings.openai_api_key or len(questions) < 2:
        return None

    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    keys_json = json.dumps([q.question_key for q in questions], ensure_ascii=False)
    prompt = (
        "Ты помогаешь разобрать ответы студента на экзамене. "
        f"Даны ключи вопросов (в таком порядке): {keys_json}.\n"
        "Формулировки вопросов:\n"
        f"{_question_prompt_lines(questions)}\n"
        "Ниже единый транскрипт (возможно несколько ответов подряд). "
        "Раздели текст на фрагменты по смыслу для каждого ключа. Студент может обозначать вопрос по-разному "
        "(«ключ …», «ключ вопроса …», «шифр», «код», «номер вопроса», порядковые «первый/второй вопрос» и т.п.). "
        "Если в транскрипте явно назван ключ вопроса, этот фрагмент нужно привязать именно к этому ключу, "
        "а не к семантически похожему соседнему вопросу. Не подменяй произнесённый ключ другим.\n"
        "Если для ключа ничего нет — пустая строка.\n"
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
    for q in questions:
        k = q.question_key
        v = data.get(k)
        out[k] = v.strip() if isinstance(v, str) else ""
    return out


async def segment_with_fallback(
    transcript: str,
    questions: list[QuestionRecord],
    *,
    use_llm: bool,
) -> tuple[dict[str, str], list[str]]:
    """Эвристики и явные разделители; при неудаче и включённом флаге — разбиение через LLM по списку ключей (без привязки к тексту бланка)."""
    from app.core.config import settings

    notes: list[str] = []
    keys = [q.question_key for q in questions]
    parts, config_err, try_llm_refinement = segment_transcript_to_keys(transcript, keys)
    if config_err:
        notes.append(config_err)
    heuristic_nonempty = sum(1 for v in parts.values() if (v or "").strip())
    if len(questions) > 1 and heuristic_nonempty <= 1 and len(transcript.strip()) > 350:
        try_llm_refinement = True

    if (
        use_llm
        and (settings.openai_api_key or "").strip()
        and len(questions) > 1
        and len(transcript.strip()) > 30
        and try_llm_refinement
    ):
        try:
            llm_parts = await segment_transcript_llm(transcript, questions)
            if llm_parts and sum(1 for v in llm_parts.values() if v.strip()) >= 2:
                return llm_parts, []
        except Exception:
            logger.exception("segment_transcript_llm failed")

    return parts, notes
