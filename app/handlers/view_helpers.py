from aiogram import types

from app.db.models import Tournament, Forecast, TournamentStatus
from app.keyboards.inline import view_forecast_kb
from app.lexicon.ru import LEXICON_RU
from app.db import crud
from app.config import config

async def show_forecast_card(
    callback_query: types.CallbackQuery, 
    tournament: Tournament, 
    forecast: Forecast, 
    session
):
    """
    Displays the forecast card (text + buttons) directly.
    """
    # Fetch player objects
    player_ids = forecast.prediction_data
    if not player_ids:
        await callback_query.answer("В этом прогнозе нет данных об игроках.", show_alert=True)
        return

    players = await crud.get_players_by_ids(session, player_ids)
    players_map = {p.id: p for p in players}

    # Format the message
    tournament_date = tournament.date.strftime("%d.%m.%Y")
    text = f"<b>Ваш прогноз на турнир «{tournament.name}» от {tournament_date}:</b>\n\n"

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
    allow_edit = (tournament.status == TournamentStatus.OPEN) 
    
    # Show 'Other Forecasts' only if NOT OPEN or if admin
    is_admin = callback_query.from_user.id in config.admin_ids
    status_str = tournament.status.name if hasattr(tournament.status, "name") else str(tournament.status)
    show_others = (status_str != "OPEN") or is_admin

    kb = view_forecast_kb(
        back_callback="predict_back_to_list", 
        forecast_id=forecast.id,
        tournament_id=tournament.id,
        allow_edit=allow_edit,
        show_others=show_others,
        is_admin=is_admin,
        tournament_status=tournament.status
    )

    await callback_query.message.edit_text(text, reply_markup=kb)
    await callback_query.answer()
