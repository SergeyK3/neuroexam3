"""FastAPI router — exam evaluation endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from app.services import evaluation_service, speech_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exam", tags=["exam"])


@router.post("/evaluate-voice")
async def evaluate_voice(
    audio: Annotated[UploadFile, File(description="Voice recording (OGG/OPUS/WAV)")],
    reference: Annotated[str, Form(description="Reference (correct) answer text")],
    language: Annotated[str, Form(description="BCP-47 language code")] = "ru",
):
    """Accept a voice recording and return a similarity score.

    Steps:
    1. Read the uploaded audio file.
    2. Transcribe speech to text.
    3. Compare the transcript against the reference answer.
    4. Return the score together with the recognised transcript.
    """
    audio_bytes = await audio.read()
    transcript = await speech_service.transcribe(audio_bytes, language=language)
    score = await evaluation_service.evaluate(transcript, reference)

    return {
        "transcript": transcript,
        "reference": reference,
        "score": score,
    }


@router.post("/evaluate-text")
async def evaluate_text(
    student_answer: Annotated[str, Form(description="Student answer as plain text")],
    reference: Annotated[str, Form(description="Reference (correct) answer text")],
):
    """Accept a text answer and return a similarity score (no STT step)."""
    score = await evaluation_service.evaluate(student_answer, reference)

    return {
        "student_answer": student_answer,
        "reference": reference,
        "score": score,
    }
