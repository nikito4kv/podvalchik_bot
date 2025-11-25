from aiogram import Router, types, F
from aiogram.filters import CommandStart
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.reply import main_menu
from app.db.models import User
from app.db.session import async_session

router = Router()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    """
    Стартовый хэндлер. Проверяет, есть ли пользователь в базе,
    добавляет его, если нет, и показывает главное меню.
    """
    async with async_session() as session:
        # Проверяем, есть ли пользователь в базе
        user = await session.get(User, message.from_user.id)
        if not user:
            # Если пользователя нет, создаем нового
            new_user = User(
                id=message.from_user.id,
                username=message.from_user.username or "unknown"
            )
            session.add(new_user)
            await session.commit()
            await message.answer(
                "Добро пожаловать! Я бот для прогнозов на настольный теннис. "
                "Я зарегистрировал вас в системе. Вот главное меню:",
                reply_markup=main_menu
            )
        else:
            await message.answer(
                f"С возвращением, {message.from_user.first_name}! Вот главное меню:",
                reply_markup=main_menu
            )


@router.message(F.text == "📊 Моя статистика")
async def handle_my_stats(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            # Этого не должно произойти, если пользователь видит кнопку
            await message.answer("Не удалось найти вашу статистику. Попробуйте /start")
            return

    stats_text = (
        f"<b>📊 Ваша статистика</b>\n\n"
        f"🏆 <b>Общий счет:</b> {user.total_points}\n"
        f"🎯 <b>Точность (Sniper Rate):</b> {user.accuracy_rate:.2f}%\n"
        f"📉 <b>Средняя ошибка (MAE):</b> {user.avg_error:.2f}\n\n"
        f"<i>Точность - это % точных угадываний места.</i>\n"
        f"<i>Средняя ошибка - среднее отклонение от фактического места (чем ниже, тем лучше).</i>"
    )
    await message.answer(stats_text)


@router.message(F.text == "🏆 Рейтинг клуба")
async def handle_leaderboard(message: types.Message):
    async with async_session() as session:
        top_users_result = await session.execute(
            select(User).order_by(User.total_points.desc()).limit(10)
        )
        top_users = top_users_result.scalars().all()

    if not top_users:
        await message.answer("Рейтинг пока пуст. Сделайте первый прогноз!")
        return

    leaderboard_text = "<b>🏆 Топ-10 прогнозистов клуба:</b>\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, user in enumerate(top_users, 1):
        place = medals.get(i, f" {i}.")
        username = user.username or "id" + str(user.id)
        leaderboard_text += f"{place} @{username} - <b>{user.total_points}</b> очков\n"

    await message.answer(leaderboard_text)


@router.message(F.text == "ℹ️ Правила")
async def handle_rules(message: types.Message):
    rules_text = """
    <b>Правила игры:</b>

    1.  Перед каждым турниром вы делаете прогноз на <b>Топ-5</b> мест.
    2.  Выбор 5 <b>уникальных</b> игроков обязателен.
    3.  Прием прогнозов закрывается перед началом турнира.

    <b>Начисление очков:</b>
    - За каждого угаданного игрока в Топ-5 вы получаете очки.
    - Чем ближе ваш прогноз к реальному месту, тем больше очков.
    - Формула: <code>Очки = max(0, 100 - (|Прогноз - Факт| * 15))</code>
    - <b>Бонус +20 очков</b> за точное попадание (место в место).
    - Если игрок не попал в Топ-5, за него вы получаете 0 очков.

    Удачи!
    """
    await message.answer(rules_text, parse_mode="HTML")
