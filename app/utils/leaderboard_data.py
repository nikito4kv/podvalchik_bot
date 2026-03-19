import logging
from datetime import date
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.scoring import calculate_forecast_points
from app.db.crud import get_forecasts_by_date
from app.db.models import Forecast, Season, Tournament, TournamentStatus
from app.utils.formatting import get_user_rank


LOGGER = logging.getLogger(__name__)


async def build_daily_leaderboard_snapshot(
    session: AsyncSession, target_date: date
) -> dict:
    started = perf_counter()
    forecasts = await get_forecasts_by_date(session, target_date)
    user_stats: dict[int, dict] = {}

    for forecast in forecasts:
        user_entry = user_stats.setdefault(
            forecast.user_id,
            {
                "user_id": forecast.user_id,
                "name": forecast.user.full_name
                or forecast.user.username
                or f"User {forecast.user_id}",
                "points": 0,
                "played": 0,
                "perfects": 0,
                "global_points": forecast.user.total_points or 0,
            },
        )
        user_entry["played"] += 1
        user_entry["points"] += forecast.points_earned or 0

        if forecast.points_earned is None or not forecast.tournament.results:
            continue

        results_map = {
            int(key): int(value) for key, value in forecast.tournament.results.items()
        }
        _, _, exact_hits = calculate_forecast_points(
            forecast.prediction_data, results_map
        )
        if exact_hits == len(forecast.prediction_data) and forecast.prediction_data:
            user_entry["perfects"] += 1

    leaders = []
    for user_entry in user_stats.values():
        rank_str = get_user_rank(user_entry["global_points"])
        league_emoji = rank_str.split()[0] if rank_str else ""
        leaders.append(
            {
                "user_id": user_entry["user_id"],
                "name": user_entry["name"],
                "points": user_entry["points"],
                "played": user_entry["played"],
                "perfects": user_entry["perfects"],
                "league_emoji": league_emoji,
            }
        )
    leaders.sort(key=lambda item: (item["points"], item["perfects"]), reverse=True)

    tournament_count = len({forecast.tournament_id for forecast in forecasts})
    duration_ms = (perf_counter() - started) * 1000
    LOGGER.info(
        "leaderboard.daily.prepared date=%s forecast_count=%s users=%s tournaments=%s duration_ms=%.3f",
        target_date.isoformat(),
        len(forecasts),
        len(leaders),
        tournament_count,
        duration_ms,
    )
    return {
        "leaders": leaders,
        "forecast_count": len(forecasts),
        "tournament_count": tournament_count,
    }


async def build_detailed_season_snapshot(
    session: AsyncSession, season_id: int
) -> dict | None:
    started = perf_counter()
    season = await session.get(Season, season_id)
    if season is None:
        return None

    tournaments_stmt = (
        select(Tournament)
        .where(
            Tournament.date >= season.start_date,
            Tournament.date <= season.end_date,
            Tournament.status == TournamentStatus.FINISHED,
        )
        .order_by(Tournament.date.asc(), Tournament.id.asc())
    )
    tournaments = (await session.execute(tournaments_stmt)).scalars().all()
    tournament_ids = [tournament.id for tournament in tournaments]
    if not tournament_ids:
        return {"season": season, "tournaments": tournaments, "columns": [], "rows": []}

    forecasts_stmt = (
        select(Forecast)
        .options(joinedload(Forecast.user))
        .where(Forecast.tournament_id.in_(tournament_ids))
        .order_by(Forecast.user_id.asc(), Forecast.tournament_id.asc())
    )
    forecasts = (await session.execute(forecasts_stmt)).scalars().all()

    user_map: dict[int, dict] = {}
    for forecast in forecasts:
        user_entry = user_map.setdefault(
            forecast.user_id,
            {
                "name": forecast.user.full_name
                or forecast.user.username
                or f"User {forecast.user_id}",
                "scores": {},
                "total": 0,
            },
        )
        points = forecast.points_earned or 0
        user_entry["scores"][forecast.tournament_id] = points
        user_entry["total"] += points

    rows = []
    for user_entry in sorted(
        user_map.values(), key=lambda item: item["total"], reverse=True
    ):
        rows.append(
            {
                "name": user_entry["name"],
                "scores": [
                    user_entry["scores"].get(tournament.id)
                    for tournament in tournaments
                ],
                "total": user_entry["total"],
            }
        )

    duration_ms = (perf_counter() - started) * 1000
    LOGGER.info(
        "leaderboard.season_detail.prepared season_id=%s tournaments=%s rows=%s forecasts=%s duration_ms=%.3f",
        season_id,
        len(tournaments),
        len(rows),
        len(forecasts),
        duration_ms,
    )
    return {
        "season": season,
        "tournaments": tournaments,
        "columns": [tournament.name for tournament in tournaments],
        "rows": rows,
    }
