import asyncio
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.db.session import engine
from app.db.models import User, Tournament, Forecast, TournamentStatus, Player
from app.core.scoring import calculate_forecast_points, calculate_new_stats

# Re-define async_session here to avoid circular imports or init issues if running standalone
from sqlalchemy.ext.asyncio import async_sessionmaker
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def recalculate_all_scores():
    print("Starting global score recalculation...")
    
    async with async_session() as session:
        # 1. Reset all User stats
        print("Resetting user stats...")
        users_res = await session.execute(select(User))
        users = users_res.scalars().all()
        
        for user in users:
            user.total_points = 0
            user.total_slots = 0
            user.accuracy_rate = 0.0
            user.avg_error = 0.0
        
        # 2. Fetch all FINISHED tournaments
        print("Fetching finished tournaments...")
        tournaments_res = await session.execute(
            select(Tournament)
            .where(Tournament.status == TournamentStatus.FINISHED)
            .options(selectinload(Tournament.forecasts))
        )
        tournaments = tournaments_res.scalars().all()
        
        print(f"Found {len(tournaments)} finished tournaments.")
        
        # 3. Iterate and recalculate
        for tournament in tournaments:
            print(f"Processing tournament: {tournament.name} (ID: {tournament.id})")
            results_dict = tournament.results # {"player_id": rank}
            
            if not results_dict:
                print(f"  Skipping (no results data)")
                continue
                
            # We need to cast keys to int just in case JSON stored them as strings
            results_dict = {int(k): int(v) for k, v in results_dict.items()}
            
            for forecast in tournament.forecasts:
                # Recalculate points for this specific forecast
                points, diffs, exact_hits = calculate_forecast_points(
                    forecast.prediction_data, results_dict
                )
                
                forecast.points_earned = points
                
                # Aggregate to user stats immediately? 
                # We already have the User object in the session identity map from step 1.
                # But we need to fetch it or ensure it's attached.
                # Forecast.user might be lazy loaded.
                
                user = await session.get(User, forecast.user_id)
                
                # Recalculate accumulators
                total_slots_before = user.total_slots or 0
                
                new_total, new_acc, new_mae = calculate_new_stats(
                    user.total_points, user.accuracy_rate, user.avg_error, 
                    total_slots_before, 
                    points, diffs, exact_hits
                )
                
                user.total_points = new_total
                user.accuracy_rate = new_acc
                user.avg_error = new_mae
                user.total_slots = total_slots_before + len(forecast.prediction_data)
                
        await session.commit()
        print("Recalculation complete! Database updated.")

if __name__ == "__main__":
    asyncio.run(recalculate_all_scores())
