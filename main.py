import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.config import BOT_TOKEN
from app.db.session import init_db
from app.handlers import common, admin, prediction, tournament_management, pagination, player_management

# Включаем логирование, чтобы видеть информацию о работе бота
logging.basicConfig(level=logging.INFO)

async def main():
    """
    Главная функция, запускающая бота
    """
    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    # Регистрируем роутеры
    dp.include_router(admin.router)
    dp.include_router(tournament_management.router)
    dp.include_router(player_management.router)
    dp.include_router(pagination.router) 
    dp.include_router(prediction.router)
    dp.include_router(common.router)

    # Инициализируем базу данных
    await init_db()

    # Удаляем старые вебхуки и запускаем поллинг
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
