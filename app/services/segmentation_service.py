"""Разбиение одного транскрипта на фрагменты по ключам вопросов (эвристики + опционально LLM)."""

from __future__ import annotations

import json
import logging
import re

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


def segment_transcript_to_keys(
    transcript: str,
    keys: list[str],
) -> tuple[dict[str, str], str | None]:
    """
    Вернуть словарь «ключ → фрагмент ответа» и опциональное предупреждение.
    Если разбить не удалось, весь текст кладётся в первый ключ, остальные пустые.
    """
    t = transcript.strip()
    if not keys:
        return {}, "Нет ключей в настройках (MVP_REFERENCES_JSON / MVP_QUESTION_KEY)."

    if len(keys) == 1:
        return {keys[0]: t}, None

    hdr = _try_key_headers(t, keys)
    if hdr:
        return hdr, None

    for sep in ("\n---\n", "\r\n---\r\n", "\n###\n", "\n***\n"):
        parts = t.split(sep)
        if len(parts) == len(keys):
            return {k: p.strip() for k, p in zip(keys, parts, strict=True)}, None

    paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    if len(paras) == len(keys):
        return {k: p for k, p in zip(keys, paras, strict=True)}, None

    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if len(lines) == len(keys):
        return {k: p for k, p in zip(keys, lines, strict=True)}, None

    out = {keys[0]: t}
    for k in keys[1:]:
        out[k] = ""
    warn = (
        "Не удалось автоматически разбить ответ на части по числу ключей. "
        "Весь текст отнесён к первому ключу; остальные — пустые. "
        "Используйте разделители «---» между блоками, пустые строки между абзацами "
        "или подписи «Q1: …», «Q2: …»."
    )
    return out, warn


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
        temperature=0.2,
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
    """Сначала эвристики; при предупреждении и флаге — попытка LLM."""
    notes: list[str] = []
    parts, warn = segment_transcript_to_keys(transcript, keys)
    if warn:
        notes.append(warn)

    if (
        use_llm
        and len(keys) > 1
        and len(transcript.strip()) > 30
        and notes
    ):
        try:
            llm_parts = await segment_transcript_llm(transcript, keys)
            if llm_parts and sum(1 for v in llm_parts.values() if v.strip()) >= 2:
                return llm_parts, notes + ["Сегментация уточнена моделью (LLM)."]
        except Exception:
            logger.exception("segment_transcript_llm failed")

    return parts, notes
