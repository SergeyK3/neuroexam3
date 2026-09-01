from __future__ import annotations

from pathlib import Path
import re

import pytest
from httpx import ASGITransport, AsyncClient
import yaml

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


def test_redis_runs_as_pinned_non_root_user_with_hardening():
    compose = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))
    redis = compose["services"]["redis"]
    assert redis["user"] == "999:1000"
    assert redis["cap_drop"] == ["ALL"]
    assert redis["read_only"] is True
    assert "no-new-privileges:true" in redis["security_opt"]
    assert redis["tmpfs"] == ["/tmp:rw,noexec,nosuid,size=16m"]
    assert "redis_data:/data" in redis["volumes"]
    assert redis["healthcheck"]["test"] == ["CMD", "redis-cli", "ping"]
    assert not redis.get("ports")


def test_ci_runs_safe_compose_runtime_smoke_and_always_cleans_up():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(workflow)
    job = parsed["jobs"]["test"]
    assert 0 < job["timeout-minutes"] <= 15
    smoke = next(
        step["run"]
        for step in job["steps"]
        if step.get("name") == "Runtime smoke production Compose"
    )
    cleanup = next(
        step
        for step in job["steps"]
        if step.get("name") == "Cleanup runtime smoke"
    )
    assert "docker compose -f docker-compose.prod.yml build --pull" in workflow
    assert 'timeout 180s "${compose[@]}" up -d --no-build' in smoke
    assert "wait_for_health redis" in smoke
    assert "wait_for_health web" in smoke
    assert "local deadline=$((SECONDS + 120))" in smoke
    assert "curl --fail --silent --show-error --output /dev/null" in smoke
    assert "--connect-timeout 3 --max-time 10" in smoke
    assert "worker_restarts" in smoke
    for line in smoke.splitlines():
        if "docker inspect" in line:
            assert "timeout 10s docker inspect" in line
    assert cleanup["if"] == "always()"
    assert cleanup["run"].startswith("timeout 120s docker compose")
    assert "down -v --remove-orphans || true" in cleanup["run"]
    unsafe = ("docker compose logs", "Config.Env", "printenv", "api.telegram.org/bot")
    assert not any(marker in smoke for marker in unsafe)
    assert "docker compose config" not in workflow.replace(
        "docker compose -f docker-compose.prod.yml config --quiet",
        "",
    )


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
