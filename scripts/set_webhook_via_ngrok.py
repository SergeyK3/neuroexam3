"""Выставить Telegram setWebhook, взяв публичный HTTPS URL из локального API ngrok (127.0.0.1:4040).

Запуск из корня репозитория (с активированным .venv):
  python scripts/set_webhook_via_ngrok.py

Условия: крутится ngrok с inspect (по умолчанию), в .env задан TELEGRAM_BOT_TOKEN.
Если задан TELEGRAM_WEBHOOK_SECRET — в setWebhook уйдёт тот же secret_token.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx

from app.core.config import settings


def main() -> int:
    try:
        r = httpx.get("http://127.0.0.1:4040/api/tunnels", timeout=5.0)
        r.raise_for_status()
    except httpx.HTTPError as e:
        print("Не удалось прочитать http://127.0.0.1:4040/api/tunnels — ngrok запущен?", file=sys.stderr)
        print(e, file=sys.stderr)
        return 1

    data = r.json()
    tunnels = data.get("tunnels") or []
    https_url = None
    for t in tunnels:
        if t.get("proto") == "https":
            https_url = t.get("public_url")
            break
    if not https_url:
        print("В ответе ngrok нет HTTPS-туннеля.", file=sys.stderr)
        return 1

    base = https_url.rstrip("/")
    webhook = f"{base}/telegram/webhook"

    token = settings.telegram_bot_token.strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN пуст в .env", file=sys.stderr)
        return 1

    params: dict[str, str] = {"url": webhook}
    sec = (settings.telegram_webhook_secret or "").strip()
    if sec:
        params["secret_token"] = sec

    api = f"https://api.telegram.org/bot{token}/setWebhook"
    out = httpx.get(api, params=params, timeout=30.0)
    print(json.dumps(out.json(), indent=2, ensure_ascii=False))
    info = httpx.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=30.0)
    print(json.dumps(info.json(), indent=2, ensure_ascii=False))
    return 0 if out.json().get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
