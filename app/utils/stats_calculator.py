from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Forecast, Tournament, TournamentStatus, User


async def calculate_user_tournament_streaks(
    session: AsyncSession, user_id: int
) -> tuple[int, int]:
    """
    Calculates current and max tournament streaks without writing to the DB.

    The phase-1 stats contract uses tournament participation as a derived display
    value and keeps `User.streak_days` untouched inside the read path.
    """

    tournaments_stmt = (
        select(Tournament.id)
        .where(Tournament.status != TournamentStatus.DRAFT)
        .order_by(Tournament.date.asc(), Tournament.id.asc())
    )
    tournament_ids = (await session.execute(tournaments_stmt)).scalars().all()
    if not tournament_ids:
        return 0, 0

    forecasts_stmt = select(Forecast.tournament_id).where(Forecast.user_id == user_id)
    user_forecast_ids = set((await session.execute(forecasts_stmt)).scalars().all())

    current_streak = 0
    max_streak = 0
    temp_streak = 0

    for tournament_id in tournament_ids:
        if tournament_id in user_forecast_ids:
            temp_streak += 1
            current_streak = temp_streak
            continue

        max_streak = max(max_streak, temp_streak)
        temp_streak = 0
        current_streak = 0

    max_streak = max(max_streak, temp_streak)
    current_streak = temp_streak
    return current_streak, max_streak


async def recalculate_user_streaks(
    session: AsyncSession, user_id: int
) -> tuple[int, int]:
    """
    Explicit persistence helper for tournament streak snapshots.

    The helper updates the in-session `User` object but intentionally does not
    commit. Callers must decide whether a write belongs to their flow.
    """

    current_streak, max_streak = await calculate_user_tournament_streaks(
        session, user_id
    )
    user = await session.get(User, user_id)
    if user is not None:
        setattr(user, "streak_days", current_streak)
        setattr(user, "max_streak", max_streak)
    return current_streak, max_streak
