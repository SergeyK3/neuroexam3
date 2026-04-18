# NeuroExam3

Сервис на **Python 3.12** и **FastAPI**: экзамен в **Telegram** (текст и голос), распознавание речи (OpenAI Whisper), сегментация ответа по ключам вопроса, сравнение с эталонами и предварительная оценка. Основной режим оценки сейчас: **coverage / rubric** (покрытие смысловых элементов, `0…100`), резервный режим: **similarity** (`0…1`). Эталоны — из **Google Sheets** или fallback из `.env`; результаты при настроенных таблицах дописываются на лист результатов.

Дополнительно есть REST **`/exam/*`** для ручной проверки STT и оценки без Telegram.

Канонический порядок развития MVP: **[docs/01-architecture.md](docs/01-architecture.md)** (раздел «11. Порядок внедрения MVP»).
Канонические правила поведения бота по отношению к студенту: **[docs/ai_behavior_spec.md](docs/ai_behavior_spec.md)**.

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

Основной сценарий бота работает через **webhook**; отдельный polling-бот в репозитории не используется.

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
├── docs/                    # бриф, архитектура, модель поставки, поведение бота
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
| `TELEGRAM_WEBHOOK_SECRET` | Секрет, передаваемый в `setWebhook(secret_token=...)`. В проде — **обязателен** (см. `REQUIRE_WEBHOOK_SECRET`) |
| `REQUIRE_WEBHOOK_SECRET` | По умолчанию `true`: при заданном `TELEGRAM_BOT_TOKEN` без `TELEGRAM_WEBHOOK_SECRET` приложение не запустится. Для локальной разработки/тестов: `false` |
| `API_BEARER_TOKEN` | Bearer-токен для `/exam/evaluate-*`. Пустое значение → эндпоинты отключены (HTTP 503). Нужно для внешних тестов без Telegram |
| `MAX_UPDATE_BYTES` | Жёсткий лимит тела webhook Telegram (default `262144` = 256 КБ) |
| `MAX_AUDIO_BYTES` | Лимит входящего аудио для `/exam/evaluate-voice` (default `20971520` = 20 МБ) |
| `MAX_TEXT_CHARS` | Лимит текста в `/exam/evaluate-*` (default `32000`) |
| `MAX_STUDENT_ANSWER_FOR_LLM` | Текст ответа студента усекается до этого размера **перед** отправкой в LLM (default `8000`) |
| `ARQ_MAX_JOBS` | Параллелизм воркера arq (default `8`). Раньше было `1` — это искусственно сериализовывало студентов |
| `ARQ_JOB_TIMEOUT` | Таймаут обработки одного апдейта в воркере, сек (default `180`) |
| `OPENAI_API_KEY` | Whisper и при `MVP_SEGMENTATION_USE_LLM=true` — сегментация через LLM |
| `SPEECH_MODEL` | Обычно `whisper-1` |
| `GOOGLE_SHEETS_CREDENTIALS` или `GOOGLE_APPLICATION_CREDENTIALS` | Путь к JSON сервисного аккаунта Google |
| `GOOGLE_SHEET_ID` | ID одной таблицы, если не используете карту дисциплин |
| `DISCIPLINE_GOOGLE_SHEET_IDS_JSON` | JSON `slug → spreadsheet_id`; при **нескольких** slug в боте показывается выбор дисциплины |
| `DEFAULT_DISCIPLINE` | Slug по умолчанию, если карта задана, но `discipline_id` не выбран |
| `GOOGLE_SHEET_IDEAL_TAB` | Лист с эталонами (по умолчанию `ideal_answers`) |
| `GOOGLE_SHEET_RESULTS_TAB` | Лист для append результатов (по умолчанию `students_answers`) |
| `MVP_QUESTION_KEY`, `MVP_REFERENCE_ANSWER` | Один эталон без JSON |
| `MVP_REFERENCES_JSON` | Несколько ключей: `{"Q1":"эталон",...}` |
| `MVP_SEGMENTATION_USE_LLM` | `true` — при неудачной эвристической сегментации пробовать разбиение через OpenAI |
| `REDIS_URL` | Если задан (например `redis://localhost:6379/0`), вебхук Telegram **только ставит задачу** в очередь `arq` **и** сессии студентов переезжают в Redis (переживают рестарт). Если пусто — синхронная обработка, сессии в памяти процесса |
| `HOST`, `PORT`, `DEBUG` | Сервер uvicorn (см. `app/core/config.py`) |

### Безопасность и надёжность (коротко)

- `/exam/evaluate-*` закрыты Bearer-токеном (`API_BEARER_TOKEN`), иначе возвращают `503`.
- Webhook Telegram требует `TELEGRAM_WEBHOOK_SECRET` в `production` (`REQUIRE_WEBHOOK_SECRET=true`).
- Размеры запросов ограничены (`MAX_UPDATE_BYTES`, `MAX_AUDIO_BYTES`, `MAX_TEXT_CHARS`).
- Ответ студента усекается до `MAX_STUDENT_ANSWER_FOR_LLM` и оборачивается в `<reference>`/`<student_answer>` с экранированием угловых скобок — для защиты от prompt injection.
- Google Sheets: при создании нового листа добавляется колонка `Dedup Key` (идемпотентный append). Существующие листы из 11 колонок продолжают работать.
- Логи: токен бота и ключи OpenAI маскируются; ФИО и номер группы маскируются в production (при `DEBUG=false`).

---

## Telegram: вебхук

Пользовательское поведение бота (`/start`, `/new`, локализация ответов, отказ в подсказках, обязательный дисклеймер к оценке) описано в **`docs/ai_behavior_spec.md`**. Этот раздел ниже покрывает только техническую настройку webhook.

1. Приложение должно быть доступно по **HTTPS** (деплой или туннель: ngrok, cloudflare tunnel и т.д.).
2. Путь у приложения фиксированный: **`/telegram/webhook`** (см. `app/api/telegram_webhook.py`). Полный адрес для Telegram всегда: **`https://<публичный-домен>/telegram/webhook`**.

### Что значит «ваш-хост» и откуда взять адрес (ngrok)

В документации **`<ваш-хост>` — не переменная в коде и не отдельный файл**. Это **домен, который выдаёт ngrok** в окне терминала.

**Windows — важно:** команда `ngrok http 8000` часто шлёт трафик на `localhost`, который резолвится в **IPv6 (`::1`)**. На `::1:8000` может сидеть **другой** процесс, не ваш FastAPI — тогда Telegram получит **404** (`Wrong response from the webhook: 404 Not Found`), а бот молчит. Запускайте туннель **явно на IPv4:**

```bash
ngrok http http://127.0.0.1:8000
```

Проверка: в браузере откройте `http://127.0.0.1:8000/health` — должно быть `{"status":"ok"}`. Если `http://localhost:8000/health` даёт **другой** ответ — используйте только **127.0.0.1** для uvicorn/ngrok, пока не разберётесь с конфликтом порта.

1. В одном терминале крутится **`uvicorn`** на порту **8000** (и при необходимости Redis + `arq`).
2. Во втором терминале: **`ngrok http http://127.0.0.1:8000`** (не просто `8000`, если на Windows ловите 404 через туннель).
3. В таблице ngrok найдите строку **Forwarding**. Слева будет что-то вроде:
   - `https://untamed-bearlike-xxxx.ngrok-free.app` (у вас будет **свой** поддомен, каждый запуск на бесплатном плане может отличаться).

**Этот `https://....ngrok-free.app` и есть «хост»** — его **целиком копируете** (со схемой `https://`, без слэша в конце). Дальше **дописываете путь приложения**:

```text
https://untamed-bearlike-xxxx.ngrok-free.app/telegram/webhook
```

Подставьте **свой** URL из ngrok вместо примера. Строки вроде **`example.com`** в старых примерах — это **иллюстрация**, не реальный адрес.

**Отдельной команды «webhook» в терминале нет.** Третий терминал не обязателен: вебхук настраивается **одним** запросом к API Telegram (ниже) или через браузер. Дополнительно можно открыть в браузере веб-интерфейс ngrok: `http://127.0.0.1:4040` — там видны входящие запросы к туннелю.

### Секрет вебхука и ошибка 401

- Если в `.env` задан **`TELEGRAM_WEBHOOK_SECRET`**, то при вызове **`setWebhook`** нужно передать **тот же** секрет параметром **`secret_token`**, иначе Telegram не пришлёт нужный заголовок → ответ API **`401 Invalid webhook secret`**.
- Если секрет в `.env` **пустой**, проверка заголовка **не выполняется** — тогда `setWebhook` можно вызывать **без** `secret_token` (удобно для первого теста).

### Вызов setWebhook

Подставьте **токен бота** и **полный HTTPS URL** вебхука (из ngrok + `/telegram/webhook`). Без секрета:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://ВАШ-ДОМЕН-ИЗ-NGROK/telegram/webhook
```

С секретом (строка `secret` должна совпадать с `TELEGRAM_WEBHOOK_SECRET` в `.env`):

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://ВАШ-ДОМЕН-ИЗ-NGROK/telegram/webhook&secret_token=ВАШ_СЕКРЕТ
```

Проверка: `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo`

Повторно выставить вебхук после смены URL ngrok: из корня репозитория **`python scripts/set_webhook_via_ngrok.py`** (нужны запущенные ngrok и запись в `.env`).

Telegram шлёт `POST` с заголовком `X-Telegram-Bot-Api-Secret-Token`, если при `setWebhook` был задан `secret_token`. Локальный `http://127.0.0.1` без туннеля к Telegram **не подключить** — это ограничение Bot API.

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
     -H "Authorization: Bearer $API_BEARER_TOKEN" \
     -F "student_answer=Ответ студента" \
     -F "reference=Эталонный ответ"
```

Без заголовка `Authorization` при заданном `API_BEARER_TOKEN` сервер вернёт `401`, при пустом `API_BEARER_TOKEN` — `503`.

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

## Документы-источники

- `docs/ai_behavior_spec.md` — канонические правила поведения Telegram-бота.
- `docs/00-project_brief.md` — бизнес-цели и проектные ограничения.
- `docs/01-architecture.md` — архитектурные инварианты и порядок внедрения MVP.
- `docs/02-delivery-model.md` — модель ведения проекта по этапам.

## Расширение логики

Точки замены: **`speech_service.transcribe`**, **`evaluation_service.evaluate`**, правила FSM — **`fsm_service`**. Подробные инварианты, сценарий и пользовательские правила — в **`docs/`**.
