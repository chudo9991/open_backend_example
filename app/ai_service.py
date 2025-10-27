"""AI сервис для работы с Ollama через очередь."""
import asyncio
import httpx
import uuid
from datetime import datetime
from asyncio import Queue
from typing import Dict, Optional

from .schemas import AIResponse

# Глобальная очередь и воркер
ai_queue = Queue(maxsize=50)
processing_tasks: Dict[str, asyncio.Task] = {}

async def call_ollama(prompt: str, model: str = "qwen3:0.6b") -> str:
    """Прямой вызов Ollama API"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "http://open_backend_example-ollama-1:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            }
        )
        response.raise_for_status()
        return response.json()["response"]

async def process_ai_requests():
    """Воркер для обработки очереди AI запросов"""
    while True:
        try:
            request = await ai_queue.get()
            request_id = request['id']
            
            # Обрабатываем запрос
            result = await call_ollama(
                request['prompt'], 
                request.get('model', 'qwen3:0.6b')
            )
            
            # Возвращаем результат
            request['future'].set_result(AIResponse(
                id=request_id,
                response=result,
                status='completed',
                model=request.get('model', 'qwen3:0.6b'),
                created_at=datetime.now()
            ))
            
        except Exception as e:
            request['future'].set_exception(e)
        finally:
            ai_queue.task_done()

async def queue_ai_request(prompt: str, model: str = "qwen3:0.6b") -> AIResponse:
    """Добавить запрос в очередь и дождаться результата"""
    request_id = str(uuid.uuid4())
    future = asyncio.Future()
    
    await ai_queue.put({
        'id': request_id,
        'prompt': prompt,
        'model': model,
        'future': future
    })
    
    return await future
