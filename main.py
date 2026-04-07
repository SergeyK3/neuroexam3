"""NeuroExam3 — FastAPI application entry point."""

import logging

import uvicorn
from fastapi import FastAPI

from app.api.routes import router
from app.core.config import settings

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)

app = FastAPI(
    title="NeuroExam3",
    description=(
        "Accepts a student's voice answer, converts speech to text, "
        "compares it with a reference answer and returns a similarity score."
    ),
    version="0.1.0",
)

app.include_router(router)


@app.get("/health", tags=["system"])
async def health() -> dict:
    """Simple liveness probe."""
    return {"status": "ok"}


if __name__ == "__main__":  # pragma: no cover
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
