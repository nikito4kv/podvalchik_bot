import asyncio
import logging
import os
from sqlalchemy import text, insert
from sqlalchemy.ext.asyncio import create_async_engine

# Import models
from app.db.models import (
    Base, User, Season, Player, Tournament, 
    SeasonResult, Forecast, BugReport, tournament_participants
)

# Configs
SQLITE_URL = "sqlite+aiosqlite:///./app1.db"
# Explicitly set Postgres URL matching docker-compose
POSTGRES_URL = "postgresql+asyncpg://podval_user:podval_password@localhost:5432/podval_bot_db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate_table(sqlite_conn, pg_conn, table_obj, table_name):
    logger.info(f"Migrating table: {table_name}...")
    
    # Read from SQLite
    result = await sqlite_conn.execute(text(f"SELECT * FROM {table_name}"))
    rows = result.fetchall()
    
    if not rows:
        logger.info(f"No data in {table_name}, skipping.")
        return

    # Convert rows to list of dicts for bulk insert
    # We need to map columns correctly. `rows` are Row objects (tuple-like but accessible by key in some drivers)
    # SQLAlchemy Core rows map to keys.
    
    # Get column names
    keys = result.keys()
    data_to_insert = []
    
    for row in rows:
        # Convert Row to dict
        row_dict = dict(zip(keys, row))
        
        # Handle JSON fields if necessary? SQLAlchemy usually handles this if column type is JSON.
        # But in SQLite raw SELECT, JSON columns come out as strings? 
        # No, aiosqlite returns them as strings usually unless parsed.
        # However, we are inserting into a model that expects dict/list for JSON columns.
        # If SQLite returns string for a JSON column, we might need to json.loads it?
        # Let's check which tables have JSON.
        # SeasonResult.user_snapshot
        # Tournament.results
        # Forecast.prediction_data
        
        # Let's verify manually for JSON columns
        import json
        from datetime import date, datetime
        
        json_cols = ['user_snapshot', 'results', 'prediction_data']
        for col in json_cols:
            if col in row_dict and isinstance(row_dict[col], str):
                try:
                    row_dict[col] = json.loads(row_dict[col])
                except Exception:
                    pass # Maybe it's already None or not a string

        # Handle Date/DateTime columns (SQLite returns str, Postgres expects date/datetime object)
        date_cols = ['start_date', 'end_date', 'date', 'last_forecast_date']
        datetime_cols = ['created_at']
        
        for col in date_cols:
            if col in row_dict and isinstance(row_dict[col], str):
                try:
                    # SQLite stores dates as ISO strings usually
                    row_dict[col] = date.fromisoformat(row_dict[col])
                except ValueError:
                    pass # Keep as is if parsing fails

        for col in datetime_cols:
            if col in row_dict and isinstance(row_dict[col], str):
                try:
                    # SQLite datetime format might vary, but ISO is common.
                    # Usually "YYYY-MM-DD HH:MM:SS.mmmmmm" or similar
                    # fromisoformat handles most ISO formats in modern Python
                    row_dict[col] = datetime.fromisoformat(row_dict[col])
                except ValueError:
                    # Fallback for simpler formats if needed, or keeping it str might fail later
                    pass 
        
        data_to_insert.append(row_dict)

    # Insert into Postgres
    # We use core insert.
    if data_to_insert:
        # Disable foreign key checks? No, we insert in order.
        # But we need to keep IDs.
        await pg_conn.execute(insert(table_obj), data_to_insert)
        logger.info(f"Inserted {len(data_to_insert)} rows into {table_name}.")
        
        # Reset sequence
        # Find PK column
        pk_col = list(table_obj.primary_key.columns)[0].name
        seq_name = f"{table_name}_{pk_col}_seq"
        
        # Check if sequence exists (usually defaults to table_id_seq)
        # For 'users', id is not autoincrement in the model definition (it's Telegram ID)? 
        # "id = Column(Integer, primary_key=True)" - if no autoincrement=True, but Integer PK usually is serial.
        # But Telegram IDs are huge, we don't want a sequence there usually.
        # However, for others like Forecasts, it is autoincrement.
        
        if table_name != "users":
             try:
                 # Postgres specific: setval
                 max_id = max(d[pk_col] for d in data_to_insert)
                 
                 # Use nested transaction (SAVEPOINT) so if setval fails, it doesn't abort the main transaction
                 async with pg_conn.begin_nested():
                    await pg_conn.execute(text(f"SELECT setval('{seq_name}', {max_id})"))
             except Exception as e:
                 logger.warning(f"Could not reset sequence for {table_name} (might not exist or custom): {e}")

async def main():
    sqlite_engine = create_async_engine(SQLITE_URL)
    pg_engine = create_async_engine(POSTGRES_URL)

    async with sqlite_engine.connect() as sqlite_conn:
        async with pg_engine.begin() as pg_conn: # Transaction
            # Order matters!
            
            # 1. Users (no FK)
            await migrate_table(sqlite_conn, pg_conn, User.__table__, "users")
            
            # 2. Seasons (no FK)
            await migrate_table(sqlite_conn, pg_conn, Season.__table__, "seasons")
            
            # 3. Players (no FK)
            await migrate_table(sqlite_conn, pg_conn, Player.__table__, "players")
            
            # 4. Tournaments (uses Players via secondary, but table itself depends on nothing? No, wait)
            # Tournament has no FKs in columns, only relationship. So safe.
            await migrate_table(sqlite_conn, pg_conn, Tournament.__table__, "tournaments")
            
            # 5. Tournament Participants (Association table)
            # Depends on Tournaments and Players.
            await migrate_table(sqlite_conn, pg_conn, tournament_participants, "tournament_participants")
            
            # 6. Season Results (FK to Season, User)
            await migrate_table(sqlite_conn, pg_conn, SeasonResult.__table__, "season_results")
            
            # 7. Forecasts (FK to User, Tournament)
            await migrate_table(sqlite_conn, pg_conn, Forecast.__table__, "forecasts")
            
            # 8. Bug Reports (FK to User)
            await migrate_table(sqlite_conn, pg_conn, BugReport.__table__, "bug_reports")
            
            logger.info("Migration completed successfully!")

    await sqlite_engine.dispose()
    await pg_engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())