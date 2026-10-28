# FastAPI application exposing CRUD operations for users.
from __future__ import annotations

import asyncio
from typing import List
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
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

# Ensure the database tables exist when the application starts.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Open Backend Example", version="0.1.0", description="Эксперименты в Кванториуме, 2025")


@app.on_event("startup")
async def on_startup() -> None:
    # Initialize the database and start AI worker when the application starts.
    init_db()
    # Launch background worker for AI queue.
    asyncio.create_task(process_ai_requests())


# Original JSON API root
@app.get("/")
def root() -> dict:
    # Return a greeting message.
    return {"message": "Hello Stranger!"}


@app.get("/users", response_model=List[schemas.UserRead])
def list_users(db: Session = Depends(get_db)) -> List[models.User]:
    # Return all users in the database.
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@app.post(
    "/users",
    response_model=schemas.UserRead,
    status_code=status.HTTP_201_CREATED,
)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)) -> models.User:
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


@app.get("/users/{user_id}", response_model=schemas.UserRead)
def get_user(user_id: UUID, db: Session = Depends(get_db)) -> models.User:
    # Retrieve a single user by ID.
    db_user = db.query(models.User).filter(models.User.id == str(user_id)).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user


@app.patch("/users/{user_id}", response_model=schemas.UserRead)
def update_user(
    user_id: UUID, user_update: schemas.UserUpdate, db: Session = Depends(get_db)
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


@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_user(user_id: UUID, db: Session = Depends(get_db)) -> None:
    # Delete a user from the database.
    db_user = db.query(models.User).filter(models.User.id == str(user_id)).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(db_user)
    db.commit()


# Chat endpoints
@app.get("/messages", response_model=List[schemas.MessageRead])
def list_messages(db: Session = Depends(get_db)) -> List[models.Message]:
    # Return all chat messages oldest first.
    return db.query(models.Message).order_by(models.Message.created_at).all()


@app.post(
    "/messages",
    response_model=schemas.MessageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_message(message: schemas.MessageCreate, db: Session = Depends(get_db)) -> models.Message:
    # Store a new chat message.
    db_message = models.Message(**message.dict())
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message


@app.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_message(message_id: UUID, author: str, db: Session = Depends(get_db)) -> None:
    # Delete a message, but only the author's own message.
    db_message = db.query(models.Message).filter(models.Message.id == str(message_id)).first()
    if db_message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if db_message.author != author:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")

    db.delete(db_message)
    db.commit()


# AI Endpoints
@app.post("/ai/generate", response_model=schemas.AIResponse)
async def generate_text(request: schemas.AIGenerateRequest):
    # Generate text with the AI model.
    return await queue_ai_request(request.prompt, request.model)


@app.post("/ai/chat", response_model=schemas.AIResponse)
async def chat_with_ai(request: schemas.AIChatRequest):
    # Chat with the AI model.
    # Преобразуем сообщения в промпт
    prompt = "\n".join([f"{msg['role']}: {msg['content']}" for msg in request.messages])
    return await queue_ai_request(prompt, request.model or DEFAULT_MODEL)


@app.get("/ai/models")
async def list_models():
    # List of available AI models.
    try:
        models = await list_yandex_models()
    except Exception:
        models = []
    if not models:
        models = [DEFAULT_MODEL]

    return {"models": models, "default": DEFAULT_MODEL}


@app.get("/ai/queue/status")
async def queue_status():
    # Status of the AI task queue.
    return {
        "queue_size": ai_queue.qsize(),
        "max_queue_size": ai_queue.maxsize,
        "processing_tasks": len(processing_tasks)
    }
