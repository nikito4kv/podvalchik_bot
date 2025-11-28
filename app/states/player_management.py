from aiogram.fsm.state import State, StatesGroup

class PlayerManagement(StatesGroup):
    viewing_list = State()
    adding_new_player_name = State()
    adding_new_player_rating = State()
    editing_player_name = State()
    editing_player_rating = State()
    confirming_delete = State()
