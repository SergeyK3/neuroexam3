from fastapi import APIRouter
from pydantic import BaseModel

from app.services.evaluation import evaluate_answer

router = APIRouter()


class EvaluateRequest(BaseModel):
    student_answer: str
    reference_answer: str


class EvaluateResponse(BaseModel):
    score: float
    feedback: str


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(request: EvaluateRequest) -> EvaluateResponse:
    """Compare a student's answer with a reference answer and return a similarity score."""
    score = evaluate_answer(request.student_answer, request.reference_answer)
    feedback = _score_to_feedback(score)
    return EvaluateResponse(score=score, feedback=feedback)


def _score_to_feedback(score: float) -> str:
    if score >= 0.8:
        return "Excellent answer!"
    if score >= 0.5:
        return "Good answer, but could be improved."
    return "The answer needs significant improvement."
