import asyncio
import datetime
from sqlalchemy import text, select
from app.db.session import engine
from app.db.models import Forecast
from sqlalchemy.ext.asyncio import async_sessionmaker

async def run_migration():
    print("Adding 'created_at' to 'forecasts'...")
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE forecasts ADD COLUMN created_at DATETIME"))
            print("✅ Column added.")
        except Exception as e:
            if "duplicate" in str(e).lower():
                print("ℹ️ Column already exists.")
            else:
                print(f"⚠️ Error adding column: {e}")

    print("Filling existing data...")
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    async with async_session() as session:
        forecasts = (await session.execute(select(Forecast))).scalars().all()
        print(f"Updating {len(forecasts)} forecasts...")
        
        base_time = datetime.datetime(2024, 1, 1, 0, 0, 0)
        
        count = 0
        for f in forecasts:
            if not f.created_at:
                # Fake time based on ID to preserve order
                fake_time = base_time + datetime.timedelta(seconds=f.id)
                f.created_at = fake_time
                count += 1
        
        await session.commit()
        print(f"✅ Updated {count} records.")

if __name__ == "__main__":
    asyncio.run(run_migration())