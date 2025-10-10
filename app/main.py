"""FastAPI application exposing CRUD operations for users."""
from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas
from .database import Base, engine, get_db, init_db

# Ensure the database tables exist when the application starts.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Open Backend Example", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    """Initialize the database when the application starts."""
    init_db()


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


@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: UUID, db: Session = Depends(get_db)) -> None:
    """Delete a user from the database."""
    db_user = db.query(models.User).filter(models.User.id == str(user_id)).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(db_user)
    db.commit()
