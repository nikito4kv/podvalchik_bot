import asyncio
from sqlalchemy import text
from app.db.session import engine, Base

async def migrate():
    async with engine.begin() as conn:
        # Check if tables exist
        # We'll just try to create them. SQLAlchemy handles "if not exists" usually? 
        # No, create_all does. But for existing DB we need to be careful.
        # Let's just run raw SQL to be safe and simple for SQLite.
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number INTEGER NOT NULL UNIQUE,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                status VARCHAR DEFAULT 'active'
            );
        """))
        
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS season_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                rank INTEGER NOT NULL,
                points INTEGER NOT NULL,
                tournaments_played INTEGER DEFAULT 0,
                user_snapshot JSON,
                FOREIGN KEY(season_id) REFERENCES seasons(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
        """))
        
        print("Migration v4 (Seasons) applied successfully.")

if __name__ == "__main__":
    asyncio.run(migrate())
