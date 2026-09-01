from __future__ import annotations

from pathlib import Path
import re

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from app.core.config import Settings

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.asyncio
async def test_root_redirects_to_docs():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get("/")
    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/docs"


def test_production_compose_is_ps_kz_isolated():
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    lowered = compose.lower()
    assert "traefik" not in lowered
    assert "n8n_default" not in lowered
    assert '"127.0.0.1:8200:8000"' in compose
    assert '"6379:6379"' not in compose
    assert "neuroexam3_internal" in compose
    assert "neuroexam3_redis_data" in compose
    assert 'ARQ_MAX_JOBS: "${ARQ_MAX_JOBS:-2}"' in compose


def test_worker_does_not_inherit_http_healthcheck():
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    worker = compose.split("  worker:", 1)[1].split("\nnetworks:", 1)[0]
    assert "healthcheck:" in worker
    assert "disable: true" in worker
    assert "http://" not in worker


def test_google_credentials_are_external_read_only_and_not_in_image():
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "/etc/neuroexam3/google-service-account.json" in compose
    assert "/run/secrets/neuroexam3-google-service-account.json" in compose
    assert "read_only: true" in compose
    assert "credentials" not in dockerfile.lower()
    assert "*credential*.json" in dockerignore
    assert "*service-account*.json" in dockerignore
    assert "tests/" in dockerignore
    assert "deploy/" in dockerignore
    assert "requirements-test.lock" in dockerignore
    assert "scripts/*" in dockerignore
    assert "!scripts/manage_telegram_webhook.py" in dockerignore


def test_prepare_script_is_lf_only_and_does_not_manage_shared_projects_dir():
    raw = (ROOT / "deploy" / "prepare-ps-kz.sh").read_bytes()
    text = raw.decode("utf-8")
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert "install -d" in text
    assert '"${CONFIG_DIR}"' in text
    assert "install -d /opt/projects" not in text
    assert "chown" not in "\n".join(
        line for line in text.splitlines() if "/opt/projects" in line
    )
    assert "docker compose up" not in text
    assert "readonly CONTAINER_UID=10001" in text
    assert "${mode} != 400" in text
    assert "-L ${ENV_FILE}" in text
    assert "-L ${CREDENTIALS_FILE}" in text


def test_env_example_lists_every_setting_without_values():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assignments = dict(
        re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, flags=re.MULTILINE),
    )
    expected = {name.upper() for name in Settings.model_fields}
    expected.add("GOOGLE_APPLICATION_CREDENTIALS")
    assert expected <= assignments.keys()
    assert all(value == "" for value in assignments.values())
