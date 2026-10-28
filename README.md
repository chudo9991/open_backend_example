# open_backend_example

Пример простого backend-приложения на [FastAPI](https://fastapi.tiangolo.com/),
которое реализует модель и структуру базы данных согласно изображению с таблицей
`Users`. Приложение предоставляет CRUD-интерфейс для управления сотрудниками.

## Структура данных

В таблице `users` хранятся следующие поля:

| Поле                | Тип                    | Описание                         |
|---------------------|------------------------|----------------------------------|
| `id`                | UUID (строка)          | Уникальный идентификатор записи |
| `created_at`        | datetime (timezone)    | Дата создания записи             |
| `name`              | varchar(100)           | Имя сотрудника                   |
| `surname`           | varchar(100)           | Фамилия сотрудника               |
| `email`             | varchar(255)           | Email сотрудника                 |
| `phone`             | varchar(20)            | Номер телефона                   |
| `city`              | varchar(100)           | Город проживания                 |
| `working_format`    | enum(remote/office/…)  | Формат работы                    |

Enum `working_format_enum` содержит значения `remote`, `office`, `hybrid`.

## Запуск через Docker

1. Создайте файл `.env` с доступами к Yandex AI Studio:

   ```bash
   YANDEX_API_KEY=<API-ключ сервисного аккаунта>
   YANDEX_FOLDER_ID=<идентификатор каталога>
   YANDEX_DEFAULT_MODEL=yandexgpt-lite
   ```

2. Запустите приложение с помощью Docker Compose:

   ```bash
   docker-compose up -d
   ```

3. Приложение будет доступно по адресу `http://localhost:8001`

4. Для остановки:

   ```bash
   docker-compose down
   ```

База данных SQLite создается внутри контейнера. Данные будут потеряны при удалении контейнера.

### Заполнение тестовыми данными

Для заполнения базы данных 40 фейковыми записями пользователей:

```bash
docker cp seed_db.py open_backend_example-app-1:/app/
docker compose exec app python seed_db.py
```

## Локальный запуск без Docker

1. Создайте и активируйте виртуальное окружение Python 3.10+.
2. Установите зависимости:

   ```bash
   pip install -r requirements.txt
   ```

3. Запустите приложение:

   ```bash
   uvicorn app.main:app --reload
   ```

По умолчанию используется SQLite-файл `app.db` в корне проекта. Для работы с
PostgreSQL установите переменную окружения `DATABASE_URL`, например:

```bash
export DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/mydb
```

При старте приложения автоматически создаются таблицы, соответствующие модели.

## Примеры запросов

После запуска FastAPI документация доступна по адресу `http://127.0.0.1:8000/docs` (или `http://127.0.0.1:8001/docs` при запуске через Docker).

### CRUD операции с пользователями

- `POST /users` — создание пользователя;
- `GET /users` — список пользователей;
- `GET /users/{id}` — получение пользователя по идентификатору;
- `PATCH /users/{id}` — обновление данных;
- `DELETE /users/{id}` — удаление.

Каждый ответ соответствует Pydantic-схеме `UserRead` и содержит актуальную
информацию по модели.

### AI эндпоинты

Приложение интегрировано с [Yandex AI Studio](https://yandex.cloud/ru/docs/ai-studio/)
через OpenAI-совместимый API. Список моделей берётся динамически из каталога:

- `POST /ai/generate` — генерация текста по промпту;
- `POST /ai/chat` — чат с AI моделью;
- `GET /ai/models` — список доступных AI моделей;
- `GET /ai/queue/status` — статус очереди AI запросов.

#### Настройка

Задайте переменные окружения (см. `.env`):

```bash
export YANDEX_API_KEY=<API-ключ сервисного аккаунта>
export YANDEX_FOLDER_ID=<идентификатор каталога>
export YANDEX_DEFAULT_MODEL=yandexgpt-lite   # опционально
```

`model` можно указывать коротким именем (`yandexgpt-lite`) или полным URI
(`gpt://<folder-id>/yandexgpt-lite/latest`). Пустое значение — модель по
умолчанию.

#### Примеры AI запросов

```bash
# Генерация текста
curl -X POST "http://localhost:8001/ai/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Привет! Как дела?", "model": "yandexgpt-lite"}'

# Чат с AI
curl -X POST "http://localhost:8001/ai/chat" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Расскажи историю"}], "model": "yandexgpt-lite"}'

# Список моделей
curl -X GET "http://localhost:8001/ai/models"

# Статус очереди
curl -X GET "http://localhost:8001/ai/queue/status"
```

Доступные модели определяются каталогом: YandexGPT (`yandexgpt`,
`yandexgpt-lite`, `yandexgpt-5-pro` и др.), а также открытые модели
(`deepseek-v4-flash`, `qwen3.6-35b-a3b`, `gpt-oss-120b`, `aliceai-llm` и др.).

## Деплой на VPS

Продакшн-сервер: `45.144.30.194` (`ssh root@45.144.30.194`).
Каталог проекта на сервере: `/opt/open_backend_example`.

1. Скопировать файлы проекта на сервер (из корня репозитория):

   ```bash
   rsync -az \
     --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' --exclude 'app.db' \
     ./ root@45.144.30.194:/opt/open_backend_example/
   ```

2. Пересобрать и перезапустить контейнер:

   ```bash
   ssh root@45.144.30.194 'cd /opt/open_backend_example && docker compose down --remove-orphans && docker compose up -d --build'
   ```

Приложение доступно по адресу `http://45.144.30.194:8001`.
