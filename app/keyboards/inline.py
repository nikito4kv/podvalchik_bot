from typing import List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import math

from app.db.models import Tournament, Player, Forecast, TournamentStatus


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


def tournament_user_menu_kb(tournament_id: int, tournament_status: TournamentStatus, is_admin: bool) -> InlineKeyboardMarkup:
    """Creates a user menu for a selected tournament."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔮 Сделать прогноз", callback_data=f"predict_start_{tournament_id}")
    builder.button(text="👥 Список участников", callback_data=f"view_participants_{tournament_id}")
    
    # Show "View Other Forecasts" only if LIVE/FINISHED or if admin
    if tournament_status != TournamentStatus.OPEN or is_admin:
        builder.button(text="👀 Прогнозы участников", callback_data=f"vof_summary:{tournament_id}:menu")
        
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

    # Modified sorting: Rating desc, then Name asc
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
        status_icon = "🟢" # Default OPEN
        if tournament.status == TournamentStatus.LIVE:
            status_icon = "🔴"
        elif tournament.status == TournamentStatus.FINISHED:
            status_icon = "🏁"
            
        text = f"{status_icon} «{tournament.name}» ({tournament.date.strftime('%d.%m.%Y')})"
        builder.button(text=text, callback_data=f"view_forecast:{tournament.id}")
    builder.adjust(1)
    # Add a back button
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_forecasts_menu")
    )
    return builder.as_markup()


def view_forecast_kb(
    back_callback: str, 
    forecast_id: int | None = None,
    tournament_id: int | None = None
) -> InlineKeyboardMarkup:
    """Creates a keyboard with a dynamic back button and an optional edit button."""
    builder = InlineKeyboardBuilder()
    if forecast_id:
        builder.button(
            text="✏️ Изменить прогноз", callback_data=f"edit_forecast_start:{forecast_id}"
        )
    
    if tournament_id:
        # Calculate source for return path
        source = "menu"
        if "forecasts:active" in back_callback:
            source = "active"
        elif "forecasts:history" in back_callback:
             if forecast_id:
                 # back_callback format is forecasts:history:PAGE
                 try:
                     page = back_callback.split(":")[-1]
                     source = f"hist_{forecast_id}_{page}"
                 except:
                     pass
        
        builder.button(text="👀 Прогнозы участников", callback_data=f"vof_summary:{tournament_id}:{source}")

    builder.button(text="◀️ Назад к списку", callback_data=back_callback)
    builder.adjust(1)
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
    builder.button(text="👥 Управление игроками", callback_data="pm_list_players:0")
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
    builder.button(text="◀️ Назад", callback_data="rating:back_to_options")
    return builder.as_markup()


def get_paginated_players_management_kb(
    players: List[Player],
    page: int = 0,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    """
    Creates a paginated keyboard for player management.
    """
    # Sorting: Active first, then Alphabetical
    available_players = sorted(
        players, key=lambda p: (not (p.is_active if p.is_active is not None else True), p.full_name)
    )

    builder = InlineKeyboardBuilder()
    total_players = len(available_players)
    total_pages = max(1, math.ceil(total_players / page_size))
    page = max(0, min(page, total_pages - 1))

    start_index = page * page_size
    end_index = start_index + page_size
    page_players = available_players[start_index:end_index]

    for player in page_players:
        is_active = player.is_active if player.is_active is not None else True
        status_icon = "" if is_active else "❌ "
        builder.button(
            text=f"{status_icon}{player.full_name}", 
            callback_data=f"pm_select:{player.id}"
        )
    builder.adjust(2)

    nav_buttons = []
    if total_pages > 1:
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"pm_paginate:{page-1}"
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop")
        )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=f"pm_paginate:{page+1}"
                )
            )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="➕ Добавить игрока", callback_data="pm_add_new")
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_back_main")
    )

    return builder.as_markup()


def player_management_menu_kb(player: Player) -> InlineKeyboardMarkup:
    """Menu for managing a specific player."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить имя", callback_data=f"pm_edit_name:{player.id}")
    builder.button(text="✏️ Изменить рейтинг", callback_data=f"pm_edit_rating:{player.id}")
    
    is_active = player.is_active if player.is_active is not None else True
    
    if is_active:
        builder.button(text="🗑 Удалить (архивировать)", callback_data=f"pm_delete:{player.id}")
    else:
        builder.button(text="♻️ Восстановить", callback_data=f"pm_restore:{player.id}")
        
    builder.button(text="◀️ Назад к списку", callback_data="pm_back_list")
    builder.adjust(1)
    return builder.as_markup()


def player_management_back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="pm_back_list")
    return builder.as_markup()


# --- New keyboards for viewing other forecasts ---

def view_others_forecasts_menu_kb(tournament_id: int, source: str) -> InlineKeyboardMarkup:
    """Menu for viewing summary or detailed list of forecasts."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Список всех прогнозов", callback_data=f"vof_list:{tournament_id}:0:{source}")
    
    # Determine back button based on source
    if source == "menu":
        builder.button(text="◀️ Назад", callback_data=f"select_tournament_{tournament_id}")
    elif source == "active":
        builder.button(text="◀️ Назад", callback_data=f"view_forecast:{tournament_id}")
    elif source.startswith("hist_"):
        # hist_FID_PAGE
        try:
            parts = source.split("_")
            fid = parts[1]
            page = parts[2]
            builder.button(text="◀️ Назад", callback_data=f"view_history:{fid}:{page}")
        except:
             builder.button(text="◀️ Назад", callback_data=f"select_tournament_{tournament_id}")
    else:
        builder.button(text="◀️ Назад", callback_data=f"select_tournament_{tournament_id}")

    builder.adjust(1)
    return builder.as_markup()

def get_paginated_forecasts_list_kb(
    forecasts: List[Forecast],
    tournament_id: int,
    page: int = 0,
    page_size: int = 8,
    source: str = "menu"
) -> InlineKeyboardMarkup:
    """Paginated list of users who made a forecast."""
    builder = InlineKeyboardBuilder()
    
    sorted_forecasts = sorted(forecasts, key=lambda f: (f.points_earned or 0, f.user_id), reverse=True)

    total_items = len(sorted_forecasts)
    total_pages = max(1, math.ceil(total_items / page_size))
    page = max(0, min(page, total_pages - 1))

    start_index = page * page_size
    end_index = start_index + page_size
    page_forecasts = sorted_forecasts[start_index:end_index]

    for f in page_forecasts:
        user_name = f.user.username or f"User {f.user_id}"
        points_str = f" ({f.points_earned} очков)" if f.points_earned is not None else ""
        builder.button(
            text=f"👤 {user_name}{points_str}", 
            callback_data=f"vof_detail:{f.id}:{source}"
        )
    builder.adjust(1)

    nav_buttons = []
    if total_pages > 1:
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"vof_paginate:{tournament_id}:{page-1}:{source}"
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop")
        )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=f"vof_paginate:{tournament_id}:{page+1}:{source}"
                )
            )
    if nav_buttons:
        builder.row(*nav_buttons)
        
    builder.row(
        InlineKeyboardButton(text="◀️ Назад к сводке", callback_data=f"vof_summary:{tournament_id}:{source}")
    )
    return builder.as_markup()

def view_single_forecast_back_kb(tournament_id: int, page: int = 0, source: str = "menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад к списку", callback_data=f"vof_list:{tournament_id}:{page}:{source}")
    return builder.as_markup()