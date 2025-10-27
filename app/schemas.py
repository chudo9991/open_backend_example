"""Pydantic schemas for request and response validation."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .models import WorkingFormatEnum


class UserBase(BaseModel):
    name: str = Field(..., description="Имя сотрудника", max_length=100)
    surname: str = Field(..., description="Фамилия сотрудника", max_length=100)
    email: Optional[str] = Field(None, description="Email сотрудника", max_length=255)
    phone: Optional[str] = Field(None, description="Номер телефона", max_length=20)
    city: Optional[str] = Field(None, description="Город проживания", max_length=100)
    working_format: WorkingFormatEnum = Field(
        WorkingFormatEnum.REMOTE, description="Формат работы"
    )


class UserCreate(UserBase):
    """Schema for user creation."""


class UserUpdate(BaseModel):
    """Schema for partial updates of a user."""

    name: Optional[str] = Field(None, max_length=100)
    surname: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    city: Optional[str] = Field(None, max_length=100)
    working_format: Optional[WorkingFormatEnum] = None


class UserRead(UserBase):
    """Schema returned in responses for user data."""

    id: UUID
    created_at: datetime

    class Config:
        orm_mode = True


# AI Schemas
class AIGenerateRequest(BaseModel):
    """Schema for AI text generation requests."""
    prompt: str = Field(..., description="Текст для генерации", max_length=2000)
    max_tokens: Optional[int] = Field(100, description="Максимальное количество токенов")
    temperature: Optional[float] = Field(0.7, description="Температура генерации (0.0-1.0)")


class AIChatRequest(BaseModel):
    """Schema for AI chat requests."""
    messages: List[dict] = Field(..., description="Список сообщений для чата")
    model: str = Field("qwen3:0.6b", description="Модель для использования")


class AIResponse(BaseModel):
    """Schema for AI responses."""
    id: str
    response: str
    status: str
    model: str
    created_at: datetime
