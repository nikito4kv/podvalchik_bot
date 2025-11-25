from aiogram.fsm.state import State, StatesGroup

class TournamentManagement(StatesGroup):
    choosing_tournament = State()
    managing_tournament = State()
    
    creating_tournament_enter_name = State()
    creating_tournament_enter_date = State()

    adding_participant_choosing_player = State()
    adding_participant_creating_new = State()
    
    removing_participant_choosing_player = State()

class SetResults(StatesGroup):
    entering_results = State()
    confirming_results = State()