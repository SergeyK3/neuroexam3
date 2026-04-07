# NeuroExam

AI-powered answer evaluation system built with Python and FastAPI.

## Features

- **REST API** — `/evaluate` endpoint compares a student's answer with a reference answer and returns a similarity score (0–1).
- **Modular architecture** — separate packages for the API, services, AI speech, and AI evaluation logic.
- **Extensible** — swap in real NLP/embedding models or speech-to-text engines without touching the API layer.

---

## Project Structure

```
neuroexam3/
├── backend/
│   └── app/
│       ├── main.py            # FastAPI application entry point
│       ├── api/
│       │   └── routes.py      # /evaluate endpoint
│       └── services/
│           └── evaluation.py  # Similarity scoring logic
├── ai/
│   ├── speech/
│   │   └── stt.py             # Speech-to-text placeholder
│   └── evaluation/
│       └── similarity.py      # Semantic similarity placeholder
├── bot/                       # Chatbot integration (future)
├── data/                      # Reference answers / question banks
├── tests/
│   └── test_evaluate.py       # pytest test suite
├── .env.example
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Clone & set up environment

```bash
git clone https://github.com/SergeyK3/neuroexam3.git
cd neuroexam3
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env as needed
```

### 3. Run the server

```bash
cd backend
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

---

## API

### `POST /evaluate`

Compare a student's answer with a reference answer.

**Request body**
```json
{
  "student_answer": "the mitochondria is the powerhouse of the cell",
  "reference_answer": "the mitochondria is the powerhouse of the cell"
}
```

**Response**
```json
{
  "score": 1.0,
  "feedback": "Excellent answer!"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `score` | `float` | Similarity score from 0.0 to 1.0 |
| `feedback` | `string` | Human-readable feedback based on the score |

---

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Roadmap

- [ ] Integrate Whisper / Google STT for voice input
- [ ] Replace word-overlap scorer with sentence-transformer embeddings
- [ ] Add Telegram / Discord bot
- [ ] Add question bank management endpoints
- [ ] Dockerize the application
