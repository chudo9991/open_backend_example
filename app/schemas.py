"""Pydantic schemas for request and response validation."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .models import WorkingFormatEnum


class UserBase(BaseModel):
    name: str = Field(..., description="Employee first name", max_length=100)
    surname: str = Field(..., description="Employee last name", max_length=100)
    email: Optional[str] = Field(None, description="Employee email", max_length=255)
    phone: Optional[str] = Field(None, description="Employee phone number", max_length=20)
    city: Optional[str] = Field(None, description="City of residence", max_length=100)
    working_format: WorkingFormatEnum = Field(
        WorkingFormatEnum.REMOTE, description="Working format"
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


# Chat schemas
class MessageCreate(BaseModel):
    """Schema for creating a chat message."""

    author: str = Field(..., max_length=100)
    text: str = Field(..., max_length=256)


class MessageRead(MessageCreate):
    """Schema returned in responses for chat messages."""

    id: UUID
    created_at: datetime

    class Config:
        orm_mode = True


# AI Schemas
class AIGenerateRequest(BaseModel):
    """Schema for AI text generation requests."""
    prompt: str = Field(..., description="Prompt text", max_length=2000)
    model: str = Field("lakomoor/vikhr-llama-3.2-1b-instruct:1b", description="Model name")
    max_tokens: Optional[int] = Field(100, description="Maximum tokens")
    temperature: Optional[float] = Field(0.7, description="Temperature (0.0-1.0)")


class AIChatRequest(BaseModel):
    """Schema for AI chat requests."""
    messages: List[dict] = Field(..., description="Chat messages")
    model: str = Field("lakomoor/vikhr-llama-3.2-1b-instruct:1b", description="Model name")


class AIResponse(BaseModel):
    """Schema for AI responses."""
    id: str
    response: str
    status: str
    model: str
    created_at: datetime
