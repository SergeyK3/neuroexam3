from fastapi import FastAPI
from dotenv import load_dotenv

from app.api.routes import router

load_dotenv()

app = FastAPI(
    title="NeuroExam API",
    description="AI-powered answer evaluation system",
    version="0.1.0",
)

app.include_router(router)
