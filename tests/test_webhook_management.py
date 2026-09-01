from __future__ import annotations

import argparse
import importlib
import io
import json
import logging
import traceback

import httpx
import pytest

from scripts import manage_telegram_webhook as webhook


TOKEN = "1234567890:" + "TESTONLY" * 5
SECRET = "webhook-secret-for-offline-tests"
TARGET = "https://staging.example.test/telegram/webhook"
BOT_API_PREFIX = "https://api.telegram.org/bot"


def _environment() -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "TELEGRAM_WEBHOOK_SECRET": SECRET,
    }


def _run(argv: list[str], handler):
    stdout = io.StringIO()
    stderr = io.StringIO()
    result = webhook.main(
        argv,
        environ=_environment(),
        transport=httpx.MockTransport(handler),
        stdout=stdout,
        stderr=stderr,
    )
    combined = stdout.getvalue() + stderr.getvalue()
    assert TOKEN not in repr(argv)
    assert SECRET not in repr(argv)
    assert TOKEN not in combined
    assert TOKEN.split(":", 1)[0] not in combined
    assert TOKEN.split(":", 1)[1] not in combined
    assert SECRET not in combined
    assert BOT_API_PREFIX not in combined
    return result, stdout.getvalue(), stderr.getvalue()


def _assert_failed_set(handler) -> tuple[str, str]:
    result, output, errors = _run(["set", "--url", TARGET], handler)
    assert result != 0
    assert json.loads(output) == {"confirmed": False, "operation": "set"}
    assert errors
    return output, errors


def test_set_posts_twice_with_one_client_and_closes_it(monkeypatch):
    captured: list[tuple[str, str, object]] = []
    clients: list[httpx.Client] = []
    client_options: list[dict[str, object]] = []
    real_client = httpx.Client

    def counting_client(*args, **kwargs):
        client = real_client(*args, **kwargs)
        clients.append(client)
        client_options.append(kwargs)
        return client

    monkeypatch.setattr(webhook.httpx, "Client", counting_client)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append((request.method, request.url.path, json.loads(request.content)))
        if request.url.path.endswith("/setWebhook"):
            return httpx.Response(200, json={"ok": True, "result": True})
        assert request.url.path.endswith("/getWebhookInfo")
        return httpx.Response(
            200,
            json={"ok": True, "result": {"url": TARGET, "pending_update_count": 0}},
        )

    result, output, errors = _run(["set", "--url", TARGET], handler)
    assert result == 0
    assert errors == ""
    assert json.loads(output)["confirmed"] is True
    assert len(captured) == 2
    assert captured[0][0] == captured[1][0] == "POST"
    assert captured[0][1].endswith("/setWebhook")
    assert captured[0][2] == {"url": TARGET, "secret_token": SECRET}
    assert captured[1][1].endswith("/getWebhookInfo")
    assert captured[1][2] == {}
    assert len(clients) == 1
    assert clients[0].is_closed
    assert isinstance(client_options[0]["transport"], httpx.MockTransport)
    assert client_options[0]["timeout"] == 20.0


def test_set_url_mismatch_is_not_confirmed():
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.url.path.rsplit("/", 1)[-1])
        if request.url.path.endswith("/setWebhook"):
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"url": "https://different.example.test/telegram/webhook"},
            },
        )

    result, output, errors = _run(["set", "--url", TARGET], handler)
    assert result == 1
    assert methods == ["setWebhook", "getWebhookInfo"]
    assert json.loads(output) == {"confirmed": False, "operation": "set"}
    assert errors == "Webhook target was not confirmed.\n"
    assert "different.example.test" not in output + errors


def test_set_empty_actual_url_is_not_confirmed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/setWebhook"):
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(200, json={"ok": True, "result": {"url": ""}})

    output, errors = _assert_failed_set(handler)
    assert errors == "Webhook target was not confirmed.\n"
    assert TARGET not in output + errors


@pytest.mark.parametrize("failure_at", [1, 2])
def test_set_malformed_response_is_not_confirmed(failure_at: int):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == failure_at:
            return httpx.Response(200, content=b"{malformed-json")
        if calls == 1:
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(200, json={"ok": True, "result": {"url": TARGET}})

    _output, errors = _assert_failed_set(handler)
    assert calls == failure_at
    assert "Telegram request failed" in errors


@pytest.mark.parametrize("failure_at", [1, 2])
def test_set_malformed_payload_is_not_confirmed(failure_at: int):
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == failure_at:
            if failure_at == 1:
                return httpx.Response(200, json={"unexpected": True})
            return httpx.Response(200, json={"ok": True, "result": []})
        if calls == 1:
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(200, json={"ok": True, "result": {"url": TARGET}})

    _output, errors = _assert_failed_set(handler)
    assert calls == failure_at
    assert errors.startswith("Webhook management failed:")


@pytest.mark.parametrize("failure_at", [1, 2])
def test_set_http_status_error_is_not_confirmed(failure_at: int):
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == failure_at:
            return httpx.Response(503, json={"ok": False})
        if calls == 1:
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(200, json={"ok": True, "result": {"url": TARGET}})

    _output, errors = _assert_failed_set(handler)
    assert calls == failure_at
    assert errors == "Webhook management failed: Telegram did not confirm the operation\n"


@pytest.mark.parametrize("failure_at", [1, 2])
@pytest.mark.parametrize("failure_kind", ["timeout", "transport"])
def test_set_transport_error_is_not_confirmed(failure_at: int, failure_kind: str):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == failure_at:
            message = f"synthetic failure {TOKEN} {SECRET}"
            if failure_kind == "timeout":
                raise httpx.ReadTimeout(message, request=request)
            raise RuntimeError(message)
        if calls == 1:
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(200, json={"ok": True, "result": {"url": TARGET}})

    _output, errors = _assert_failed_set(handler)
    assert calls == failure_at
    expected_type = "ReadTimeout" if failure_kind == "timeout" else "RuntimeError"
    assert errors == f"Webhook management failed: Telegram request failed ({expected_type})\n"


def test_set_rejects_non_https_url_before_network():
    with pytest.raises(argparse.ArgumentTypeError, match="HTTPS URL"):
        webhook._https_url("http://staging.example.test/telegram/webhook")


def test_inspect_verifies_expected_target_without_printing_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/getWebhookInfo")
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "url": TARGET,
                    "pending_update_count": 0,
                    "has_custom_certificate": False,
                    "max_connections": 40,
                },
            },
        )

    result, output, errors = _run(["inspect", "--expect-url", TARGET], handler)
    assert result == 0
    assert errors == ""
    safe = json.loads(output)
    assert safe["expected_url_matches"] is True
    assert safe["pending_update_count"] == 0
    assert TARGET not in output


def test_inspect_mismatch_returns_nonzero_without_disclosing_targets():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True, "result": {"url": "https://old.example.test/webhook"}},
        )

    result, output, errors = _run(["inspect", "--expect-url", TARGET], handler)
    assert result == 1
    assert json.loads(output)["expected_url_matches"] is False
    assert TARGET not in output + errors
    assert "old.example.test" not in output + errors


def test_delete_preserves_pending_updates_by_default():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        assert request.url.path.endswith("/deleteWebhook")
        return httpx.Response(200, json={"ok": True, "result": True})

    result, output, errors = _run(["delete"], handler)
    assert result == 0
    assert errors == ""
    assert captured["payload"] == {"drop_pending_updates": False}
    assert json.loads(output)["pending_updates_dropped"] is False


def test_transport_failure_does_not_leak_secrets_in_error_or_exception():
    records: list[logging.LogRecord] = []

    class RawHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("neuroexam.webhook-transport-test")
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    raw_handler = RawHandler()
    logger.addHandler(raw_handler)

    def handler(_request: httpx.Request) -> httpx.Response:
        logger.error("fake transport error", extra={"token": TOKEN})
        raise RuntimeError(f"network failure {TOKEN} {SECRET}")

    try:
        result, output, errors = _run(["inspect"], handler)
        assert result == 1
        assert output == ""
        assert "Telegram request failed (RuntimeError)" in errors

        try:
            with webhook.TelegramWebhookClient(
                token=TOKEN,
                secret=SECRET,
                transport=httpx.MockTransport(handler),
            ) as client:
                client.inspect()
        except webhook.WebhookManagementError as exc:
            rendered = repr(exc)
            rendered_traceback = "".join(traceback.format_exception(exc))
            assert exc.__context__ is None
        else:  # pragma: no cover - the fake transport always fails
            raise AssertionError("expected safe management error")
    finally:
        logger.removeHandler(raw_handler)
    assert TOKEN not in rendered
    assert TOKEN.split(":", 1)[0] not in rendered
    assert TOKEN.split(":", 1)[1] not in rendered
    assert SECRET not in rendered
    assert TOKEN not in rendered_traceback
    assert TOKEN.split(":", 1)[0] not in rendered_traceback
    assert TOKEN.split(":", 1)[1] not in rendered_traceback
    assert SECRET not in rendered_traceback
    assert records
    raw_records = repr([record.__dict__ for record in records])
    assert TOKEN not in raw_records
    assert TOKEN.split(":", 1)[0] not in raw_records
    assert TOKEN.split(":", 1)[1] not in raw_records
    assert SECRET not in raw_records


def test_import_and_reload_never_perform_network(monkeypatch):
    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("network client constructed during import")

    monkeypatch.setattr(httpx, "Client", forbidden_client)
    importlib.reload(webhook)
