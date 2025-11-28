from aiogram import Router, types, F
from aiogram.filters import CommandStart
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.keyboards.reply import main_menu
from app.keyboards.inline import (
    my_forecasts_menu_kb,
    active_tournaments_kb,
    view_forecast_kb,
    forecast_history_kb,
    confirmation_kb,
)
from app.db.models import User, Tournament, Forecast, TournamentStatus, Player
from app.db.session import async_session
from app.utils.formatting import format_player_list, get_medal_str

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
                username=message.from_user.username or "unknown",
            )
            session.add(new_user)
            await session.commit()
            await message.answer(
                "Добро пожаловать! Я бот для прогнозов на настольный теннис. "
                "Я зарегистрировал вас в системе. Вот главное меню:",
                reply_markup=main_menu,
            )
        else:
            await message.answer(
                f"С возвращением, {message.from_user.first_name}! Вот главное меню:",
                reply_markup=main_menu,
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
    for i, user in enumerate(top_users, 1):
        place = get_medal_str(i)
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
    - Формула: <code>Очки = max(0, (100 - (|Прогноз - Факт| * 15)) / 10)</code>
    - <b>Бонус +2 очка</b> за точное попадание (место в место).
    - Если игрок не попал в Топ-5, за него вы получаете 0 очков.

    Удачи!
    """
    await message.answer(rules_text, parse_mode="HTML")


@router.message(F.text == "🔮 Прогнозы")
async def handle_my_forecasts(message: types.Message):
    """
    Shows the menu for viewing active or past forecasts.
    """
    await message.answer(
        "Выберите, какие прогнозы вы хотите посмотреть:",
        reply_markup=my_forecasts_menu_kb(),
    )


@router.callback_query(F.data == "back_to_forecasts_menu")
async def back_to_forecasts_menu(callback_query: types.CallbackQuery):
    """
    Returns the user to the main forecasts menu.
    """
    await callback_query.message.edit_text(
        "Выберите, какие прогнозы вы хотите посмотреть:",
        reply_markup=my_forecasts_menu_kb(),
    )
    await callback_query.answer()


@router.callback_query(F.data == "forecasts:active")
async def show_active_forecasts(callback_query: types.CallbackQuery):
    """
    Shows a list of tournaments for which the user has an active forecast.
    """
    user_id = callback_query.from_user.id
    async with async_session() as session:
        active_forecasts_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .join(Tournament, Forecast.tournament_id == Tournament.id)
            .where(
                Forecast.user_id == user_id,
                Tournament.status.in_([TournamentStatus.OPEN, TournamentStatus.LIVE]),
            )
            .order_by(Tournament.date.desc())
        )
        result = await session.execute(active_forecasts_stmt)
        forecasts = result.scalars().all()

        if not forecasts:
            await callback_query.answer("У вас нет активных прогнозов.", show_alert=True)
            return

        await callback_query.message.edit_text(
            "Выберите турнир, чтобы посмотреть ваш прогноз:",
            reply_markup=active_tournaments_kb([f.tournament for f in forecasts]),
        )
    await callback_query.answer()


@router.callback_query(F.data.startswith("view_forecast:"))
async def show_specific_forecast(callback_query: types.CallbackQuery):
    """
    Shows the user's specific forecast for a selected tournament.
    """
    tournament_id = int(callback_query.data.split(":")[1])
    user_id = callback_query.from_user.id

    async with async_session() as session:
        # Fetch the forecast with tournament info
        forecast_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .where(
                Forecast.user_id == user_id, Forecast.tournament_id == tournament_id
            )
        )
        result = await session.execute(forecast_stmt)
        forecast = result.scalar_one_or_none()

        if not forecast:
            await callback_query.answer("Прогноз не найден.", show_alert=True)
            return

        # Fetch player names
        player_ids = forecast.prediction_data
        if not player_ids:
            await callback_query.answer(
                "В этом прогнозе нет данных об игроках.", show_alert=True
            )
            return

        players_stmt = select(Player).where(Player.id.in_(player_ids))
        result = await session.execute(players_stmt)
        players = {p.id: p.full_name for p in result.scalars()}

        # Format the message
        tournament_date = forecast.tournament.date.strftime("%d.%m.%Y")
        text = f"<b>Ваш прогноз на турнир «{forecast.tournament.name}» от {tournament_date}:</b>\n\n"

        text += format_player_list(player_ids, players)

        # Show 'Edit' button only for OPEN tournaments
        # Also show 'Other Forecasts' button
        kb = (
            view_forecast_kb(
                back_callback="forecasts:active", 
                forecast_id=forecast.id, # ALWAYS PASS forecast.id HERE
                tournament_id=tournament_id
            )
            if forecast.tournament.status == TournamentStatus.OPEN
            else view_forecast_kb(
                back_callback="forecasts:active",
                forecast_id=forecast.id, # ALWAYS PASS forecast.id HERE
                tournament_id=tournament_id
            )
        )

        await callback_query.message.edit_text(text, reply_markup=kb)
    await callback_query.answer()


@router.callback_query(F.data.startswith("edit_forecast_start:"))
async def cq_edit_forecast_start(callback_query: types.CallbackQuery):
    """Asks for confirmation to edit a forecast."""
    forecast_id = int(callback_query.data.split(":")[1])
    text = "Вы уверены, что хотите изменить прогноз? Ваш старый прогноз будет заменен только **после сохранения нового**."
    await callback_query.message.edit_text(
        text,
        reply_markup=confirmation_kb(action_prefix=f"edit_confirm:{forecast_id}"),
    )
    await callback_query.answer()


@router.callback_query(F.data.startswith("forecasts:history:"))
async def show_forecast_history(callback_query: types.CallbackQuery):
    """
    Shows a paginated list of the user's past forecasts.
    """
    page = int(callback_query.data.split(":")[2])
    user_id = callback_query.from_user.id

    async with async_session() as session:
        history_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .join(Tournament, Forecast.tournament_id == Tournament.id)
            .where(
                Forecast.user_id == user_id,
                Tournament.status == TournamentStatus.FINISHED,
            )
            .order_by(Tournament.date.desc())
        )
        result = await session.execute(history_stmt)
        forecasts = result.scalars().all()

        if not forecasts:
            await callback_query.answer("У вас нет прошлых прогнозов.", show_alert=True)
            return

        await callback_query.message.edit_text(
            "История ваших прогнозов:",
            reply_markup=forecast_history_kb(forecasts, page),
        )
    await callback_query.answer()


@router.callback_query(F.data.startswith("view_history:"))
async def show_specific_history(callback_query: types.CallbackQuery):
    """
    Shows a detailed comparison for a past forecast.
    """
    parts = callback_query.data.split(":")
    forecast_id, page = int(parts[1]), int(parts[2])

    async with async_session() as session:
        # Fetch the forecast with tournament info
        forecast_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .where(Forecast.id == forecast_id)
        )
        result = await session.execute(forecast_stmt)
        forecast = result.scalar_one_or_none()

        if not forecast or not forecast.tournament.results:
            await callback_query.answer(
                "История для этого прогноза не найдена.", show_alert=True
            )
            return

        # Get all player IDs from prediction and results to fetch names in one query
        pred_ids = forecast.prediction_data
        res_ids = [int(k) for k in forecast.tournament.results.keys()]
        all_player_ids = list(set(pred_ids) | set(res_ids))

        players_stmt = select(Player).where(Player.id.in_(all_player_ids))
        result = await session.execute(players_stmt)
        players = {p.id: p.full_name for p in result.scalars()}

        # Format message
        tournament_date = forecast.tournament.date.strftime("%d.%m.%Y")
        text = f"<b>История прогноза на турнир «{forecast.tournament.name}» от {tournament_date}</b>\n\n"
        text += "<b>📜 Ваш прогноз:</b>\n"
        
        text += format_player_list(pred_ids, players)

        text += "\n<b>🏆 Итоги турнира:</b>\n"
        # Sort results by rank
        sorted_results = sorted(
            forecast.tournament.results.items(), key=lambda item: item[1]
        )
        
        # Manual formatting for results as dict structure differs slightly
        for player_id_str, rank in sorted_results:
            place = get_medal_str(rank)
            player_name = players.get(int(player_id_str), "?")
            text += f"{place} {player_name}\n"

        text += f"\n<b>💰 Очки за прогноз:</b> {forecast.points_earned or 0}"

        # Pass tournament_id to enable 'Other Forecasts' button
        await callback_query.message.edit_text(
            text, reply_markup=view_forecast_kb(
                back_callback=f"forecasts:history:{page}",
                forecast_id=forecast.id, # ALWAYS PASS forecast.id HERE
                tournament_id=forecast.tournament_id
            )
        )
    await callback_query.answer()
