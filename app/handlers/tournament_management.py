from aiogram import Bot, Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
import asyncio
import datetime
import logging

from app.filters.is_admin import IsAdmin
from app.db.models import Tournament, Player, TournamentStatus, Forecast, User
from app.db.session import async_session
from app.states.tournament_management import TournamentManagement, SetResults
from app.keyboards.inline import (
    get_paginated_players_kb,
    confirmation_kb,
    cancel_fsm_kb,
    admin_menu_kb,
    get_paginated_tournaments_kb,
    enter_rating_fsm_kb,
    new_player_rating_kb,
    add_player_success_kb
)
from app.core.scoring import calculate_forecast_points, calculate_new_stats
from app.utils.formatting import format_player_list, get_medal_str
from app.utils.broadcaster import broadcast_message


router = Router()
router.message.filter(IsAdmin())

# --- HELPER FUNCTIONS (SHOW MENUS) ---

async def show_tournament_menu(message_or_cb: types.Message | types.CallbackQuery, state: FSMContext, tournament_id: int):
    """Displays the main management menu for a specific tournament."""
    await state.set_state(TournamentManagement.managing_tournament)
    await state.update_data(managed_tournament_id=tournament_id)
    
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id)
    
    if not tournament:
        await cmd_manage_tournaments(message_or_cb, state, "⚠️ Турнир не найден!")
        return

    text = f"Управление турниром «{tournament.name}» от {tournament.date.strftime('%d.%m.%Y')} ({tournament.status.name})"
    kb = tournament_management_menu_kb(tournament)

    if isinstance(message_or_cb, types.Message):
        await message_or_cb.answer(text, reply_markup=kb)
    else: # CallbackQuery
        try:
            await message_or_cb.message.edit_text(text, reply_markup=kb)
        except Exception:
            # Fallback if message to edit is not found (e.g., message was deleted)
            await message_or_cb.message.answer(text, reply_markup=kb)
        await message_or_cb.answer()

async def show_add_participant_menu(cb: types.CallbackQuery, state: FSMContext):
    """Shows the paginated menu for adding players."""
    data = await state.get_data()
    tournament_id = data['managed_tournament_id']
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
        participant_ids = {p.id for p in tournament.participants}
        all_players_res = await session.execute(select(Player))
        all_players = all_players_res.scalars().all()
    
    await state.set_state(TournamentManagement.adding_participant_choosing_player)
    await state.update_data(all_players={p.id: p.full_name for p in all_players})
    
    kb = get_paginated_players_kb(
        players=all_players, action="add_player", selected_ids=list(participant_ids),
        tournament_id=tournament_id, show_create_new=True, show_back_to_menu=True
    )
    await cb.message.edit_text("Выберите игрока для добавления:", reply_markup=kb)
    await cb.answer()

async def show_remove_participant_menu(cb: types.CallbackQuery, state: FSMContext):
    """Shows the paginated menu for removing players."""
    data = await state.get_data()
    tournament_id = data['managed_tournament_id']
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
    
    if not tournament.participants:
        await cb.answer("В турнире нет участников для удаления.", show_alert=True)
        return

    await state.set_state(TournamentManagement.removing_participant_choosing_player)
    await state.update_data(all_players={p.id: p.full_name for p in tournament.participants})
    kb = get_paginated_players_kb(
        players=tournament.participants, action="remove_player",
        tournament_id=tournament_id, show_back_to_menu=True
    )
    await cb.message.edit_text("Выберите игрока для удаления:", reply_markup=kb)
    await cb.answer()


# --- UI BUILDERS ---

def tournament_management_menu_kb(tournament: Tournament) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    tournament_id = tournament.id
    
    # Participant management is available only during setup
    if tournament.status in [TournamentStatus.DRAFT, TournamentStatus.OPEN]:
        builder.button(text="➕ Добавить участника", callback_data=f"tm_add_participant_start_{tournament_id}")
        builder.button(text="➖ Удалить участника", callback_data=f"tm_remove_participant_start_{tournament_id}")
    
    builder.button(text="👥 Список участников", callback_data=f"tm_list_participants_{tournament_id}")

    if tournament.status == TournamentStatus.DRAFT:
        builder.button(text="📢 Опубликовать турнир", callback_data=f"tm_publish_{tournament_id}")
    elif tournament.status == TournamentStatus.OPEN:
        builder.button(text="🔐 Закрыть ставки", callback_data=f"tm_close_bets_{tournament_id}")
    elif tournament.status == TournamentStatus.LIVE:
        builder.button(text="🔓 Открыть ставки", callback_data=f"tm_open_bets_{tournament_id}")

    # Results can only be set when the tournament is LIVE
    if tournament.status == TournamentStatus.LIVE:
        builder.button(text="✏️ Ввести результаты", callback_data=f"tm_set_results_start_{tournament_id}")
    
    # Admin can always view forecasts (analytics)
    builder.button(text="👀 Прогнозы участников", callback_data=f"vof_summary:{tournament_id}:tm_menu")

    if tournament.status == TournamentStatus.FINISHED:
        builder.button(text="🏆 Результаты турнира", callback_data=f"tm_results_{tournament_id}")

    builder.button(text="❌ Удалить турнир", callback_data=f"tm_delete_{tournament_id}")
    builder.button(text="◀️ Назад к списку", callback_data="tm_back_to_list")
    
    # Adjust layout based on status
    if tournament.status == TournamentStatus.DRAFT:
         builder.adjust(2, 1, 1, 1, 2)
    elif tournament.status == TournamentStatus.OPEN:
         builder.adjust(2, 1, 1, 1, 1, 2)
    elif tournament.status == TournamentStatus.LIVE:
         builder.adjust(1, 1, 1, 1, 2)
    else: # FINISHED
        builder.adjust(1, 1, 1, 2) # Adjusted for new button
        
    return builder.as_markup()


# --- ROOT COMMAND & NAVIGATION ---

@router.message(Command("manage_tournaments"))
async def cmd_manage_tournaments(message: types.Message | types.CallbackQuery, state: FSMContext, extra_text: str = None):
    await state.clear()
    text = "<b>Управление турнирами</b>\nВыберите категорию:"
    if extra_text:
        text = f"{extra_text}\n\n{text}"
    
    await state.set_state(TournamentManagement.choosing_tournament)
    
    kb = admin_menu_kb()
    
    if isinstance(message, types.Message):
         await message.answer(text, reply_markup=kb)
    else: # Is a CallbackQuery
        try:
            await message.message.edit_text(text, reply_markup=kb)
        except:
             if message.message:
                await message.message.delete()
             await message.from_user.send(text, reply_markup=kb)
        await message.answer()


@router.callback_query(TournamentManagement.choosing_tournament, F.data.startswith("tm_group:"))
async def cq_view_tournament_group(callback: types.CallbackQuery, state: FSMContext):
    status_group = callback.data.split(":")[1]
    await list_tournaments_logic(callback, status_group, page=0)

@router.callback_query(TournamentManagement.choosing_tournament, F.data.startswith("paginate_tm:"))
async def cq_paginate_tournaments(callback: types.CallbackQuery, state: FSMContext):
    _, status_group, page = callback.data.split(":")
    await list_tournaments_logic(callback, status_group, int(page))

async def list_tournaments_logic(callback: types.CallbackQuery, status_group: str, page: int):
    async with async_session() as session:
        query = select(Tournament).order_by(Tournament.date.desc())
        
        if status_group == "active":
            query = query.where(Tournament.status.in_([TournamentStatus.DRAFT, TournamentStatus.OPEN, TournamentStatus.LIVE]))
            title = "⚡️ Актуальные турниры"
        elif status_group == "finished":
            query = query.where(Tournament.status == TournamentStatus.FINISHED)
            title = "🏁 Завершенные турниры"
        else:
            await callback.answer("Неизвестная группа", show_alert=True)
            return

        result = await session.execute(query)
        tournaments = result.scalars().all()

    if not tournaments:
        await callback.answer("В этой категории пока нет турниров.", show_alert=True)
        return

    kb = get_paginated_tournaments_kb(tournaments, status_group, page)
    await callback.message.edit_text(f"<b>{title}</b>", reply_markup=kb)
    await callback.answer()


@router.callback_query(
    F.data.startswith("manage_tournament_")
)
async def cq_select_tournament_to_manage(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    tournament_id = int(callback.data.split("_")[-1])
    await show_tournament_menu(callback, state, tournament_id)
    await callback.answer()

@router.callback_query(F.data == "tm_back_to_list")
async def cq_back_to_tournament_list(callback: types.CallbackQuery, state: FSMContext):
    await cmd_manage_tournaments(callback, state)

@router.callback_query(StateFilter(TournamentManagement.creating_tournament_enter_name, TournamentManagement.creating_tournament_enter_date), F.data == "fsm_cancel")
async def cq_creation_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Cancels the tournament creation process."""
    await state.clear()
    await callback.answer("Создание турнира отменено.")
    await cmd_manage_tournaments(callback, state)


# --- TOURNAMENT CREATION & DELETION ---

@router.callback_query(TournamentManagement.choosing_tournament, F.data == "tm_create_new")
async def cq_create_tournament_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(TournamentManagement.creating_tournament_enter_name)
    await callback.message.edit_text(
        "Введите название нового турнира:", reply_markup=cancel_fsm_kb()
    )
    await callback.answer()

@router.message(TournamentManagement.creating_tournament_enter_name)
async def msg_create_tournament_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(TournamentManagement.creating_tournament_enter_date)
    await message.answer(
        "Отлично! Теперь введите дату турнира в формате ДД.ММ.ГГГГ:",
        reply_markup=cancel_fsm_kb(),
    )

@router.message(TournamentManagement.creating_tournament_enter_date)
async def msg_create_tournament_date(message: types.Message, state: FSMContext):
    try:
        event_date = datetime.datetime.strptime(message.text, "%d.%m.%Y").date()
    except ValueError:
        await message.answer("Неверный формат даты. Используйте ДД.ММ.ГГГГ. Попробуйте еще раз.")
        return
    
    await state.update_data(date=event_date.isoformat())
    await state.set_state(TournamentManagement.creating_tournament_select_prediction_count)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="3 места", callback_data="pred_count:3")
    builder.button(text="5 мест", callback_data="pred_count:5")
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data="fsm_cancel"))
    
    await message.answer(
        "Сколько мест нужно будет угадать в этом турнире?",
        reply_markup=builder.as_markup()
    )

@router.callback_query(TournamentManagement.creating_tournament_select_prediction_count, F.data.startswith("pred_count:"))
async def cq_create_tournament_finish(callback: types.CallbackQuery, state: FSMContext):
    count = int(callback.data.split(":")[1])
    data = await state.get_data()
    name = data.get("name")
    event_date = datetime.date.fromisoformat(data.get("date"))

    async with async_session() as session:
        new_tournament = Tournament(name=name, date=event_date, prediction_count=count)
        session.add(new_tournament)
        await session.commit()
        # Refresh to get the ID
        await session.refresh(new_tournament)
        
        await callback.message.edit_text(f"✅ Турнир '{name}' на {event_date.strftime('%d.%m.%Y')} успешно создан (Топ-{count}).")
        # Show menu for the NEW tournament
        new_tournament_id = new_tournament.id

    await state.clear()
    # We need to pass the ID. Since show_tournament_menu creates its own session, passing ID is fine.
    await show_tournament_menu(callback, state, new_tournament_id)


@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_delete_"))
async def cq_delete_tournament_confirm(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    await state.update_data(delete_tournament_id=tournament_id)
    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить турнир ID {tournament_id}? Это действие необратимо.",
        reply_markup=confirmation_kb("confirm_delete")
    )
    await callback.answer()

@router.callback_query(TournamentManagement.managing_tournament, F.data == "confirm_delete:yes")
async def cq_delete_tournament_execute(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tournament_id = data.get("delete_tournament_id")
    async with async_session() as session:
        await session.execute(delete(Tournament).where(Tournament.id == tournament_id))
        await session.commit()
    await callback.answer(f"Турнир ID {tournament_id} удален.", show_alert=True)
    await cmd_manage_tournaments(callback, state)

@router.callback_query(TournamentManagement.managing_tournament, F.data == "confirm_delete:no")
async def cq_delete_tournament_cancel(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tournament_id = data.get("managed_tournament_id")
    await show_tournament_menu(callback, state, tournament_id)


@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_results_"))
async def cq_show_tournament_results(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    
    async with async_session() as session:
        # Load tournament with forecasts and users
        tournament = await session.get(
            Tournament, 
            tournament_id, 
            options=[selectinload(Tournament.forecasts).selectinload(Forecast.user)]
        )
        
        if not tournament or not tournament.forecasts:
            await callback.answer("Нет данных о прогнозах.", show_alert=True)
            return

        # Sort forecasts by points descending, then by created_at ascending (who predicted earlier wins tie)
        sorted_forecasts = sorted(
            tournament.forecasts, 
            key=lambda f: (f.points_earned or 0, f.created_at), 
            reverse=True # Reversing logic: points DESC, created_at DESC (wrong).
        )
        # Manual stable sort for correct order:
        sorted_forecasts.sort(key=lambda f: f.created_at) # Sort ASC by time (earlier is better)
        sorted_forecasts.sort(key=lambda f: (f.points_earned or 0), reverse=True) # Sort DESC by points
        
        text = f"<b>🏆 Результаты турнира «{tournament.name}»</b>\n\n<code>"
        text += "#   Имя             Баллы   Время\n" 
        text += "--------------------------------------\n" # Adjusted separator length
        
        for i, f in enumerate(sorted_forecasts, 1):
            user_name = f.user.username or f"id{f.user_id}"
            points = f.points_earned or 0
            
            # Conditional display of created_at
            if f.created_at and f.created_at >= datetime.datetime(2024, 1, 1, 0, 0, 1): # If not the fake time from migration
                 # For the new created_at, it's default=datetime.datetime.utcnow, which means it will be a real timestamp.
                 # The fake one starts at 2024-01-01 00:00:00.
                 # So check for "real" time or "just after fake base time"
                 created_time_str = f.created_at.strftime('%H:%M') # Just HH:MM
            else:
                created_time_str = "N/A  " # Placeholder for old/fake entries, with padding
            
            display_name = user_name
            if len(display_name) > 15:
                display_name = display_name[:12] + "..."
            
            place_icon = f"{i}."
            if i == 1: place_icon = "🥇"
            elif i == 2: place_icon = "🥈"
            elif i == 3: place_icon = "🥉"
            
            # Adjusted points width to ensure alignment
            line = f"{place_icon:<3} {display_name:<15} {points:>5}   {created_time_str}" # Points width increased to 5
            text += f"{line}\n"
            
        text += "</code>"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="◀️ Назад", callback_data=f"manage_tournament_{tournament_id}")
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
        await callback.answer()


# --- PARTICIPANT MANAGEMENT ---

async def add_player_to_tournament_logic(message: types.Message | types.CallbackQuery, state: FSMContext, player_id: int, tournament_id: int):
    """Helper to finalize adding a player to the tournament."""
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
        player = await session.get(Player, player_id)
        
        if player not in tournament.participants:
            tournament.participants.append(player)
            await session.commit()
            text = f"✅ {player.full_name} добавлен"
            if player.current_rating is not None:
                text += f" (Рейтинг: {player.current_rating})"
            else:
                text += " (Без рейтинга)"
            
            await notify_predictors_of_change(message.bot, session, tournament, player, "added")
            
            if isinstance(message, types.CallbackQuery):
                await message.message.edit_text(text, reply_markup=add_player_success_kb(tournament_id))
                await message.answer() # Close loading animation
            else:
                # If from a message (e.g. initial add_player text input), send new message
                await message.answer(text, reply_markup=add_player_success_kb(tournament_id))
        else:
            if isinstance(message, types.CallbackQuery):
                await message.answer(f"⚠️ {player.full_name} уже в турнире.", show_alert=True)
            else:
                await message.answer(f"⚠️ {player.full_name} уже в турнире.")
            
            # If duplicate, we return to the menu so user can pick someone else
            if isinstance(message, types.CallbackQuery):
                await show_add_participant_menu(message, state)
            else:
                # For text input duplicate (unlikely in this flow but possible), we need to restore state
                await state.set_state(TournamentManagement.adding_participant_choosing_player)
                # Re-show menu? Hard with message object. Let's just let them use previous menu or send a new one.
                # Since text input comes from "New Player" flow, and we check duplicate name earlier...
                # This else block is for "Player ID is already in tournament".
                # This happens if they select same existing player twice.
                pass 

    # REMOVED: The unconditional call to show_add_participant_menu
    # User will use the buttons in success message to navigate.


@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_list_participants_"))
async def cq_list_participants(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
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
    builder.button(text="◀️ Назад в меню", callback_data=f"manage_tournament_{tournament_id}")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("tm_add_participant_start_"))
async def cq_add_participant_start(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    await state.update_data(managed_tournament_id=tournament_id)
    await show_add_participant_menu(callback, state)
    await callback.answer()

async def notify_predictors_of_change(bot: Bot, session: async_session, tournament: Tournament, changed_player: Player, action: str):
    """Notifies users who have made a forecast about a change in participants."""
    if tournament.status != TournamentStatus.OPEN:
        return 

    forecasts_res = await session.execute(
        select(Forecast).where(Forecast.tournament_id == tournament.id)
    )
    forecasts = forecasts_res.scalars().all()
    
    if not forecasts:
        return

    action_text = "добавлен в" if action == "added" else "удален из"
    rating_info = f" (Рейтинг: {changed_player.current_rating})" if changed_player.current_rating is not None else ""
    message_text = (
        f"Внимание! Участник <b>{changed_player.full_name}</b>{rating_info} был {action_text} турнир «{tournament.name}».\n"
        "Возможно, вы захотите обновить свой прогноз."
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Перейти к прогнозу", callback_data=f"view_forecast:{tournament.id}")
    kb = builder.as_markup()

    for forecast in forecasts:
        try:
            await bot.send_message(forecast.user_id, message_text, reply_markup=kb, parse_mode="HTML")
            await asyncio.sleep(0.2)
        except Exception as e:
            logging.warning(f"Failed to send participant change notification to user {forecast.user_id}: {e}")


async def show_rating_options_menu(message_or_cb: types.Message | types.CallbackQuery, state: FSMContext, player_id: int):
    """Helper to show the rating options menu for a selected player."""
    async with async_session() as session:
        player = await session.get(Player, player_id)
        if not player:
            if isinstance(message_or_cb, types.CallbackQuery):
                await message_or_cb.answer("Игрок не найден!", show_alert=True)
            else:
                await message_or_cb.answer("Игрок не найден!")
            await show_add_participant_menu(message_or_cb, state) 
            return
            
    current_rating = player.current_rating
    rating_text = str(current_rating) if current_rating is not None else "Нет"
    text = f"Игрок: <b>{player.full_name}</b>\nТекущий рейтинг: <b>{rating_text}</b>\n\nЧто делаем с рейтингом?"
    
    builder = InlineKeyboardBuilder()
    if current_rating is not None:
        builder.button(text=f"✅ Оставить {current_rating}", callback_data="rating:keep")
        builder.button(text="✏️ Изменить", callback_data="rating:change")
    else:
        builder.button(text="✏️ Установить рейтинг", callback_data="rating:change")
        
    builder.button(text="🗑 Без рейтинга", callback_data="rating:clear")
    builder.button(text="↩️ Отмена", callback_data="rating:cancel")
    builder.adjust(1, 1, 2)
    
    await state.set_state(TournamentManagement.adding_participant_rating_options)

    if isinstance(message_or_cb, types.Message):
        await message_or_cb.answer(text, reply_markup=builder.as_markup())
    else:
        await message_or_cb.message.edit_text(text, reply_markup=builder.as_markup())
    await message_or_cb.answer() 

@router.callback_query(TournamentManagement.adding_participant_rating_options, F.data == "rating:keep")
async def cq_rating_keep(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    player_id = data.get("selected_player_id")
    tournament_id = data.get("managed_tournament_id")
    await add_player_to_tournament_logic(callback, state, player_id, tournament_id)

@router.callback_query(TournamentManagement.adding_participant_rating_options, F.data == "rating:clear")
async def cq_rating_clear(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    player_id = data.get("selected_player_id")
    tournament_id = data.get("managed_tournament_id")
    
    async with async_session() as session:
        player = await session.get(Player, player_id)
        player.current_rating = None
        await session.commit()
        
    await add_player_to_tournament_logic(callback, state, player_id, tournament_id)

@router.callback_query(TournamentManagement.adding_participant_rating_options, F.data == "rating:change")
async def cq_rating_change_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    player_id = data.get("selected_player_id")
    
    async with async_session() as session:
        player = await session.get(Player, player_id)
        current_rating = player.current_rating
    
    rating_info = f" (текущий: {current_rating})" if current_rating is not None else " (текущий: нет)"
    await state.set_state(TournamentManagement.adding_participant_entering_rating)
    await callback.message.edit_text(
        f"Введите значение рейтинга (целое число):{rating_info}",
        reply_markup=enter_rating_fsm_kb()
    )
    await callback.answer()

@router.callback_query(TournamentManagement.adding_participant_entering_rating, F.data == "rating:back_to_options")
async def cq_rating_back_to_options(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    player_id = data.get("selected_player_id")
    await show_rating_options_menu(callback, state, player_id)

@router.message(TournamentManagement.adding_participant_entering_rating)
async def msg_rating_input(message: types.Message, state: FSMContext):
    try:
        new_rating = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введите целое число.")
        return

    data = await state.get_data()
    player_id = data.get("selected_player_id")
    tournament_id = data.get("managed_tournament_id")

    async with async_session() as session:
        player = await session.get(Player, player_id)
        player.current_rating = new_rating
        await session.commit()
    
    await add_player_to_tournament_logic(message, state, player_id, tournament_id)

@router.callback_query(TournamentManagement.adding_participant_rating_options, F.data == "rating:cancel")
async def cq_rating_cancel(callback: types.CallbackQuery, state: FSMContext):
    await show_add_participant_menu(callback, state)
    await callback.answer()

@router.callback_query(TournamentManagement.adding_participant_choosing_player, F.data.startswith("add_player:"))
async def cq_add_participant_select(callback: types.CallbackQuery, state: FSMContext):
    """Handles selection of an existing player to add."""
    player_id = int(callback.data.split(":")[1])
    await state.update_data(selected_player_id=player_id)
    await show_rating_options_menu(callback, state, player_id)

@router.callback_query(TournamentManagement.adding_participant_choosing_player, F.data == "create_new:add_player")
async def cq_add_participant_create_new(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(TournamentManagement.adding_participant_creating_new)
    await callback.message.edit_text("Введите ФИО нового игрока:")
    await callback.answer()

@router.message(TournamentManagement.adding_participant_creating_new)
async def msg_add_participant_create_and_add(message: types.Message, state: FSMContext):
    new_player_name = message.text.strip()
    data = await state.get_data()

    async with async_session() as session:
        existing_player = await session.scalar(select(Player).where(func.lower(Player.full_name) == func.lower(new_player_name)))
        if existing_player:
            await message.answer(f"⚠️ Игрок '{new_player_name}' уже существует. Добавьте его из списка.")
            tournament_id = data.get("managed_tournament_id")
            await state.set_state(TournamentManagement.adding_participant_choosing_player)
            tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
            participant_ids = {p.id for p in tournament.participants}
            all_players_res = await session.execute(select(Player))
            all_players = all_players_res.scalars().all()
            await state.update_data(all_players={p.id: p.full_name for p in all_players})
            kb = get_paginated_players_kb(
                players=all_players, action="add_player", selected_ids=list(participant_ids),
                tournament_id=tournament_id, show_create_new=True, show_back_to_menu=True
            )
            await message.answer("Выберите игрока для добавления:", reply_markup=kb)
            return
        else:
            new_player = Player(full_name=new_player_name)
            session.add(new_player)
            await session.commit() 
            await session.refresh(new_player)
            
            await state.update_data(selected_player_id=new_player.id)
            
            text = (
                f"✅ Новый игрок <b>{new_player.full_name}</b> создан.\n\n"
                "Введите его рейтинг (целое число) или нажмите кнопку, чтобы оставить без рейтинга:"
            )
            
            await state.set_state(TournamentManagement.adding_new_participant_rating)
            await message.answer(text, reply_markup=new_player_rating_kb())

@router.message(TournamentManagement.adding_new_participant_rating)
async def msg_new_player_rating_input(message: types.Message, state: FSMContext):
    try:
        new_rating = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введите целое число или нажмите кнопку 'Пропустить'.")
        return

    data = await state.get_data()
    player_id = data.get("selected_player_id")
    tournament_id = data.get("managed_tournament_id")

    async with async_session() as session:
        player = await session.get(Player, player_id)
        player.current_rating = new_rating
        await session.commit()
    
    await add_player_to_tournament_logic(message, state, player_id, tournament_id)

@router.callback_query(TournamentManagement.adding_new_participant_rating, F.data == "new_rating:skip")
async def cq_new_player_rating_skip(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    player_id = data.get("selected_player_id")
    tournament_id = data.get("managed_tournament_id")
    
    # Player already has None rating by default, just add to tournament
    await add_player_to_tournament_logic(callback, state, player_id, tournament_id)

@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_remove_participant_start_"))
async def cq_remove_participant_start(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    await state.update_data(managed_tournament_id=tournament_id)
    await show_remove_participant_menu(callback, state)
    await callback.answer()

@router.callback_query(TournamentManagement.removing_participant_choosing_player, F.data.startswith("remove_player:"))
async def cq_remove_participant_select(callback: types.CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    tournament_id = data['managed_tournament_id']
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
        player_to_remove = await session.get(Player, player_id)
        
        if player_to_remove in tournament.participants:
            tournament.participants.remove(player_to_remove)
            await session.commit()
            await callback.answer(f"✅ {player_to_remove.full_name} удален.", show_alert=True)
            await notify_predictors_of_change(callback.bot, session, tournament, player_to_remove, "removed")
        else:
            await callback.answer(f"⚠️ {player_to_remove.full_name} уже был удален.", show_alert=True)
            
    await show_remove_participant_menu(callback, state)


# --- TOURNAMENT ACTIONS & SCORING ---

@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_publish_"))
async def cq_publish_tournament(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    async with async_session() as session:
        # Load with participants for validation
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
        if not tournament:
            await callback.answer("⚠️ Турнир не найден.", show_alert=True)
            return
        if tournament.status != TournamentStatus.DRAFT:
            await callback.answer(f"⚠️ Этот турнир уже опубликован или начат. Статус: {tournament.status.name}", show_alert=True)
            return
            
        # Validate participant count
        min_count = tournament.prediction_count or 5
        current_count = len(tournament.participants)
        if current_count < min_count:
            await callback.answer(
                f"⛔️ Нельзя опубликовать турнир!\n\nВ турнире всего {current_count} участников, а прогноз требует {min_count} мест. Добавьте еще участников.", 
                show_alert=True
            )
            return

        tournament.status = TournamentStatus.OPEN
        await session.commit()
        await callback.answer("✅ Турнир опубликован и открыт для прогнозов.", show_alert=True)
        
        # --- Broadcast Notification ---
        # Run in background. We pass IDs/data, NOT the session.
        asyncio.create_task(notify_users_about_new_tournament(callback.bot, tournament.id, tournament.name, tournament.date))

    await show_tournament_menu(callback, state, tournament_id)


async def notify_users_about_new_tournament(bot: Bot, tournament_id: int, tournament_name: str, tournament_date: datetime.date):
    """Helper to broadcast the new tournament notification."""
    # Create a NEW session for this background task
    async with async_session() as session:
        users_res = await session.execute(select(User.id))
        user_ids = users_res.scalars().all()
    
    if not user_ids:
        return

    text = (
        f"📢 <b>Новый турнир открыт для прогнозов!</b>\n\n"
        f"🏓 <b>«{tournament_name}»</b>\n"
        f"📅 Дата: {tournament_date.strftime('%d.%m.%Y')}\n\n"
        f"Успейте сделать свой прогноз и побороться за очки! 👇"
    )
    
    # Direct link to the tournament menu
    builder = InlineKeyboardBuilder()
    builder.button(text="🔮 Сделать прогноз", callback_data=f"select_tournament_{tournament_id}")
    
    await broadcast_message(bot, user_ids, text, reply_markup=builder.as_markup())


@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_close_bets_"))
async def cq_close_bets(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id)
        if not tournament:
            await callback.answer("⚠️ Турнир не найден.", show_alert=True)
            return
        if tournament.status != TournamentStatus.OPEN:
            await callback.answer(f"⚠️ Ставки уже закрыты или турнир завершен. Статус: {tournament.status.name}", show_alert=True)
            return
        tournament.status = TournamentStatus.LIVE
        await session.commit()
        await callback.answer("✅ Прием ставок закрыт. Статус изменен на LIVE.", show_alert=True)
        
        # Notify forecasters
        asyncio.create_task(notify_forecasters_status_change(callback.bot, tournament.id, tournament.name, "LIVE"))

    await show_tournament_menu(callback, state, tournament_id)


@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_open_bets_"))
async def cq_open_bets(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id)
        if not tournament:
            await callback.answer("⚠️ Турнир не найден.", show_alert=True)
            return
        if tournament.status != TournamentStatus.LIVE:
            await callback.answer(f"⚠️ Ставки уже открыты или турнир завершен. Статус: {tournament.status.name}", show_alert=True)
            return
        tournament.status = TournamentStatus.OPEN
        await session.commit()
        await callback.answer("✅ Прием ставок снова открыт. Статус изменен на OPEN.", show_alert=True)
        
        # Notify forecasters
        asyncio.create_task(notify_forecasters_status_change(callback.bot, tournament.id, tournament.name, "OPEN"))

    await show_tournament_menu(callback, state, tournament_id)


async def notify_forecasters_status_change(bot: Bot, tournament_id: int, tournament_name: str, new_status: str):
    """Notifies users who predicted on this tournament about status change."""
    async with async_session() as session:
        # Get user IDs who made a forecast
        result = await session.execute(select(Forecast.user_id).where(Forecast.tournament_id == tournament_id))
        user_ids = result.scalars().all()
    
    if not user_ids:
        return

    builder = InlineKeyboardBuilder()
    
    if new_status == "LIVE":
        text = (
            f"🔐 <b>Ставки на турнир «{tournament_name}» закрыты!</b>\n\n"
            "Турнир начался. Теперь вы можете посмотреть прогнозы других участников и болеть за своих фаворитов!"
        )
        builder.button(text="👀 Прогнозы участников", callback_data=f"vof_summary:{tournament_id}:active")
    else: # OPEN
        text = (
            f"🔓 <b>Прием ставок на турнир «{tournament_name}» возобновлен!</b>\n\n"
            "Если вы хотели изменить свой прогноз, сейчас самое время."
        )
        builder.button(text="👀 Мой прогноз", callback_data=f"view_forecast:{tournament_id}")
    
    await broadcast_message(bot, user_ids, text, reply_markup=builder.as_markup())


@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_set_results_start_"))
async def cq_set_results_start(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
    if tournament.status != TournamentStatus.LIVE:
        await callback.answer(f"Нельзя ввести результаты для этого турнира. Текущий статус: {tournament.status.name}", show_alert=True)
        return
    
    prediction_count = tournament.prediction_count or 5
    if not tournament.participants or len(tournament.participants) < prediction_count:
        await callback.answer(f"Недостаточно участников в турнире ({len(tournament.participants)}) для ввода результатов (требуется {prediction_count}).", show_alert=True)
        return
        
    await state.set_state(SetResults.entering_results)
    await state.update_data(
        managed_tournament_id=tournament_id,
        tournament_players={p.id: p.full_name for p in tournament.participants},
        results_list=[],
        prediction_count=prediction_count
    )
    kb = get_paginated_players_kb(players=tournament.participants, action="set_result", tournament_id=tournament_id, show_back_to_menu=True)
    await callback.message.edit_text(f"<b>Ввод результатов. Шаг 1/{prediction_count}:</b> Выберите <b>1 место</b>:", reply_markup=kb)
    await callback.answer()

@router.callback_query(SetResults.entering_results, F.data.startswith("set_result:"))
async def cq_process_result_selection(callback: types.CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    results_list = data.get("results_list", [])
    prediction_count = data.get("prediction_count", 5)
    
    if player_id in results_list:
        await callback.answer("Этот игрок уже в списке результатов!", show_alert=True)
        return
    results_list.append(player_id)
    await state.update_data(results_list=results_list)
    
    next_place = len(results_list) + 1
    if next_place <= prediction_count:
        async with async_session() as session:
             tournament = await session.get(Tournament, data.get("managed_tournament_id"), options=[selectinload(Tournament.participants)])
             players = tournament.participants

        kb = get_paginated_players_kb(players=players, action="set_result", selected_ids=results_list, tournament_id=data.get("managed_tournament_id"), show_back_to_menu=True)
        await callback.message.edit_text(f"<b>Шаг {next_place}/{prediction_count}:</b> Выберите <b>{next_place} место</b>:", reply_markup=kb)
    else:
        await state.set_state(SetResults.confirming_results)
        async with async_session() as session:
             players = await session.execute(select(Player).where(Player.id.in_(results_list)))
             players_map = {p.id: p.full_name for p in players.scalars()}
             
        final_results_text = "<b>Итоговый список для подтверждения:</b>\n" + "\n".join(f"{i+1}. {players_map.get(pid, 'Неизвестный')}" for i, pid in enumerate(results_list))
        await callback.message.edit_text(final_results_text, reply_markup=confirmation_kb(action_prefix="confirm_results"))
    await callback.answer()

@router.callback_query(SetResults.confirming_results, F.data == "confirm_results:yes")
async def cq_set_results_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tournament_id = data.get("managed_tournament_id")
    results_list = data.get("results_list", [])
    results_dict = {player_id: rank + 1 for rank, player_id in enumerate(results_list)}

    await callback.message.edit_text("⏳ Начинаю расчет очков и рассылку...")
    await callback.answer()

    async with async_session() as session:
        try:
            tournament = await session.get(
                Tournament,
                tournament_id,
                options=[
                    selectinload(Tournament.forecasts).selectinload(Forecast.user)
                ],
            )
            if not tournament:
                raise ValueError("Турнир не найден.")

            # --- Data Processing ---
            tournament.status = TournamentStatus.FINISHED
            tournament.results = results_dict

            # Collect all player IDs from results and all forecasts to fetch names in one query
            all_player_ids = set(results_dict.keys())
            for forecast in tournament.forecasts:
                all_player_ids.update(forecast.prediction_data)
            
            player_name_map = {}
            if all_player_ids:
                players_res = await session.execute(select(Player).where(Player.id.in_(all_player_ids)))
                player_name_map = {p.id: p.full_name for p in players_res.scalars()}

            # Process each forecast
            for forecast in tournament.forecasts:
                points, diffs, exact_hits = calculate_forecast_points(
                    forecast.prediction_data, results_dict
                )
                forecast.points_earned = points
                user = forecast.user
                
                # New logic: using stored total_slots
                total_slots_before = user.total_slots or 0
                
                # If migrating from old system where total_slots was 0 but forecasts existed:
                # We can't easily fix it here without re-scanning all history.
                # Assuming migration script or fresh start handled it or we accept slight inaccuracy for old users.
                
                new_total, new_acc, new_mae = calculate_new_stats(
                    user.total_points, user.accuracy_rate, user.avg_error, 
                    total_slots_before, 
                    points, diffs, exact_hits
                )
                user.total_points = new_total
                user.accuracy_rate = new_acc
                user.avg_error = new_mae
                user.total_slots = total_slots_before + len(forecast.prediction_data)
                
                # Update gamification stats
                user.tournaments_played = (user.tournaments_played or 0) + 1
                user.exact_guesses = (user.exact_guesses or 0) + exact_hits
                
                # Check perfect bonus
                slots_count = len(forecast.prediction_data)
                if slots_count > 0 and exact_hits == slots_count:
                    user.perfect_tournaments = (user.perfect_tournaments or 0) + 1

            await session.commit()

            await callback.message.edit_text(
                f"✅ Расчет завершен! Обработано {len(tournament.forecasts)} прогнозов. Начинаю рассылку..."
            )
            
            # Format final results once
            sorted_results = sorted(results_dict.items(), key=lambda item: item[1])
            final_results_pids = [item[0] for item in sorted_results]
            results_text = f"<b>🏆 Итоги турнира:</b>\n" + format_player_list(final_results_pids, player_name_map)

            # Notify users
            for forecast in tournament.forecasts:
                try:
                    # Build detailed prediction text with points
                    prediction_text = f"<b>📜 Ваш прогноз:</b>\n"
                    
                    total_points = forecast.points_earned or 0
                    # Re-calculate breakdown for display (or we could store it, but calc is cheap)
                    # We need the diffs/hits logic here locally or helper
                    
                    for i, pid in enumerate(forecast.prediction_data):
                        predicted_rank = i + 1
                        p_name = player_name_map.get(pid, "Неизвестный")
                        
                        line_points = 0
                        extra_info = ""
                        
                        if pid in results_dict:
                            actual_rank = results_dict[pid]
                            diff = abs(predicted_rank - actual_rank)
                            
                            if diff == 0:
                                line_points = 5
                                extra_info = " (🎯 Точно!)"
                            else:
                                line_points = 1
                                extra_info = f" (факт: {actual_rank})"
                        else:
                             line_points = 0
                             extra_info = " (не в топе)"
                        
                        prediction_text += f"{i+1}. {p_name}{extra_info} — <b>+{line_points}</b>\n"

                    # Add logic to show Bonus if perfect
                    # Re-calculate if bonus applies? Or just check total_points
                    # Simple check: if total_points == (count * 5) + 15, then bonus applied.
                    # Or better: check diffs here locally.
                    
                    current_hits = 0
                    for i, pid in enumerate(forecast.prediction_data):
                         if pid in results_dict and results_dict[pid] == i + 1:
                             current_hits += 1
                    
                    if current_hits == len(forecast.prediction_data) and len(forecast.prediction_data) > 0:
                        prediction_text += "\n🎉 <b>БОНУС: +15 очков за идеальный прогноз!</b>\n"

                    user_message = (
                        f"<b>Итоги турнира «{tournament.name}» от {tournament.date.strftime('%d.%m.%Y')}</b>\n\n"
                        f"{results_text}\n"
                        f"{prediction_text}\n"
                        f"<b>💰 Итого очков: {total_points}</b>"
                    )
                    await callback.bot.send_message(forecast.user_id, user_message)
                    await asyncio.sleep(0.2)
                except Exception as e:
                    logging.warning(
                        f"Failed to send notification to user {forecast.user_id}: {e}"
                    )
            
            # Notify admin with ALL forecasters
            all_forecasters = sorted(tournament.forecasts, key=lambda f: (f.points_earned or 0, -f.id), reverse=True)
            
            admin_summary_text = f"<b>🏆 Итоги прогнозов турнира «{tournament.name}»:</b>\n\n"
            
            for i, forecast in enumerate(all_forecasters):
                place = get_medal_str(i + 1)
                username = forecast.user.username or f"id:{forecast.user.id}"
                line = f"{place} @{username} - <b>{forecast.points_earned or 0}</b> очков\n"
                
                if len(admin_summary_text) + len(line) > 4000:
                    await callback.message.answer(admin_summary_text)
                    admin_summary_text = ""
                
                admin_summary_text += line

            if admin_summary_text:
                await callback.message.answer(admin_summary_text)

        except Exception as e:
            await session.rollback()
            logging.error(
                f"Critical error during result confirmation: {e}", exc_info=True
            )
            await callback.message.edit_text(f"❌ Произошла критическая ошибка: {e}")

    await state.clear()
    await show_tournament_menu(callback, state, tournament_id)

@router.callback_query(SetResults.confirming_results, F.data == "confirm_results:no")
async def cq_set_results_cancel(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tournament_id = data.get("managed_tournament_id")
    await callback.answer("Ввод результатов отменен.")
    await show_tournament_menu(callback, state, tournament_id)