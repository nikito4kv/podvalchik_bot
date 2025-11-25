from typing import List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import math

from app.db.models import Tournament, Player


def tournament_selection_kb(tournaments: List[Tournament]) -> InlineKeyboardMarkup:
    """Creates a keyboard for selecting a tournament."""
    builder = InlineKeyboardBuilder()
    for tournament in tournaments:
        builder.button(
            text=f"ID: {tournament.id} ({tournament.date.strftime('%d.%m.%Y')})",
            callback_data=f"select_tournament_{tournament.id}"
        )
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
    show_back_to_menu: bool = False
) -> InlineKeyboardMarkup:
    """
    Creates a universal paginated keyboard for player selection.
    """
    if selected_ids is None:
        selected_ids = []

    available_players = sorted([p for p in players if p.id not in selected_ids], key=lambda p: p.full_name)
    
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
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"paginate:{action}:{page-1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"paginate:{action}:{page+1}"))
    if nav_buttons:
        builder.row(*nav_buttons)

    if show_create_new:
        builder.row(InlineKeyboardButton(text="➕ Создать и добавить", callback_data=f"create_new:{action}"))

    if show_back_to_menu and tournament_id:
        builder.row(InlineKeyboardButton(text="◀️ Назад в меню", callback_data=f"manage_tournament_{tournament_id}"))

    return builder.as_markup()