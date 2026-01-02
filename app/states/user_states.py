from aiogram.fsm.state import State, StatesGroup

class MakeForecast(StatesGroup):
    choosing_tournament = State()
    making_prediction = State() # Replaces all entering_place_X states
    confirming_forecast = State()

class BugReportState(StatesGroup):
    entering_description = State()
    entering_screenshot = State()

class LeaderboardState(StatesGroup):
    waiting_for_date = State()
