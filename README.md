# NeuroExam3

A modular AI-powered exam evaluation system built with Python and FastAPI.

The system accepts a student's **voice answer** via Telegram, converts speech to text,
compares the transcript with a reference answer, and returns a similarity score from **0 to 1**.

---

## Features

| Capability | Module |
|---|---|
| Telegram bot interface | `app/bot/bot.py` |
| Speech-to-text (STT) | `app/services/speech_service.py` |
| Answer similarity scoring | `app/services/evaluation_service.py` |
| REST API | `app/api/routes.py` (FastAPI) |
| Configuration | `app/core/config.py` + `.env` |

---

## Project structure

```
neuroexam3/
├── main.py                        # FastAPI application entry point
├── requirements.txt
├── .env.example                   # Template for environment variables
├── README.md
└── app/
    ├── api/
    │   └── routes.py              # /exam/evaluate-voice & /exam/evaluate-text
    ├── bot/
    │   └── bot.py                 # Telegram bot (placeholder)
    ├── core/
    │   └── config.py              # Pydantic-settings configuration
    └── services/
        ├── speech_service.py      # STT placeholder
        └── evaluation_service.py  # Similarity scoring placeholder
```

---

## Quick start

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/SergeyK3/neuroexam3.git
cd neuroexam3
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, etc.
```

### 4. Run the API server

```bash
uvicorn main:app --reload
```

Open the interactive docs at <http://localhost:8000/docs>.

### 5. Run the Telegram bot (optional)

```bash
python -m app.bot.bot
```

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Liveness probe |
| `POST` | `/exam/evaluate-voice` | Upload a voice file + reference answer → score |
| `POST` | `/exam/evaluate-text`  | Submit text answer + reference answer → score |

### Example — text evaluation

```bash
curl -X POST http://localhost:8000/exam/evaluate-text \
     -F "student_answer=The mitochondria is the powerhouse of the cell" \
     -F "reference=The mitochondria is the powerhouse of the cell"
```

```json
{
  "student_answer": "The mitochondria is the powerhouse of the cell",
  "reference": "The mitochondria is the powerhouse of the cell",
  "score": 1.0
}
```

---

## Implementing the placeholder services

### Speech recognition (`app/services/speech_service.py`)

Replace the body of `transcribe()` with a real STT backend, for example:

```python
import openai

async def transcribe(audio_bytes: bytes, *, language: str = "ru") -> str:
    client = openai.AsyncOpenAI()
    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=("audio.ogg", audio_bytes, "audio/ogg"),
        language=language,
    )
    return response.text
```

### Answer evaluation (`app/services/evaluation_service.py`)

Replace the body of `evaluate()` with a similarity metric, for example
cosine similarity of sentence embeddings:

```python
from sentence_transformers import SentenceTransformer, util

_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

async def evaluate(student_answer: str, reference_answer: str) -> float:
    emb = _model.encode([student_answer, reference_answer], convert_to_tensor=True)
    return float(util.cos_sim(emb[0], emb[1]))
```

### Telegram bot (`app/bot/bot.py`)

Uncomment `python-telegram-bot` in `requirements.txt`, install it, then
implement the `_handle_voice` coroutine following the sketch in the file.

---

## Running tests

```bash
pytest
```
