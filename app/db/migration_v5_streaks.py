import asyncio
from app.db.session import engine
from sqlalchemy import text

async def migrate_v5():
    async with engine.begin() as conn:
        try:
            # Add streak_days
            await conn.execute(text("ALTER TABLE users ADD COLUMN streak_days INTEGER DEFAULT 0"))
            print("Successfully added 'streak_days' column.")
        except Exception as e:
            print(f"Skip streak_days (probably exists): {e}")

        try:
            # Add last_forecast_date
            # SQLite DATE storage class is usually TEXT, NUMERIC or REAL. SQLAlchemy uses DATE.
            await conn.execute(text("ALTER TABLE users ADD COLUMN last_forecast_date DATE"))
            print("Successfully added 'last_forecast_date' column.")
        except Exception as e:
            print(f"Skip last_forecast_date (probably exists): {e}")

if __name__ == "__main__":
    asyncio.run(migrate_v5())
