"""Pydantic schemas for request and response validation.

Все описания полей на русском языке — документация Swagger рассчитана на
учеников, поэтому формулы и термины поясняются простыми словами.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .models import WorkingFormatEnum


class RootResponse(BaseModel):
    """Приветствие сервера — ответ на проверочный запрос ``GET /``."""

    message: str = Field(
        ...,
        description="Приветственный текст.",
        example="Hello Stranger!",
    )


class ErrorResponse(BaseModel):
    """Описание ошибки. Так выглядит ответ сервера, когда что-то пошло не так."""

    detail: str = Field(
        ...,
        description="Текст ошибки простыми словами.",
        example="User not found",
    )


class UserBase(BaseModel):
    """Базовые поля сотрудника (используются при создании и в ответах)."""

    name: str = Field(
        ...,
        description="Имя сотрудника.",
        max_length=100,
        example="Иван",
    )
    surname: str = Field(
        ...,
        description="Фамилия сотрудника.",
        max_length=100,
        example="Иванов",
    )
    email: Optional[str] = Field(
        None,
        description="Электронная почта. Необязательное поле.",
        max_length=255,
        example="ivan@example.com",
    )
    phone: Optional[str] = Field(
        None,
        description="Номер телефона. Необязательное поле.",
        max_length=20,
        example="+7 900 123-45-67",
    )
    city: Optional[str] = Field(
        None,
        description="Город проживания. Необязательное поле.",
        max_length=100,
        example="Москва",
    )
    working_format: WorkingFormatEnum = Field(
        WorkingFormatEnum.REMOTE,
        description=(
            "Формат работы. Возможные значения: "
            "`remote` — удалённо, "
            "`office` — в офисе, "
            "`hybrid` — смешанный."
        ),
        example="remote",
    )


class UserCreate(UserBase):
    """Данные для создания нового сотрудника."""


class UserUpdate(BaseModel):
    """Данные для частичного изменения сотрудника.

    Присылать нужно только те поля, которые хотите изменить, — остальные
    останутся без изменений.
    """

    name: Optional[str] = Field(None, description="Новое имя.", max_length=100, example="Пётр")
    surname: Optional[str] = Field(
        None, description="Новая фамилия.", max_length=100, example="Петров"
    )
    email: Optional[str] = Field(
        None, description="Новая почта.", max_length=255, example="petr@example.com"
    )
    phone: Optional[str] = Field(
        None, description="Новый телефон.", max_length=20, example="+7 900 765-43-21"
    )
    city: Optional[str] = Field(
        None, description="Новый город.", max_length=100, example="Санкт-Петербург"
    )
    working_format: Optional[WorkingFormatEnum] = Field(
        None,
        description="Новый формат работы: `remote`, `office` или `hybrid`.",
        example="office",
    )


class UserRead(UserBase):
    """Сотрудник, как его возвращает сервер."""

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор сотрудника (UUID).",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания записи.",
        example="2025-01-01T12:00:00",
    )

    class Config:
        orm_mode = True


# Chat schemas
class MessageCreate(BaseModel):
    """Данные для отправки сообщения в чат."""

    author: str = Field(
        ...,
        description="Имя автора сообщения.",
        max_length=100,
        example="Иван",
    )
    text: str = Field(
        ...,
        description="Текст сообщения (не длиннее 256 символов).",
        max_length=256,
        example="Привет, как дела?",
    )


class MessageRead(MessageCreate):
    """Сообщение чата, как его возвращает сервер."""

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор сообщения (UUID).",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время отправки сообщения.",
        example="2025-01-01T12:00:00",
    )

    class Config:
        orm_mode = True


# AI Schemas
class AIGenerateRequest(BaseModel):
    """Запрос на генерацию текста: один вопрос — один ответ."""

    prompt: str = Field(
        ...,
        description="Текст запроса (промпт) к модели. Максимум 2000 символов.",
        max_length=2000,
        example="Придумай короткое поздравление с днём рождения.",
    )
    model: str = Field(
        "",
        description=(
            "Название модели. Можно указать коротко (`yandexgpt-lite`) или "
            "полным адресом (`gpt://<каталог>/yandexgpt-lite/latest`). "
            "Если оставить пустым — используется модель по умолчанию."
        ),
        example="yandexgpt-lite",
    )


class AIChatRequest(BaseModel):
    """Запрос на чат: история сообщений с ролями."""

    messages: List[dict] = Field(
        ...,
        description=(
            "История сообщений. Каждый элемент — объект с полями "
            "`role` (роль: `user` — пользователь, `assistant` — модель, "
            "`system` — инструкция) и `content` (текст сообщения)."
        ),
        example=[
            {"role": "system", "content": "Ты дружелюбный помощник."},
            {"role": "user", "content": "Расскажи короткую историю про робота."},
        ],
    )
    model: str = Field(
        "",
        description=(
            "Название модели (коротко или полным адресом). "
            "Пустая строка — модель по умолчанию."
        ),
        example="yandexgpt-lite",
    )


class AIResponse(BaseModel):
    """Ответ модели на запрос."""

    id: str = Field(
        ...,
        description="Идентификатор запроса (нужен, чтобы различать запросы в очереди).",
        example="0b8c1f6e-4b2a-4d3c-9f1a-1234567890ab",
    )
    response: str = Field(
        ...,
        description="Текст, который сгенерировала модель.",
        example="С днём рождения! Желаю счастья и успехов.",
    )
    status: str = Field(
        ...,
        description="Статус обработки запроса. Успешный ответ — `completed`.",
        example="completed",
    )
    model: str = Field(
        ...,
        description="Модель, которая отвечала на запрос.",
        example="yandexgpt-lite",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время ответа.",
        example="2025-01-01T12:00:00",
    )


class AIModelsResponse(BaseModel):
    """Список доступных моделей и модель по умолчанию."""

    models: List[str] = Field(
        ...,
        description="Список доступных моделей в виде адресов `gpt://...`.",
        example=[
            "gpt://b1g5r3ansrg0qof13lj3/yandexgpt-lite/latest",
            "gpt://b1g5r3ansrg0qof13lj3/deepseek-v4.1-flash/latest",
        ],
    )
    default: str = Field(
        ...,
        description="Модель, которая используется, если не указать её в запросе.",
        example="yandexgpt-lite",
    )


class AIQueueStatus(BaseModel):
    """Состояние очереди запросов к ИИ."""

    queue_size: int = Field(
        ...,
        description="Сколько запросов сейчас ждут своей очереди.",
        example=0,
    )
    max_queue_size: int = Field(
        ...,
        description="Максимальный размер очереди.",
        example=50,
    )
    processing_tasks: int = Field(
        ...,
        description="Сколько запросов обрабатывается прямо сейчас.",
        example=0,
    )
    image_queue_size: int = Field(
        ...,
        description="Сколько задач на генерацию изображений ждут своей очереди.",
        example=1,
    )
    image_max_queue_size: int = Field(
        ...,
        description="Максимальный размер очереди генерации изображений.",
        example=50,
    )
    image_processing_tasks: int = Field(
        ...,
        description="Сколько задач на генерацию изображений выполняется прямо сейчас.",
        example=1,
    )
    stored_images: int = Field(
        ...,
        description="Сколько готовых изображений сейчас хранится в памяти.",
        example=3,
    )


class AIImageGenerateRequest(BaseModel):
    """Запрос на генерацию изображения.

    Задача не выполняется внутри HTTP-запроса: сервер сразу ставит её в
    очередь и возвращает идентификатор. Готовое изображение можно получить
    отдельным запросом по этому идентификатору.
    """

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description=(
            "Текстовое описание изображения. Для YandexART максимальная длина "
            "промпта составляет 500 символов, для CometAPI — до 2000 символов."
        ),
        example=(
            "Женщина в синем платье с цветочным узором стоит у деревянных "
            "перил традиционного китайского дома. Реалистичная живопись, "
            "внимание к фактуре ткани и дерева."
        ),
    )
    model: str = Field(
        "",
        description=(
            "Идентификатор модели. Для CometAPI можно использовать модель из "
            "`GET /ai/image-models`, например `gemini-3.1-flash-image-preview` "
            "или `flux-3-image`. Для YandexART используйте "
            "`aliceai-image-art-3.0`. Пустая строка означает модель по умолчанию."
        ),
        example="gemini-3.1-flash-image-preview",
    )
    aspect_ratio: str = Field(
        "1:1",
        description=(
            "Соотношение сторон изображения. Поддерживаются значения `1:1`, "
            "`2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9` и `21:9`. "
            "Для OpenAI-совместимых моделей CometAPI значение преобразуется в "
            "подходящий размер, например `1024x1024` или `1024x1536`."
        ),
        example="9:16",
    )


class AIImageTaskAccepted(BaseModel):
    """Ответ на постановку задачи генерации изображения в очередь."""

    task_id: UUID = Field(
        ...,
        description="Уникальный идентификатор задачи. По нему запрашивается результат.",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    )
    status: str = Field(
        ...,
        description=(
            "Статус задачи сразу после постановки в очередь. Обычно `queued`."
        ),
        example="queued",
    )
    provider: str = Field(
        ...,
        description=(
            "Провайдер генерации: `cometapi` или `yandex`. Определяется по "
            "выбранной модели."
        ),
        example="cometapi",
    )
    model: str = Field(
        ...,
        description="Модель, которая будет генерировать изображение.",
        example="gemini-3.1-flash-image-preview",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время постановки задачи в очередь.",
        example="2026-01-01T12:00:00+00:00",
    )
    status_url: str = Field(
        ...,
        description="Адрес, по которому можно узнать статус и получить изображение.",
        example="/ai/images/3fa85f64-5717-4562-b3fc-2c963f66afa6",
    )


class AIImageTaskStatus(BaseModel):
    """Текущее состояние задачи генерации изображения."""

    task_id: UUID = Field(
        ...,
        description="Идентификатор задачи.",
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
    )
    status: str = Field(
        ...,
        description=(
            "Статус задачи: `queued` — ждёт очереди, `processing` — выполняется, "
            "`completed` — изображение готово, `failed` — произошла ошибка."
        ),
        example="processing",
    )
    provider: str = Field(
        ...,
        description="Провайдер генерации: `cometapi` или `yandex`.",
        example="yandex",
    )
    model: str = Field(
        ...,
        description="Модель генерации изображения.",
        example="aliceai-image-art-3.0",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания задачи.",
        example="2026-01-01T12:00:00+00:00",
    )
    started_at: Optional[datetime] = Field(
        None,
        description="Дата и время начала генерации. Пока задача в очереди, поле пустое.",
        example="2026-01-01T12:00:05+00:00",
    )
    finished_at: Optional[datetime] = Field(
        None,
        description="Дата и время завершения генерации или ошибки.",
        example="2026-01-01T12:00:18+00:00",
    )
    expires_at: Optional[datetime] = Field(
        None,
        description=(
            "Дата и время удаления готового изображения. TTL по умолчанию "
            "составляет 15 минут с момента завершения."
        ),
        example="2026-01-01T12:15:18+00:00",
    )
    error: Optional[str] = Field(
        None,
        description="Текст ошибки, если задача завершилась со статусом `failed`.",
        example="Провайдер вернул ошибку: превышен лимит запросов.",
    )


class AIImageModelInfo(BaseModel):
    """Описание одной модели генерации изображений."""

    id: str = Field(
        ...,
        description="Идентификатор модели, который нужно передать в поле `model`.",
        example="gemini-3.1-flash-image-preview",
    )
    name: str = Field(
        ...,
        description="Понятное название модели.",
        example="Nano Banana 2",
    )
    provider: str = Field(
        ...,
        description="Провайдер модели: `CometAPI` или `Yandex`.",
        example="CometAPI",
    )
    endpoint_type: str = Field(
        ...,
        description=(
            "Тип API: `gemini` — Gemini generateContent, `openai_images` — "
            "OpenAI-совместимый Images API, `yandex_images` — Yandex AI Studio "
            "Images API."
        ),
        example="gemini",
    )
    features: List[str] = Field(
        ...,
        description="Возможности модели, например `text-to-image`.",
        example=["text-to-image", "image-editing"],
    )
    price_usd: Optional[float] = Field(
        None,
        description=(
            "Минимальная стоимость одного изображения в долларах США. Для "
            "моделей, где цена известна только за токены, значение является "
            "оценкой и помечается полем `price_is_estimated`."
        ),
        example=0.036,
    )
    price_unit: str = Field(
        ...,
        description=(
            "Единица цены: `per_image` — за изображение, `per_request` — за "
            "запрос, `per_1m_tokens` — за 1 миллион токенов (оценка)."
        ),
        example="per_image",
    )
    price_is_estimated: bool = Field(
        ...,
        description="`true`, если цена является оценкой, а не точным тарифом.",
        example=True,
    )
    available: bool = Field(
        ...,
        description="Доступна ли модель текущему API-ключу.",
        example=True,
    )
    note: Optional[str] = Field(
        None,
        description="Дополнительное пояснение по модели или цене.",
        example="Цена рассчитана по минимальному тарифу за изображение.",
    )


class AIImageModelsResponse(BaseModel):
    """Каталог моделей генерации изображений.

    Модели CometAPI и YandexART возвращаются отдельными списками, чтобы их
    можно было показывать в интерфейсе разными группами.
    """

    currency: str = Field(
        ...,
        description="Валюта цен.",
        example="USD",
    )
    default: str = Field(
        ...,
        description="Модель CometAPI по умолчанию.",
        example="gemini-3.1-flash-image-preview",
    )
    default_yandex: str = Field(
        ...,
        description="Модель YandexART по умолчанию.",
        example="aliceai-image-art-3.0",
    )
    cometapi_models: List[AIImageModelInfo] = Field(
        ...,
        description=(
            "Модели CometAPI с минимальной стоимостью изображения не выше "
            "лимита, настроенного на сервере."
        ),
    )
    yandex_models: List[AIImageModelInfo] = Field(
        ...,
        description="Отдельный список моделей YandexART, доступных через Yandex AI Studio.",
    )
    count: int = Field(
        ...,
        description="Общее количество моделей в обоих списках.",
        example=21,
    )
    updated_at: datetime = Field(
        ...,
        description="Дата и время последнего обновления каталога.",
        example="2026-01-01T12:00:00+00:00",
    )
    availability_checked: bool = Field(
        ...,
        description=(
            "`true`, если удалось проверить доступность моделей через "
            "`GET /v1/models` CometAPI. Если проверка не удалась, каталог "
            "возвращается с предупреждением."
        ),
        example=True,
    )
    warnings: List[str] = Field(
        ...,
        description="Предупреждения о неполных данных каталога или проверки доступности.",
        example=[],
    )
