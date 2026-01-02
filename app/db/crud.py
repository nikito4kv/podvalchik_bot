from typing import Sequence, Optional, Iterable
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Tournament, TournamentStatus, Player, Forecast, BugReport

async def get_user_forecast_tournament_ids(session: AsyncSession, user_id: int) -> Sequence[int]:
    """Returns a list of tournament IDs that the user has already predicted."""
    result = await session.execute(
        select(Forecast.tournament_id).where(Forecast.user_id == user_id)
    )
    return result.scalars().all()

async def get_open_tournaments(session: AsyncSession) -> Sequence[Tournament]:
    """Returns all tournaments with OPEN status, ordered by date descending."""
    result = await session.execute(
        select(Tournament).where(Tournament.status == TournamentStatus.OPEN).order_by(Tournament.date.desc())
    )
    return result.scalars().all()

async def get_tournament(session: AsyncSession, tournament_id: int) -> Optional[Tournament]:
    """Returns a tournament by ID."""
    return await session.get(Tournament, tournament_id)

async def get_tournament_with_participants(session: AsyncSession, tournament_id: int) -> Optional[Tournament]:
    """Returns a tournament with its participants loaded."""
    return await session.get(
        Tournament, 
        tournament_id, 
        options=[selectinload(Tournament.participants)]
    )

async def get_forecast_for_editing(session: AsyncSession, forecast_id: int) -> Optional[Forecast]:
    """Returns a forecast with tournament and its participants loaded (for editing validation)."""
    return await session.get(
        Forecast,
        forecast_id,
        options=[selectinload(Forecast.tournament).selectinload(Tournament.participants)],
    )

async def get_players_by_ids(session: AsyncSession, player_ids: Iterable[int]) -> Sequence[Player]:
    """Returns players matching the given IDs."""
    # SQLAlchemy's in_ expects a list or tuple, not a set, strictly speaking in some versions, 
    # but let's convert to list to be safe.
    ids_list = list(player_ids)
    if not ids_list:
        return []
    result = await session.execute(select(Player).where(Player.id.in_(ids_list)))
    return result.scalars().all()

async def delete_forecast(session: AsyncSession, forecast_id: int) -> None:
    """Deletes a forecast by ID."""
    await session.execute(delete(Forecast).where(Forecast.id == forecast_id))

async def get_tournament_with_forecasts(session: AsyncSession, tournament_id: int) -> Optional[Tournament]:
    """Returns a tournament with forecasts loaded."""
    return await session.get(
        Tournament, 
        tournament_id, 
        options=[selectinload(Tournament.forecasts)]
    )

async def get_tournament_with_forecasts_and_users(session: AsyncSession, tournament_id: int) -> Optional[Tournament]:
    """Returns a tournament with forecasts and their users loaded."""
    return await session.get(
        Tournament, 
        tournament_id, 
        options=[selectinload(Tournament.forecasts).selectinload(Forecast.user)]
    )

async def get_forecast_details(session: AsyncSession, forecast_id: int) -> Optional[Forecast]:
    """Returns a forecast with user and tournament loaded."""
    return await session.get(
        Forecast, 
        forecast_id, 
        options=[selectinload(Forecast.user), selectinload(Forecast.tournament)]
    )

async def create_forecast(session: AsyncSession, forecast: Forecast) -> None:
    """Adds a new forecast to the session."""
    session.add(forecast)

async def create_bug_report(session: AsyncSession, report: BugReport) -> None:
    """Adds a new bug report to the session."""
    session.add(report)

async def get_forecasts_by_date(session: AsyncSession, target_date) -> Sequence[Forecast]:
    """Returns all forecasts for tournaments occurring on the specified date."""
    stmt = (
        select(Forecast)
        .join(Forecast.tournament)
        .where(Tournament.date == target_date)
        .options(
            selectinload(Forecast.user),
            selectinload(Forecast.tournament)
        )
    )
    result = await session.execute(stmt)
    return result.scalars().all()