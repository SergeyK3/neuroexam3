"""Запуск воркера: arq app.workers.worker_settings.WorkerSettings"""

from arq.connections import RedisSettings

from app.core.config import settings
from app.workers.jobs import process_telegram_update


def _redis() -> RedisSettings:
    url = (settings.redis_url or "").strip()
    if not url:
        return RedisSettings(host="127.0.0.1", port=6379)
    return RedisSettings.from_dsn(url)


class WorkerSettings:
    functions = [process_telegram_update]
    redis_settings = _redis()
