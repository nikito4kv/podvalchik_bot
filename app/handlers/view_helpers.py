from aiogram import types

from app.db.models import Tournament, Forecast
from app.keyboards.inline import view_forecast_kb
from app.db import crud
from app.config import config
from app.handlers.render_helpers import (
    build_forecast_card_text,
    get_forecast_view_flags,
)


async def show_forecast_card(
    callback_query: types.CallbackQuery,
    tournament: Tournament,
    forecast: Forecast,
    session,
):
    """
    Displays the forecast card (text + buttons) directly.
    """
    # Fetch player objects
    player_ids = forecast.prediction_data
    if not player_ids:
        await callback_query.answer(
            "В этом прогнозе нет данных об игроках.", show_alert=True
        )
        return

    players = await crud.get_players_by_ids(session, player_ids)
    players_map = {p.id: p for p in players}

    tournament_date = tournament.date.strftime("%d.%m.%Y")
    text = build_forecast_card_text(
        tournament_name=tournament.name,
        tournament_date_str=tournament_date,
        player_ids=player_ids,
        players_map=players_map,
        escape_html=False,
    )
    admin_ids = config.admin_ids if isinstance(config.admin_ids, list) else []
    allow_edit, is_admin, show_others = get_forecast_view_flags(
        tournament_status=tournament.status,
        user_id=callback_query.from_user.id,
        admin_ids=admin_ids,
    )

    kb = view_forecast_kb(
        back_callback="predict_back_to_list",
        forecast_id=forecast.id,
        tournament_id=tournament.id,
        allow_edit=allow_edit,
        show_others=show_others,
        is_admin=is_admin,
        tournament_status=tournament.status,
    )

    await callback_query.message.edit_text(text, reply_markup=kb)
    await callback_query.answer()
