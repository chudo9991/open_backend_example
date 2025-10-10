#!/usr/bin/env python3
"""Script to populate the database with fake user data."""
import random
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

from faker import Faker
from app.database import SessionLocal
from app.models import User, WorkingFormatEnum

fake = Faker('ru_RU')


def create_fake_users(count: int = 40) -> None:
    """Create fake users in the database."""
    db = SessionLocal()
    
    try:
        print(f"Создаю {count} фейковых пользователей...")
        
        for i in range(count):
            user = User(
                name=fake.first_name(),
                surname=fake.last_name(),
                email=fake.email(),
                phone=fake.phone_number(),
                city=fake.city(),
                working_format=random.choice(list(WorkingFormatEnum))
            )
            db.add(user)
            
            if (i + 1) % 10 == 0:
                print(f"Создано {i + 1} пользователей...")
        
        db.commit()
        print(f"✓ Успешно создано {count} пользователей!")
        
    except Exception as e:
        db.rollback()
        print(f"✗ Ошибка: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_fake_users(40)

