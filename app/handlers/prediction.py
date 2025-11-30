from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.db import crud
from app.db.models import Tournament, TournamentStatus, Player, Forecast
from app.db.session import async_session
from app.states.user_states import MakeForecast
from app.config import ADMIN_IDS
from app.utils.formatting import draw_progress_bar
from app.lexicon.ru import LEXICON_RU
from app.keyboards.inline import (
    get_paginated_players_kb, 
    confirmation_kb, 
    tournament_user_menu_kb,
    tournament_selection_kb,
    view_others_forecasts_menu_kb,
    get_paginated_forecasts_list_kb,
    view_single_forecast_back_kb,
    view_participants_back_kb,
    view_forecast_kb
)

router = Router()

async def get_open_tournaments(user_id: int):
    """Helper to get tournaments a user has NOT predicted on yet."""
    async with async_session() as session:
        # Get IDs of tournaments the user has already made a forecast for
        predicted_tournament_ids = await crud.get_user_forecast_tournament_ids(session, user_id)

        # Get all OPEN tournaments
        open_tournaments = await crud.get_open_tournaments(session)
        
        # Filter out the ones the user has already predicted on
        available_tournaments = [
            t for t in open_tournaments if t.id not in predicted_tournament_ids
        ]
        return available_tournaments

@router.message(F.text == "🏁 Актуальные турниры")
@router.message(Command("predict"))
async def cmd_predict_start(message: types.Message | types.CallbackQuery, state: FSMContext):
    """Starts the forecast creation process."""
    user_id = message.from_user.id
    available_tournaments = await get_open_tournaments(user_id)

    if not available_tournaments:
        # Check if user has ANY open tournaments they predicted on, to offer editing
        async with async_session() as session:
             predicted_ids = await crud.get_user_forecast_tournament_ids(session, user_id)
             all_open = await crud.get_open_tournaments(session)
             # Filter open tournaments that are IN predicted_ids
             editable_tournaments = [t for t in all_open if t.id in predicted_ids]
             
        if not editable_tournaments:
             text = LEXICON_RU["no_open_tournaments"]
             if isinstance(message, types.Message):
                 await message.answer(text)
             else:
                 await message.message.edit_text(text)
             return
        else:
             # Show list of tournaments to EDIT
             text = "Вы уже сделали прогнозы на все доступные турниры. Выберите турнир, чтобы изменить прогноз:"
             if isinstance(message, types.Message):
                 await message.answer(text, reply_markup=tournament_selection_kb(editable_tournaments))
             else:
                 await message.message.edit_text(text, reply_markup=tournament_selection_kb(editable_tournaments))
             return

    await state.set_state(MakeForecast.choosing_tournament)
    
    text = LEXICON_RU["choose_tournament"]
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
        tournament = await crud.get_tournament(session, tournament_id)
        if not tournament:
            await callback.answer(LEXICON_RU["tournament_not_found"], show_alert=True)
            await cmd_predict_start(callback, state)
            return

    # Determine if current user is admin
    is_admin = callback.from_user.id in ADMIN_IDS
    
    # Check if user has forecast for this tournament
    user_has_forecast = False
    forecast_res = await session.execute(select(Forecast).where(Forecast.user_id == callback.from_user.id, Forecast.tournament_id == tournament_id))
    if forecast_res.scalar_one_or_none():
        user_has_forecast = True

    text = LEXICON_RU["tournament_title"].format(name=tournament.name, date=tournament.date.strftime('%d.%m.%Y'))
    await callback.message.edit_text(text, reply_markup=tournament_user_menu_kb(tournament_id, tournament.status, is_admin, user_has_forecast=user_has_forecast)) 
    await callback.answer()

@router.callback_query(F.data.startswith("view_participants_"))
async def cq_view_participants(callback: types.CallbackQuery, state: FSMContext):
    """Shows the list of participants for the selected tournament."""
    tournament_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        tournament = await crud.get_tournament_with_participants(session, tournament_id)
        
        text = LEXICON_RU["participants_title"].format(name=tournament.name)
        if not tournament.participants:
            text += LEXICON_RU["no_participants"]
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
    builder.button(text=LEXICON_RU["back_button"], callback_data=f"select_tournament_{tournament_id}")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("predict_start_"))
async def cq_predict_start(callback: types.CallbackQuery, state: FSMContext):
    """Starts the actual prediction flow (picking players)."""
    tournament_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        # Double check if user already has a forecast (in case of race condition or old button)
        forecast_res = await session.execute(select(Forecast).where(Forecast.user_id == callback.from_user.id, Forecast.tournament_id == tournament_id))
        if forecast_res.scalar_one_or_none():
             # Redirect to view/edit forecast
             # We can trigger the view_forecast handler logic here, or just send a message
             # Let's show a simple alert and refresh the menu to "My Forecast" state
             await callback.answer("У вас уже есть прогноз на этот турнир!", show_alert=True)
             # Refresh the menu (will show 'View Forecast' button now)
             await cq_show_tournament_menu(callback, state)
             return

        tournament = await crud.get_tournament_with_participants(session, tournament_id)
        if not tournament or not tournament.participants:
            await callback.answer(LEXICON_RU["no_participants_forecast_impossible"], show_alert=True)
            return
        
        players = tournament.participants
        prediction_count = tournament.prediction_count or 5

    await state.set_state(MakeForecast.making_prediction)
    await state.update_data(
        tournament_id=tournament_id,
        tournament_players={
            p.id: f"{p.full_name} ({p.current_rating})" if p.current_rating is not None else p.full_name 
            for p in players
        },
        forecast_list=[],
        prediction_count=prediction_count
    )
    
    kb = get_paginated_players_kb(
        players=players,
        action="predict"
    )
    await callback.message.edit_text(
        LEXICON_RU["step_1"].replace("5", str(prediction_count)), # Quick fix for text
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
            await callback.answer(LEXICON_RU["edit_cancelled"])
        except (ValueError, IndexError):
            await callback.answer(LEXICON_RU["error_cancel"], show_alert=True)
        return

    forecast_id = int(parts[1])

    async with async_session() as session:
        forecast = await crud.get_forecast_for_editing(session, forecast_id)
        if not forecast or not forecast.tournament:
            await callback.answer(LEXICON_RU["tournament_not_found_for_forecast"], show_alert=True)
            return
        
        tournament = forecast.tournament
        if tournament.status != TournamentStatus.OPEN:
            await callback.answer(LEXICON_RU["edit_forbidden"], show_alert=True)
            return

        if not tournament.participants:
            await callback.message.edit_text(LEXICON_RU["no_participants_forecast_impossible"])
            await state.clear()
            return
        
        prediction_count = tournament.prediction_count or 5

    await state.set_state(MakeForecast.making_prediction)
    await state.update_data(
        tournament_id=tournament.id,
        tournament_players={
            p.id: f"{p.full_name} ({p.current_rating})" if p.current_rating is not None else p.full_name 
            for p in tournament.participants
        },
        forecast_list=[],
        editing_forecast_id=forecast_id,
        prediction_count=prediction_count
    )

    kb = get_paginated_players_kb(players=tournament.participants, action="predict")
    await callback.message.edit_text(
        LEXICON_RU["step_1"].replace("5", str(prediction_count)),
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(MakeForecast.making_prediction, F.data.startswith("predict:"))
async def cq_process_prediction_selection(callback: types.CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split(":")[1])
    
    data = await state.get_data()
    players_dict = data.get("tournament_players", {})
    forecast_list = data.get("forecast_list", [])
    prediction_count = data.get("prediction_count", 5)

    if player_id in forecast_list:
        await callback.answer(LEXICON_RU["player_already_selected"], show_alert=True)
        return

    forecast_list.append(player_id)
    await state.update_data(forecast_list=forecast_list)
    
    next_place = len(forecast_list) + 1

    if next_place <= prediction_count:
        # Ask for the next place
        # Fetch players with ratings from DB for correct sorting
        tournament_id = data.get("tournament_id")
        async with async_session() as session:
             tournament = await crud.get_tournament_with_participants(session, tournament_id)
             players = tournament.participants

        kb = get_paginated_players_kb(
            players=players,
            action="predict",
            selected_ids=forecast_list
        )
        await callback.message.edit_text(
            LEXICON_RU["step_n"].format(next_place=next_place).replace("5", str(prediction_count)),
            reply_markup=kb
        )
    else:
        await state.set_state(MakeForecast.confirming_forecast)
        
        final_forecast_text = LEXICON_RU["final_forecast_header"]
        for i, pid in enumerate(forecast_list):
            final_forecast_text += f"{i+1}. {players_dict.get(pid, LEXICON_RU['unknown_player'])}\n"
        final_forecast_text += LEXICON_RU["confirm_choice"]

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
            LEXICON_RU["forecast_error"]
        )
        await state.clear()
        return

    editing_forecast_id = data.get("editing_forecast_id")
    tournament_id = data.get("tournament_id")
    forecast_list = data.get("forecast_list")
    players_dict = data.get("tournament_players", {}) # Contains names with ratings now

    new_forecast = Forecast(
        user_id=callback.from_user.id,
        tournament_id=tournament_id,
        prediction_data=forecast_list,
    )

    async with async_session() as session:
        if editing_forecast_id:
            await crud.delete_forecast(session, editing_forecast_id)
        
        await crud.create_forecast(session, new_forecast)
        await session.commit()
        await session.refresh(new_forecast) # Get ID
        
        # Construct success message
        text_header = LEXICON_RU["forecast_updated"] if editing_forecast_id else LEXICON_RU["forecast_accepted"]
        text_body = LEXICON_RU["your_choice"]
        
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        for i, pid in enumerate(forecast_list):
            place = medals.get(i, f" {i+1}.")
            player_name = players_dict.get(pid, LEXICON_RU["unknown_player"])
            text_body += f"{place} {player_name}\n"
            
        # Show buttons to manage this forecast immediately
        
        await callback.message.edit_text(
            text_header + text_body,
            reply_markup=view_forecast_kb(
                back_callback="predict_back_to_list",
                forecast_id=new_forecast.id,
                tournament_id=tournament_id,
                allow_edit=True
            )
        )

    await state.clear()


@router.callback_query(MakeForecast.confirming_forecast, F.data == "confirm_forecast:no")
async def cq_predict_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(LEXICON_RU["forecast_cancelled"])
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
        tournament = await crud.get_tournament_with_forecasts(session, tournament_id)
        if not tournament:
            await callback.answer(LEXICON_RU["tournament_not_found"], show_alert=True)
            return

        is_admin = user_id in ADMIN_IDS
        if tournament.status == TournamentStatus.OPEN and not is_admin:
            await callback.answer(LEXICON_RU["forecasts_closed"], show_alert=True)
            return

        forecasts = tournament.forecasts
        if not forecasts:
            await callback.answer(LEXICON_RU["no_forecasts_yet"], show_alert=True)
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
            players = await crud.get_players_by_ids(session, all_player_ids)
            for p in players:
                player_names_map[p.id] = p.full_name

        text = LEXICON_RU["analytics_title"].format(name=tournament.name)
        text += LEXICON_RU["total_participants"].format(count=total_forecasts)

        text += LEXICON_RU["popular_top"]
        
        sorted_by_points = sorted(stats.items(), key=lambda x: x[1]['points'], reverse=True)[:5]
        
        for i, (pid, data) in enumerate(sorted_by_points):
            p_name = player_names_map.get(pid, LEXICON_RU["unknown_player"])
            text += f"{i+1}. <b>{p_name}</b> — {data['points']} баллов\n"
        
        text += "\n━━━━━━━━━━━━━━━━━━\n"

        medals = {1: LEXICON_RU["favorites_gold"], 2: LEXICON_RU["favorites_silver"], 3: LEXICON_RU["favorites_bronze"]}
        
        for place in range(1, 4):
            text += LEXICON_RU["favorites_header"].format(medal=medals[place])
            candidates = [
                (pid, data[place]) 
                for pid, data in stats.items() 
                if data.get(place, 0) > 0
            ]
            sorted_candidates = sorted(candidates, key=lambda x: x[1], reverse=True)[:3] 
            
            if not sorted_candidates:
                text += LEXICON_RU["no_data"]
            
            for pid, count in sorted_candidates:
                p_name = player_names_map.get(pid, LEXICON_RU["unknown_player"])
                percent = int((count / total_forecasts) * 100)
                bar = draw_progress_bar(percent, length=6)
                text += f"• {p_name}\n   {bar} <b>{percent}%</b> ({count} чел.)\n"

        text += LEXICON_RU["click_below"]
        
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
        tournament = await crud.get_tournament_with_forecasts_and_users(session, tournament_id)
        if not tournament:
            await callback.answer(LEXICON_RU["tournament_not_found"], show_alert=True)
            return
        
        forecasts = tournament.forecasts
        
    await callback.message.edit_text(
        LEXICON_RU["forecast_list_title"],
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
        tournament = await crud.get_tournament_with_forecasts_and_users(session, tournament_id)
        forecasts = tournament.forecasts
        
    await callback.message.edit_text(
        LEXICON_RU["forecast_list_title"],
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
        forecast = await crud.get_forecast_details(session, forecast_id)
        if not forecast:
            await callback.answer(LEXICON_RU["tournament_not_found"], show_alert=True) # Although "Прогноз не найден" was there, let's check
            return
            
        user_name = forecast.user.username or f"User {forecast.user.id}"
        
        # Batch fetch player names for the forecast
        player_names_map = {}
        if forecast.prediction_data:
             players = await crud.get_players_by_ids(session, forecast.prediction_data)
             for p in players:
                 player_names_map[p.id] = p.full_name

        text = LEXICON_RU["forecast_detail_title"].format(name=user_name)
        
        for rank, player_id in enumerate(forecast.prediction_data):
            p_name = player_names_map.get(player_id, LEXICON_RU["unknown_player"])
            medal = ""
            if rank == 0: medal = "🥇 "
            elif rank == 1: medal = "🥈 "
            elif rank == 2: medal = "🥉 "
            text += f"{medal}{rank+1}. {p_name}\n"
            
        if forecast.points_earned is not None:
            text += LEXICON_RU["points_earned"].format(points=forecast.points_earned)
            
        await callback.message.edit_text(
            text, 
            reply_markup=view_single_forecast_back_kb(forecast.tournament_id, page=0, source=source)
        )

@router.callback_query(F.data.startswith("vof_participants:"))
async def cq_view_participants_from_forecast(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    tournament_id = int(parts[1])
    source = ":".join(parts[2:])
    if not source: source = "menu"
    if source.startswith("hist_") and len(parts) >= 5: 
         source = f"{parts[2]}_{parts[3]}_{parts[4]}"

    async with async_session() as session:
        tournament = await crud.get_tournament_with_participants(session, tournament_id)
        if not tournament:
            await callback.answer(LEXICON_RU["tournament_not_found"], show_alert=True)
            return
        
        text = LEXICON_RU["participants_title"].format(name=tournament.name)
        if not tournament.participants:
            text += LEXICON_RU["no_participants"]
        else:
            sorted_participants = sorted(
                tournament.participants, 
                key=lambda p: (-(p.current_rating or 0), p.full_name)
            )
            lines = []
            for p in sorted_participants:
                rating_str = f" ({p.current_rating})" if p.current_rating is not None else ""
                lines.append(f"• {p.full_name}{rating_str}")
            text += "\n".join(lines)
            
    await callback.message.edit_text(
        text, 
        reply_markup=view_participants_back_kb(tournament_id, source)
    )