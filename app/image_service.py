"""Сервис генерации изображений через CometAPI и Yandex AI Studio.

Задачи выполняются в отдельной очереди, чтобы долгая генерация изображения
не блокировала текстовые запросы к ИИ. Готовые изображения хранятся в памяти
ограниченное время (TTL).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import httpx  # type: ignore[import]

from .ai_service import YANDEX_BASE_URL, resolve_art_model, yandex_headers

logger = logging.getLogger(__name__)

COMETAPI_BASE_URL = os.getenv(
    "COMETAPI_BASE_URL", "https://api.cometapi.com"
).rstrip("/")
COMETAPI_KEY = os.getenv("COMETAPI_KEY")
COMETAPI_DEFAULT_IMAGE_MODEL = os.getenv(
    "COMETAPI_DEFAULT_IMAGE_MODEL", "gemini-3.1-flash-image-preview"
)
COMETAPI_IMAGE_MAX_PRICE = float(os.getenv("COMETAPI_IMAGE_MAX_PRICE", "0.3"))
COMETAPI_TIMEOUT_SECONDS = float(os.getenv("COMETAPI_TIMEOUT_SECONDS", "180"))
COMETAPI_MODELS_PAGE_URL = os.getenv(
    "COMETAPI_MODELS_PAGE_URL",
    "https://www.cometapi.com/models/?features=text-to-image&price=0%2C0.6",
)

IMAGE_TTL_SECONDS = int(os.getenv("IMAGE_TTL_SECONDS", "900"))
IMAGE_QUEUE_MAXSIZE = int(os.getenv("IMAGE_QUEUE_MAXSIZE", "50"))
IMAGE_MAX_STORED = int(os.getenv("IMAGE_MAX_STORED", "50"))
IMAGE_CATALOG_TTL_SECONDS = int(os.getenv("IMAGE_CATALOG_TTL_SECONDS", "600"))

YANDEX_IMAGE_MODEL = os.getenv("YANDEX_IMAGE_MODEL", "aliceai-image-art-3.0")
YANDEX_IMAGE_MODELS = [
    item.strip()
    for item in os.getenv("YANDEX_IMAGE_MODELS", YANDEX_IMAGE_MODEL).split(",")
    if item.strip()
]
YANDEX_IMAGE_PRICE_USD = float(os.getenv("YANDEX_IMAGE_PRICE_USD", "0.01"))
YANDEX_IMAGE_PROMPT_MAX_LENGTH = 500

SUPPORTED_ASPECT_RATIOS = {
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
}


class ImageTaskStatus(str, Enum):
    """Допустимые состояния задачи генерации изображения."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ImageServiceError(Exception):
    """Базовая ошибка сервиса изображений."""


class ImageNotConfiguredError(ImageServiceError):
    """Провайдер не настроен."""


class ImageQueueFullError(ImageServiceError):
    """Очередь генерации изображений переполнена."""


class ImageModelNotFoundError(ImageServiceError):
    """Модель недоступна или не поддерживается."""


class ImageTaskExpiredError(ImageServiceError):
    """Срок хранения изображения истёк."""


class ImageGenerationError(ImageServiceError):
    """Ошибка генерации у провайдера."""


@dataclass
class ImageTask:
    """Задача генерации изображения и её результат."""

    id: str
    provider: str
    model: str
    prompt: str
    aspect_ratio: str
    status: str = ImageTaskStatus.QUEUED.value
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    image_data: Optional[bytes] = None
    mime_type: Optional[str] = None
    output_format: Optional[str] = None
    error: Optional[str] = None


image_queue: asyncio.Queue = asyncio.Queue(maxsize=IMAGE_QUEUE_MAXSIZE)
image_tasks: Dict[str, ImageTask] = {}
_catalog_lock = asyncio.Lock()
_catalog_state: Optional[Dict[str, Any]] = None
_catalog_cached_at: Optional[datetime] = None


def _now() -> datetime:
    """Текущее время в UTC с часовым поясом."""

    return datetime.now(timezone.utc)


def _short_yandex_model(model: str) -> str:
    """Преобразует ``art://folder/model`` в короткое имя модели."""

    if model.startswith("art://"):
        return model.rsplit("/", 1)[-1]
    return model


def _yandex_model_ids() -> set:
    """Короткие имена доступных моделей YandexART."""

    return {_short_yandex_model(model) for model in YANDEX_IMAGE_MODELS}


def _resolve_provider(model: str) -> Tuple[str, str]:
    """Определяет провайдера и каноническое имя модели."""

    model_lower = model.lower()
    is_yandex = (
        model.startswith("art://")
        or model in _yandex_model_ids()
        or "yandex-art" in model_lower
        or "aliceai-image-art" in model_lower
    )
    if is_yandex:
        return "yandex", _short_yandex_model(model)
    return "cometapi", model or COMETAPI_DEFAULT_IMAGE_MODEL


def _openai_size(aspect_ratio: str) -> str:
    """Преобразует соотношение сторон в размер OpenAI Images API."""

    return {
        "1:1": "1024x1024",
        "2:3": "1024x1536",
        "3:2": "1536x1024",
        "3:4": "1024x1536",
        "4:3": "1536x1024",
        "4:5": "1024x1536",
        "5:4": "1536x1024",
        "9:16": "1024x1536",
        "16:9": "1536x1024",
        "21:9": "1536x1024",
    }.get(aspect_ratio, "1024x1024")


def _detect_mime(data: bytes) -> str:
    """Определяет MIME-тип изображения по сигнатуре файла."""

    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _decode_base64_image(value: str) -> bytes:
    """Декодирует base64, в том числе строку с префиксом ``data:image/...``."""

    if "," in value and value.startswith("data:"):
        value = value.split(",", 1)[1]
    return base64.b64decode(value)


def _truncate_error(value: str, limit: int = 500) -> str:
    """Ограничивает текст ошибки, чтобы не раздувать ответ API."""

    value = " ".join(str(value).split())
    if not value:
        value = "неизвестная ошибка"
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _exception_text(exc: Exception) -> str:
    """Возвращает текст исключения, даже если ``str(exc)`` пустой."""

    return _truncate_error(str(exc) or type(exc).__name__)


def _provider_error(response: httpx.Response, provider: str) -> ImageGenerationError:
    """Формирует понятную ошибку провайдера без утечки ключа."""

    message = ""
    try:
        data = response.json()
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or error)
            elif error:
                message = str(error)
            if not message:
                message = str(data.get("message") or data)
        else:
            message = str(data)
    except Exception:
        message = response.text
    return ImageGenerationError(
        f"{provider}: HTTP {response.status_code}. {_truncate_error(message)}"
    )


def _validate_request(prompt: str, aspect_ratio: str) -> None:
    """Проверяет общие параметры запроса."""

    if aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
        supported = ", ".join(sorted(SUPPORTED_ASPECT_RATIOS))
        raise ValueError(
            f"Неподдерживаемое соотношение сторон «{aspect_ratio}». "
            f"Доступны: {supported}."
        )
    if not prompt.strip():
        raise ValueError("Промпт не может быть пустым.")


def _task_status_payload(task: ImageTask) -> Dict[str, Any]:
    """Преобразует задачу в данные для JSON-ответа."""

    return {
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


def get_image_queue_stats() -> Dict[str, int]:
    """Возвращает состояние очереди и хранилища изображений."""

    processing = sum(
        1
        for task in image_tasks.values()
        if task.status == ImageTaskStatus.PROCESSING.value
    )
    stored = sum(1 for task in image_tasks.values() if task.image_data is not None)
    return {
        "queue_size": image_queue.qsize(),
        "max_queue_size": image_queue.maxsize,
        "processing_tasks": processing,
        "stored_images": stored,
    }


def get_image_task(task_id: str) -> Optional[ImageTask]:
    """Возвращает задачу по UUID или ``None``."""

    task = image_tasks.get(task_id)
    if task is None:
        return None
    if task.expires_at is not None and _now() >= task.expires_at:
        raise ImageTaskExpiredError(
            "Срок хранения изображения истёк. Сгенерируйте новое изображение."
        )
    return task


def purge_expired_images() -> int:
    """Удаляет просроченные задачи и ограничивает размер хранилища."""

    now = _now()
    removed = 0
    for task_id, task in list(image_tasks.items()):
        if task.expires_at is not None and now >= task.expires_at:
            image_tasks.pop(task_id, None)
            removed += 1

    if len(image_tasks) > IMAGE_MAX_STORED:
        completed = sorted(
            (
                task
                for task in image_tasks.values()
                if task.status
                in (
                    ImageTaskStatus.COMPLETED.value,
                    ImageTaskStatus.FAILED.value,
                )
            ),
            key=lambda task: task.finished_at or task.created_at,
        )
        for task in completed[: len(image_tasks) - IMAGE_MAX_STORED]:
            image_tasks.pop(task.id, None)
            removed += 1

    return removed


async def cleanup_expired_images() -> None:
    """Фоновая очистка просроченных изображений."""

    while True:
        try:
            purge_expired_images()
        except Exception:  # pragma: no cover - защита фонового цикла
            logger.exception("Не удалось очистить просроченные изображения")
        await asyncio.sleep(60)


async def _validate_cometapi_model(model: str) -> None:
    """Проверяет модель по живому каталогу CometAPI, если он доступен."""

    state = await _get_cometapi_catalog()
    if not state or state.get("source") != "live":
        return
    items = {item["id"]: item for item in state.get("models", [])}
    if model not in items:
        raise ImageModelNotFoundError(
            f"Модель «{model}» не найдена в каталоге CometAPI. "
            "Посмотрите доступные модели в GET /ai/image-models."
        )
    if not items[model].get("available", True):
        raise ImageModelNotFoundError(
            f"Модель «{model}» сейчас недоступна текущему ключу CometAPI."
        )


async def enqueue_image_task(
    prompt: str, model: str = "", aspect_ratio: str = "1:1"
) -> ImageTask:
    """Ставит задачу генерации изображения в очередь."""

    _validate_request(prompt, aspect_ratio)
    provider, resolved_model = _resolve_provider(model)

    if provider == "yandex":
        if resolved_model not in _yandex_model_ids():
            raise ImageModelNotFoundError(
                f"Модель YandexART «{resolved_model}» не поддерживается. "
                f"Доступны: {', '.join(sorted(_yandex_model_ids()))}."
            )
        if not os.getenv("YANDEX_API_KEY") or not os.getenv("YANDEX_FOLDER_ID"):
            raise ImageNotConfiguredError(
                "Yandex AI Studio не настроен. Задайте YANDEX_API_KEY и "
                "YANDEX_FOLDER_ID."
            )
        if len(prompt) > YANDEX_IMAGE_PROMPT_MAX_LENGTH:
            raise ValueError(
                "Для YandexART промпт не должен превышать "
                f"{YANDEX_IMAGE_PROMPT_MAX_LENGTH} символов."
            )
    else:
        if not COMETAPI_KEY:
            raise ImageNotConfiguredError(
                "CometAPI не настроен. Задайте COMETAPI_KEY."
            )
        await _validate_cometapi_model(resolved_model)

    task = ImageTask(
        id=str(uuid4()),
        provider=provider,
        model=resolved_model,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
    )
    try:
        image_queue.put_nowait(task)
    except asyncio.QueueFull as exc:
        raise ImageQueueFullError(
            "Очередь генерации изображений переполнена. "
            "Попробуйте позже."
        ) from exc
    image_tasks[task.id] = task
    logger.info(
        "Изображение поставлено в очередь: task=%s provider=%s model=%s",
        task.id,
        task.provider,
        task.model,
    )
    return task


async def _generate_cometapi(task: ImageTask) -> Tuple[bytes, str, str]:
    """Генерирует изображение через CometAPI."""

    if not COMETAPI_KEY:
        raise ImageNotConfiguredError("CometAPI не настроен. Задайте COMETAPI_KEY.")

    model_lower = task.model.lower()
    is_gemini = model_lower.startswith("gemini") or "nano-banana" in model_lower

    headers = {
        "Authorization": COMETAPI_KEY,
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(COMETAPI_TIMEOUT_SECONDS)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        if is_gemini:
            url = (
                f"{COMETAPI_BASE_URL}/v1beta/models/"
                f"{task.model}:generateContent"
            )
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": task.prompt}],
                    }
                ],
                "generationConfig": {
                    "responseModalities": ["IMAGE"],
                    "imageConfig": {"aspectRatio": task.aspect_ratio},
                },
            }
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                raise _provider_error(response, "CometAPI")
            data = response.json()
            return _extract_gemini_image(data)

        url = f"{COMETAPI_BASE_URL}/v1/images/generations"
        payload = {
            "model": task.model,
            "prompt": task.prompt,
            "n": 1,
            "size": _openai_size(task.aspect_ratio),
            "response_format": "b64_json",
        }
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code == 400 and "response_format" in response.text:
            payload.pop("response_format", None)
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise _provider_error(response, "CometAPI")
        data = response.json()
        return await _extract_openai_image(data, client)


def _extract_gemini_image(data: Dict[str, Any]) -> Tuple[bytes, str, str]:
    """Извлекает изображение из ответа Gemini generateContent."""

    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ImageGenerationError(
            "CometAPI вернул ответ без изображения. "
            "Возможно, сработал фильтр безопасности."
        ) from exc

    texts: List[str] = []
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            image_bytes = _decode_base64_image(inline["data"])
            mime = inline.get("mimeType") or inline.get("mime_type") or _detect_mime(
                image_bytes
            )
            return image_bytes, mime, _format_from_mime(mime)
        if part.get("text"):
            texts.append(str(part["text"]))

    detail = _truncate_error(" ".join(texts)) if texts else "нет inlineData"
    raise ImageGenerationError(
        f"CometAPI не вернул изображение. Ответ модели: {detail}"
    )


async def _extract_openai_image(
    data: Dict[str, Any], client: httpx.AsyncClient
) -> Tuple[bytes, str, str]:
    """Извлекает изображение из OpenAI-совместимого ответа CometAPI."""

    try:
        item = data["data"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ImageGenerationError(
            "CometAPI вернул ответ без изображения."
        ) from exc

    if item.get("b64_json"):
        image_bytes = _decode_base64_image(item["b64_json"])
        mime = _detect_mime(image_bytes)
        return image_bytes, mime, _format_from_mime(mime)

    if item.get("url"):
        response = await client.get(item["url"])
        if response.status_code >= 400:
            raise _provider_error(response, "CometAPI (изображение)")
        image_bytes = response.content
        mime = response.headers.get("content-type", "").split(";")[0]
        if not mime.startswith("image/"):
            mime = _detect_mime(image_bytes)
        return image_bytes, mime, _format_from_mime(mime)

    raise ImageGenerationError(
        "CometAPI вернул ответ без поля b64_json и без ссылки на изображение."
    )


async def _generate_yandex(task: ImageTask) -> Tuple[bytes, str, str]:
    """Генерирует изображение через Yandex AI Studio Images API."""

    if len(task.prompt) > YANDEX_IMAGE_PROMPT_MAX_LENGTH:
        raise ImageGenerationError(
            "Для YandexART промпт не должен превышать "
            f"{YANDEX_IMAGE_PROMPT_MAX_LENGTH} символов."
        )

    try:
        headers = yandex_headers()
    except RuntimeError as exc:
        raise ImageNotConfiguredError(str(exc)) from exc

    model_uri = resolve_art_model(task.model)
    payload = {
        "model": model_uri,
        "prompt": task.prompt,
        "size": _openai_size(task.aspect_ratio),
    }
    timeout = httpx.Timeout(COMETAPI_TIMEOUT_SECONDS)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(
            f"{YANDEX_BASE_URL}/images/generations",
            headers=headers,
            json=payload,
        )
        if response.status_code >= 400:
            raise _provider_error(response, "Yandex AI Studio")
        data = response.json()
        try:
            item = data["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ImageGenerationError(
                "Yandex AI Studio вернул ответ без изображения."
            ) from exc

        if item.get("b64_json"):
            image_bytes = _decode_base64_image(item["b64_json"])
        elif item.get("url"):
            image_response = await client.get(item["url"])
            if image_response.status_code >= 400:
                raise _provider_error(
                    image_response, "Yandex AI Studio (изображение)"
                )
            image_bytes = image_response.content
        else:
            raise ImageGenerationError(
                "Yandex AI Studio вернул ответ без b64_json и без ссылки."
            )

        mime = _detect_mime(image_bytes)
        return image_bytes, mime, _format_from_mime(mime)


def _format_from_mime(mime: str) -> str:
    """Возвращает короткое имя формата по MIME-типу."""

    return {
        "image/jpeg": "jpeg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(mime, "binary")


async def _generate_image(task: ImageTask) -> Tuple[bytes, str, str]:
    """Выбирает провайдера и генерирует изображение."""

    if task.provider == "yandex":
        return await _generate_yandex(task)
    return await _generate_cometapi(task)


async def process_image_requests() -> None:
    """Фоновый воркер очереди изображений."""

    while True:
        task = await image_queue.get()
        started = _now()
        task.status = ImageTaskStatus.PROCESSING.value
        task.started_at = started
        logger.info(
            "Начата генерация изображения: task=%s provider=%s model=%s",
            task.id,
            task.provider,
            task.model,
        )
        try:
            image_bytes, mime_type, output_format = await _generate_image(task)
            task.image_data = image_bytes
            task.mime_type = mime_type
            task.output_format = output_format
            task.status = ImageTaskStatus.COMPLETED.value
            task.finished_at = _now()
            task.expires_at = task.finished_at + timedelta(
                seconds=IMAGE_TTL_SECONDS
            )
            logger.info(
                "Изображение готово: task=%s provider=%s model=%s bytes=%s",
                task.id,
                task.provider,
                task.model,
                len(image_bytes),
            )
        except asyncio.CancelledError:
            task.status = ImageTaskStatus.FAILED.value
            task.error = "Генерация отменена при остановке сервера."
            task.finished_at = _now()
            task.expires_at = task.finished_at + timedelta(
                seconds=IMAGE_TTL_SECONDS
            )
            raise
        except Exception as exc:  # pragma: no cover - зависит от провайдера
            task.status = ImageTaskStatus.FAILED.value
            task.error = _exception_text(exc)
            task.finished_at = _now()
            task.expires_at = task.finished_at + timedelta(
                seconds=IMAGE_TTL_SECONDS
            )
            logger.warning(
                "Ошибка генерации изображения: task=%s provider=%s model=%s error=%s",
                task.id,
                task.provider,
                task.model,
                task.error,
            )
        finally:
            image_queue.task_done()
            purge_expired_images()


def _extract_server_models(html: str) -> List[Dict[str, Any]]:
    """Извлекает массив ``serverModels`` из RSC-данных страницы CometAPI."""

    chunks: List[str] = []
    for match in re.finditer(
        r"self\.__next_f\.push\((\[.*?\])\)</script>", html, re.S
    ):
        try:
            value = json.loads(match.group(1))
            if len(value) > 1 and isinstance(value[1], str):
                chunks.append(value[1])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    decoded = "".join(chunks)
    marker = '"serverModels":'
    index = decoded.find(marker)
    if index < 0:
        return []

    payload = decoded[index + len(marker) :].lstrip()
    try:
        models, _ = json.JSONDecoder().raw_decode(payload)
    except json.JSONDecodeError:
        return []
    if isinstance(models, list):
        return models
    if isinstance(models, dict):
        return [models]
    return []


def _extract_card_prices(html: str) -> Dict[str, Dict[str, Any]]:
    """Извлекает цены с карточек моделей на странице CometAPI.

    На карточке отображается цена до и после скидки, например
    ``From $0.048 $0.0384 /request``. Берём минимальное значение и единицу.
    """

    result: Dict[str, Dict[str, Any]] = {}
    for card in re.findall(r"<article\b.*?</article>", html, re.S):
        text = re.sub(r"<[^>]+>", " ", card)
        text = re.sub(r"\s+", " ", text)
        price_match = re.search(
            r"From\s+\$([0-9]+(?:\.[0-9]+)?)"
            r"(?:\s+\$([0-9]+(?:\.[0-9]+)?))?"
            r"\s*/\s*(1M tokens|request)",
            text,
            re.I,
        )
        if not price_match:
            continue

        model_match = re.search(
            r"font-mono[^>]*>\s*([^<\s][^<]*?)\s*</div>", card, re.S
        )
        if not model_match:
            continue
        model_id = model_match.group(1).strip()
        prices = [float(price_match.group(1))]
        if price_match.group(2):
            prices.append(float(price_match.group(2)))
        unit = price_match.group(3).lower()
        result[model_id] = {
            "price": min(prices),
            "unit": "per_request" if unit == "request" else "per_1m_tokens",
        }
    return result


def _compute_model_price(
    model: Dict[str, Any], card: Optional[Dict[str, Any]]
) -> Tuple[Optional[float], str, bool]:
    """Вычисляет минимальную стоимость одного изображения.

    Для моделей с ценой за запрос используется цена с карточки. Для токенных
    моделей берётся минимальная оценка ``≈ $...`` из описания тарифов. Если
    оценку за изображение получить нельзя, модель не попадает в каталог,
    потому что сравнивать цену за 1M токенов с лимитом за изображение нельзя.
    """

    if card and card.get("unit") == "per_request":
        return float(card["price"]), "per_request", False

    pricing_content = model.get("pricing_content") or ""
    estimates = [
        float(value)
        for value in re.findall(r"≈\s*\$([0-9]+(?:\.[0-9]+)?)", pricing_content)
    ]
    if estimates:
        return min(estimates), "per_image", True

    pricing = model.get("pricing") or {}
    if pricing.get("per_request") is not None:
        return float(pricing["per_request"]), "per_request", False

    return None, "unknown", True


def _model_endpoint_type(model: Dict[str, Any]) -> str:
    """Определяет тип API для модели CometAPI."""

    model_id = str(model.get("id") or "").lower()
    if model_id.startswith("gemini") or "nano-banana" in model_id:
        return "gemini"

    endpoints = model.get("endpoints")
    if isinstance(endpoints, str):
        try:
            endpoints = json.loads(endpoints)
        except json.JSONDecodeError:
            endpoints = {}
    if isinstance(endpoints, dict) and "gemini" in endpoints:
        return "gemini"
    return "openai_images"


def _build_cometapi_catalog(
    server_models: List[Dict[str, Any]],
    card_prices: Dict[str, Dict[str, Any]],
    available_ids: Optional[set],
) -> List[Dict[str, Any]]:
    """Собирает каталог моделей CometAPI с ценами и доступностью."""

    catalog: List[Dict[str, Any]] = []
    for model in server_models:
        model_id = str(model.get("id") or "").strip()
        if not model_id:
            continue
        features = model.get("features") or []
        if "text-to-image" not in features:
            continue

        price, price_unit, estimated = _compute_model_price(
            model, card_prices.get(model_id)
        )
        if price is None:
            continue

        available = True if available_ids is None else model_id in available_ids
        endpoint_type = _model_endpoint_type(model)
        note = None
        if price_unit == "per_image":
            note = "Минимальная оценка стоимости одного изображения."
        elif price_unit == "per_request":
            note = "Цена за один запрос генерации изображения."
        else:
            note = "Цена является оценкой по тарифу провайдера."

        catalog.append(
            {
                "id": model_id,
                "name": str(model.get("name") or model_id),
                "provider": "CometAPI",
                "endpoint_type": endpoint_type,
                "features": features,
                "price_usd": round(price, 6),
                "price_unit": price_unit,
                "price_is_estimated": estimated,
                "available": available,
                "note": note,
            }
        )

    catalog.sort(key=lambda item: (item["price_usd"], item["name"].lower()))
    return catalog


def _fallback_cometapi_catalog() -> List[Dict[str, Any]]:
    """Минимальный каталог на случай недоступности страницы CometAPI."""

    items = [
        ("gemini-3.1-flash-image-preview", "Nano Banana 2", "gemini", 0.036),
        ("gemini-3-pro-image", "Nano Banana Pro", "gemini", 0.096),
        ("flux-3-image", "Flux 3 Image", "openai_images", 0.0384),
        ("qwen-image-3.0", "Qwen-Image-3.0", "openai_images", 0.024),
        ("flux-2-dev", "FLUX 2 DEV", "openai_images", 0.06),
        ("black-forest-labs/flux-2-max", "FLUX 2 MAX", "openai_images", 0.08),
        ("flux-2-flex", "FLUX 2 FLEX", "openai_images", 0.008),
        ("flux-2-pro", "FLUX 2 PRO", "openai_images", 0.008),
        ("qwen-image", "Qwen Image", "openai_images", 0.028),
        ("gen4_image_turbo", "Gen4-image-turbo", "openai_images", 0.016),
        ("gpt-image-2-all", "GPT Image 2 ALL", "openai_images", 0.04),
        ("gpt-4o-image", "GPT 4o Image", "openai_images", 0.04),
        ("doubao-seedream-4-5-251128", "Doubao Seedream 4.5", "openai_images", 0.032),
        ("grok-imagine-image-2.0", "Grok-Imagine-Image-2.0", "openai_images", 0.032),
    ]
    return [
        {
            "id": model_id,
            "name": name,
            "provider": "CometAPI",
            "endpoint_type": endpoint_type,
            "features": ["text-to-image"],
            "price_usd": price,
            "price_unit": "per_image" if endpoint_type == "gemini" else "per_request",
            "price_is_estimated": True,
            "available": True,
            "note": "Резервные данные каталога. Цена является оценкой.",
        }
        for model_id, name, endpoint_type, price in items
    ]


async def _fetch_cometapi_page() -> str:
    """Загружает страницу каталога CometAPI."""

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0), follow_redirects=True
    ) as client:
        response = await client.get(COMETAPI_MODELS_PAGE_URL)
        response.raise_for_status()
        return response.text


async def _fetch_cometapi_available_models() -> Optional[set]:
    """Возвращает идентификаторы моделей, доступных текущему ключу."""

    if not COMETAPI_KEY:
        return None
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0), follow_redirects=True
    ) as client:
        response = await client.get(
            f"{COMETAPI_BASE_URL}/v1/models",
            headers={"Authorization": COMETAPI_KEY},
        )
        if response.status_code >= 400:
            raise ImageGenerationError(
                f"CometAPI /v1/models: HTTP {response.status_code}"
            )
        data = response.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        return {
            str(item.get("id"))
            for item in items
            if isinstance(item, dict) and item.get("id")
        }


async def _get_cometapi_catalog() -> Dict[str, Any]:
    """Возвращает каталог CometAPI с кэшем и резервными данными."""

    global _catalog_state, _catalog_cached_at

    now = _now()
    if (
        _catalog_state is not None
        and _catalog_cached_at is not None
        and now - _catalog_cached_at
        < timedelta(seconds=IMAGE_CATALOG_TTL_SECONDS)
    ):
        return _catalog_state

    async with _catalog_lock:
        now = _now()
        if (
            _catalog_state is not None
            and _catalog_cached_at is not None
            and now - _catalog_cached_at
            < timedelta(seconds=IMAGE_CATALOG_TTL_SECONDS)
        ):
            return _catalog_state

        warnings: List[str] = []
        availability_checked = False
        server_models: List[Dict[str, Any]] = []
        available_ids: Optional[set] = None

        try:
            html = await _fetch_cometapi_page()
            server_models = _extract_server_models(html)
            card_prices = _extract_card_prices(html)
        except Exception as exc:
            warnings.append(
                "Не удалось обновить каталог CometAPI: "
                f"{_exception_text(exc)}"
            )
            card_prices = {}

        try:
            available_ids = await _fetch_cometapi_available_models()
            availability_checked = available_ids is not None
        except Exception as exc:
            warnings.append(
                "Не удалось проверить доступность моделей CometAPI: "
                f"{_exception_text(exc)}"
            )

        skipped_unpriced = 0
        if not server_models and _catalog_state and _catalog_state.get(
            "source"
        ) == "live":
            # Не теряем последний успешный живой каталог из-за временной
            # недоступности страницы CometAPI.
            previous = dict(_catalog_state)
            previous_warnings = list(previous.get("warnings", []))
            for warning in warnings:
                if warning not in previous_warnings:
                    previous_warnings.append(warning)
            previous["warnings"] = previous_warnings
            _catalog_state = previous
            _catalog_cached_at = _now()
            return previous

        if server_models:
            catalog = _build_cometapi_catalog(
                server_models, card_prices, available_ids
            )
            for model in server_models:
                if "text-to-image" not in (model.get("features") or []):
                    continue
                price, _, _ = _compute_model_price(
                    model, card_prices.get(str(model.get("id") or ""))
                )
                if price is None:
                    skipped_unpriced += 1
            source = "live"
        else:
            catalog = _fallback_cometapi_catalog()
            source = "fallback"
            if not warnings:
                warnings.append(
                    "Используются резервные данные каталога CometAPI."
                )

        state = {
            "models": catalog,
            "updated_at": _now(),
            "warnings": warnings,
            "availability_checked": availability_checked,
            "source": source,
            "skipped_unpriced": skipped_unpriced,
        }
        _catalog_state = state
        _catalog_cached_at = _now()
        return state


def _yandex_catalog() -> List[Dict[str, Any]]:
    """Каталог моделей YandexART."""

    models: List[Dict[str, Any]] = []
    for model in YANDEX_IMAGE_MODELS:
        short_name = _short_yandex_model(model)
        name = (
            "YandexART 3.0"
            if short_name == "aliceai-image-art-3.0"
            else short_name
        )
        models.append(
            {
                "id": short_name,
                "name": name,
                "provider": "Yandex",
                "endpoint_type": "yandex_images",
                "features": ["text-to-image"],
                "price_usd": YANDEX_IMAGE_PRICE_USD,
                "price_unit": "per_image",
                "price_is_estimated": True,
                "available": True,
                "note": (
                    "Цена задаётся настройкой YANDEX_IMAGE_PRICE_USD "
                    "и является оценкой по тарифам Yandex AI Studio."
                ),
            }
        )
    return models


async def get_image_models(max_price: float) -> Dict[str, Any]:
    """Возвращает каталог CometAPI и отдельный каталог YandexART."""

    state = await _get_cometapi_catalog()
    cometapi_models = [
        model
        for model in state.get("models", [])
        if model.get("available")
        and model.get("price_usd") is not None
        and float(model["price_usd"]) <= max_price
    ]
    yandex_models = [
        model
        for model in _yandex_catalog()
        if model.get("available")
        and model.get("price_usd") is not None
        and float(model["price_usd"]) <= max_price
    ]

    warnings = list(state.get("warnings", []))
    skipped = int(state.get("skipped_unpriced") or 0)
    if skipped:
        warnings.append(
            f"{skipped} моделей CometAPI не включены: не удалось определить "
            "минимальную стоимость одного изображения."
        )

    all_models = cometapi_models + yandex_models
    return {
        "currency": "USD",
        "default": COMETAPI_DEFAULT_IMAGE_MODEL,
        "default_yandex": _short_yandex_model(YANDEX_IMAGE_MODEL),
        "cometapi_models": cometapi_models,
        "yandex_models": yandex_models,
        "count": len(all_models),
        "updated_at": state.get("updated_at") or _now(),
        "availability_checked": bool(state.get("availability_checked")),
        "warnings": warnings,
    }
