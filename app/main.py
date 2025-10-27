"""FastAPI application exposing CRUD operations for users."""
from __future__ import annotations

import asyncio
from typing import List
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas
from .ai_service import process_ai_requests, queue_ai_request, ai_queue, processing_tasks
from .database import Base, engine, get_db, init_db

# Ensure the database tables exist when the application starts.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Open Backend Example", version="0.1.0")


@app.on_event("startup")
async def on_startup() -> None:
    """Initialize the database and start AI worker when the application starts."""
    init_db()
    # Запускаем AI воркер
    asyncio.create_task(process_ai_requests())


@app.get("/")
def root() -> dict:
    """Return a greeting message."""
    return {"message": "Hello Stranger!"}


@app.get("/users", response_model=List[schemas.UserRead])
def list_users(db: Session = Depends(get_db)) -> List[models.User]:
    """Return all users in the database."""
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@app.post(
    "/users",
    response_model=schemas.UserRead,
    status_code=status.HTTP_201_CREATED,
)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)) -> models.User:
    """Create a new user entry."""
    db_user = models.User(**user.dict())
    db.add(db_user)
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - runtime safeguard
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(db_user)
    return db_user


@app.get("/users/{user_id}", response_model=schemas.UserRead)
def get_user(user_id: UUID, db: Session = Depends(get_db)) -> models.User:
    """Retrieve a single user by their identifier."""
    db_user = db.query(models.User).filter(models.User.id == str(user_id)).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user


@app.patch("/users/{user_id}", response_model=schemas.UserRead)
def update_user(
    user_id: UUID, user_update: schemas.UserUpdate, db: Session = Depends(get_db)
) -> models.User:
    """Partially update a user's data."""
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


@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_user(user_id: UUID, db: Session = Depends(get_db)) -> None:
    """Delete a user from the database."""
    db_user = db.query(models.User).filter(models.User.id == str(user_id)).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(db_user)
    db.commit()


# AI Endpoints
@app.post("/ai/generate", response_model=schemas.AIResponse)
async def generate_text(request: schemas.AIGenerateRequest):
    """Генерация текста с помощью qwen3:0.6b"""
    return await queue_ai_request(request.prompt, "qwen3:0.6b")


@app.post("/ai/chat", response_model=schemas.AIResponse)
async def chat_with_ai(request: schemas.AIChatRequest):
    """Чат с AI моделью"""
    # Преобразуем сообщения в промпт
    prompt = "\n".join([f"{msg['role']}: {msg['content']}" for msg in request.messages])
    return await queue_ai_request(prompt, request.model)


@app.get("/ai/models")
async def list_models():
    """Список доступных моделей"""
    return {
        "models": ["qwen3:0.6b"],
        "default": "qwen3:0.6b"
    }


@app.get("/ai/queue/status")
async def queue_status():
    """Статус очереди AI запросов"""
    return {
        "queue_size": ai_queue.qsize(),
        "max_queue_size": ai_queue.maxsize,
        "processing_tasks": len(processing_tasks)
    }
