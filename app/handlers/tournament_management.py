from aiogram import Router, types, F
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
from app.keyboards.inline import get_paginated_players_kb, confirmation_kb
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

    text = f"Управление турниром ID: {tournament.id} от {tournament.date.strftime('%d.%m.%Y')} ({tournament.status.name})"
    kb = tournament_management_menu_kb(tournament_id)

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

# --- UI BUILDERS ---

def all_tournaments_kb(tournaments: list[Tournament]) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать новый турнир", callback_data="tm_create_new")
    for t in tournaments:
        builder.button(
            text=f"ID: {t.id} - {t.date.strftime('%d.%m.%Y')} ({t.status.name})",
            callback_data=f"manage_tournament_{t.id}"
        )
    builder.adjust(1)
    return builder.as_markup()

def tournament_management_menu_kb(tournament_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить участника", callback_data=f"tm_add_participant_start_{tournament_id}")
    builder.button(text="➖ Удалить участника", callback_data=f"tm_remove_participant_start_{tournament_id}")
    builder.button(text="👥 Список участников", callback_data=f"tm_list_participants_{tournament_id}")
    builder.button(text="🔐 Закрыть ставки", callback_data=f"tm_close_bets_{tournament_id}")
    builder.button(text="✏️ Ввести результаты", callback_data=f"tm_set_results_start_{tournament_id}")
    builder.button(text="❌ Удалить турнир", callback_data=f"tm_delete_{tournament_id}")
    builder.button(text="◀️ Назад к списку", callback_data="tm_back_to_list")
    builder.adjust(2, 1, 2, 1)
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
        TournamentManagement.managing_tournament
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


# --- TOURNAMENT CREATION & DELETION ---

@router.callback_query(TournamentManagement.choosing_tournament, F.data == "tm_create_new")
async def cq_create_tournament_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(TournamentManagement.creating_tournament_enter_date)
    await callback.message.edit_text("Введите дату турнира в формате ДД.ММ.ГГГГ:")
    await callback.answer()

@router.message(TournamentManagement.creating_tournament_enter_date)
async def msg_create_tournament_date(message: types.Message, state: FSMContext):
    try:
        event_date = datetime.datetime.strptime(message.text, "%d.%m.%Y").date()
    except ValueError:
        await message.answer("Неверный формат даты. Используйте ДД.ММ.ГГГГ. Попробуйте еще раз.")
        return
    async with async_session() as session:
        new_tournament = Tournament(date=event_date)
        session.add(new_tournament)
        await session.commit()
        await message.answer(f"✅ Турнир на {event_date.strftime('%d.%m.%Y')} успешно создан.")
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

@router.callback_query(TournamentManagement.managing_tournament, F.data.startswith("tm_list_participants_"))
async def cq_list_participants(callback: types.CallbackQuery, state: FSMContext):
    tournament_id = int(callback.data.split("_")[-1])
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
    text = f"<b>Участники турнира (ID: {tournament_id})</b>\n\n"
    if not tournament.participants:
        text += "В этом турнире пока нет зарегистрированных участников."
    else:
        text += "\n".join(f"• {p.full_name}" for p in sorted(tournament.participants, key=lambda p: p.full_name))
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
    data = await state.get_data()
    tournament_id = data['managed_tournament_id']
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
        player = await session.get(Player, player_id)
        if player not in tournament.participants:
            tournament.participants.append(player)
            await session.commit()
            await callback.answer(f"✅ {player.full_name} добавлен.", show_alert=True)
        else:
            await callback.answer(f"⚠️ {player.full_name} уже в турнире.", show_alert=True)
    await show_add_participant_menu(callback, state)

@router.callback_query(TournamentManagement.adding_participant_choosing_player, F.data == "create_new:add_player")
async def cq_add_participant_create_new(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(TournamentManagement.adding_participant_creating_new)
    await callback.message.edit_text("Введите ФИО нового игрока:")
    await callback.answer()

@router.message(TournamentManagement.adding_participant_creating_new)
async def msg_add_participant_create_and_add(message: types.Message, state: FSMContext):
    new_player_name = message.text.strip()
    data = await state.get_data()
    tournament_id = data.get("managed_tournament_id")
    async with async_session() as session:
        existing_player = await session.scalar(select(Player).where(Player.full_name == new_player_name))
        if existing_player:
            await message.answer(f"⚠️ Игрок '{new_player_name}' уже существует. Добавьте его из списка.")
        else:
            new_player = Player(full_name=new_player_name)
            session.add(new_player)
            await session.flush()
            tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
            tournament.participants.append(new_player)
            await session.commit()
            await message.answer(f"✅ Новый игрок '{new_player_name}' создан и добавлен в турнир.")
    await show_tournament_menu(message, state, tournament_id)

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
        else:
            await callback.answer(f"⚠️ {player_to_remove.full_name} уже был удален.", show_alert=True)
    await show_remove_participant_menu(callback, state)


# --- TOURNAMENT ACTIONS & SCORING ---

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
    
    await callback.message.edit_text("⏳ Начинаю расчет очков...")
    async with async_session() as session:
        try:
            tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.forecasts).selectinload(Forecast.user)])
            if not tournament: raise ValueError("Турнир не найден.")
            
            tournament.status = TournamentStatus.FINISHED
            tournament.results = results_dict
            
            users_to_notify = {}
            for forecast in tournament.forecasts:
                points, diffs, exact_hits = calculate_forecast_points(forecast.prediction_data, results_dict)
                forecast.points_earned = points
                user = forecast.user
                users_to_notify[user.id] = {"points": points, "date": tournament.date}
                
                user_forecasts_count_res = await session.execute(
                    select(func.count(Forecast.id)).where(Forecast.user_id == user.id)
                )
                user_forecasts_count = user_forecasts_count_res.scalar_one()
                
                new_total, new_acc, new_mae = calculate_new_stats(user.total_points, user.accuracy_rate, user.avg_error, user_forecasts_count, points, diffs, exact_hits)
                user.total_points = new_total
                user.accuracy_rate = new_acc
                user.avg_error = new_mae
            
            await session.commit()
            
            await callback.message.edit_text(f"✅ Расчет завершен! Обработано {len(tournament.forecasts)} прогнозов.")

            for user_id, info in users_to_notify.items():
                try:
                    await callback.bot.send_message(user_id, f"Турнир от {info['date'].strftime('%d.%m.%Y')} завершен!\nВы набрали: <b>{info['points']}</b> очков. Ваша общая статистика обновлена.")
                    await asyncio.sleep(0.2)
                except Exception as e:
                    logging.warning(f"Failed to send notification to user {user_id}: {e}")
        
        except Exception as e:
            await session.rollback()
            logging.error(f"Critical error during result confirmation: {e}", exc_info=True)
            await callback.message.edit_text(f"❌ Произошла критическая ошибка: {e}")
    
    await state.clear()
    await show_tournament_menu(callback, state, tournament_id)

@router.callback_query(SetResults.confirming_results, F.data == "confirm_results:no")
async def cq_set_results_cancel(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tournament_id = data.get("managed_tournament_id")
    await callback.answer("Ввод результатов отменен.")
    await show_tournament_menu(callback, state, tournament_id)
