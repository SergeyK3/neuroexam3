"""Safely inspect, set, or delete the Telegram webhook.

Credentials are read exclusively from the process environment. Importing this
module performs no network or configuration access.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import os
import re
import sys
import types
from typing import Any, TextIO
from urllib.parse import urlsplit

import httpx

from app.core.logging_filters import install_filters


_TOKEN_RE = re.compile(r"^\d{5,16}:[A-Za-z0-9_-]{20,}$")
_WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class WebhookManagementError(RuntimeError):
    """A deliberately secret-free management failure."""


def _https_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.netloc
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise argparse.ArgumentTypeError("webhook URL must be an HTTPS URL without credentials or fragment")
    return value


class TelegramWebhookClient:
    def __init__(
        self,
        *,
        token: str,
        secret: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not _TOKEN_RE.fullmatch(token):
            raise WebhookManagementError("TELEGRAM_BOT_TOKEN is missing or invalid")
        self._endpoint = f"https://api.telegram.org/bot{token}"
        self._secret = secret
        self._transport = transport
        self._client: httpx.Client | None = None

    def __enter__(self) -> TelegramWebhookClient:
        failure_type: str | None = None
        try:
            self._client = httpx.Client(transport=self._transport, timeout=20.0)
        except Exception as exc:
            failure_type = type(exc).__name__
        if failure_type is not None:
            raise WebhookManagementError(f"Telegram client initialization failed ({failure_type})")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback_object: types.TracebackType | None,
    ) -> bool:
        client, self._client = self._client, None
        failure_type: str | None = None
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                failure_type = type(exc).__name__
        if failure_type is not None and exc_type is None:
            raise WebhookManagementError(f"Telegram client shutdown failed ({failure_type})")
        return False

    def _post(self, method: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if self._client is None:
            raise WebhookManagementError("Telegram client is not active")
        failure_type: str | None = None
        try:
            response = self._client.post(
                f"{self._endpoint}/{method}",
                json=dict(payload or {}),
            )
            data = response.json()
        except Exception as exc:
            failure_type = type(exc).__name__
        if failure_type is not None:
            raise WebhookManagementError(f"Telegram request failed ({failure_type})")

        if response.status_code != 200 or not isinstance(data, dict) or data.get("ok") is not True:
            raise WebhookManagementError("Telegram did not confirm the operation")
        return data

    def inspect(self, *, expected_url: str | None = None) -> dict[str, Any]:
        data = self._post("getWebhookInfo")
        result = data.get("result")
        if not isinstance(result, dict):
            raise WebhookManagementError("Telegram returned invalid webhook information")
        current_url = result.get("url")
        if not isinstance(current_url, str):
            raise WebhookManagementError("Telegram returned invalid webhook information")
        pending_count = result.get("pending_update_count", 0)
        if not isinstance(pending_count, int) or isinstance(pending_count, bool):
            raise WebhookManagementError("Telegram returned invalid webhook information")

        safe: dict[str, Any] = {
            "configured": bool(current_url),
            "pending_update_count": pending_count,
            "has_custom_certificate": bool(result.get("has_custom_certificate", False)),
        }
        if isinstance(result.get("max_connections"), int):
            safe["max_connections"] = result["max_connections"]
        if expected_url is not None:
            safe["expected_url_matches"] = current_url == expected_url
        return safe

    def set(self, url: str) -> bool:
        if not self._secret or not _WEBHOOK_SECRET_RE.fullmatch(self._secret):
            raise WebhookManagementError("TELEGRAM_WEBHOOK_SECRET is missing or invalid")
        self._post("setWebhook", {"url": url, "secret_token": self._secret})
        data = self._post("getWebhookInfo")
        result = data.get("result")
        if not isinstance(result, dict):
            raise WebhookManagementError("Telegram returned invalid webhook information")
        current_url = result.get("url")
        return isinstance(current_url, str) and current_url == url

    def delete(self, *, drop_pending_updates: bool = False) -> None:
        self._post("deleteWebhook", {"drop_pending_updates": drop_pending_updates})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the Telegram webhook without exposing secrets")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect")
    inspect.add_argument("--expect-url", type=_https_url)

    set_command = commands.add_parser("set")
    set_command.add_argument("--url", required=True, type=_https_url)

    delete = commands.add_parser("delete")
    delete.add_argument("--drop-pending-updates", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    install_filters(debug=False)
    args = _parser().parse_args(argv)
    environment = os.environ if environ is None else environ
    token = environment.get("TELEGRAM_BOT_TOKEN", "")
    secret = environment.get("TELEGRAM_WEBHOOK_SECRET")

    try:
        with TelegramWebhookClient(token=token, secret=secret, transport=transport) as client:
            if args.command == "set":
                confirmed = client.set(args.url)
                result: dict[str, Any] = {"operation": "set", "confirmed": confirmed}
                if not confirmed:
                    print(json.dumps(result, sort_keys=True), file=stdout)
                    print("Webhook target was not confirmed.", file=stderr)
                    return 1
            elif args.command == "delete":
                client.delete(drop_pending_updates=args.drop_pending_updates)
                result = {
                    "operation": "delete",
                    "confirmed": True,
                    "pending_updates_dropped": bool(args.drop_pending_updates),
                }
            else:
                result = client.inspect(expected_url=args.expect_url)
                if args.expect_url is not None and not result["expected_url_matches"]:
                    print(json.dumps(result, sort_keys=True), file=stdout)
                    print("Webhook target was not confirmed.", file=stderr)
                    return 1
        print(json.dumps(result, sort_keys=True), file=stdout)
        return 0
    except WebhookManagementError as exc:
        if args.command == "set":
            print(json.dumps({"operation": "set", "confirmed": False}, sort_keys=True), file=stdout)
        print(f"Webhook management failed: {exc}", file=stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
