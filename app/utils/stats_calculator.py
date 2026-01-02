from sqlalchemy import select
from app.db.models import User, Tournament, Forecast, TournamentStatus
from sqlalchemy.ext.asyncio import AsyncSession

async def recalculate_user_streaks(session: AsyncSession, user_id: int):
    """
    Recalculates current and max streaks based on tournament participation.
    Only counts FINISHED or OPEN/LIVE tournaments (chronologically).
    """
    # 1. Get all tournaments sorted by date
    # We care about chronological order to determine streaks
    tournaments_stmt = select(Tournament).where(
        Tournament.status != TournamentStatus.DRAFT
    ).order_by(Tournament.date.asc(), Tournament.id.asc())
    
    tournaments_res = await session.execute(tournaments_stmt)
    tournaments = tournaments_res.scalars().all()
    
    if not tournaments:
        return
    
    # 2. Get all user forecasts
    forecasts_stmt = select(Forecast).where(Forecast.user_id == user_id)
    forecasts_res = await session.execute(forecasts_stmt)
    user_forecast_t_ids = {f.tournament_id for f in forecasts_res.scalars()}
    
    current_streak = 0
    max_streak = 0
    temp_streak = 0
    
    # Iterate through all tournaments
    for t in tournaments:
        if t.id in user_forecast_t_ids:
            temp_streak += 1
        else:
            # Check if max
            if temp_streak > max_streak:
                max_streak = temp_streak
            temp_streak = 0
            
    # Final check after loop
    if temp_streak > max_streak:
        max_streak = temp_streak
    
    # Current streak is simply temp_streak at the end (if the last tournament was played)
    # However, if the last tournament was NOT played, current streak is 0.
    # Logic: "Current Streak" implies active run. 
    # If a tournament is missed, streak resets.
    current_streak = temp_streak

    # Update User
    user = await session.get(User, user_id)
    if user:
        user.streak_days = current_streak # Reusing this field as 'current_streak'
        user.max_streak = max_streak
        # session.add(user) # Already tracked
        await session.commit()
    
    return current_streak, max_streak
