import asyncio
from app.db.session import engine
from sqlalchemy import text

async def migrate():
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE tournaments ADD COLUMN prediction_count INTEGER DEFAULT 5"))
            print("Successfully added 'prediction_count' column to 'tournaments' table.")
        except Exception as e:
            print(f"Migration failed (column might already exist): {e}")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(migrate())