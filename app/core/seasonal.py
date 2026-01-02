import datetime
from datetime import timedelta
from typing import Tuple, List

# Define start date (First ever season)
# Let's assume the first season starts on a Monday before the first tournament.
# We will dynamically calculate season number based on date.

# Monday is 0, Sunday is 6.
FIRST_SEASON_START = datetime.date(2024, 12, 30) # Just a safe anchor point. Monday.

def get_season_dates(season_number: int) -> Tuple[datetime.date, datetime.date]:
    """Returns start (Monday) and end (Sunday) dates for a given season number."""
    start_date = FIRST_SEASON_START + timedelta(weeks=season_number - 1)
    end_date = start_date + timedelta(days=6)
    return start_date, end_date

def get_season_number(date_obj: datetime.date) -> int:
    """Returns the season number for a given date."""
    if date_obj < FIRST_SEASON_START:
        return 0 # Pre-history
    
    delta = date_obj - FIRST_SEASON_START
    return (delta.days // 7) + 1

def get_current_season_number() -> int:
    """Returns the current season number based on today's date."""
    return get_season_number(datetime.date.today())

def get_current_season_dates() -> Tuple[datetime.date, datetime.date]:
    """Returns start and end dates for the current season."""
    return get_season_dates(get_current_season_number())

def get_previous_season_number() -> int:
    return get_current_season_number() - 1
