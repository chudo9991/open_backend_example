"""AI сервис для работы с Yandex AI Studio через очередь."""
import asyncio
import os
import uuid
from datetime import datetime
from asyncio import Queue
from typing import Dict

import httpx  # type: ignore[import]

from .schemas import AIResponse

# Константы конфигурации
YANDEX_BASE_URL = "https://ai.api.cloud.yandex.net/v1"
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
DEFAULT_MODEL = os.getenv("YANDEX_DEFAULT_MODEL", "yandexgpt-lite")


# Глобальная очередь и воркер
ai_queue = Queue(maxsize=50)
processing_tasks: Dict[str, asyncio.Task] = {}


def _headers() -> dict:
    """Заголовки авторизации Yandex AI Studio."""
    if not all([YANDEX_API_KEY, YANDEX_FOLDER_ID]):
        raise RuntimeError(
            "Yandex AI Studio не настроен. Задайте YANDEX_API_KEY и YANDEX_FOLDER_ID."
        )
    return {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "OpenAI-Project": YANDEX_FOLDER_ID,
        "Content-Type": "application/json",
    }


def _resolve_model(model: str) -> str:
    """Принимает полный URI ``gpt://...`` или короткое имя модели."""
    if "://" in model:
        return model
    return f"gpt://{YANDEX_FOLDER_ID}/{model}/latest"


def yandex_headers() -> dict:
    """Публичная обёртка над заголовками Yandex AI Studio.

    Используется другими частями приложения, чтобы не дублировать логику
    авторизации и проверку настроек каталога.
    """
    return _headers()


def resolve_art_model(model: str) -> str:
    """Принимает короткое имя YandexART или полный URI ``art://...``."""
    if not YANDEX_FOLDER_ID:
        raise RuntimeError(
            "Yandex AI Studio не настроен. Задайте YANDEX_FOLDER_ID."
        )
    if "://" in model:
        return model
    return f"art://{YANDEX_FOLDER_ID}/{model}"


async def call_yandex(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Вызов chat/completions Yandex AI Studio (OpenAI-совместимый API)."""
    payload = {
        "model": _resolve_model(model),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{YANDEX_BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:  # pragma: no cover - safety net
        raise RuntimeError("Некорректный ответ от Yandex AI Studio") from exc


async def list_yandex_models() -> list:
    """Список доступных chat-моделей Yandex AI Studio."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{YANDEX_BASE_URL}/models", headers=_headers())
        response.raise_for_status()
        data = response.json()
    return [m["id"] for m in data.get("data", []) if m["id"].startswith("gpt://")]


async def process_ai_requests() -> None:
    """Воркер для обработки очереди AI запросов."""
    while True:
        request = await ai_queue.get()
        try:
            request_id = request["id"]
            model_name = request.get("model") or DEFAULT_MODEL

            result = await call_yandex(request["prompt"], model_name)

            request["future"].set_result(
                AIResponse(
                    id=request_id,
                    response=result,
                    status="completed",
                    model=model_name,
                    created_at=datetime.now(),
                )
            )
        except Exception as exc:  # pragma: no cover - safety net
            request["future"].set_exception(exc)
        finally:
            ai_queue.task_done()


async def queue_ai_request(
    prompt: str, model: str = DEFAULT_MODEL
) -> AIResponse:
    """Добавить запрос в очередь и дождаться результата."""
    request_id = str(uuid.uuid4())
    future = asyncio.Future()

    await ai_queue.put(
        {
            "id": request_id,
            "prompt": prompt,
            "model": model,
            "future": future,
        }
    )

    return await future
