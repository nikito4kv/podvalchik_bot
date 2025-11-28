from typing import List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import math

from app.db.models import Tournament, Player, Forecast


def tournament_selection_kb(tournaments: List[Tournament]) -> InlineKeyboardMarkup:
    """Creates a keyboard for selecting a tournament."""
    builder = InlineKeyboardBuilder()
    for tournament in tournaments:
        builder.button(
            text=f"«{tournament.name}» ({tournament.date.strftime('%d.%m.%Y')})",
            callback_data=f"select_tournament_{tournament.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def tournament_user_menu_kb(tournament_id: int) -> InlineKeyboardMarkup:
    """Creates a user menu for a selected tournament."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔮 Сделать прогноз", callback_data=f"predict_start_{tournament_id}")
    builder.button(text="👥 Список участников", callback_data=f"view_participants_{tournament_id}")
    builder.button(text="◀️ Назад", callback_data="predict_back_to_list")
    builder.adjust(1)
    return builder.as_markup()


def confirmation_kb(action_prefix: str = "confirm") -> InlineKeyboardMarkup:
    """Creates a keyboard for confirmation with a dynamic prefix."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"{action_prefix}:yes")
    builder.button(text="❌ Отменить", callback_data=f"{action_prefix}:no")
    return builder.as_markup()


def get_paginated_players_kb(
    players: List[Player],
    action: str,
    page: int = 0,
    page_size: int = 8,
    selected_ids: Optional[List[int]] = None,
    tournament_id: Optional[int] = None,
    show_create_new: bool = False,
    show_back_to_menu: bool = False,
) -> InlineKeyboardMarkup:
    """
    Creates a universal paginated keyboard for player selection.
    """
    if selected_ids is None:
        selected_ids = []

    available_players = sorted(
        [p for p in players if p.id not in selected_ids], key=lambda p: (-(p.current_rating or 0), p.full_name)
    )

    builder = InlineKeyboardBuilder()
    total_players = len(available_players)
    total_pages = max(1, math.ceil(total_players / page_size))
    page = max(0, min(page, total_pages - 1))

    start_index = page * page_size
    end_index = start_index + page_size
    page_players = available_players[start_index:end_index]

    for player in page_players:
        builder.button(text=player.full_name, callback_data=f"{action}:{player.id}")
    builder.adjust(2)

    nav_buttons = []
    if total_pages > 1:
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"paginate:{action}:{page-1}"
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop")
        )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=f"paginate:{action}:{page+1}"
                )
            )
    if nav_buttons:
        builder.row(*nav_buttons)

    if show_create_new:
        builder.row(
            InlineKeyboardButton(
                text="➕ Создать и добавить", callback_data=f"create_new:{action}"
            )
        )

    if show_back_to_menu and tournament_id:
        builder.row(
            InlineKeyboardButton(
                text="◀️ Назад в меню", callback_data=f"manage_tournament_{tournament_id}"
            )
        )

    return builder.as_markup()


def my_forecasts_menu_kb() -> InlineKeyboardMarkup:
    """Creates a keyboard for the 'My Forecasts' menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Активные прогнозы", callback_data="forecasts:active")
    builder.button(text="🗂️ История прогнозов", callback_data="forecasts:history:0")
    builder.adjust(1)
    return builder.as_markup()


def active_tournaments_kb(tournaments: List[Tournament]) -> InlineKeyboardMarkup:
    """Creates a keyboard to select an active tournament to view a forecast."""
    builder = InlineKeyboardBuilder()
    for tournament in tournaments:
        text = f"«{tournament.name}» ({tournament.date.strftime('%d.%m.%Y')})"
        builder.button(text=text, callback_data=f"view_forecast:{tournament.id}")
    builder.adjust(1)
    # Add a back button
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_forecasts_menu")
    )
    return builder.as_markup()


def view_forecast_kb(
    back_callback: str, forecast_id: int | None = None
) -> InlineKeyboardMarkup:
    """Creates a keyboard with a dynamic back button and an optional edit button."""
    builder = InlineKeyboardBuilder()
    if forecast_id:
        builder.button(
            text="✏️ Изменить прогноз", callback_data=f"edit_forecast_start:{forecast_id}"
        )
    builder.button(text="◀️ Назад к списку", callback_data=back_callback)
    builder.adjust(2 if forecast_id else 1)
    return builder.as_markup()


def forecast_history_kb(
    forecasts: List[Forecast], page: int = 0, page_size: int = 5
) -> InlineKeyboardMarkup:
    """Creates a paginated keyboard for forecast history."""
    builder = InlineKeyboardBuilder()
    total_items = len(forecasts)
    total_pages = max(1, math.ceil(total_items / page_size))
    page = max(0, min(page, total_pages - 1))

    start_index = page * page_size
    end_index = start_index + page_size
    page_forecasts = forecasts[start_index:end_index]

    for forecast in page_forecasts:
        text = f"«{forecast.tournament.name}» ({forecast.tournament.date.strftime('%d.%m.%Y')})"
        builder.button(
            text=text, callback_data=f"view_history:{forecast.id}:{page}"
        )
    builder.adjust(1)

    nav_buttons = []
    if total_pages > 1:
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"forecasts:history:{page-1}"
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop")
        )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=f"forecasts:history:{page+1}"
                )
            )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_forecasts_menu")
    )
    return builder.as_markup()


def cancel_fsm_kb() -> InlineKeyboardMarkup:
    """Creates a keyboard with a single 'Cancel' button for FSM processes."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="fsm_cancel")
    return builder.as_markup()


def admin_menu_kb() -> InlineKeyboardMarkup:
    """Main menu for admin tournament management."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🆕 Создать новый турнир", callback_data="tm_create_new")
    builder.button(text="⚡️ Актуальные", callback_data="tm_group:active")
    builder.button(text="🏁 Завершенные", callback_data="tm_group:finished")
    builder.adjust(1)
    return builder.as_markup()


def get_paginated_tournaments_kb(
    tournaments: List[Tournament], status_group: str, page: int = 0, page_size: int = 6
) -> InlineKeyboardMarkup:
    """
    Creates a paginated keyboard for tournaments list.
    """
    builder = InlineKeyboardBuilder()
    total_items = len(tournaments)
    total_pages = max(1, math.ceil(total_items / page_size))
    page = max(0, min(page, total_pages - 1))

    start_index = page * page_size
    end_index = start_index + page_size
    page_tournaments = tournaments[start_index:end_index]

    for t in page_tournaments:
        builder.button(
            text=f"«{t.name}» ({t.date.strftime('%d.%m.%Y')}) - {t.status.name}",
            callback_data=f"manage_tournament_{t.id}"
        )
    builder.adjust(1)

    nav_buttons = []
    if total_pages > 1:
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"paginate_tm:{status_group}:{page-1}"
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop")
        )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=f"paginate_tm:{status_group}:{page+1}"
                )
            )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="tm_back_to_list")
    )
    
    return builder.as_markup()


def enter_rating_fsm_kb() -> InlineKeyboardMarkup:
    """Keyboard for entering a new rating, with a back button."""
    builder = InlineKeyboardBuilder()
    builder.button(text="↩️ Назад", callback_data="rating:back_to_options")
    return builder.as_markup()