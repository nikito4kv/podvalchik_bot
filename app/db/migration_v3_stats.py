import asyncio
from app.db.session import engine
from sqlalchemy import text

async def migrate_v3():
    async with engine.begin() as conn:
        try:
            # Add new stats columns
            await conn.execute(text("ALTER TABLE users ADD COLUMN tournaments_played INTEGER DEFAULT 0"))
            print("Added 'tournaments_played'")
        except Exception as e: print(f"Skip tournaments_played: {e}")
            
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN exact_guesses INTEGER DEFAULT 0"))
            print("Added 'exact_guesses'")
        except Exception as e: print(f"Skip exact_guesses: {e}")
            
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN perfect_tournaments INTEGER DEFAULT 0"))
            print("Added 'perfect_tournaments'")
        except Exception as e: print(f"Skip perfect_tournaments: {e}")

if __name__ == "__main__":
    asyncio.run(migrate_v3())
