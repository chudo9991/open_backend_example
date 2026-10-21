"""AI сервис для работы с Ollama и Azure OpenAI через очередь."""
import asyncio
import os
import uuid
from datetime import datetime
from asyncio import Queue
from typing import Dict

import httpx  # type: ignore[import]

from .schemas import AIResponse

# Константы конфигурации
DEFAULT_MODEL = "lakomoor/vikhr-llama-3.2-1b-instruct:1b"
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv(
    "AZURE_OPENAI_DEPLOYMENT_NAME"
)
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01")


# Глобальная очередь и воркер
ai_queue = Queue(maxsize=50)
processing_tasks: Dict[str, asyncio.Task] = {}


async def call_ollama(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Прямой вызов Ollama API."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "http://open_backend_example-ollama-1:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
            },
        )
        response.raise_for_status()
        return response.json()["response"]


async def call_azure_openai(prompt: str) -> str:
    """Вызов Azure OpenAI для модели gpt-4o."""
    if not all([AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT]):
        raise RuntimeError("Azure OpenAI не настроен. Проверьте переменные окружения.")

    url = (
        f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/"
        f"{AZURE_OPENAI_DEPLOYMENT}/chat/completions"
    )
    params = {"api-version": AZURE_OPENAI_API_VERSION}
    headers = {
        "api-key": AZURE_OPENAI_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, params=params, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:  # pragma: no cover - safety net
        raise RuntimeError("Некорректный ответ от Azure OpenAI") from exc


async def dispatch_request(prompt: str, model: str) -> str:
    """Маршрутизирует запрос к соответствующей модели."""
    if model.lower() == "gpt-4o":
        return await call_azure_openai(prompt)
    return await call_ollama(prompt, model)


async def process_ai_requests() -> None:
    """Воркер для обработки очереди AI запросов."""
    while True:
        request = await ai_queue.get()
        try:
            request_id = request["id"]
            model_name = request.get("model", DEFAULT_MODEL)

            result = await dispatch_request(request["prompt"], model_name)

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
