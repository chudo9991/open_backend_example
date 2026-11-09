# FastAPI application exposing CRUD operations for users.
from __future__ import annotations

import asyncio
from typing import List
from uuid import UUID

from fastapi import Body, Depends, FastAPI, HTTPException, Path, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas
from .ai_service import (
    DEFAULT_MODEL,
    ai_queue,
    list_yandex_models,
    process_ai_requests,
    processing_tasks,
    queue_ai_request,
)
from .database import Base, engine, get_db, init_db
from .image_service import (
    COMETAPI_DEFAULT_IMAGE_MODEL,
    COMETAPI_IMAGE_MAX_PRICE,
    ImageModelNotFoundError,
    ImageNotConfiguredError,
    ImageQueueFullError,
    ImageTaskExpiredError,
    ImageTaskStatus,
    cleanup_expired_images,
    enqueue_image_task,
    get_image_models,
    get_image_queue_stats,
    get_image_task,
    process_image_requests,
)

# Ensure the database tables exist when the application starts.
Base.metadata.create_all(bind=engine)

DESCRIPTION = """
## Что это за сервис?

Это учебный backend-сервис на **FastAPI**, созданный для занятий в Кванториуме.
Он умеет четыре вещи:

- **Хранить сотрудников** (пользователей): создавать, показывать, изменять и
  удалять записи.
- **Работать как простой чат**: отправлять и читать сообщения.
- **Отвечать с помощью искусственного интеллекта** через модели
  Yandex AI Studio.
- **Генерировать изображения** через CometAPI и Yandex AI Studio. Задачи
  выполняются в отдельной очереди, а готовые файлы хранятся 15 минут.

Эту документацию можно использовать как тренажёр: нажмите на нужный метод,
раскройте кнопку **Try it out**, заполните поля и нажмите **Execute** — запрос
уйдёт на сервер, а ниже появится ответ.

## Как читать адреса (эндпоинты)

| Метод | Адрес | Что делает |
|-------|-------|------------|
| `GET` | `/` | Проверка: сервер жив? |
| `GET` | `/users` | Показать всех сотрудников |
| `POST` | `/users` | Добавить сотрудника |
| `GET` | `/users/{user_id}` | Показать одного сотрудника |
| `PATCH` | `/users/{user_id}` | Изменить данные сотрудника |
| `DELETE` | `/users/{user_id}` | Удалить сотрудника |
| `GET` | `/messages` | Показать все сообщения чата |
| `POST` | `/messages` | Отправить сообщение |
| `DELETE` | `/messages/{message_id}` | Удалить своё сообщение |
| `POST` | `/ai/generate` | Попросить ИИ написать текст |
| `POST` | `/ai/chat` | Поговорить с ИИ как в чате |
| `GET` | `/ai/models` | Список текстовых моделей Yandex AI Studio |
| `POST` | `/ai/images` | Поставить генерацию изображения в очередь |
| `GET` | `/ai/images/{task_id}` | Получить статус или готовое изображение |
| `GET` | `/ai/image-models` | Модели изображений CometAPI и YandexART |
| `GET` | `/ai/queue/status` | Состояние очередей ИИ |

## Простой пример

Попросить ИИ написать поздравление:

```json
POST /ai/generate
{
  "prompt": "Придумай короткое поздравление с днём рождения.",
  "model": "yandexgpt-lite"
}
```

## Генерация изображений

Сначала получите список моделей:

```http
GET /ai/image-models
```

Ответ содержит два отдельных списка:

- `cometapi_models` — модели CometAPI с минимальной стоимостью одного
  изображения не выше лимита, настроенного на сервере;
- `yandex_models` — модели YandexART, доступные через Yandex AI Studio.

Затем поставьте задачу в очередь:

```json
POST /ai/images
{
  "prompt": "Рыжий кот в стиле аниме, мягкие пастельные тона",
  "model": "gemini-3.1-flash-image-preview",
  "aspect_ratio": "1:1"
}
```

Сервер вернёт `202 Accepted` и UUID задачи. Пока задача выполняется,
`GET /ai/images/{task_id}` возвращает `202` и текущий статус. Когда изображение
готово, тот же адрес возвращает сам файл с правильным `Content-Type`.
Готовые изображения хранятся 15 минут, затем удаляются.

## Полезно знать

- **UUID** — длинный идентификатор вида `3fa85f64-5717-4562-b3fc-2c963f66afa6`.
  Он нужен, чтобы точно найти конкретную запись.
- Все данные приходят и отправляются в формате **JSON**, кроме готового
  изображения: оно возвращается бинарным файлом.
- Если запись не найдена, сервер вернёт код **404** («не найдено»).
- Если пытаетесь удалить чужое сообщение — код **403** («запрещено»).
- Модель можно не указывать: тогда используется модель по умолчанию, её видно
  в ответе `GET /ai/models` в поле `default`.
"""

TAGS_METADATA = [
    {
        "name": "Служебное",
        "description": "Короткие проверки. Помогают убедиться, что сервер работает.",
    },
    {
        "name": "Пользователи",
        "description": (
            "Сотрудники: создание, список, просмотр, изменение и удаление. "
            "Классический набор операций CRUD."
        ),
    },
    {
        "name": "Чат",
        "description": (
            "Простые сообщения чата: отправить, показать все и удалить своё. "
            "Пары «пользователь → ИИ» здесь нет, это обычная лента сообщений."
        ),
    },
    {
        "name": "Искусственный интеллект",
        "description": (
            "Работа с моделями Yandex AI Studio и CometAPI: генерация текста, "
            "чат, генерация изображений, каталог моделей и состояние очередей. "
            "Изображения создаются в отдельной очереди и хранятся 15 минут."
        ),
    },
]

app = FastAPI(
    title="Учебный backend-сервис (Open Backend Example)",
    version="0.1.0",
    description=DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    contact={"name": "Кванториум, 2025"},
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.on_event("startup")
async def on_startup() -> None:
    # Initialize the database and start AI worker when the application starts.
    init_db()
    # Launch background workers for text and image queues.
    asyncio.create_task(process_ai_requests())
    asyncio.create_task(process_image_requests())
    asyncio.create_task(cleanup_expired_images())


# Original JSON API root
@app.get(
    "/",
    tags=["Служебное"],
    summary="Проверка работы сервера",
    description=(
        "Возвращает короткое приветствие. Удобно использовать, чтобы понять, "
        "что сервер запущен и отвечает на запросы."
    ),
    response_description="Приветственное сообщение сервера.",
    response_model=schemas.RootResponse,
)
def root() -> dict:
    # Return a greeting message.
    return {"message": "Hello Stranger!"}


# --- Пользователи (CRUD) -------------------------------------------------
@app.get(
    "/users",
    tags=["Пользователи"],
    summary="Показать всех сотрудников",
    description=(
        "Возвращает список всех сотрудников. Новые записи идут первыми "
        "(сортировка по дате создания в обратном порядке)."
    ),
    response_description="Список сотрудников.",
    response_model=List[schemas.UserRead],
)
def list_users(db: Session = Depends(get_db)) -> List[models.User]:
    # Return all users in the database.
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@app.post(
    "/users",
    tags=["Пользователи"],
    summary="Добавить сотрудника",
    description=(
        "Создаёт нового сотрудника. Обязательны только поля `name` и `surname`, "
        "остальные можно не присылать."
    ),
    response_description="Созданный сотрудник с присвоенным идентификатором.",
    response_model=schemas.UserRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {
            "model": schemas.ErrorResponse,
            "description": "Данные не подходят (например, нарушено ограничение базы).",
        }
    },
)
def create_user(
    user: schemas.UserCreate = Body(
        ...,
        description="Данные нового сотрудника.",
        example={
            "name": "Иван",
            "surname": "Иванов",
            "email": "ivan@example.com",
            "phone": "+7 900 123-45-67",
            "city": "Москва",
            "working_format": "remote",
        },
    ),
    db: Session = Depends(get_db),
) -> models.User:
    # Create a new user entry.
    db_user = models.User(**user.dict())
    db.add(db_user)
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - runtime safeguard
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(db_user)
    return db_user


@app.get(
    "/users/{user_id}",
    tags=["Пользователи"],
    summary="Показать одного сотрудника",
    description="Возвращает сотрудника по его идентификатору (`UUID`).",
    response_description="Найденный сотрудник.",
    response_model=schemas.UserRead,
    responses={
        404: {"model": schemas.ErrorResponse, "description": "Сотрудник не найден."}
    },
)
def get_user(
    user_id: UUID = Path(
        ...,
        description="Идентификатор сотрудника (UUID).",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    ),
    db: Session = Depends(get_db),
) -> models.User:
    # Retrieve a single user by ID.
    db_user = db.query(models.User).filter(models.User.id == str(user_id)).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user


@app.patch(
    "/users/{user_id}",
    tags=["Пользователи"],
    summary="Изменить данные сотрудника",
    description=(
        "Частично обновляет сотрудника: присылайте только те поля, которые "
        "хотите изменить. Остальные значения останутся прежними."
    ),
    response_description="Обновлённый сотрудник.",
    response_model=schemas.UserRead,
    responses={
        404: {"model": schemas.ErrorResponse, "description": "Сотрудник не найден."}
    },
)
def update_user(
    user_id: UUID = Path(
        ...,
        description="Идентификатор сотрудника (UUID).",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    ),
    user_update: schemas.UserUpdate = Body(
        ...,
        description="Поля, которые нужно изменить.",
        example={"city": "Санкт-Петербург", "working_format": "office"},
    ),
    db: Session = Depends(get_db),
) -> models.User:
    # Partially update a user's data.
    db_user = db.query(models.User).filter(models.User.id == str(user_id)).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_user, field, value)

    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.delete(
    "/users/{user_id}",
    tags=["Пользователи"],
    summary="Удалить сотрудника",
    description="Удаляет сотрудника по идентификатору. В ответ ничего не возвращается.",
    response_description="Пустой ответ, код 204 (успешно, без тела).",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        404: {"model": schemas.ErrorResponse, "description": "Сотрудник не найден."}
    },
)
def delete_user(
    user_id: UUID = Path(
        ...,
        description="Идентификатор сотрудника (UUID).",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    ),
    db: Session = Depends(get_db),
) -> None:
    # Delete a user from the database.
    db_user = db.query(models.User).filter(models.User.id == str(user_id)).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(db_user)
    db.commit()


# --- Чат -----------------------------------------------------------------
@app.get(
    "/messages",
    tags=["Чат"],
    summary="Показать все сообщения чата",
    description=(
        "Возвращает все сообщения чата. Сначала идут самые старые, "
        "затем — новые."
    ),
    response_description="Список сообщений.",
    response_model=List[schemas.MessageRead],
)
def list_messages(db: Session = Depends(get_db)) -> List[models.Message]:
    # Return all chat messages oldest first.
    return db.query(models.Message).order_by(models.Message.created_at).all()


@app.post(
    "/messages",
    tags=["Чат"],
    summary="Отправить сообщение",
    description="Добавляет новое сообщение в чат. Нужны имя автора и текст.",
    response_description="Сохранённое сообщение с идентификатором и датой.",
    response_model=schemas.MessageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_message(
    message: schemas.MessageCreate = Body(
        ...,
        description="Новое сообщение.",
        example={"author": "Иван", "text": "Привет, как дела?"},
    ),
    db: Session = Depends(get_db),
) -> models.Message:
    # Store a new chat message.
    db_message = models.Message(**message.dict())
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message


@app.delete(
    "/messages/{message_id}",
    tags=["Чат"],
    summary="Удалить своё сообщение",
    description=(
        "Удаляет сообщение чата. Удалить можно только своё сообщение: имя автора "
        "передаётся в параметре `author` и должно совпадать с автором сообщения."
    ),
    response_description="Пустой ответ, код 204 (успешно, без тела).",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={
        403: {
            "model": schemas.ErrorResponse,
            "description": "Попытка удалить чужое сообщение.",
        },
        404: {"model": schemas.ErrorResponse, "description": "Сообщение не найдено."},
    },
)
def delete_message(
    message_id: UUID = Path(
        ...,
        description="Идентификатор сообщения (UUID).",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    ),
    author: str = Query(
        ...,
        description="Имя автора, который удаляет сообщение. Должно совпадать с автором сообщения.",
        example="Иван",
    ),
    db: Session = Depends(get_db),
) -> None:
    # Delete a message, but only the author's own message.
    db_message = db.query(models.Message).filter(models.Message.id == str(message_id)).first()
    if db_message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if db_message.author != author:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")

    db.delete(db_message)
    db.commit()


# --- Искусственный интеллект --------------------------------------------
@app.post(
    "/ai/generate",
    tags=["Искусственный интеллект"],
    summary="Сгенерировать текст по запросу",
    description=(
        "Отправляет один запрос (промпт) модели и возвращает её ответ. "
        "Подходит для простых задач: придумать текст, ответить на вопрос, "
        "объяснить тему. Запросы обрабатываются по очереди фоновым воркером."
    ),
    response_description="Ответ модели вместе с данными о запросе.",
    response_model=schemas.AIResponse,
)
async def generate_text(
    request: schemas.AIGenerateRequest = Body(
        ...,
        description="Запрос к модели.",
        example={
            "prompt": "Придумай короткое поздравление с днём рождения.",
            "model": "yandexgpt-lite",
        },
    )
) -> schemas.AIResponse:
    # Generate text with the AI model.
    return await queue_ai_request(request.prompt, request.model)


@app.post(
    "/ai/chat",
    tags=["Искусственный интеллект"],
    summary="Поговорить с моделью как в чате",
    description=(
        "Принимает историю сообщений с ролями (`system`, `user`, `assistant`) "
        "и возвращает ответ модели. В отличие от `/ai/generate`, здесь можно "
        "передать контекст диалога."
    ),
    response_description="Ответ модели вместе с данными о запросе.",
    response_model=schemas.AIResponse,
)
async def chat_with_ai(
    request: schemas.AIChatRequest = Body(
        ...,
        description="История сообщений.",
        example={
            "messages": [
                {"role": "system", "content": "Ты дружелюбный помощник."},
                {"role": "user", "content": "Расскажи короткую историю про робота."},
            ],
            "model": "yandexgpt-lite",
        },
    )
) -> schemas.AIResponse:
    # Chat with the AI model.
    # Преобразуем сообщения в промпт
    prompt = "\n".join([f"{msg['role']}: {msg['content']}" for msg in request.messages])
    return await queue_ai_request(prompt, request.model or DEFAULT_MODEL)


@app.get(
    "/ai/models",
    tags=["Искусственный интеллект"],
    summary="Список доступных моделей",
    description=(
        "Возвращает модели, доступные в вашем каталоге Yandex AI Studio, "
        "в виде адресов `gpt://...`. Поле `default` — модель, которая "
        "используется, если не указывать её в запросе."
    ),
    response_description="Список моделей и модель по умолчанию.",
    response_model=schemas.AIModelsResponse,
)
async def list_models() -> schemas.AIModelsResponse:
    # List of available AI models.
    try:
        models = await list_yandex_models()
    except Exception:
        models = []
    if not models:
        models = [DEFAULT_MODEL]

    return {"models": models, "default": DEFAULT_MODEL}


# --- Генерация изображений ------------------------------------------------
@app.post(
    "/ai/images",
    tags=["Искусственный интеллект"],
    summary="Поставить генерацию изображения в очередь",
    description=(
        "Принимает текстовый промпт и ставит задачу генерации изображения в "
        "отдельную очередь. Сервер не ждёт окончания генерации: он сразу "
        "возвращает `202 Accepted`, UUID задачи и текущий статус `queued`.\n\n"
        "Поддерживаются два провайдера:\n\n"
        "- **CometAPI** — модели Gemini и OpenAI-совместимые модели из "
        "`GET /ai/image-models`;\n"
        "- **YandexART** — модель `aliceai-image-art-3.0` через существующий "
        "слой Yandex AI Studio.\n\n"
        "Провайдер определяется по имени модели. Для YandexART промпт не "
        "должен превышать 500 символов. Готовое изображение хранится 15 минут."
    ),
    response_description=(
        "Задача принята в очередь. В ответе есть UUID для получения результата."
    ),
    response_model=schemas.AIImageTaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        422: {
            "model": schemas.ErrorResponse,
            "description": (
                "Некорректный промпт, соотношение сторон или неизвестная модель."
            ),
        },
        429: {
            "model": schemas.ErrorResponse,
            "description": "Очередь генерации изображений переполнена.",
        },
        503: {
            "model": schemas.ErrorResponse,
            "description": "Провайдер генерации не настроен.",
        },
    },
)
async def create_image_task(
    request: schemas.AIImageGenerateRequest = Body(
        ...,
        description="Параметры генерации изображения.",
        example={
            "prompt": (
                "Рыжий кот в стиле аниме, мягкие пастельные тона, "
                "высокая детализация"
            ),
            "model": "gemini-3.1-flash-image-preview",
            "aspect_ratio": "1:1",
        },
    )
) -> schemas.AIImageTaskAccepted:
    # Поставить задачу в очередь изображений и вернуть её UUID.
    try:
        task = await enqueue_image_task(
            request.prompt, request.model, request.aspect_ratio
        )
    except ImageQueueFullError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except (ImageNotConfiguredError,) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (ImageModelNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return schemas.AIImageTaskAccepted(
        task_id=task.id,
        status=task.status,
        provider=task.provider,
        model=task.model,
        created_at=task.created_at,
        status_url=f"/ai/images/{task.id}",
    )


@app.get(
    "/ai/images/{task_id}",
    tags=["Искусственный интеллект"],
    summary="Получить статус или готовое изображение",
    description=(
        "Возвращает текущее состояние задачи по UUID.\n\n"
        "Пока задача находится в очереди или выполняется, ответ имеет код "
        "`202 Accepted` и JSON со статусом `queued` или `processing`. Когда "
        "изображение готово, возвращается `200 OK` и сам файл с корректным "
        "`Content-Type` (`image/jpeg`, `image/png` или `image/webp`).\n\n"
        "Если задача завершилась ошибкой, возвращается `422` с текстом ошибки. "
        "Если UUID неизвестен — `404`. Если срок хранения изображения истёк — "
        "`410`. Готовые изображения хранятся 15 минут."
    ),
    response_description=(
        "Статус задачи в формате JSON либо готовое изображение в бинарном виде."
    ),
    response_class=Response,
    responses={
        200: {
            "description": "Готовое изображение.",
            "content": {
                "image/jpeg": {},
                "image/png": {},
                "image/webp": {},
            },
        },
        202: {
            "model": schemas.AIImageTaskStatus,
            "description": "Задача ещё находится в очереди или выполняется.",
        },
        404: {
            "model": schemas.ErrorResponse,
            "description": "Задача с таким UUID не найдена.",
        },
        410: {
            "model": schemas.ErrorResponse,
            "description": "Срок хранения изображения истёк.",
        },
        422: {
            "model": schemas.ErrorResponse,
            "description": "Генерация завершилась ошибкой.",
        },
    },
)
async def get_image_result(
    task_id: UUID = Path(
        ...,
        description="UUID задачи, полученный при постановке в очередь.",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    )
) -> Response:
    # Вернуть статус задачи, готовое изображение или понятную ошибку.
    try:
        task = get_image_task(str(task_id))
    except ImageTaskExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=str(exc),
        ) from exc

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Задача не найдена. Проверьте UUID или сгенерируйте "
                "изображение заново."
            ),
        )

    if task.status in (
        ImageTaskStatus.QUEUED.value,
        ImageTaskStatus.PROCESSING.value,
    ):
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=jsonable_encoder(
                {
                    "task_id": task.id,
                    "status": task.status,
                    "provider": task.provider,
                    "model": task.model,
                    "created_at": task.created_at,
                    "started_at": task.started_at,
                    "finished_at": task.finished_at,
                    "expires_at": task.expires_at,
                    "error": task.error,
                }
            ),
            headers={"Retry-After": "3"},
        )

    if task.status == ImageTaskStatus.FAILED.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=task.error or "Генерация изображения завершилась ошибкой.",
        )

    if not task.image_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Изображение не найдено.",
        )

    extension = task.output_format or "img"
    headers = {
        "X-Task-Id": task.id,
        "X-Image-Provider": task.provider,
        "X-Image-Model": task.model,
        "Cache-Control": "no-store",
        "Content-Disposition": f'inline; filename="image.{extension}"',
    }
    if task.expires_at is not None:
        headers["X-Expires-At"] = task.expires_at.isoformat()

    return Response(
        content=task.image_data,
        media_type=task.mime_type or "application/octet-stream",
        headers=headers,
    )


@app.get(
    "/ai/image-models",
    tags=["Искусственный интеллект"],
    summary="Каталог моделей генерации изображений",
    description=(
        "Возвращает модели CometAPI и YandexART отдельными списками. "
        "Лимит стоимости изображения задаётся на сервере и не принимается "
        "от клиента.\n\n"
        "- `cometapi_models` — модели CometAPI, у которых минимальная "
        "стоимость одного изображения не превышает серверный лимит. Цена "
        "берётся с карточки модели или рассчитывается по минимальному тарифу "
        "за изображение. Для токенных моделей без оценки за изображение цена "
        "не угадывается, и такая модель в список не попадает.\n"
        "- `yandex_models` — модели YandexART, доступные через Yandex AI "
        "Studio. Сейчас используется `aliceai-image-art-3.0`.\n\n"
        "Доступность моделей CometAPI дополнительно проверяется через "
        "`GET /v1/models`. Каталог кэшируется на 10 минут. Если внешний "
        "каталог временно недоступен, возвращаются резервные данные и "
        "предупреждение в поле `warnings`."
    ),
    response_description=(
        "Два списка моделей: CometAPI и YandexART, с ценами и признаками "
        "доступности."
    ),
    response_model=schemas.AIImageModelsResponse,
)
async def list_image_models() -> schemas.AIImageModelsResponse:
    # Серверный лимит цены не является публичным параметром API.
    return await get_image_models(COMETAPI_IMAGE_MAX_PRICE)


@app.get(
    "/ai/queue/status",
    tags=["Искусственный интеллект"],
    summary="Состояние очередей запросов к ИИ",
    description=(
        "Показывает, сколько текстовых запросов и задач на генерацию "
        "изображений ждут обработки, сколько выполняется прямо сейчас и "
        "сколько готовых изображений хранится в памяти. Полезно, если "
        "запросов много и они выполняются с задержкой."
    ),
    response_description="Текущее состояние очередей и хранилища изображений.",
    response_model=schemas.AIQueueStatus,
)
async def queue_status() -> schemas.AIQueueStatus:
    # Status of text and image AI queues.
    image_stats = get_image_queue_stats()
    return {
        "queue_size": ai_queue.qsize(),
        "max_queue_size": ai_queue.maxsize,
        "processing_tasks": len(processing_tasks),
        "image_queue_size": image_stats["queue_size"],
        "image_max_queue_size": image_stats["max_queue_size"],
        "image_processing_tasks": image_stats["processing_tasks"],
        "stored_images": image_stats["stored_images"],
    }
