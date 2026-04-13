"""FastAPI router — exam evaluation endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services import evaluation_service, speech_service
from app.services.exam_text_parsing import strip_answer_completion_markers, strip_embedded_bot_output

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exam", tags=["exam"])


@router.post("/evaluate-voice")
async def evaluate_voice(
    audio: Annotated[UploadFile, File(description="Voice recording (OGG/OPUS/WAV)")],
    reference: Annotated[str, Form(description="Reference (correct) answer text")],
    language: Annotated[str, Form(description="BCP-47 language code")] = "ru",
):
    """Распознавание речи и оценка: покрытие смысловых элементов или семантическое сходство 0–1."""
    audio_bytes = await audio.read()
    transcript = strip_embedded_bot_output(strip_answer_completion_markers(
        (await speech_service.transcribe(audio_bytes, language=language)).strip(),
    ))
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="После удаления служебных фраз о конце ответа не осталось текста для оценки.",
        )

    if evaluation_service.use_coverage_scoring():
        r = await evaluation_service.evaluate_coverage(transcript, reference)
        return {
            "mode": "coverage",
            "transcript": transcript,
            "reference": reference,
            "score": r.score,
            "total_elements": r.total_elements,
            "covered_elements": r.covered_elements,
            "partial_elements": r.partial_elements,
            "missing_elements": r.missing_elements,
            "general_comment": r.general_comment,
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
    """Текстовый ответ: покрытие смысловых элементов или семантическое сходство по эмбеддингам."""
    student_answer = strip_embedded_bot_output(strip_answer_completion_markers(student_answer.strip()))
    if not student_answer:
        raise HTTPException(
            status_code=400,
            detail="После удаления служебных фраз о конце ответа не осталось текста для оценки.",
        )
    if evaluation_service.use_coverage_scoring():
        r = await evaluation_service.evaluate_coverage(student_answer, reference)
        return {
            "mode": "coverage",
            "student_answer": student_answer,
            "reference": reference,
            "score": r.score,
            "total_elements": r.total_elements,
            "covered_elements": r.covered_elements,
            "partial_elements": r.partial_elements,
            "missing_elements": r.missing_elements,
            "general_comment": r.general_comment,
        }

    score = await evaluation_service.evaluate_similarity(student_answer, reference)
    return {
        "mode": "similarity",
        "student_answer": student_answer,
        "reference": reference,
        "score": score,
    }
