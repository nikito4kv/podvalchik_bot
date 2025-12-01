import asyncio
from sqlalchemy import text
from app.db.session import engine

async def run_migrations():
    print("🔄 Starting schema migration for legacy database...")
    
    async with engine.begin() as conn:
        # 1. Update Users Table
        print("Checking 'users' table...")
        user_columns = [
            ("total_slots", "INTEGER DEFAULT 0"),
            ("tournaments_played", "INTEGER DEFAULT 0"),
            ("exact_guesses", "INTEGER DEFAULT 0"),
            ("perfect_tournaments", "INTEGER DEFAULT 0"),
            ("accuracy_rate", "FLOAT DEFAULT 0.0"),
            ("avg_error", "FLOAT DEFAULT 0.0")
        ]
        
        for col_name, col_type in user_columns:
            try:
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                print(f"✅ Added column 'users.{col_name}'")
            except Exception as e:
                if "duplicate column name" in str(e).lower():
                    print(f"ℹ️ Column 'users.{col_name}' already exists.")
                else:
                    print(f"⚠️ Error adding 'users.{col_name}': {e}")

        # 2. Update Tournaments Table
        print("Checking 'tournaments' table...")
        try:
            await conn.execute(text("ALTER TABLE tournaments ADD COLUMN prediction_count INTEGER DEFAULT 5"))
            print("✅ Added column 'tournaments.prediction_count'")
        except Exception as e:
            if "duplicate column name" in str(e).lower():
                 print("ℹ️ Column 'tournaments.prediction_count' already exists.")
            else:
                 print(f"⚠️ Error adding 'tournaments.prediction_count': {e}")

        # 3. Update Players Table
        print("Checking 'players' table...")
        try:
            await conn.execute(text("ALTER TABLE players ADD COLUMN is_active INTEGER DEFAULT 1"))
            print("✅ Added column 'players.is_active'")
        except Exception as e:
            if "duplicate column name" in str(e).lower():
                 print("ℹ️ Column 'players.is_active' already exists.")
            else:
                 print(f"⚠️ Error adding 'players.is_active': {e}")

    print("🏁 Schema migration completed.\n")

if __name__ == "__main__":
    asyncio.run(run_migrations())
