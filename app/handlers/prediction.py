from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, and_, delete
from sqlalchemy.orm import selectinload

from app.db.models import Tournament, TournamentStatus, Player, Forecast, User
from app.db.session import async_session
from app.states.user_states import MakeForecast
from app.config import ADMIN_IDS
from app.utils.formatting import draw_progress_bar
from app.keyboards.inline import (
    get_paginated_players_kb, 
    confirmation_kb, 
    tournament_user_menu_kb,
    tournament_selection_kb,
    view_others_forecasts_menu_kb,
    get_paginated_forecasts_list_kb,
    view_single_forecast_back_kb
)

router = Router()

async def get_open_tournaments(user_id: int):
    """Helper to get tournaments a user has NOT predicted on yet."""
    async with async_session() as session:
        # Get IDs of tournaments the user has already made a forecast for
        user_forecasts_res = await session.execute(
            select(Forecast.tournament_id).where(Forecast.user_id == user_id)
        )
        predicted_tournament_ids = user_forecasts_res.scalars().all()

        # Get all OPEN tournaments
        open_tournaments_res = await session.execute(
            select(Tournament).where(Tournament.status == TournamentStatus.OPEN).order_by(Tournament.date.desc())
        )
        # Filter out the ones the user has already predicted on
        available_tournaments = [
            t for t in open_tournaments_res.scalars().all() if t.id not in predicted_tournament_ids
        ]
        return available_tournaments

@router.message(F.text == "🏁 Актуальные турниры")
@router.message(Command("predict"))
async def cmd_predict_start(message: types.Message | types.CallbackQuery, state: FSMContext):
    """Starts the forecast creation process."""
    user_id = message.from_user.id
    available_tournaments = await get_open_tournaments(user_id)

    if not available_tournaments:
        text = "Сейчас нет турниров, открытых для прогнозов, или вы уже сделали прогноз на все доступные. Загляните позже!"
        if isinstance(message, types.Message):
            await message.answer(text)
        else:
            await message.message.edit_text(text)
        return

    await state.set_state(MakeForecast.choosing_tournament)
    
    text = "Выберите турнир для создания прогноза:"
    if isinstance(message, types.Message):
        await message.answer(text, reply_markup=tournament_selection_kb(available_tournaments))
    else:
        await message.message.edit_text(text, reply_markup=tournament_selection_kb(available_tournaments))

@router.callback_query(F.data == "predict_back_to_list")
async def cq_predict_back_to_list(callback: types.CallbackQuery, state: FSMContext):
    await cmd_predict_start(callback, state)
    await callback.answer()

@router.callback_query(F.data.startswith("select_tournament_"))
async def cq_show_tournament_menu(callback: types.CallbackQuery, state: FSMContext):
    """Handles tournament selection and shows the user menu for that tournament."""
    tournament_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id)
        if not tournament:
            await callback.answer("Турнир не найден.", show_alert=True)
            await cmd_predict_start(callback, state)
            return

    # Determine if current user is admin
    is_admin = callback.from_user.id in ADMIN_IDS
    text = f"<b>Турнир: «{tournament.name}»</b>\nДата: {tournament.date.strftime('%d.%m.%Y')}\n\nВыберите действие:"
    await callback.message.edit_text(text, reply_markup=tournament_user_menu_kb(tournament_id, tournament.status, is_admin)) 
    await callback.answer()

@router.callback_query(MakeForecast.choosing_tournament, F.data.startswith("view_participants_"))
async def cq_view_participants(callback: types.CallbackQuery, state: FSMContext):
    """Shows the list of participants for the selected tournament."""
    tournament_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
        
        text = f"<b>Участники турнира «{tournament.name}»</b>\n\n"
        if not tournament.participants:
            text += "В этом турнире пока нет зарегистрированных участников."
        else:
            # Sort by rating (desc) then name
            sorted_participants = sorted(
                tournament.participants, 
                key=lambda p: (-(p.current_rating or 0), p.full_name)
            )
            lines = []
            for p in sorted_participants:
                rating_str = f" ({p.current_rating})" if p.current_rating is not None else ""
                lines.append(f"• {p.full_name}{rating_str}")
            text += "\n".join(lines)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад к меню турнира", callback_data=f"select_tournament_{tournament_id}")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(MakeForecast.choosing_tournament, F.data.startswith("predict_start_"))
async def cq_predict_start(callback: types.CallbackQuery, state: FSMContext):
    """Starts the actual prediction flow (picking players)."""
    tournament_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
        if not tournament or not tournament.participants:
            await callback.answer("В этом турнире пока нет участников. Прогноз невозможен.", show_alert=True)
            return
        
        players = tournament.participants

    await state.set_state(MakeForecast.making_prediction)
    await state.update_data(
        tournament_id=tournament_id,
        tournament_players={p.id: p.full_name for p in players},
        forecast_list=[]
    )
    
    kb = get_paginated_players_kb(
        players=players,
        action="predict"
    )
    await callback.message.edit_text(
        "<b>Шаг 1/5:</b> Выберите, кто, по-вашему, займет <b>1 место</b>:",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_confirm:"))
async def cq_edit_forecast_confirm_yes(callback: types.CallbackQuery, state: FSMContext):
    """Handles the 'Yes' confirmation to edit a forecast and starts the process."""
    parts = callback.data.split(":")
    if len(parts) < 3 or parts[2] != "yes":
        try:
            await callback.message.delete()
            await callback.answer("Редактирование отменено.")
        except (ValueError, IndexError):
            await callback.answer("Ошибка отмены.", show_alert=True)
        return

    forecast_id = int(parts[1])

    async with async_session() as session:
        forecast = await session.get(
            Forecast,
            forecast_id,
            options=[selectinload(Forecast.tournament).selectinload(Tournament.participants)],
        )
        if not forecast or not forecast.tournament:
            await callback.answer("Турнир для этого прогноза не найден.", show_alert=True)
            return
        
        tournament = forecast.tournament
        if not tournament.participants:
            await callback.message.edit_text("В этом турнире пока нет зарегистрированных участников. Прогноз невозможен.")
            await state.clear()
            return

    await state.set_state(MakeForecast.making_prediction)
    await state.update_data(
        tournament_id=tournament.id,
        tournament_players={p.id: p.full_name for p in tournament.participants},
        forecast_list=[],
        editing_forecast_id=forecast_id,
    )

    kb = get_paginated_players_kb(players=tournament.participants, action="predict")
    await callback.message.edit_text(
        "<b>Шаг 1/5:</b> Выберите, кто, по-вашему, займет <b>1 место</b>:",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(MakeForecast.making_prediction, F.data.startswith("predict:"))
async def cq_process_prediction_selection(callback: types.CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split(":")[1])
    
    data = await state.get_data()
    players_dict = data.get("tournament_players", {})
    forecast_list = data.get("forecast_list", [])

    if player_id in forecast_list:
        await callback.answer("Этот игрок уже в вашем прогнозе!", show_alert=True)
        return

    forecast_list.append(player_id)
    await state.update_data(forecast_list=forecast_list)
    
    next_place = len(forecast_list) + 1

    if next_place <= 5:
        player_objects = [Player(id=pid, full_name=name) for pid, name in players_dict.items()]
        kb = get_paginated_players_kb(
            players=player_objects,
            action="predict",
            selected_ids=forecast_list
        )
        await callback.message.edit_text(
            f"<b>Шаг {next_place}/5:</b> Выберите, кто займет <b>{next_place} место</b>:",
            reply_markup=kb
        )
    else:
        await state.set_state(MakeForecast.confirming_forecast)
        
        final_forecast_text = "<b>Ваш итоговый прогноз:</b>\n"
        for i, pid in enumerate(forecast_list):
            final_forecast_text += f"{i+1}. {players_dict.get(pid, 'Неизвестный')}\n"
        final_forecast_text += "\nПодтверждаете свой выбор?"

        await callback.message.edit_text(
            final_forecast_text,
            reply_markup=confirmation_kb(action_prefix="confirm_forecast")
        )
    await callback.answer()


@router.callback_query(MakeForecast.confirming_forecast, F.data == "confirm_forecast:yes")
async def cq_predict_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    if not all(k in data for k in ["tournament_id", "forecast_list"]):
        await callback.message.edit_text(
            "Произошла ошибка, не вся информация для прогноза найдена. Попробуйте снова."
        )
        await state.clear()
        return

    editing_forecast_id = data.get("editing_forecast_id")

    new_forecast = Forecast(
        user_id=callback.from_user.id,
        tournament_id=data.get("tournament_id"),
        prediction_data=data.get("forecast_list"),
    )

    async with async_session() as session:
        if editing_forecast_id:
            await session.execute(
                delete(Forecast).where(Forecast.id == editing_forecast_id)
            )
        
        session.add(new_forecast)
        await session.commit()
        
        message = (
            "✅ Ваш прогноз обновлен!"
            if editing_forecast_id
            else "✅ Ваш прогноз принят!"
        )
        await callback.message.edit_text(message)

    await state.clear()


@router.callback_query(MakeForecast.confirming_forecast, F.data == "confirm_forecast:no")
async def cq_predict_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Прогноз отменен.")
    await callback.answer()


# --- View Other Forecasts Logic ---

@router.callback_query(F.data.startswith("vof_summary:"))
async def cq_view_other_forecasts(callback: types.CallbackQuery, state: FSMContext):
    """Entry point to view others' forecasts (Detailed Summary)."""
    parts = callback.data.split(":")
    tournament_id = int(parts[1])
    source = ":".join(parts[2:]) 
    if not source:
        source = "menu"
    if source.startswith("hist_") and len(parts) >= 5: 
         source = f"{parts[2]}_{parts[3]}_{parts[4]}"

    user_id = callback.from_user.id
    
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.forecasts)])
        if not tournament:
            await callback.answer("Турнир не найден.", show_alert=True)
            return

        is_admin = user_id in ADMIN_IDS
        if tournament.status == TournamentStatus.OPEN and not is_admin:
            await callback.answer("🔒 Прогнозы участников откроются после начала турнира!", show_alert=True)
            return

        forecasts = tournament.forecasts
        if not forecasts:
            await callback.answer("Пока нет прогнозов на этот турнир.", show_alert=True)
            return

        total_forecasts = len(forecasts)
        
        # Stats aggregation
        stats = {} 
        all_player_ids = set()

        for f in forecasts:
            for rank, player_id in enumerate(f.prediction_data):
                place = rank + 1
                points = 6 - place 
                all_player_ids.add(player_id)
                if player_id not in stats:
                    stats[player_id] = {'points': 0, 1: 0, 2: 0, 3: 0}
                stats[player_id]['points'] += points
                if place <= 3:
                    stats[player_id][place] += 1

        # Batch fetch names
        player_names_map = {}
        if all_player_ids:
            players_res = await session.execute(select(Player).where(Player.id.in_(all_player_ids)))
            for p in players_res.scalars():
                player_names_map[p.id] = p.full_name

        text = f"📊 <b>Аналитика прогнозов «{tournament.name}»</b>\n"
        text += f"Всего участников: <b>{total_forecasts}</b>\n\n"

        text += "🧠 <b>Народный ТОП (мнение большинства):</b>\n"
        text += "<i>(на основе суммы баллов за места)</i>\n"
        
        sorted_by_points = sorted(stats.items(), key=lambda x: x[1]['points'], reverse=True)[:5]
        
        for i, (pid, data) in enumerate(sorted_by_points):
            p_name = player_names_map.get(pid, "Неизвестный")
            text += f"{i+1}. <b>{p_name}</b> — {data['points']} баллов\n"
        
        text += "\n━━━━━━━━━━━━━━━━━━\n"

        medals = {1: "🥇 Золото", 2: "🥈 Серебро", 3: "🥉 Бронза"}
        
        for place in range(1, 4):
            text += f"\n<b>{medals[place]} (Фавориты):</b>\n"
            candidates = [
                (pid, data[place]) 
                for pid, data in stats.items() 
                if data.get(place, 0) > 0
            ]
            sorted_candidates = sorted(candidates, key=lambda x: x[1], reverse=True)[:3] 
            
            if not sorted_candidates:
                text += "• Нет данных\n"
            
            for pid, count in sorted_candidates:
                p_name = player_names_map.get(pid, "Неизвестный")
                percent = int((count / total_forecasts) * 100)
                bar = draw_progress_bar(percent, length=6)
                text += f"• {p_name}\n   {bar} <b>{percent}%</b> ({count} чел.)\n"

        text += "\n👇 Нажмите кнопку ниже, чтобы увидеть прогнозы каждого участника."
        
        await callback.message.edit_text(text, reply_markup=view_others_forecasts_menu_kb(tournament_id, source))


@router.callback_query(F.data.startswith("vof_list:"))
async def cq_view_other_forecasts_list(callback: types.CallbackQuery, state: FSMContext):
    """Shows list of users who made forecasts."""
    parts = callback.data.split(":")
    tournament_id = int(parts[1])
    page = int(parts[2])
    source = ":".join(parts[3:])
    if not source:
        source = "menu"
    if source.startswith("hist_") and len(parts) >= 6: 
         source = f"{parts[3]}_{parts[4]}_{parts[5]}"
    
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.forecasts).selectinload(Forecast.user)])
        if not tournament:
            await callback.answer("Tурнир не найден.", show_alert=True)
            return
        
        forecasts = tournament.forecasts
        
    await callback.message.edit_text(
        "📋 <b>Список прогнозистов</b>\nНажмите на участника, чтобы увидеть его прогноз:",
        reply_markup=get_paginated_forecasts_list_kb(forecasts, tournament_id, page, page_size=8, source=source)
    )

@router.callback_query(F.data.startswith("vof_paginate:"))
async def cq_paginate_other_forecasts(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    tournament_id = int(parts[1])
    page = int(parts[2])
    source = ":".join(parts[3:]) 
    if not source:
        source = "menu"
    if source.startswith("hist_") and len(parts) >= 6: 
         source = f"{parts[3]}_{parts[4]}_{parts[5]}"
    
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.forecasts).selectinload(Forecast.user)])
        forecasts = tournament.forecasts
        
    await callback.message.edit_text(
        "📋 <b>Список прогнозистов</b>\nНажмите на участника, чтобы увидеть его прогноз:",
        reply_markup=get_paginated_forecasts_list_kb(forecasts, tournament_id, page, page_size=8, source=source)
    )

@router.callback_query(F.data.startswith("vof_detail:"))
async def cq_view_other_forecast_detail(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    forecast_id = int(parts[1])
    source = ":".join(parts[2:])
    if not source:
        source = "menu"
    if source.startswith("hist_") and len(parts) >= 5: 
         source = f"{parts[2]}_{parts[3]}_{parts[4]}"
    
    async with async_session() as session:
        forecast = await session.get(Forecast, forecast_id, options=[selectinload(Forecast.user), selectinload(Forecast.tournament)])
        if not forecast:
            await callback.answer("Прогноз не найден.", show_alert=True)
            return
            
        user_name = forecast.user.username or f"User {forecast.user.id}"
        
        # Batch fetch player names for the forecast
        player_names_map = {}
        if forecast.prediction_data:
             players_res = await session.execute(select(Player).where(Player.id.in_(forecast.prediction_data)))
             for p in players_res.scalars():
                 player_names_map[p.id] = p.full_name

        text = f"👤 <b>Прогноз {user_name}</b>\n\n"
        
        for rank, player_id in enumerate(forecast.prediction_data):
            p_name = player_names_map.get(player_id, "Неизвестный")
            medal = ""
            if rank == 0: medal = "🥇 "
            elif rank == 1: medal = "🥈 "
            elif rank == 2: medal = "🥉 "
            text += f"{medal}{rank+1}. {p_name}\n"
            
        if forecast.points_earned is not None:
            text += f"\n💰 Очки: <b>{forecast.points_earned}</b>"
            
        await callback.message.edit_text(
            text, 
            reply_markup=view_single_forecast_back_kb(forecast.tournament_id, page=0, source=source)
        )
