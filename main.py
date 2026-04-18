"""NeuroExam3 — FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.routes import router
from app.api.telegram_webhook import router as telegram_router
from app.core.config import settings
from app.core.logging_filters import install_filters

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
install_filters(debug=settings.debug)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Пул arq к Redis: только если задан REDIS_URL (очередь для вебхука Telegram).

    Параллельно инициализируется SessionStore (Redis или in-memory).
    """
    from app.services.session_service import get_store
    from app.services.session_store import RedisSessionStore

    pool = None
    url = (settings.redis_url or "").strip()
    if url:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(url))
        logging.getLogger(__name__).info("Redis queue enabled: arq pool created")
    app.state.arq_pool = pool

    store = await get_store()
    app.state.session_store = store
    try:
        yield
    finally:
        if pool is not None:
            await pool.close()
        if isinstance(store, RedisSessionStore):
            await store.close()


app = FastAPI(
    title="NeuroExam3",
    description=(
        "Exam pipeline: voice/text → optional rubric scoring (0–100 by fields) or string similarity (0–1)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
app.include_router(telegram_router)


@app.get("/health", tags=["system"])
async def health() -> dict:
    """Simple liveness probe."""
    return {"status": "ok"}


if __name__ == "__main__":  # pragma: no cover
    # reload намеренно отключён: включать только через CLI (`uvicorn main:app --reload`)
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
    )
