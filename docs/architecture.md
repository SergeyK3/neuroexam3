# Архитектура системы: нейроэкзаменатор

## 1. Общая архитектура

Система построена по многоуровневой асинхронной архитектуре:
Telegram Bot
↓
FastAPI Backend (Webhook)
↓
Application Layer (FSM, Session Manager)
↓
Domain Layer (Evaluation, Speech)
↓
Infrastructure Layer (DB, Google Sheets, APIs)
↓
External Services (OpenAI, Whisper)


---

## 2. Основные компоненты

### 2.1 Telegram Bot (Transport Layer)

- Принимает:
  - команды (`/start`)
  - текстовые сообщения
  - голосовые сообщения
- Передает данные в FastAPI через webhook

---

### 2.2 FastAPI Backend

- Центральная точка входа
- Обрабатывает webhook
- Маршрутизирует запросы
- Управляет сессиями пользователей

---

### 2.3 FSM (Finite State Machine)

Управляет сценарием экзамена:
START → LANGUAGE → REGISTRATION → ANSWERING → FINISH


Отвечает за:
- переходы между состояниями
- контроль времени экзамена
- завершение сессии

---

### 2.4 Session Manager
Управляет пользовательскими сессиями:
session = {
user_id,
discipline_id,
session_id,
state,
start_time,
language
}


Обеспечивает:
- изоляцию пользователей
- поддержку параллельных сессий
- контроль таймаута

---

### 2.5 Evaluation Service

Функции:
- сопоставление ответа с эталоном
- расчет оценки
- генерация объяснения

Использует:
- правила полноты ответа
- sentence-transformers
- cosine similarity
- LLM (при необходимости)

---

### 2.6 Speech Service

Функции:
- преобразование аудио в текст (STT)
- нормализация текста

Использует:
- Whisper API

---

### 2.7 Persistence Layer

#### PostgreSQL (основное хранилище)
Хранит:
- пользователей
- сессии
- ответы
- оценки
- логи

#### Google Sheets (операционный слой)
Используется для:
- просмотра кафедрой
- редактирования эталонов
- выгрузки результатов

---

### 2.8 Background Workers

Используются для:
- транскрибации
- оценки
- повторных попыток записи

Технологии:
- Redis
- Celery или RQ

---

## 3. Структура backend
app/
├── main.py
├── api/
│ └── telegram_webhook.py
├── core/
│ ├── config.py
│ ├── logger.py
├── services/
│ ├── fsm_service.py
│ ├── session_service.py
│ ├── evaluation_service.py
│ ├── speech_service.py
├── repositories/
│ ├── user_repo.py
│ ├── session_repo.py
│ ├── attempt_repo.py
├── integrations/
│ ├── openai_client.py
│ ├── sheets_client.py
│ ├── telegram_client.py
├── models/
│ ├── user.py
│ ├── session.py
│ ├── attempt.py
│ ├── discipline.py
├── workers/
│ ├── tasks.py


---

## 4. Поток обработки запроса

1. Пользователь отправляет сообщение в Telegram
2. Telegram вызывает webhook FastAPI
3. Backend:
   - определяет пользователя и дисциплину
   - извлекает сессию
4. FSM определяет состояние:
   - если голос → Speech Service
   - если текст → Evaluation
5. Evaluation Service:
   - сравнивает с эталоном
   - рассчитывает оценку
6. Результат:
   - сохраняется в PostgreSQL
   - синхронизируется в Google Sheets
7. Ответ возвращается пользователю

---

## 5. Модель данных

### Discipline
id
name
google_sheet_id
monetized


---

### User
id
telegram_id
full_name


---

### Session
id
user_id
discipline_id
state
start_time
language


---

### Attempt
id
session_id
question_key
student_answer
transcribed_answer
score
explanation
reference_version
timestamp


---

### Usage (метрики токенов)

id
discipline_id
tokens_used
type
timestamp


---

## 6. Multi-discipline модель

- 1 дисциплина = 1 Google Sheet
- 3 листа:
  - reference_answers
  - student_answers
  - metadata

Данные НЕ удаляются

Используются поля:
- group_id
- session_id
- attempt_id

---

## 7. Multi-group модель

- 1 дисциплина → несколько групп
- ~12 человек в группе
- 3–6 активных одновременно

Система должна:
- поддерживать параллельную работу
- изолировать пользователей
- группировать результаты

---

## 8. Стратегия бота

- Один бот обслуживает:
  - несколько дисциплин
  - несколько групп

Маршрутизация:

user → discipline → group → session


Отдельный бот на группу НЕ требуется

---

## 9. Нагрузочная модель

- 3–5 дисциплин
- 3–6 пользователей на дисциплину
- пик: 20–25 пользователей

Требования:
- асинхронная обработка
- неблокирующий код
- использование очередей

---

## 10. Критические требования

### 10.1 Надежность
- отсутствие потери данных
- retry при ошибках
- идемпотентность

### 10.2 Обработка ошибок
- дубли webhook
- сбои API
- задержки STT

### 10.3 Аудит
- хранение истории
- трассировка действий
- версия эталонов

---

## 11. Ограничения MVP

Не реализуются на первом этапе:
- UI кабинет
- биллинг
- сложная аналитика
- multi-bot система

---

## 12. Итог

Система должна быть:
- асинхронной
- масштабируемой
- устойчивой к ошибкам
- пригодной для multi-discipline и multi-group работы