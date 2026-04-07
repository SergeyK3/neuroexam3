import sys
import os
import pytest
from fastapi.testclient import TestClient

# Allow imports from backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.main import app

client = TestClient(app)


def test_evaluate_high_score():
    response = client.post(
        "/evaluate",
        json={
            "student_answer": "the mitochondria is the powerhouse of the cell",
            "reference_answer": "the mitochondria is the powerhouse of the cell",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["score"] == 1.0
    assert "Excellent" in data["feedback"]


def test_evaluate_partial_score():
    response = client.post(
        "/evaluate",
        json={
            "student_answer": "mitochondria powerhouse cell",
            "reference_answer": "the mitochondria is the powerhouse of the cell",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert 0.0 < data["score"] < 1.0


def test_evaluate_empty_answer():
    response = client.post(
        "/evaluate",
        json={
            "student_answer": "",
            "reference_answer": "the mitochondria is the powerhouse of the cell",
        },
    )
    assert response.status_code == 200
    assert response.json()["score"] == 0.0


def test_evaluate_missing_field():
    response = client.post("/evaluate", json={"student_answer": "hello"})
    assert response.status_code == 422
