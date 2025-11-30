from aiogram import Router, types, F
from aiogram.filters import CommandStart
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.keyboards.reply import main_menu
from app.keyboards.inline import (
    my_forecasts_menu_kb,
    active_tournaments_kb,
    view_forecast_kb,
    forecast_history_kb,
    confirmation_kb,
    help_menu_kb,
    help_back_kb
)
from app.db.models import User, Tournament, Forecast, TournamentStatus, Player
from app.db.session import async_session
from app.utils.formatting import get_medal_str, get_user_rank
from app.config import ADMIN_IDS

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
async def handle_my_stats(message: types.Message): # ADDED async
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Не удалось найти вашу статистику. Попробуйте /start")
            return
        
        # Calculate global rank using Window Function
        # 1. Points (DESC), 2. Perfects (DESC), 3. Exacts (DESC), 4. Played (ASC), 5. ID (ASC)
        
        rank_subquery = select(
            User.id,
            func.rank().over(
                order_by=[
                    User.total_points.desc(),
                    User.perfect_tournaments.desc(),
                    User.exact_guesses.desc(),
                    User.tournaments_played.asc(),
                    User.id.asc()
                ]
            ).label("rank_val")
        ).subquery()
        
        current_rank = await session.scalar(
            select(rank_subquery.c.rank_val).where(rank_subquery.c.id == user.id)
        )

    rank_title = get_user_rank(user.total_points)
    
    # Calculate average score
    tournaments = user.tournaments_played or 0
    avg_score = round(user.total_points / tournaments, 1) if tournaments > 0 else 0.0

    stats_text = (
        f"👤 <b>{message.from_user.full_name}</b> ({rank_title})\n\n"
        f"🏆 <b>Место в рейтинге:</b> {current_rank}\n"
        f"💰 <b>Всего очков:</b> {user.total_points}\n"
        f"📊 <b>Средний балл:</b> {avg_score} (за турнир)\n\n"
        f"<b>Достижения:</b>\n"
        f"💎 <b>Идеальных прогнозов:</b> {user.perfect_tournaments or 0}\n"
        f"🎯 <b>В яблочко:</b> {user.exact_guesses or 0}\n"
        f"🏟 <b>Турниров:</b> {tournaments}"
    )
    await message.answer(stats_text)


@router.message(F.text == "🏆 Рейтинг клуба")
async def handle_leaderboard(message: types.Message):
    async with async_session() as session:
        # Sort criteria:
        # 1. Points (DESC)
        # 2. Perfect Tournaments (DESC)
        # 3. Exact Guesses (DESC)
        # 4. Tournaments Played (ASC) - efficiency
        # 5. ID (ASC) - seniority
        top_users_result = await session.execute(
            select(User).order_by(
                User.total_points.desc(),
                User.perfect_tournaments.desc(),
                User.exact_guesses.desc(),
                User.tournaments_played.asc(),
                User.id.asc()
            ).limit(10)
        )
        top_users = top_users_result.scalars().all()

    if not top_users:
        await message.answer("Рейтинг пока пуст. Сделайте первый прогноз!")
        return

    leaderboard_text = "<b>🏆 Топ-10 прогнозистов клуба:</b>\n\n<code>"
    
    # Add headers
    leaderboard_text += "#  Ранг Имя             Очки  Игры Ср. Идеал \n" # Added 'Игры' header
    leaderboard_text += "----------------------------------------------\n" # Adjusted separator length
    
    for i, user in enumerate(top_users, 1):
        place_num = i
        username = user.username or f"id{user.id}"
        rank_icon = get_user_rank(user.total_points).split()[0]
        
        t_played = user.tournaments_played or 0
        avg = round(user.total_points / t_played, 1) if t_played > 0 else 0.0
        
        diamonds_str = f"💎{user.perfect_tournaments}"
        
        display_username = username
        if len(display_username) > 15:
            display_username = display_username[:12] + "..."
        
        line = (
            f"{place_num:>2}. {rank_icon} "
            f"{display_username:<15}"
            f"{user.total_points:>6} "
            f"{t_played:>4} " # Display tournaments played
            f"{avg:>5.1f} "
            f"{diamonds_str}"
        )
        leaderboard_text += f"{line}\n"

    leaderboard_text += "</code>"
    await message.answer(leaderboard_text)


@router.message(F.text == "ℹ️ Правила")
async def handle_rules(message: types.Message): # ADDED async
    text = "<b>📚 Справочный центр</b>\n\nВыберите интересующий вас раздел:"
    await message.answer(text, reply_markup=help_menu_kb())

@router.callback_query(F.data == "help:main")
async def cq_help_main(callback: types.CallbackQuery):
    text = "<b>📚 Справочный центр</b>\n\nВыберите интересующий вас раздел:"
    await callback.message.edit_text(text, reply_markup=help_menu_kb())

@router.callback_query(F.data == "help:scoring")
async def cq_help_scoring(callback: types.CallbackQuery):
    text = """
    <b>📈 Система начисления очков (РТТФ)</b>

    Мы используем справедливую систему оценки прогнозов:

    🔸 <b>+1 балл:</b> Вы угадали, что игрок займет призовое место, но ошиблись с точной позицией.
    <i>Пример: Поставили на 1-е, а он занял 3-е.</i>

    🎯 <b>+5 баллов:</b> Вы угадали игрока и его точное место.
    <i>Пример: Поставили на 1-е, и он занял 1-е.</i>

    💎 <b>БОНУС +15 баллов:</b> Вы угадали <b>всех</b> призеров и их места в точности.
    <i>Это высшее мастерство!</i>
    """
    await callback.message.edit_text(text, reply_markup=help_back_kb())

@router.callback_query(F.data == "help:ranks")
async def cq_help_ranks(callback: types.CallbackQuery):
    text = """
    <b>🏅 Ранги и Достижения</b>

    Ваш статус зависит от суммы очков:
    👶 <b>Новичок</b>: 0 - 50
    🧢 <b>Любитель</b>: 51 - 200
    🎱 <b>Профи</b>: 201 - 500
    🧠 <b>Эксперт</b>: 501 - 1000
    🔮 <b>Оракул</b>: 1000+

    <b>Специальные отметки:</b>
    💎 — Количество "Идеальных турниров" (с бонусом +15).
    🎯 — Количество точных попаданий в место (+5 баллов).
    """
    await callback.message.edit_text(text, reply_markup=help_back_kb())

@router.callback_query(F.data == "help:how_to")
async def cq_help_howto(callback: types.CallbackQuery):
    text = """
    <b>📝 Как сделать прогноз</b>

    1. Нажмите кнопку <b>"🏁 Актуальные турниры"</b>.
    2. Выберите турнир из списка (если есть открытые).
    3. Нажмите <b>"🔮 Сделать прогноз"</b>.
    4. Выберите игроков последовательно для каждого места (1-е, 2-е, и т.д.).
    5. Подтвердите выбор.

    Вы можете изменить прогноз в любой момент до начала турнира!
    """
    await callback.message.edit_text(text, reply_markup=help_back_kb())


@router.message(F.text == "🗂 Архив прогнозов")
async def handle_my_forecasts(message: types.Message): # ADDED async
    """
    Shows the menu for viewing active or past forecasts.
    """
    await message.answer(
        "Выберите, какие прогнозы вы хотите посмотреть:",
        reply_markup=my_forecasts_menu_kb(),
    )


@router.callback_query(F.data == "back_to_forecasts_menu")
async def back_to_forecasts_menu(callback_query: types.CallbackQuery): # ADDED async
    """
    Returns the user to the main forecasts menu.
    """
    await callback_query.message.edit_text(
        "Выберите, какие прогнозы вы хотите посмотреть:",
        reply_markup=my_forecasts_menu_kb(),
    )
    await callback_query.answer()


@router.callback_query(F.data == "forecasts:active")
async def show_active_forecasts(callback_query: types.CallbackQuery): # ADDED async
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
async def show_specific_forecast(callback_query: types.CallbackQuery): # ADDED async
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

        # Fetch player objects
        player_ids = forecast.prediction_data
        if not player_ids:
            await callback_query.answer(
                "В этом прогнозе нет данных об игроках.", show_alert=True
            )
            return

        players_stmt = select(Player).where(Player.id.in_(player_ids))
        result = await session.execute(players_stmt)
        players_map = {p.id: p for p in result.scalars()}

        # Format the message
        tournament_date = forecast.tournament.date.strftime("%d.%m.%Y")
        text = f"<b>Ваш прогноз на турнир «{forecast.tournament.name}» от {tournament_date}:</b>\n\n"

        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        for i, player_id in enumerate(player_ids):
            place = medals.get(i, f" {i + 1}.")
            player = players_map.get(player_id)
            if player:
                rating_str = f" ({player.current_rating})" if player.current_rating is not None else ""
                name_str = f"{player.full_name}{rating_str}"
            else:
                name_str = "Неизвестный игрок"
            text += f"{place} {name_str}\n"

        # Show 'Edit' button only for OPEN tournaments
        allow_edit = (forecast.tournament.status == TournamentStatus.OPEN)
        
        # Show 'Other Forecasts' only if NOT OPEN or if admin (based on rules from tournament_user_menu_kb)
        is_admin = user_id in ADMIN_IDS
        status_str = forecast.tournament.status.name if hasattr(forecast.tournament.status, "name") else str(forecast.tournament.status)
        _show_others = (status_str != "OPEN") or is_admin # Recalc as it's passed directly

        kb = view_forecast_kb(
            back_callback="forecasts:active", 
            forecast_id=forecast.id,
            tournament_id=tournament_id,
            allow_edit=allow_edit,
            show_others=_show_others,
            is_admin=is_admin, # Pass for consistency check in KB
            tournament_status=forecast.tournament.status # Pass for consistency check in KB
        )

        await callback_query.message.edit_text(text, reply_markup=kb)
    await callback_query.answer()


@router.callback_query(F.data.startswith("edit_forecast_start:"))
async def cq_edit_forecast_start(callback_query: types.CallbackQuery): # ADDED async
    """Asks for confirmation to edit a forecast."""
    forecast_id = int(callback_query.data.split(":")[1])
    text = "Вы уверены, что хотите изменить прогноз? Ваш старый прогноз будет заменен только <b>после сохранения нового</b>."
    await callback_query.message.edit_text(
        text,
        reply_markup=confirmation_kb(action_prefix=f"edit_confirm:{forecast_id}"),
    )
    await callback_query.answer()


import logging

# ... imports

@router.callback_query(F.data.startswith("forecasts:history:"))
async def show_forecast_history(callback_query: types.CallbackQuery): # ADDED async
    """
    Shows a paginated list of the user's past forecasts.
    """
    page = int(callback_query.data.split(":")[2])
    user_id = callback_query.from_user.id
    logging.info(f"DEBUG: Fetching history for user {user_id}, page {page}")

    async with async_session() as session:
        # Debug: Check if user exists and has any forecasts
        total_forecasts = await session.scalar(select(func.count(Forecast.id)).where(Forecast.user_id == user_id))
        logging.info(f"DEBUG: Total forecasts for user {user_id}: {total_forecasts}")

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
        
        logging.info(f"DEBUG: Found {len(forecasts)} FINISHED forecasts.")

        if not forecasts:
            # Fallback: Check if we have string mismatch for Enum
            # This is a hack, but helpful for debugging SQLite
            logging.info("DEBUG: Forecasts list is empty. Checking raw statuses...")
            
            debug_res = await session.execute(select(Forecast).where(Forecast.user_id == user_id))
            debug_forecasts = debug_res.scalars().all()
            
            if debug_forecasts:
                t_ids = [f.tournament_id for f in debug_forecasts]
                all_t_res = await session.execute(select(Tournament).where(Tournament.id.in_(t_ids)))
                all_t = all_t_res.scalars().all()
                for t in all_t:
                    logging.info(f"DEBUG: Tournament {t.id} status: {t.status} (type: {type(t.status)})")
            else:
                logging.info("DEBUG: No forecasts found for user at all (even ignoring status).")

            await callback_query.answer("У вас нет прошлых прогнозов.", show_alert=True)
            return

        await callback_query.message.edit_text(
            "История ваших прогнозов:",
            reply_markup=forecast_history_kb(forecasts, page),
        )
    await callback_query.answer()


@router.callback_query(F.data.startswith("view_history:"))
async def show_specific_history(callback_query: types.CallbackQuery): # ADDED async
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
        players_map = {p.id: p for p in result.scalars()}

        # Format message
        tournament_date = forecast.tournament.date.strftime("%d.%m.%Y")
        
        # 1. Actual Results Block
        results_dict = {int(k): int(v) for k, v in forecast.tournament.results.items()}
        sorted_results = sorted(results_dict.items(), key=lambda item: item[1])
        
        results_text = f"<b>🏆 Итоги турнира «{forecast.tournament.name}» ({tournament_date})</b>\n\n"
        for pid, rank in sorted_results:
            p_name = players_map.get(pid).full_name if players_map.get(pid) else "Неизвестный"
            medal = get_medal_str(rank)
            results_text += f"{medal} {p_name}\n"
            
        # 2. User Forecast Block (Detailed)
        prediction_text = f"\n<b>📜 Ваш прогноз:</b>\n"
        
        current_hits = 0
        for i, pid in enumerate(pred_ids):
            predicted_rank = i + 1
            p_name = players_map.get(pid).full_name if players_map.get(pid) else "Неизвестный"
            
            line_points = 0
            extra_info = ""
            
            if pid in results_dict:
                actual_rank = results_dict[pid]
                diff = abs(predicted_rank - actual_rank)
                
                if diff == 0:
                    line_points = 5
                    extra_info = " (🎯 Точно!)"
                    current_hits += 1
                else:
                    line_points = 1
                    extra_info = f" (факт: {actual_rank})"
            else:
                 line_points = 0
                 extra_info = " (не в топе)"
            
            prediction_text += f"{i+1}. {p_name}{extra_info} — <b>+{line_points}</b>\n"

        if current_hits == len(pred_ids) and len(pred_ids) > 0:
            prediction_text += "\n🎉 <b>БОНУС: +15 очков за идеальный прогноз!</b>\n"

        final_text = results_text + prediction_text + f"\n<b>💰 Итого очков:</b> {forecast.points_earned or 0}"

        # Pass tournament_id to enable 'Other Forecasts' button
        # History implies finished, so show_others=True
        await callback_query.message.edit_text(
            final_text, reply_markup=view_forecast_kb(
                back_callback=f"forecasts:history:{page}",
                forecast_id=forecast.id,
                tournament_id=forecast.tournament_id,
                allow_edit=False,
                show_others=True,
                is_admin=False,
                tournament_status=TournamentStatus.FINISHED
            )
        )
    await callback_query.answer()