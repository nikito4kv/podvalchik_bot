from aiogram import Bot, Router, types, F
from aiogram.filters import Command
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
from app.keyboards.inline import get_paginated_players_kb, confirmation_kb, cancel_fsm_kb
from app.core.scoring import calculate_forecast_points, calculate_new_stats


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
            if message_or_cb.message:
                try: await message_or_cb.message.delete()
                except: pass
            await message_or_cb.from_user.send(text, reply_markup=kb)

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


async def notify_predictors_of_change(bot: Bot, session: async_session, tournament: Tournament, changed_player: Player, action: str):
    """Notifies users who have made a forecast about a change in participants."""
    if tournament.status != TournamentStatus.OPEN:
        return # Only notify for open tournaments

    forecasts_res = await session.execute(
        select(Forecast).where(Forecast.tournament_id == tournament.id)
    )
    forecasts = forecasts_res.scalars().all()
    
    if not forecasts:
        return

    action_text = "добавлен в" if action == "added" else "удален из"
    message_text = (
        f"Внимание! Участник <b>{changed_player.full_name}</b> был {action_text} турнир «{tournament.name}».\n"
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

# --- UI BUILDERS ---

def all_tournaments_kb(tournaments: list[Tournament]) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать новый турнир", callback_data="tm_create_new")
    for t in tournaments:
        builder.button(
            text=f"«{t.name}» ({t.date.strftime('%d.%m.%Y')}) - {t.status.name}",
            callback_data=f"manage_tournament_{t.id}"
        )
    builder.adjust(1)
    return builder.as_markup()

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
    
    builder.button(text="❌ Удалить турнир", callback_data=f"tm_delete_{tournament_id}")
    builder.button(text="◀️ Назад к списку", callback_data="tm_back_to_list")
    
    # Adjust layout based on status
    if tournament.status == TournamentStatus.DRAFT:
         builder.adjust(2, 1, 1, 2)
    elif tournament.status == TournamentStatus.OPEN:
         builder.adjust(2, 1, 1, 1, 2)
    elif tournament.status == TournamentStatus.LIVE:
         builder.adjust(1, 1, 1, 2) # New adjustment for LIVE
    else: # FINISHED
        builder.adjust(1, 2)
        
    return builder.as_markup()


# --- ROOT COMMAND & NAVIGATION ---

@router.message(Command("manage_tournaments"))
async def cmd_manage_tournaments(message: types.Message | types.CallbackQuery, state: FSMContext, extra_text: str = None):
    await state.clear()
    async with async_session() as session:
        result = await session.execute(select(Tournament).order_by(Tournament.date.desc()))
        tournaments = result.scalars().all()

    text = "Выберите турнир для управления или создайте новый:"
    if extra_text:
        text = f"{extra_text}\n\n{text}"
    kb = all_tournaments_kb(tournaments)

    await state.set_state(TournamentManagement.choosing_tournament)
    if isinstance(message, types.Message):
         await message.answer(text, reply_markup=kb)
    else: # Is a CallbackQuery
        try:
            await message.message.edit_text(text, reply_markup=kb)
        except:
             if message.message:
                await message.message.delete()
             await message.from_user.send(text, reply_markup=kb)


from aiogram.filters import Command, StateFilter


@router.callback_query(
    StateFilter(
        TournamentManagement.choosing_tournament,
        TournamentManagement.adding_participant_choosing_player,
        TournamentManagement.removing_participant_choosing_player,
        TournamentManagement.managing_tournament,
        SetResults.entering_results,
        SetResults.confirming_results,
    ),
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
    
    data = await state.get_data()
    name = data.get("name")

    async with async_session() as session:
        new_tournament = Tournament(name=name, date=event_date)
        session.add(new_tournament)
        await session.commit()
        await message.answer(f"✅ Турнир '{name}' на {event_date.strftime('%d.%m.%Y')} успешно создан.")
    
    await state.clear() # Clear state after creation
    # Show the main menu again, but it requires a message/callback, so we call the root handler
    await cmd_manage_tournaments(message, state)


@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_delete_"))
async def cq_delete_tournament_confirm(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    await state.update_data(delete_tournament_id=tournament_id)
    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить турнир ID {tournament_id}? Это действие необратимо.",
        reply_markup=confirmation_kb("confirm_delete")
    )

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
            
            # Notify users
            await notify_predictors_of_change(message.bot, session, tournament, player, "added")
            
            if isinstance(message, types.CallbackQuery):
                await message.answer(text, show_alert=True)
            else:
                await message.answer(text)
        else:
            if isinstance(message, types.CallbackQuery):
                await message.answer(f"⚠️ {player.full_name} уже в турнире.", show_alert=True)
            else:
                await message.answer(f"⚠️ {player.full_name} уже в турнире.")

    if isinstance(message, types.CallbackQuery):
        await show_add_participant_menu(message, state)
    else:
        # Trick to reuse the show_add_participant_menu which expects a CallbackQuery
        # We need to send a message with the menu
        await state.set_state(TournamentManagement.adding_participant_choosing_player)
        # We need to re-fetch data to pass to get_paginated_players_kb, easiest is to call the menu shower
        # But show_add_participant_menu takes a CallbackQuery.
        # Let's manually trigger the menu display logic for Message context
        async with async_session() as session:
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

@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_add_participant_start_"))
async def cq_add_participant_start(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    await state.update_data(managed_tournament_id=tournament_id)
    await show_add_participant_menu(callback, state)
    await callback.answer()

@router.callback_query(TournamentManagement.adding_participant_choosing_player, F.data.startswith("add_player:"))
async def cq_add_participant_select(callback: types.CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split(":")[1])
    await state.update_data(selected_player_id=player_id)
    
    async with async_session() as session:
        player = await session.get(Player, player_id)
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
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

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
    await state.set_state(TournamentManagement.adding_participant_entering_rating)
    await callback.message.edit_text("Введите значение рейтинга (целое число):")
    await callback.answer()

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

@router.callback_query(TournamentManagement.adding_participant_choosing_player, F.data == "create_new:add_player")
async def cq_add_participant_create_new(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(TournamentManagement.adding_participant_creating_new)
    await callback.message.edit_text("Введите ФИО нового игрока:")
    await callback.answer()

@router.message(TournamentManagement.adding_participant_creating_new)
async def msg_add_participant_create_and_add(message: types.Message, state: FSMContext):
    new_player_name = message.text.strip()
    data = await state.get_data()
    # tournament_id = data.get("managed_tournament_id") # Not needed here immediately anymore

    async with async_session() as session:
        existing_player = await session.scalar(select(Player).where(func.lower(Player.full_name) == func.lower(new_player_name)))
        if existing_player:
            await message.answer(f"⚠️ Игрок '{new_player_name}' уже существует. Добавьте его из списка.")
            # Need to go back to list or selection.
            # Using logic similar to the end of add_player_to_tournament_logic for Message context
            # But here we just want to show the list again.
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
            await session.commit() # Commit to get ID
            await session.refresh(new_player)
            
            await state.update_data(selected_player_id=new_player.id)
            
            # Now go to rating options
            text = f"✅ Новый игрок <b>{new_player.full_name}</b> создан.\nРейтинга пока нет.\n\nЧто делаем?"
            builder = InlineKeyboardBuilder()
            builder.button(text="✏️ Установить рейтинг", callback_data="rating:change")
            builder.button(text="🗑 Без рейтинга", callback_data="rating:clear")
            builder.button(text="↩️ Отмена (не добавлять)", callback_data="rating:cancel")
            builder.adjust(1, 1)
            
            await state.set_state(TournamentManagement.adding_participant_rating_options)
            await message.answer(text, reply_markup=builder.as_markup())

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
            # Notify users
            await notify_predictors_of_change(callback.bot, session, tournament, player_to_remove, "removed")
        else:
            await callback.answer(f"⚠️ {player_to_remove.full_name} уже был удален.", show_alert=True)
            
    await show_remove_participant_menu(callback, state)


# --- TOURNAMENT ACTIONS & SCORING ---

@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_publish_"))
async def cq_publish_tournament(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id)
        if not tournament:
            await callback.answer("⚠️ Турнир не найден.", show_alert=True)
            return
        if tournament.status != TournamentStatus.DRAFT:
            await callback.answer(f"⚠️ Этот турнир уже опубликован или начат. Статус: {tournament.status.name}", show_alert=True)
            return
        tournament.status = TournamentStatus.OPEN
        await session.commit()
        await callback.answer("✅ Турнир опубликован и открыт для прогнозов.", show_alert=True)
    await show_tournament_menu(callback, state, tournament_id)


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
    await show_tournament_menu(callback, state, tournament_id)


@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_set_results_start_"))
async def cq_set_results_start(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
    if tournament.status != TournamentStatus.LIVE:
        await callback.answer(f"Нельзя ввести результаты для этого турнира. Текущий статус: {tournament.status.name}", show_alert=True)
        return
    if not tournament.participants or len(tournament.participants) < 5:
        await callback.answer(f"Недостаточно участников в турнире ({len(tournament.participants)}) для ввода результатов.", show_alert=True)
        return
    await state.set_state(SetResults.entering_results)
    await state.update_data(
        managed_tournament_id=tournament_id,
        tournament_players={p.id: p.full_name for p in tournament.participants},
        results_list=[]
    )
    kb = get_paginated_players_kb(players=tournament.participants, action="set_result", tournament_id=tournament_id, show_back_to_menu=True)
    await callback.message.edit_text("<b>Ввод результатов. Шаг 1/5:</b> Выберите <b>1 место</b>:", reply_markup=kb)
    await callback.answer()

@router.callback_query(SetResults.entering_results, F.data.startswith("set_result:"))
async def cq_process_result_selection(callback: types.CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    players_dict = data.get("tournament_players", {})
    results_list = data.get("results_list", [])
    if player_id in results_list:
        await callback.answer("Этот игрок уже в списке результатов!", show_alert=True)
        return
    results_list.append(player_id)
    await state.update_data(results_list=results_list)
    next_place = len(results_list) + 1
    if next_place <= 5:
        player_objects = [Player(id=pid, full_name=name) for pid, name in players_dict.items()]
        kb = get_paginated_players_kb(players=player_objects, action="set_result", selected_ids=results_list, tournament_id=data.get("managed_tournament_id"), show_back_to_menu=True)
        await callback.message.edit_text(f"<b>Шаг {next_place}/5:</b> Выберите <b>{next_place} место</b>:", reply_markup=kb)
    else:
        await state.set_state(SetResults.confirming_results)
        final_results_text = "<b>Итоговый список для подтверждения:</b>\n" + "\n".join(f"{i+1}. {players_dict.get(pid, 'Неизвестный')}" for i, pid in enumerate(results_list))
        await callback.message.edit_text(final_results_text, reply_markup=confirmation_kb(action_prefix="confirm_results"))
    await callback.answer()

@router.callback_query(SetResults.confirming_results, F.data == "confirm_results:yes")
async def cq_set_results_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tournament_id = data.get("managed_tournament_id")
    results_list = data.get("results_list", [])
    results_dict = {player_id: rank + 1 for rank, player_id in enumerate(results_list)}

    await callback.message.edit_text("⏳ Начинаю расчет очков и рассылку...")

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
                
                # Update user's global stats
                user_forecasts_count_res = await session.execute(
                    select(func.count(Forecast.id)).where(Forecast.user_id == user.id)
                )
                user_forecasts_count = user_forecasts_count_res.scalar_one()

                new_total, new_acc, new_mae = calculate_new_stats(
                    user.total_points, user.accuracy_rate, user.avg_error, user_forecasts_count, points, diffs, exact_hits
                )
                user.total_points = new_total
                user.accuracy_rate = new_acc
                user.avg_error = new_mae

            await session.commit()

            # --- Notifications ---
            await callback.message.edit_text(
                f"✅ Расчет завершен! Обработано {len(tournament.forecasts)} прогнозов. Начинаю рассылку..."
            )

            def format_ranking(player_ids, title):
                medals = {0: "🥇", 1: "🥈", 2: "🥉"}
                text = f"<b>{title}</b>\n"
                for i, pid in enumerate(player_ids):
                    place = medals.get(i, f" {i + 1}.")
                    player_name = player_name_map.get(pid, "Неизвестный игрок")
                    text += f"{place} {player_name}\n"
                return text
            
            # Format final results once
            sorted_results = sorted(results_dict.items(), key=lambda item: item[1])
            final_results_pids = [item[0] for item in sorted_results]
            results_text = format_ranking(final_results_pids, "🏆 Итоги турнира:")

            # Notify users
            for forecast in tournament.forecasts:
                try:
                    prediction_text = format_ranking(forecast.prediction_data, "📜 Ваш прогноз:")
                    user_message = (
                        f"<b>Итоги турнира «{tournament.name}» от {tournament.date.strftime('%d.%m.%Y')}</b>\n\n"
                        f"{results_text}\n"
                        f"{prediction_text}\n"
                        f"<b>💰 Очки за прогноз: {forecast.points_earned or 0}</b>"
                    )
                    await callback.bot.send_message(forecast.user_id, user_message)
                    await asyncio.sleep(0.2)
                except Exception as e:
                    logging.warning(
                        f"Failed to send notification to user {forecast.user_id}: {e}"
                    )
            
            # Notify admin with ALL forecasters
            # Tie-breaker: earlier forecast (lower ID) wins.
            # We sort by (points descending, id ascending).
            # Since we use reverse=True (descending), we use (points, -id).
            all_forecasters = sorted(tournament.forecasts, key=lambda f: (f.points_earned or 0, -f.id), reverse=True)
            
            admin_summary_text = f"<b>🏆 Итоги прогнозов турнира «{tournament.name}»:</b>\n\n"
            medals = {0: "🥇", 1: "🥈", 2: "🥉"}
            
            for i, forecast in enumerate(all_forecasters):
                place = medals.get(i, f" {i + 1}.")
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
