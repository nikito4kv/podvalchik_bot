import asyncio
import logging
from sqlalchemy import select, func, and_
from sqlalchemy.orm import joinedload
from app.db.session import async_session
from app.db.models import Season, SeasonResult, Tournament, Forecast, User
from app.core.seasonal import get_season_number, get_season_dates

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate_seasons():
    """
    1. Iterates over all existing Tournaments.
    2. Determines which season they belong to.
    3. Creates/Updates Season records.
    4. Calculates and stores SeasonResult snapshots for past seasons.
    """
    async with async_session() as session:
        logger.info("Starting seasonal migration...")
        
        # 1. Get all tournaments ordered by date
        stmt = select(Tournament).order_by(Tournament.date)
        result = await session.execute(stmt)
        tournaments = result.scalars().all()
        
        if not tournaments:
            logger.info("No tournaments found. Migration skipped.")
            return

        # 2. Identify unique seasons needed
        season_map = {} # number -> {start, end, tournament_ids}
        
        for t in tournaments:
            s_num = get_season_number(t.date)
            if s_num == 0: continue # Skip pre-history
            
            if s_num not in season_map:
                start, end = get_season_dates(s_num)
                season_map[s_num] = {
                    "start": start,
                    "end": end,
                    "t_ids": []
                }
            season_map[s_num]["t_ids"].append(t.id)

        logger.info(f"Identified {len(season_map)} seasons to process.")

        # 3. Create Seasons and Results
        for s_num, data in season_map.items():
            # Check if season exists
            s_stmt = select(Season).where(Season.number == s_num)
            s_res = await session.execute(s_stmt)
            season = s_res.scalar_one_or_none()
            
            if not season:
                season = Season(
                    number=s_num,
                    start_date=data["start"],
                    end_date=data["end"],
                    status="closed" # Default to closed, we'll open current later
                )
                session.add(season)
                await session.flush() # Get ID
                logger.info(f"Created Season {s_num} (ID: {season.id})")
            
            # 4. Calculate Results for this season
            # Sum points from Forecasts linked to tournaments in this season
            t_ids = data["t_ids"]
            if not t_ids: continue

            # Aggregate stats per user for this season
            # We need: User, Sum(Points), Count(Forecasts)
            
            stats_stmt = (
                select(
                    Forecast.user_id,
                    func.sum(Forecast.points_earned).label("total_points"),
                    func.count(Forecast.id).label("played_count")
                )
                .where(Forecast.tournament_id.in_(t_ids))
                .group_by(Forecast.user_id)
                .order_by(func.sum(Forecast.points_earned).desc())
            )
            
            stats_res = await session.execute(stats_stmt)
            stats = stats_res.all()
            
            # Save SeasonResult
            # First, clear existing results for this season (to be safe/idempotent)
            await session.execute(
                select(SeasonResult).where(SeasonResult.season_id == season.id).execution_options(synchronize_session=False)
            )
            # Actually delete is better
            # But let's just add if not exists or skip?
            # For migration, let's just wipe and rewrite for simplicity
            # No, 'delete' via ORM is tricky with async without explicit query
            # We will just check if results exist
            
            check_res = await session.execute(select(SeasonResult).where(SeasonResult.season_id == season.id))
            if check_res.first():
                logger.info(f"Season {s_num} already has results. Skipping calculation.")
                continue

            logger.info(f"Calculating results for Season {s_num}...")
            
            for rank, (user_id, points, played) in enumerate(stats, 1):
                # Fetch user for snapshot
                user = await session.get(User, user_id)
                snapshot = {
                    "full_name": user.full_name,
                    "username": user.username
                }
                
                res = SeasonResult(
                    season_id=season.id,
                    user_id=user_id,
                    rank=rank,
                    points=points or 0,
                    tournaments_played=played,
                    user_snapshot=snapshot
                )
                session.add(res)
            
        await session.commit()
        logger.info("Seasonal migration completed successfully.")

if __name__ == "__main__":
    asyncio.run(migrate_seasons())
