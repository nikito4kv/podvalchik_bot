import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage # Added
from redis.asyncio import Redis # Added
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from app.config import config
from app.db.session import init_db
from app.handlers import (
    common,
    admin,
    prediction,
    tournament_management,
    pagination,
    player_management,
    feedback
)
from app.middlewares.auth import AuthMiddleware
from app.scripts.migrate_seasons import migrate_seasons
from app.core.scheduler_tasks import scheduled_season_rotation

# Включаем логирование, чтобы видеть информацию о работе бота
logging.basicConfig(level=logging.INFO)

async def main():
    """
    Главная функция, запускающая бота
    """
    # Инициализация бота
    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    
    # Инициализация Redis для FSM
    redis = Redis(host=config.redis_host, port=config.redis_port)
    storage = RedisStorage(redis=redis)
    
    # Диспетчер с Redis хранилищем
    dp = Dispatcher(storage=storage)

    # Middleware
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # Регистрируем роутеры
    dp.include_router(admin.router)
    dp.include_router(feedback.router)
    dp.include_router(tournament_management.router)
    dp.include_router(player_management.router)
    dp.include_router(pagination.router) 
    dp.include_router(prediction.router)
    dp.include_router(common.router)

    # Инициализируем базу данных
    await init_db()
    
    # Run initial season check on startup to ensure current season exists
    await migrate_seasons()

    # Scheduler Setup
    scheduler = AsyncIOScheduler(timezone=pytz.timezone('Asia/Tbilisi'))
    
    # Run every Monday at 00:00 Tbilisi time
    scheduler.add_job(
        scheduled_season_rotation,
        trigger=CronTrigger(day_of_week='mon', hour=0, minute=0)
    )
    scheduler.start()

    # Удаляем старые вебхуки и запускаем поллинг
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())