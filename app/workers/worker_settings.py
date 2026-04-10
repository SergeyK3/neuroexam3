"""Запуск воркера: arq app.workers.worker_settings.WorkerSettings

Важно: обработка апдейтов Telegram выполняется в этом процессе. После изменений в
`app/services/*` (сегментация, FSM, бот) обязательно перезапустите воркер arq —
перезапуск только uvicorn не подхватит новый код в очереди.
"""

import logging

from arq.connections import RedisSettings

from app.core.config import settings

# Процесс arq не импортирует main.py — иначе logger.info из приложения не виден в консоли.
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

from app.workers.jobs import process_telegram_update


def _redis() -> RedisSettings:
    url = (settings.redis_url or "").strip()
    if not url:
        return RedisSettings(host="127.0.0.1", port=6379)
    return RedisSettings.from_dsn(url)


class WorkerSettings:
    functions = [process_telegram_update]
    redis_settings = _redis()
