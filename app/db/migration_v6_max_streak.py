import asyncio
from app.db.session import engine
from sqlalchemy import text

async def migrate_v6():
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN max_streak INTEGER DEFAULT 0"))
            print("Successfully added 'max_streak' column.")
        except Exception as e:
            print(f"Skip max_streak (probably exists): {e}")

if __name__ == "__main__":
    asyncio.run(migrate_v6())
