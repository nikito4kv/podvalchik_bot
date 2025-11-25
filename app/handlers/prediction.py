from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.db.models import Tournament, TournamentStatus, Player, Forecast, User
from app.db.session import async_session
from app.states.user_states import MakeForecast
from app.keyboards.inline import get_paginated_players_kb, confirmation_kb

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
async def cmd_predict_start(message: types.Message, state: FSMContext):
    """Starts the forecast creation process."""
    available_tournaments = await get_open_tournaments(message.from_user.id)

    if not available_tournaments:
        await message.answer("Сейчас нет турниров, открытых для прогнозов, или вы уже сделали прогноз на все доступные. Загляните позже!")
        return

    # Using the old keyboard here, as it's just for tournament selection.
    from app.keyboards.inline import tournament_selection_kb
    await state.set_state(MakeForecast.choosing_tournament)
    await message.answer(
        "Выберите турнир для создания прогноза:",
        reply_markup=tournament_selection_kb(available_tournaments)
    )

@router.callback_query(MakeForecast.choosing_tournament, F.data.startswith("select_tournament_"))
async def cq_predict_tournament_chosen(callback: types.CallbackQuery, state: FSMContext):
    """Handles tournament selection and starts the prediction process."""
    tournament_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        tournament = await session.get(Tournament, tournament_id, options=[selectinload(Tournament.participants)])
        if not tournament or not tournament.participants:
            await callback.message.edit_text("В этом турнире пока нет зарегистрированных участников. Прогноз невозможен.")
            await state.clear()
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
        # Ask for the next place
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
        # Move to confirmation
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
    
    # Ensure all data is present
    if not all(k in data for k in ['tournament_id', 'forecast_list']):
        await callback.message.edit_text("Произошла ошибка, не вся информация для прогноза найдена. Попробуйте снова.")
        await state.clear()
        return

    new_forecast = Forecast(
        user_id=callback.from_user.id,
        tournament_id=data.get("tournament_id"),
        prediction_data=data.get("forecast_list")
    )

    async with async_session() as session:
        session.add(new_forecast)
        await session.commit()
        await callback.message.edit_text("✅ Ваш прогноз принят!")
            
    await state.clear()


@router.callback_query(MakeForecast.confirming_forecast, F.data == "confirm_forecast:no")
async def cq_predict_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Прогноз отменен.")
    await callback.answer()