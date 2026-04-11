"""FastAPI router — exam evaluation endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services import evaluation_service, speech_service
from app.services.exam_text_parsing import strip_answer_completion_markers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exam", tags=["exam"])


@router.post("/evaluate-voice")
async def evaluate_voice(
    audio: Annotated[UploadFile, File(description="Voice recording (OGG/OPUS/WAV)")],
    reference: Annotated[str, Form(description="Reference (correct) answer text")],
    language: Annotated[str, Form(description="BCP-47 language code")] = "ru",
):
    """Распознавание речи и оценка: рубрика (JSON) или семантическое сходство 0–1 по эмбеддингам (нужен OPENAI_API_KEY)."""
    audio_bytes = await audio.read()
    transcript = strip_answer_completion_markers(
        (await speech_service.transcribe(audio_bytes, language=language)).strip(),
    )
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="После удаления служебных фраз о конце ответа не осталось текста для оценки.",
        )

    if evaluation_service.use_rubric_scoring():
        r = await evaluation_service.evaluate_rubric(transcript, reference)
        return {
            "mode": "rubric",
            "transcript": transcript,
            "reference": reference,
            "content_score": r.content_score,
            "accuracy_score": r.accuracy_score,
            "structure_score": r.structure_score,
            "conciseness_score": r.conciseness_score,
            "total": r.total,
            "content_rationale": r.content_rationale,
            "accuracy_rationale": r.accuracy_rationale,
            "structure_rationale": r.structure_rationale,
            "conciseness_rationale": r.conciseness_rationale,
        }

    score = await evaluation_service.evaluate_similarity(transcript, reference)
    return {
        "mode": "similarity",
        "transcript": transcript,
        "reference": reference,
        "score": score,
    }


@router.post("/evaluate-text")
async def evaluate_text(
    student_answer: Annotated[str, Form(description="Student answer as plain text")],
    reference: Annotated[str, Form(description="Reference (correct) answer text")],
):
    """Текстовый ответ: рубрика или семантическое сходство по эмбеддингам — как у голоса."""
    student_answer = strip_answer_completion_markers(student_answer.strip())
    if not student_answer:
        raise HTTPException(
            status_code=400,
            detail="После удаления служебных фраз о конце ответа не осталось текста для оценки.",
        )
    if evaluation_service.use_rubric_scoring():
        r = await evaluation_service.evaluate_rubric(student_answer, reference)
        return {
            "mode": "rubric",
            "student_answer": student_answer,
            "reference": reference,
            "content_score": r.content_score,
            "accuracy_score": r.accuracy_score,
            "structure_score": r.structure_score,
            "conciseness_score": r.conciseness_score,
            "total": r.total,
            "content_rationale": r.content_rationale,
            "accuracy_rationale": r.accuracy_rationale,
            "structure_rationale": r.structure_rationale,
            "conciseness_rationale": r.conciseness_rationale,
        }

    score = await evaluation_service.evaluate_similarity(student_answer, reference)
    return {
        "mode": "similarity",
        "student_answer": student_answer,
        "reference": reference,
        "score": score,
    }
