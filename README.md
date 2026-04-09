# NeuroExam3

Сервис на **Python 3.12** и **FastAPI**: экзамен в **Telegram** (текст и голос), распознавание речи (OpenAI Whisper), сегментация ответа по ключам вопроса, сравнение с эталонами и оценка **0…1**. Эталоны — из **Google Sheets** или fallback из `.env`; результаты при настроенных таблицах дописываются на лист результатов.

Дополнительно есть REST **`/exam/*`** для ручной проверки STT и оценки без Telegram.

Канонический порядок развития MVP: **[docs/01-architecture.md](docs/01-architecture.md)** (раздел «11. Порядок внедрения MVP»).

---

## Возможности и модули

| Что | Где в коде |
|-----|------------|
| Входящий вебхук Telegram, FSM, сценарий экзамена | `app/api/telegram_webhook.py`, `app/services/bot_update_handler.py`, `app/services/fsm_service.py` |
| Сессии пользователя (память процесса) | `app/services/session_service.py`, `app/models/session.py` |
| Речь → текст | `app/services/speech_service.py` |
| Оценка близости ответа к эталону | `app/services/evaluation_service.py` |
| Сегментация одного текста по ключам | `app/services/segmentation_service.py` |
| Эталоны (Sheets / .env) | `app/services/reference_map_service.py` |
| Запись строк оценки в Google Sheets | `app/services/results_export_service.py`, `app/integrations/sheets_client.py` |
| Исходящие сообщения и скачивание голоса | `app/integrations/telegram_client.py` |
| REST для тестов без бота | `app/api/routes.py` |
| Очередь Redis (arq), фоновая обработка вебхука | `app/workers/` |
| Настройки | `app/core/config.py`, `.env` |

Черновик `app/bot/bot.py` к основному сценарию **не относится** — бот работает через **webhook**.

---

## Структура репозитория (ключевое)

```
neuroexam3/
├── main.py
├── requirements.txt
├── Dockerfile
├── .env.example
├── .github/workflows/ci.yml
├── docker-compose.yml         # web + redis + worker (всё в контейнерах)
├── docker-compose.redis.yml   # только Redis для dev на хосте
├── docs/                    # бриф, архитектура, модель поставки
└── app/
    ├── api/
    │   ├── routes.py        # /exam/evaluate-text, /exam/evaluate-voice
    │   └── telegram_webhook.py   # POST /telegram/webhook
    ├── core/config.py
    ├── integrations/      # Telegram API, Google Sheets
    ├── models/
    ├── services/
    └── workers/             # arq: process_telegram_update
```

---

## Быстрый старт (локально)

```bash
git clone <url-репозитория>
cd neuroexam3
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Отредактируйте .env — см. таблицу ниже
uvicorn main:app --reload --port 8000
```

- Документация API: <http://localhost:8000/docs>
- Проверка живости: `GET /health` → `{"status":"ok"}`

---

## Переменные окружения

Шаблон — **`.env.example`**. В репозиторий коммитится только он; файл **`.env`** с секретами — нет.

| Переменная | Назначение |
|------------|------------|
| `TELEGRAM_BOT_TOKEN` | Токен бота от [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_WEBHOOK_SECRET` | Опционально: тот же секрет, что при `setWebhook(secret_token=...)`; иначе вебхук без проверки заголовка |
| `OPENAI_API_KEY` | Whisper и при `MVP_SEGMENTATION_USE_LLM=true` — сегментация через LLM |
| `SPEECH_MODEL` | Обычно `whisper-1` |
| `GOOGLE_SHEETS_CREDENTIALS` или `GOOGLE_APPLICATION_CREDENTIALS` | Путь к JSON сервисного аккаунта Google |
| `GOOGLE_SHEET_ID` | ID одной таблицы, если не используете карту дисциплин |
| `DISCIPLINE_GOOGLE_SHEET_IDS_JSON` | JSON `slug → spreadsheet_id`; при **нескольких** slug в боте показывается выбор дисциплины |
| `DEFAULT_DISCIPLINE` | Slug по умолчанию, если карта задана, но `discipline_id` не выбран |
| `GOOGLE_SHEET_IDEAL_TAB` | Лист с эталонами (по умолчанию `ideal answers`) |
| `GOOGLE_SHEET_RESULTS_TAB` | Лист для append результатов (по умолчанию `student_answers`) |
| `MVP_QUESTION_KEY`, `MVP_REFERENCE_ANSWER` | Один эталон без JSON |
| `MVP_REFERENCES_JSON` | Несколько ключей: `{"Q1":"эталон",...}` |
| `MVP_SEGMENTATION_USE_LLM` | `true` — при неудачной эвристической сегментации пробовать разбиение через OpenAI |
| `REDIS_URL` | Если задан (например `redis://localhost:6379/0`), вебхук Telegram **только ставит задачу** в очередь; обработку выполняет отдельный процесс `arq` (см. ниже). Если пусто — как раньше, обработка в процессе uvicorn |
| `HOST`, `PORT`, `DEBUG` | Сервер uvicorn (см. `app/core/config.py`) |

---

## Telegram: вебхук

1. Приложение должно быть доступно по **HTTPS** (деплой или туннель: ngrok, cloudflare tunnel и т.д.).
2. URL вебхука в этом проекте: **`https://<ваш-хост>/telegram/webhook`**.
3. Рекомендуется задать секрет и тот же секрет в `.env` как `TELEGRAM_WEBHOOK_SECRET`.

Пример (подставьте токен и URL; `secret_token` — произвольная строка, её же укажите в `.env`):

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://example.com/telegram/webhook&secret_token=<случайная_строка>
```

Проверка: Telegram шлёт `POST` с заголовком `X-Telegram-Bot-Api-Secret-Token`, если секрет задан. Локальный `http://127.0.0.1` без туннеля к Telegram **не подключить** — это ограничение Bot API.

---

## HTTP API (кроме Telegram)

| Метод | Путь | Описание |
|--------|------|----------|
| `GET` | `/health` | Liveness |
| `POST` | `/exam/evaluate-text` | Текст ответа + эталон → оценка |
| `POST` | `/exam/evaluate-voice` | Аудио + эталон → транскрипт и оценка |
| `POST` | `/telegram/webhook` | Тело `Update` от Telegram |

Пример — текстовая оценка:

```bash
curl -X POST http://localhost:8000/exam/evaluate-text \
     -F "student_answer=Ответ студента" \
     -F "reference=Эталонный ответ"
```

---

## Тесты

```bash
pytest
```

В CI (GitHub Actions) на push/PR в `main` или `master` выполняется то же самое. Redis в CI **не** поднимается: в тестах `REDIS_URL` принудительно пустой.

---

## Очередь Redis (arq)

Нужна, если обработка вебхука (Whisper, оценка, Sheets) **не укладывается в ответ** или нужно разгрузить процесс HTTP.

### Локально: только Redis в Docker, API и воркер на хосте

Из **корня репозитория**:

```bash
docker compose -f docker-compose.redis.yml up -d
```

В **`.env`** (один файл для обоих процессов):

```env
REDIS_URL=redis://127.0.0.1:6379/0
```

Терминал 1 — API:

```bash
uvicorn main:app --reload --port 8000
```

Терминал 2 — воркер (читает тот же `.env` через `app.core.config`):

```bash
arq app.workers.worker_settings.WorkerSettings
```

Остановить только Redis: `docker compose -f docker-compose.redis.yml down`.

### Общая схема

1. Поднимите Redis и задайте в `.env` **`REDIS_URL`** (одинаковый в API и воркере).
2. Запустите API (`uvicorn` или Docker).
3. Запустите воркер из **корня репозитория**:

```bash
arq app.workers.worker_settings.WorkerSettings
```

Воркер вызывает ту же функцию, что и синхронный путь: `handle_telegram_update` в `app/services/bot_update_handler.py`.

**Без воркера** при включённом `REDIS_URL` задачи копятся в Redis, ответы пользователю не отправляются.

**Всё в Docker сразу** (web + redis + worker): **`docker compose up --build`** (файл `docker-compose.yml`).

---

## Минимальная инфраструктура

### CI (GitHub Actions)

Установка зависимостей из `requirements.txt` и `pytest tests/`. Секреты репозитория не требуются.

### Docker

```bash
docker build -t neuroexam3 .
docker run --rm -p 8000:8000 --env-file .env neuroexam3
```

Проверка: `GET http://localhost:8000/health`. Для Telegram по-прежнему нужен публичный HTTPS.

Очередь: см. раздел **«Очередь Redis (arq)»**; для compose-сценария используйте `docker-compose.yml`.

---

## Расширение логики

Точки замены: **`speech_service.transcribe`**, **`evaluation_service.evaluate`**, правила FSM — **`fsm_service`**. Подробные инварианты и сценарий — в **`docs/`**.
