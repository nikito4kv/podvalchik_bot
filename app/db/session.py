from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.config import config
from app.db.models import Base

# Создаем асинхронный "движок" для нашей базы данных
# echo=True будет выводить в консоль все SQL-запросы, полезно для отладки
engine = create_async_engine(config.database_url, echo=False)

# Создаем фабрику сессий, через которую мы будем подключаться к БД
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    """
    Функция для инициализации таблиц в базе данных.
    """
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all) # Раскомментируйте для удаления всех таблиц при перезапуске
        # await conn.run_sync(Base.metadata.create_all)
        pass
