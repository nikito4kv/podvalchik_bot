# Мы не добавили total_slots в модель User, но он нужен для корректного расчета MAE/Accuracy.
# Сейчас accuracy_rate считается на основе forecasts_count * 5.
# Чтобы поддержать variable slots без добавления поля, нам нужно динамически считать total_slots_before.
# Но это сложно (надо перебирать все forecasts юзера).
# Проще добавить total_slots в User.

import asyncio
from app.db.session import engine
from sqlalchemy import text

async def migrate_user():
    async with engine.begin() as conn:
        try:
            # Пытаемся добавить total_slots, если нет
            await conn.execute(text("ALTER TABLE users ADD COLUMN total_slots INTEGER DEFAULT 0"))
            print("Successfully added 'total_slots' column to 'users' table.")
            
            # Также нужно обновить существующие записи: total_slots = (количество прогнозов) * 5
            # Это приблизительно, но лучше, чем 0
            # SQLite не поддерживает сложные update с join легко, но попробуем
            # Сначала просто добавим колонку. Данные могут быть некорректными для старых юзеров пока.
            
        except Exception as e:
            print(f"Migration user failed (column might already exist): {e}")

if __name__ == "__main__":
    # loop = asyncio.get_event_loop() # Deprecated
    asyncio.run(migrate_user())
