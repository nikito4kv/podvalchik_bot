from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext

from app.db.models import Player
from app.keyboards.inline import get_paginated_players_kb

router = Router()

@router.callback_query(F.data.startswith("paginate:"))
async def cq_paginate_players(callback: types.CallbackQuery, state: FSMContext):
    """
    Handles pagination button clicks for any player list.
    The callback data is expected to be in the format: "paginate:{action}:{page}"
    e.g., "paginate:add_player_123:1" or "paginate:predict_1:0"
    """
    await callback.answer()

    # Parse callback data
    try:
        _, action, page_str = callback.data.split(":", 2)
        page = int(page_str)
    except (ValueError, IndexError):
        # Log this error or handle it gracefully
        return

    data = await state.get_data()
    
    # Player data can be stored in different keys depending on the context
    # For tournament management, it's 'all_players'
    # For prediction, it's 'tournament_players'
    player_dict = data.get("all_players") or data.get("tournament_players") or {}
    
    if not player_dict:
        # Cannot paginate without a list of players
        return

    all_players = []
    for pid, data_val in player_dict.items():
        if isinstance(data_val, dict):
            # New format: {'name': '...', 'rating': ...}
            p = Player(
                id=pid, 
                full_name=data_val.get('name', 'Unknown'), 
                current_rating=data_val.get('rating')
            )
        else:
            # Old format: just string name
            p = Player(id=pid, full_name=str(data_val))
        all_players.append(p)

    # Determine which players are already selected
    # This also depends on the context
    selected_ids = []
    if 'predict' in action:
        selected_ids = data.get("forecast_list", [])
    elif 'add_player' in action:
        # In this case, 'selected' means already a participant
        participant_ids = data.get("participant_ids", [])
        selected_ids = participant_ids
    elif 'remove_player' in action:
        # When removing, there are no 'selected' players to filter out from the list itself.
        # The list of participants IS the list of players to show.
        # This case is handled by the initial players list passed to the keyboard.
        pass

    # Re-create the keyboard for the new page
    # Pass kwargs from state to include things like tournament_id for the back button
    kb = get_paginated_players_kb(
        players=all_players,
        action=action,
        page=page,
        selected_ids=selected_ids,
        tournament_id=data.get('managed_tournament_id')
    )
    
    await callback.message.edit_reply_markup(reply_markup=kb)

@router.callback_query(F.data == "noop")
async def cq_noop(callback: types.CallbackQuery):
    """Handles clicks on non-operational buttons, like page counters."""
    await callback.answer()