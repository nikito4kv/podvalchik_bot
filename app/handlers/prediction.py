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
from app.handlers.view_helpers import show_forecast_card
from app.keyboards.inline import (
    get_paginated_players_kb, 
    confirmation_kb, 
    tournament_user_menu_kb,
    tournament_selection_kb,
    view_others_forecasts_menu_kb,
    get_paginated_forecasts_list_kb,
    view_single_forecast_back_kb,
    view_participants_back_kb,
    view_forecast_kb,
    tournament_start_kb,
    all_forecasts_text_back_kb # <--- ADDED THIS IMPORT
)

router = Router()

async def get_open_tournaments(user_id: int):
    """Helper to get ALL open tournaments and the user's predicted IDs."""
    async with async_session() as session:
        # Get IDs of tournaments the user has already made a forecast for
        predicted_tournament_ids = await crud.get_user_forecast_tournament_ids(session, user_id)

        # Get all OPEN tournaments
        open_tournaments = await crud.get_open_tournaments(session)
        
        return open_tournaments, predicted_tournament_ids

@router.message(F.text == "🏁 Актуальные турниры")
@router.message(Command("predict"))
async def cmd_predict_start(message: types.Message | types.CallbackQuery, state: FSMContext):
    """Starts the forecast creation process."""
    user_id = message.from_user.id
    available_tournaments, predicted_ids = await get_open_tournaments(user_id)

    if not available_tournaments:
         text = LEXICON_RU["no_open_tournaments"]
         if isinstance(message, types.Message):
             await message.answer(text)
         else:
             await message.message.edit_text(text)
         return

    await state.set_state(MakeForecast.choosing_tournament)
    
    text = "Выберите турнир (✅ - прогноз сделан):"
    if isinstance(message, types.Message):
        await message.answer(text, reply_markup=tournament_selection_kb(available_tournaments, predicted_ids))
    else:
        await message.message.edit_text(text, reply_markup=tournament_selection_kb(available_tournaments, predicted_ids))

@router.callback_query(F.data == "predict_back_to_list")
async def cq_predict_back_to_list(callback: types.CallbackQuery, state: FSMContext):
    await cmd_predict_start(callback, state)
    await callback.answer()

async def show_tournament_menu_logic(callback: types.CallbackQuery, state: FSMContext, tournament_id: int):
    """Helper to show tournament menu, shared by multiple handlers."""
    async with async_session() as session:
        tournament = await crud.get_tournament(session, tournament_id)
        if not tournament:
            await callback.answer(LEXICON_RU["tournament_not_found"], show_alert=True)
            await cmd_predict_start(callback, state)
            return

        # Check if user has forecast for this tournament
        forecast_stmt = select(Forecast).where(Forecast.user_id == callback.from_user.id, Forecast.tournament_id == tournament_id)
        forecast_res = await session.execute(forecast_stmt)
        forecast = forecast_res.scalar_one_or_none()

        if forecast:
            # SHOW FORECAST CARD DIRECTLY
            await show_forecast_card(callback, tournament, forecast, session)
        else:
            # SHOW PARTICIPANTS LIST + MAKE FORECAST BUTTON
            # Need to fetch participants. Since tournament object is already in session, 
            # we use refresh to load the relationship explicitly.
            await session.refresh(tournament, ["participants"])
            
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
                    rating_str = f"[{p.current_rating}] " if p.current_rating is not None else ""
                    lines.append(f"• {rating_str}{p.full_name}")
                text += "\n".join(lines)
            
            try:
                await callback.message.edit_text(text, reply_markup=tournament_start_kb(tournament_id))
            except Exception:
                await callback.message.answer(text, reply_markup=tournament_start_kb(tournament_id))

@router.callback_query(F.data.startswith("select_tournament_"))
async def cq_show_tournament_menu(callback: types.CallbackQuery, state: FSMContext):
    """Handles tournament selection and shows the user menu for that tournament."""
    tournament_id = int(callback.data.split("_")[2])
    await show_tournament_menu_logic(callback, state, tournament_id)
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
             await show_tournament_menu_logic(callback, state, tournament_id)
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
            p.id: {"name": p.full_name, "rating": p.current_rating}
            for p in players
        },
        forecast_list=[],
        prediction_count=prediction_count
    )
    
    kb = get_paginated_players_kb(
        players=players,
        action="predict",
        tournament_id=tournament_id,
        show_back_to_menu=True
    )
    await callback.message.edit_text(
        LEXICON_RU["step_1"].replace("5", str(prediction_count)), # Quick fix for text
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_confirm:"))
async def cq_edit_forecast_decision(callback: types.CallbackQuery, state: FSMContext):
    """Handles the confirmation to edit a forecast (Yes/No)."""
    parts = callback.data.split(":")
    # format: edit_confirm:FORECAST_ID:yes/no
    if len(parts) < 3:
        await callback.answer("Ошибка данных.", show_alert=True)
        return
        
    action = parts[2]
    forecast_id = int(parts[1])

    if action == "no":
        # User cancelled editing. Return to view forecast.
        # We need to find tournament_id to redirect back to 'view_forecast' logic
        async with async_session() as session:
            forecast = await crud.get_forecast_details(session, forecast_id)
            if forecast:
                # Manually call the view forecast logic (from common.py, but we can't import handler easily)
                # Or simpler: modify callback data and let router handle it? No, can't modify incoming object easily.
                # We can send a new message or just edit this one.
                # But logic is complex (medals, etc).
                
                # Best way: Import show_specific_forecast from common if possible? No circular dep.
                # Or duplicate logic? Ugly.
                # Or use a shared helper?
                
                # Let's cheat: The user was at 'view_forecast:TOURNAMENT_ID'.
                # We can just delete this message and say "Cancelled", user sees previous menu?
                # No, the previous menu WAS this message (it was edited).
                
                # We need to re-render 'view_forecast'.
                # Since 'show_specific_forecast' is in 'common.py' and 'prediction.py' imports 'common' router... no.
                # Let's move 'show_specific_forecast' logic to a shared helper in 'utils' or just duplicate the simple render here for now.
                # Actually, we can just call `show_tournament_menu_logic` which shows 'My Forecast' button. 
                # User clicks 'My Forecast' -> sees forecast. One extra click but safe.
                
                # Better: Let's try to invoke the handler by constructing a fake object? No.
                
                # Let's just go back to the tournament menu.
                await callback.answer(LEXICON_RU["edit_cancelled"])
                await show_tournament_menu_logic(callback, state, forecast.tournament_id)
                return
            else:
                await callback.answer(LEXICON_RU["forecast_error"], show_alert=True)
                return

    # Action == "yes" -> Continue to editing logic
    await cq_edit_forecast_confirm_yes_logic(callback, state, forecast_id)


async def cq_edit_forecast_confirm_yes_logic(callback: types.CallbackQuery, state: FSMContext, forecast_id: int):
    """Logic for starting edit when confirmed."""
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
            p.id: {"name": p.full_name, "rating": p.current_rating}
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
            selected_ids=forecast_list,
            tournament_id=tournament_id,
            show_back_to_menu=True
        )
        await callback.message.edit_text(
            LEXICON_RU["step_n"].format(next_place=next_place).replace("5", str(prediction_count)),
            reply_markup=kb
        )
    else:
        await state.set_state(MakeForecast.confirming_forecast)
        
        final_forecast_text = LEXICON_RU["final_forecast_header"]
        for i, pid in enumerate(forecast_list):
            p_data = players_dict.get(pid)
            if p_data:
                p_name = p_data['name']
                p_rating = p_data.get('rating')
                display_name = f"{p_name} ({p_rating})" if p_rating is not None else p_name
            else:
                display_name = LEXICON_RU['unknown_player']
            final_forecast_text += f"{i+1}. {display_name}\n"
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
            p_data = players_dict.get(pid)
            if p_data:
                p_name = p_data['name']
                p_rating = p_data.get('rating')
                player_name = f"{p_name} ({p_rating})" if p_rating is not None else p_name
            else:
                player_name = LEXICON_RU["unknown_player"]
            
            text_body += f"{place} {player_name}\n"
            
        # Show buttons to manage this forecast immediately
        # User just made a forecast, so status is likely OPEN.
        # Show others only if admin.
        is_admin = callback.from_user.id in ADMIN_IDS
        
        # We don't have forecast.tournament loaded here easily (forecast object is new)
        # But we know it's OPEN.
        # We can pass tournament_status explicitly if we fetch it, or rely on defaults if we pass show_others directly.
        # Since show_others overrides status logic in KB if status is None? No, KB logic is:
        # if tournament_status is not None: ... else: _show_others = show_others.
        # So if we pass show_others=is_admin and tournament_status=None, it works.
        
        await callback.message.edit_text(
            text_header + text_body,
            reply_markup=view_forecast_kb(
                back_callback="predict_back_to_list",
                forecast_id=new_forecast.id,
                tournament_id=tournament_id,
                allow_edit=True,
                show_others=is_admin,
                is_admin=is_admin
            )
        )
    
    await callback.answer()
    await state.clear()


@router.callback_query(MakeForecast.confirming_forecast, F.data == "confirm_forecast:no")
async def cq_predict_cancel(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tournament_id = data.get("tournament_id")
    await state.clear()
    await callback.answer(LEXICON_RU["forecast_cancelled"])
    
    if tournament_id:
        await show_tournament_menu_logic(callback, state, tournament_id)
    else:
        await cmd_predict_start(callback, state)


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

        forecasts = tournament.forecasts
        if not forecasts:
            await callback.answer(LEXICON_RU["no_forecasts_yet"], show_alert=True)
            return

        total_forecasts = len(forecasts)
        
        # Stats aggregation: Calculate points per player
        # 1st place pick = 5 pts (potential max without bonus)
        # Actually, in RTTF: 1 pt for top, 5 for exact.
        # But here "Popular Top" is about who people PREDICT will win.
        # We should probably weigh 1st place picks higher than 5th place picks.
        # Simple weighted sum: 1st place vote = 5 pts, 2nd = 4 pts ... 5th = 1 pt.
        # This reflects "hype".
        
        stats = {} 
        all_player_ids = set()

        for f in forecasts:
            for rank, player_id in enumerate(f.prediction_data):
                # Rank 0 (1st place) -> 5 points weight
                # Rank 4 (5th place) -> 1 point weight
                # Formula: 6 - (rank + 1) for 5-slot tournament.
                # For 3-slot: 4 - (rank + 1) ?
                # Let's make it dynamic based on prediction length? Or fixed?
                # Fixed 5,4,3,2,1 is good for "popularity".
                
                weight = 5 - rank
                if weight < 1: weight = 1 # Safety
                
                all_player_ids.add(player_id)
                if player_id not in stats:
                    stats[player_id] = {'hype_points': 0, 'votes': 0}
                
                stats[player_id]['hype_points'] += weight
                stats[player_id]['votes'] += 1

        # Batch fetch names
        player_names_map = {}
        if all_player_ids:
            players = await crud.get_players_by_ids(session, all_player_ids)
            for p in players:
                player_names_map[p.id] = p.full_name

        text = LEXICON_RU["analytics_title"].format(name=tournament.name)
        text += LEXICON_RU["total_participants"].format(count=total_forecasts)

        text += LEXICON_RU["popular_top"]
        text += "(очки популярности: 1 место=5, 2=4, 3=3...)\n\n"
        
        sorted_by_hype = sorted(stats.items(), key=lambda x: x[1]['hype_points'], reverse=True)[:10]
        
        for i, (pid, data) in enumerate(sorted_by_hype):
            p_name = player_names_map.get(pid, LEXICON_RU["unknown_player"])
            text += f"{i+1}. <b>{p_name}</b> — {data['hype_points']} (голосов: {data['votes']})\n"
        
        text += LEXICON_RU["click_below"]
        
        await callback.message.edit_text(text, reply_markup=view_others_forecasts_menu_kb(tournament_id, source))
        await callback.answer()


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
    await callback.answer()

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
    await callback.answer()

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
        # Load forecast with tournament info
        forecast = await crud.get_forecast_details(session, forecast_id)
        if not forecast:
            await callback.answer(LEXICON_RU["tournament_not_found"], show_alert=True) 
            return
            
        user_name = forecast.user.username or f"User {forecast.user.id}"
        
        # Batch fetch player names
        player_names_map = {}
        if forecast.prediction_data:
             players = await crud.get_players_by_ids(session, forecast.prediction_data)
             for p in players:
                 player_names_map[p.id] = p.full_name

        text = LEXICON_RU["forecast_detail_title"].format(name=user_name)
        
        # Check if we have results
        results_dict = forecast.tournament.results
        if results_dict:
            # Convert keys to int
            results_dict = {int(k): int(v) for k, v in results_dict.items()}
            
            current_hits = 0
            for rank, player_id in enumerate(forecast.prediction_data):
                p_name = player_names_map.get(player_id, LEXICON_RU["unknown_player"])
                predicted_rank = rank + 1
                
                line_points = 0
                extra_info = ""
                
                if player_id in results_dict:
                    actual_rank = results_dict[player_id]
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
                
                text += f"{predicted_rank}. {p_name}{extra_info} — <b>+{line_points}</b>\n"
            
            if current_hits == len(forecast.prediction_data) and len(forecast.prediction_data) > 0:
                text += "\n🎉 <b>БОНУС: +15 очков за идеальный прогноз!</b>\n"
                
        else:
            # No results yet (LIVE or just published)
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
        await callback.answer()

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
    await callback.answer()


@router.callback_query(F.data.startswith("vof_all_text:"))
async def cq_view_all_forecasts_text(callback: types.CallbackQuery, state: FSMContext):
    """Shows all forecasts in a compact text list."""
    parts = callback.data.split(":")
    tournament_id = int(parts[1])
    source = ":".join(parts[2:])
    if not source:
        source = "menu"
    if source.startswith("hist_") and len(parts) >= 5: 
         source = f"{parts[2]}_{parts[3]}_{parts[4]}"

    async with async_session() as session:
        # Use the method that fetches Users to avoid N+1
        tournament = await crud.get_tournament_with_forecasts_and_users(session, tournament_id)
        if not tournament:
            await callback.answer(LEXICON_RU["tournament_not_found"], show_alert=True)
            return
        
        forecasts = tournament.forecasts
        if not forecasts:
            await callback.answer(LEXICON_RU["no_forecasts_yet"], show_alert=True)
            return
            
        # Pre-fetch all player names
        all_player_ids = set()
        for f in forecasts:
            all_player_ids.update(f.prediction_data)
            
        player_names_map = {}
        if all_player_ids:
            players = await crud.get_players_by_ids(session, all_player_ids)
            for p in players:
                player_names_map[p.id] = p.full_name

        # Sort forecasts: Points desc (if any), then Created At asc (earlier is better)
        sorted_forecasts = sorted(
            forecasts, 
            key=lambda f: (-(f.points_earned or 0), f.created_at)
        )

        header = LEXICON_RU["all_forecasts_header"].format(name=tournament.name)
        
        # Prepare results dict if available
        results_dict = {}
        if tournament.results:
             results_dict = {int(k): int(v) for k, v in tournament.results.items()}

        lines = []
        for f in sorted_forecasts:
            user_name = f.user.username or f"User {f.user.id}"
            points_str = f" (💰 {f.points_earned})" if f.points_earned is not None else ""
            
            # User Header
            block = LEXICON_RU["all_forecasts_user_header"].format(username=user_name, points_str=points_str)
            
            # Vertical list of players
            for rank, pid in enumerate(f.prediction_data):
                p_name = player_names_map.get(pid, LEXICON_RU["unknown_player"])
                
                # Medals for top 3
                prefix = f"{rank+1}."
                if rank == 0: prefix = "🥇"
                elif rank == 1: prefix = "🥈"
                elif rank == 2: prefix = "🥉"
                
                # Result info
                info_suffix = ""
                if results_dict:
                    actual_rank = results_dict.get(pid)
                    predicted_rank = rank + 1
                    
                    if actual_rank:
                        if predicted_rank == actual_rank:
                            info_suffix = " (🎯 Точно!) — <b>+5</b>"
                        else:
                            info_suffix = f" (факт: {actual_rank}) — <b>+1</b>"
                    else:
                        info_suffix = " — <b>+0</b>" # Not in top results

                block += f"{prefix} {p_name}{info_suffix}\n"
            
            block += "\n" # Empty line between users
            lines.append(block)

        # Chunking logic
        messages = []
        current_msg = header
        
        for line in lines:
            # Telegram limit is 4096. We use 4000 to be safe.
            if len(current_msg) + len(line) > 4000:
                messages.append(current_msg)
                current_msg = line
            else:
                current_msg += line
        
        if current_msg:
            messages.append(current_msg)

        # Send messages
        back_kb_for_all_text = all_forecasts_text_back_kb(tournament_id, source) # Use the new keyboard
        
        if len(messages) == 1:
            await callback.message.edit_text(messages[0], reply_markup=back_kb_for_all_text)
        else:
            # If multiple, send them sequentially.
            # First one edits the menu.
            await callback.message.edit_text(messages[0]) 
            
            for i, msg in enumerate(messages[1:]):
                # Only the very last message gets the back button
                is_last = (i == len(messages) - 2)
                kb = back_kb_for_all_text if is_last else None # Use the new keyboard here too
                await callback.message.answer(msg, reply_markup=kb)
                
    await callback.answer()