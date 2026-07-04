# Персональный помощник «от текста до действия»

Сервис превращает произвольный входящий текст в структурированные **задачи** и **заметки** с помощью ИИ-структурирования (или локальных эвристик без API-ключа), сохраняет их в SQLite и показывает в веб-панели. Неоднозначные случаи помечаются флагом **«требует проверки»**, причина записывается в журнал аудита.

## Возможности

- Создание задачи или заметки из текста (`POST /capture`)
- ИИ-структурирование (`POST /ai/structure`) — OpenAI или fallback-эвристики
- Ручная проверка неоднозначных случаев (`needs_review`)
- Список задач с фильтрами (`GET /tasks`)
- Отметка задач выполненными (`POST /tasks/{id}/done`)
- Входящие: задачи + заметки (`GET /inbox`)
- Журнал аудита всех операций (`GET /audit`)
- Экспорт журнала и витрины в JSON/CSV (`GET /audit/export`, `GET /export/inbox`)
- Нормализованные теги без дублей
- Пользователи в отдельной таблице
- Загрузка тестовых данных (`python -m app.seed`)

## Стек

- **Backend:** Python 3.11+, FastAPI
- **БД:** SQLite (`data/app.db`)
- **ORM:** SQLAlchemy 2.x
- **Frontend:** HTML + CSS + Vanilla JS

## Установка

### Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Скопируйте `.env.example` в `.env` и при необходимости укажите ключ [ProxyAPI](https://proxyapi.ru/docs/openai-compatible-api).  
Без ключа работает fallback на локальных эвристиках — проект можно показать без API.

Подробнее о переменных — в разделе [Переменные окружения](#переменные-окружения).

## Переменные окружения

| Переменная | Обязательна | По умолчанию | Описание |
|------------|:-----------:|--------------|----------|
| `OPENAI_API_KEY` | нет | пусто | Ключ ProxyAPI / OpenAI-совместимого API. Без ключа — локальные эвристики |
| `OPENAI_BASE_URL` | нет | `https://openai.api.proxyapi.ru/v1` | Базовый URL API |
| `OPENAI_MODEL` | нет | `gpt-4o-mini` | Модель для структурирования текста |

Пример `.env`:

```env
OPENAI_API_KEY=your_proxyapi_api_key_here
OPENAI_BASE_URL=https://openai.api.proxyapi.ru/v1
OPENAI_MODEL=gpt-4o-mini
```

Файл-образец: [`.env.example`](.env.example) (без реальных секретов).

База данных всегда создаётся в **`data/app.db`** (не настраивается через env).

## Запуск

```bash
uvicorn app.main:app --reload
```

Откройте в браузере: **http://127.0.0.1:8000**

## Запуск в Docker

Требуется [Docker](https://docs.docker.com/get-docker/) и Docker Compose.

```bash
# скопируйте ключ (опционально — без него работает fallback)
cp .env.example .env

# сборка и запуск
docker compose up --build -d

# логи
docker compose logs -f app
```

Приложение: **http://127.0.0.1:8000**

База SQLite сохраняется в каталоге `./data` на хосте (volume).

Загрузка тестовых данных в контейнере:

```bash
docker compose exec app python -m app.seed
```

Остановка:

```bash
docker compose down
```

Пересборка после изменений кода:

```bash
docker compose up --build -d
```

## Загрузка тестовых данных

```bash
python -m app.seed
```

Скрипт читает `tests_data/inputs.jsonl` (**11 кейсов**) и сверяет результат с `tests_data/specs.jsonl`.  
Среди тестов **2 кейса** (#1, #4) должны давать `needs_review=true` (слишком общий / неоднозначный ввод).

### Воспроизведение ручной проверки

**Автоматически (seed):**

```bash
# чистая база
rm -f data/app.db          # Linux/macOS
# del data\app.db          # Windows

python -m app.seed
```

В выводе seed кейсы **#1** и **#4** должны содержать `needs_review` у элементов.

**Вручную в UI или curl:**

1. Отправьте текст кейса #1: `надо что-то сделать с жизнью`
2. Откройте «Задачи → Требует проверки» — элемент с меткой
3. Вкладка «Журнал» или `GET /audit` — в поле `error` будет `TOO_GENERAL` или `LOW_CONFIDENCE`

Подробнее: [tests_data/README.md](tests_data/README.md).

Для чистого прогона удалите `data/app.db` перед загрузкой.

## Память пользователя

Таблица `memory_facts` хранит **устойчивые факты** о предпочтениях и контексте пользователя — не разовые задачи и не эмоции.

### Что может сохраняться

- Предпочтения: «короткие названия задач», «тег проект для учёбы»
- Контекст проекта, привычки, часто используемые теги
- Факты с `confidence=high` сохраняются автоматически после capture
- Неуверенные факты — с флагом `needs_review=true`

### Что не сохраняется

- Разовые задачи («купить кофе», «завтра созвон»)
- Эмоции и filler-текст
- Чувствительные данные (медицина, политика, паспорт и т.п.)

### В интерфейсе

1. Откройте вкладку **«Память»**
2. Добавьте факт вручную (key, value, category) или дождитесь автоматического извлечения после capture
3. Редактируйте, **отключайте** (`is_active=false`) или удаляйте факты
4. Факты с `needs_review=true` не попадают в ИИ-контекст, пока вы их не подтвердите

### Использование в ИИ

Перед структурированием текста система собирает блок «Контекст пользователя» из активных подтверждённых фактов и передаёт его модели — для тегов, названий и общего контекста, без выдумывания новых задач.

### API памяти

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/memory?user_id=...` | Список фактов |
| POST | `/memory` | Добавить факт вручную |
| PATCH | `/memory/{id}` | Изменить факт |
| POST | `/memory/{id}/deactivate` | Отключить факт |
| DELETE | `/memory/{id}?user_id=...` | Удалить факт |

Ответ `POST /capture` включает блок `memory: { created, needs_review, skipped }`.

### Демо-сценарий памяти

1. Вкладка **«Память»** → добавьте: `preferred_task_style` / `короткие названия задач` / `preference`
2. Создайте задачу: «Срочно оплатить хостинг»
3. Вернитесь в **«Память»** — факт на месте
4. Нажмите **«Отключить»** — `is_active=false`, факт не используется в ИИ

---

## API

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/capture` | Текст → задача/заметка в БД |
| GET | `/tasks?user_id=...` | Список задач |
| POST | `/tasks/{id}/done` | Отметить выполненной |
| POST | `/ai/structure` | Только ИИ-структурирование |
| GET | `/inbox?user_id=...` | Последние 50 элементов |
| GET | `/items/{type}/{id}?user_id=...` | Карточка + аудит |
| PATCH | `/tasks/{id}` | Ручное исправление задачи |
| PATCH | `/notes/{id}` | Ручное исправление заметки |
| GET | `/audit?user_id=...` | Журнал аудита |
| GET | `/audit/export?user_id=...&format=json\|csv` | Скачать журнал |
| GET | `/export/inbox?user_id=...&format=json\|csv` | Экспорт задач и заметок |
| GET | `/tags?user_id=...` | Список тегов |

### Примеры запросов (curl)

Создать элемент из текста:

```bash
curl -s -X POST http://127.0.0.1:8000/capture \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"надо что-то сделать с жизнью\",\"user_id\":\"u_1\"}"
```

Список задач, требующих проверки:

```bash
curl -s "http://127.0.0.1:8000/tasks?user_id=u_1&needs_review=true"
```

Журнал аудита (только записи с причиной проверки / ошибкой):

```bash
curl -s "http://127.0.0.1:8000/audit?user_id=u_1&only_errors=true&actions_only=false"
```

Скачать журнал в JSON:

```bash
curl -s -o audit_u_1.json \
  "http://127.0.0.1:8000/audit/export?user_id=u_1&format=json&limit=500"
```

Экспорт витрины (задачи + заметки) в CSV:

```bash
curl -s -o inbox_u_1.csv \
  "http://127.0.0.1:8000/export/inbox?user_id=u_1&format=csv&limit=500"
```

### POST /capture

```json
{"text": "Срочно оплатить хостинг", "user_id": "u_1"}
```

Ответ (сокращённо):

```json
{
  "status": "ok",
  "items": [{"item_id": "task_...", "item_type": "task", "title": "...", "needs_review": false}],
  "count": 1,
  "memory": {"created": 0, "needs_review": 0, "skipped": 0}
}
```

## База данных и аудит

| Что | Где |
|-----|-----|
| Файл SQLite | `data/app.db` (создаётся при первом запуске) |
| Задачи | таблица `tasks` |
| Заметки | таблица `notes` |
| Память | таблица `memory_facts` |
| Журнал | таблица `audit_runs` |

### Просмотр через UI

- **Задачи / Заметки** — витрина данных
- **Журнал** — все ключевые действия; фильтр «Ошибки / проверка» показывает `needs_review` и коды вроде `TOO_GENERAL`
- Кнопки **«Скачать JSON / CSV»** на вкладке «Журнал»
- Кнопки **«Экспорт JSON / CSV»** на вкладке «Задачи» (все задачи и заметки пользователя)

### Просмотр через sqlite3

```bash
sqlite3 data/app.db

-- последние записи аудита
SELECT action, error, status, created_at FROM audit_runs ORDER BY created_at DESC LIMIT 10;

-- элементы на ручной проверке
SELECT id, title, needs_review FROM tasks WHERE needs_review = 1;
SELECT id, title, needs_review FROM notes WHERE needs_review = 1;

-- факты памяти
SELECT key, value, needs_review, is_active FROM memory_facts;
```

В Docker (через Python, CLI sqlite3 в образе может отсутствовать):

```bash
docker compose exec app python -c "import sqlite3; c=sqlite3.connect('/app/data/app.db'); print(*c.execute('SELECT action, error, created_at FROM audit_runs ORDER BY created_at DESC LIMIT 5').fetchall(), sep='\n')"
```

## Ручная проверка

Элемент получает `needs_review=true`, причина пишется в `audit_runs.error`:

| Код | Когда |
|-----|-------|
| `LOW_CONFIDENCE` | confidence = low от ИИ |
| `INVALID_JSON` | JSON от ИИ не распарсился |
| `SCHEMA_MISMATCH` | JSON не прошёл Pydantic-схему |
| `TOO_GENERAL` | Слишком общий ввод («сделай важное») |
| `MULTIPLE_INTENTS` | Несколько намерений в одном тексте |

## Мини-экономика

**До внедрения:**
- 1 ручная операция = 4 минуты
- 100 операций = 400 минут ≈ **6,7 часа**

**После внедрения:**
- 1 операция = 1,5 минуты (авто + быстрая проверка)
- 100 операций = 150 минут ≈ **2,5 часа**

**Экономия:** 250 минут на 100 операций ≈ **4,2 часа**.

## Демонстрационный сценарий

1. Запустите сервер: `uvicorn app.main:app --reload`
2. Откройте http://127.0.0.1:8000
3. Введите: `Срочно: оплатить хостинг, иначе сайт ляжет.`
4. Нажмите «Создать элемент» — должна появиться задача с высоким приоритетом
5. Вкладка «Задачи» → «Выполнить»
6. Введите: `Сделай важное, а остальное потом. Разберись.`
7. Убедитесь, что элемент помечен «требует проверки»
8. Вкладка «Журнал» — причина `TOO_GENERAL` в поле error
9. Кнопки «Скачать JSON» / «Скачать CSV» на вкладке «Журнал» — экспорт аудита
10. На вкладке «Задачи» — «Экспорт JSON» / «Экспорт CSV» для выгрузки витрины

## Структура проекта

```
app/
  main.py           # FastAPI, endpoints
  database.py       # SQLite + PRAGMA foreign_keys
  models.py         # SQLAlchemy модели
  schemas.py        # Pydantic схемы
  crud.py           # capture_text и CRUD
  ai_service.py     # structure_text (OpenAI / fallback)
  memory_service.py  # память пользователя
  tag_service.py    # normalize_tag, get_or_create_tag
  audit_service.py  # create_audit_run
  seed.py           # загрузка тестовых данных
  static/           # CSS, JS
  templates/        # index.html
tests_data/
  inputs.jsonl       # 11 входных текстов
  specs.jsonl        # ожидания по каждому кейсу
  README.md
data/
  app.db            # создаётся автоматически
app/export_service.py  # экспорт JSON/CSV
Dockerfile
docker-compose.yml
.dockerignore
```

## Лицензия

Учебный MVP-проект.
