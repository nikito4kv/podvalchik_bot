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
    report_lines = ["# 📊 Отчет о миграции и пересчете баллов\n"]
    
    async with async_session() as session:
        # 1. Fetch Users and memorize OLD stats
        print("Fetching users and snapshotting old stats...")
        users_res = await session.execute(select(User))
        users = users_res.scalars().all()
        
        old_stats = {}
        for user in users:
            old_stats[user.id] = {
                "points": user.total_points,
                "name": user.username or f"ID {user.id}"
            }
            
            # Reset stats
            user.total_points = 0
            user.total_slots = 0
            user.accuracy_rate = 0.0
            user.avg_error = 0.0
            user.tournaments_played = 0
            user.exact_guesses = 0
            user.perfect_tournaments = 0
        
        report_lines.append(f"Всего пользователей для обработки: {len(users)}\n")
        
        # 2. Fetch all FINISHED tournaments
        print("Fetching finished tournaments...")
        tournaments_res = await session.execute(
            select(Tournament)
            .where(Tournament.status == TournamentStatus.FINISHED)
            .options(selectinload(Tournament.forecasts))
        )
        tournaments = tournaments_res.scalars().all()
        
        print(f"Found {len(tournaments)} finished tournaments.")
        report_lines.append(f"Найдено завершенных турниров: {len(tournaments)}\n")
        report_lines.append("-" * 30 + "\n")
        
        # 3. Iterate and recalculate
        for tournament in tournaments:
            print(f"Processing tournament: {tournament.name} (ID: {tournament.id})")
            results_dict = tournament.results # {"player_id": rank}
            
            if not results_dict:
                print(f"  Skipping (no results data)")
                report_lines.append(f"⚠️ Турнир '{tournament.name}' пропущен (нет результатов)\n")
                continue
                
            # Cast keys to int
            results_dict = {int(k): int(v) for k, v in results_dict.items()}
            
            for forecast in tournament.forecasts:
                points, diffs, exact_hits = calculate_forecast_points(
                    forecast.prediction_data, results_dict
                )
                
                forecast.points_earned = points
                
                user = await session.get(User, forecast.user_id)
                if not user: continue

                # Update counters
                user.tournaments_played += 1
                user.exact_guesses += exact_hits
                
                slots_count = len(forecast.prediction_data)
                if slots_count > 0 and exact_hits == slots_count:
                    user.perfect_tournaments += 1
                
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
        
        # 4. Final Report Generation
        report_lines.append("## 👥 Изменения статистики пользователей\n")
        report_lines.append(f"{'Пользователь':<20} | {'Было':<5} -> {'Стало':<5} | {'Турниров':<8} | {'Идеал 💎'}\n")
        report_lines.append("-" * 70 + "\n")
        
        for user in users:
            old = old_stats.get(user.id, {"points": 0})["points"] or 0
            new = user.total_points
            name = user.username or str(user.id)
            diff = new - old
            diff_str = f"(+{diff})" if diff >= 0 else f"({diff})"
            
            line = f"{name:<20} | {old:<5} -> {new:<5} {diff_str:<6} | {user.tournaments_played:<8} | {user.perfect_tournaments}\n"
            report_lines.append(line)

    with open("MIGRATION_REPORT.txt", "w", encoding="utf-8") as f:
        f.writelines(report_lines)
    
    print("Recalculation complete! Report saved to MIGRATION_REPORT.txt")

if __name__ == "__main__":
    asyncio.run(recalculate_all_scores())
