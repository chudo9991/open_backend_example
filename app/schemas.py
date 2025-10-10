"""Pydantic schemas for request and response validation."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .models import WorkingFormatEnum


class UserBase(BaseModel):
    name: str = Field(..., description="Имя сотрудника", max_length=100)
    surname: str = Field(..., description="Фамилия сотрудника", max_length=100)
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
    city: Optional[str] = Field(None, max_length=100)
    working_format: Optional[WorkingFormatEnum] = None


class UserRead(UserBase):
    """Schema returned in responses for user data."""

    id: UUID
    created_at: datetime

    class Config:
        orm_mode = True
