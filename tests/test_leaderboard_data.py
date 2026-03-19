import os
import tempfile
import unittest
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.scoring import calculate_forecast_points
from app.db.models import Base, Forecast, Season, Tournament, TournamentStatus, User
from app.utils.leaderboard_data import (
    build_daily_leaderboard_snapshot,
    build_detailed_season_snapshot,
)


class LeaderboardDataTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}")
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_build_daily_leaderboard_snapshot_counts_perfects(self):
        target_date = date(2026, 1, 15)
        tournament_results = {"1": 1, "2": 2, "3": 3}

        async with self.session_maker() as session:
            session.add_all(
                [
                    User(id=1, username="alpha", full_name="Alpha", total_points=100),
                    User(id=2, username="beta", full_name="Beta", total_points=60),
                ]
            )
            session.add(
                Tournament(
                    id=1,
                    name="Daily Cup",
                    date=target_date,
                    status=TournamentStatus.FINISHED,
                    results=tournament_results,
                )
            )

            perfect_prediction = [1, 2, 3]
            partial_prediction = [1, 3, 2]
            perfect_points, _, _ = calculate_forecast_points(
                perfect_prediction, {1: 1, 2: 2, 3: 3}
            )
            partial_points, _, _ = calculate_forecast_points(
                partial_prediction, {1: 1, 2: 2, 3: 3}
            )

            session.add_all(
                [
                    Forecast(
                        user_id=1,
                        tournament_id=1,
                        prediction_data=perfect_prediction,
                        points_earned=perfect_points,
                    ),
                    Forecast(
                        user_id=2,
                        tournament_id=1,
                        prediction_data=partial_prediction,
                        points_earned=partial_points,
                    ),
                ]
            )
            await session.commit()

            snapshot = await build_daily_leaderboard_snapshot(session, target_date)

        self.assertEqual(snapshot["forecast_count"], 2)
        self.assertEqual(snapshot["tournament_count"], 1)
        self.assertEqual(snapshot["leaders"][0]["user_id"], 1)
        self.assertEqual(snapshot["leaders"][0]["perfects"], 1)
        self.assertNotIn("streak_emoji", snapshot["leaders"][0])

    async def test_build_detailed_season_snapshot_preserves_totals(self):
        async with self.session_maker() as session:
            session.add_all(
                [
                    User(id=1, username="alpha", full_name="Alpha"),
                    User(id=2, username="beta", full_name="Beta"),
                ]
            )
            session.add(
                Season(
                    id=1,
                    number=1,
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 31),
                    status="closed",
                )
            )
            session.add_all(
                [
                    Tournament(
                        id=1,
                        name="Cup 1",
                        date=date(2026, 1, 1),
                        status=TournamentStatus.FINISHED,
                    ),
                    Tournament(
                        id=2,
                        name="Cup 2",
                        date=date(2026, 1, 8),
                        status=TournamentStatus.FINISHED,
                    ),
                ]
            )
            session.add_all(
                [
                    Forecast(
                        user_id=1,
                        tournament_id=1,
                        prediction_data=[1],
                        points_earned=10,
                    ),
                    Forecast(
                        user_id=1,
                        tournament_id=2,
                        prediction_data=[1],
                        points_earned=15,
                    ),
                    Forecast(
                        user_id=2, tournament_id=1, prediction_data=[1], points_earned=8
                    ),
                ]
            )
            await session.commit()

            snapshot = await build_detailed_season_snapshot(session, 1)

        self.assertEqual(snapshot["columns"], ["Cup 1", "Cup 2"])
        self.assertEqual(snapshot["rows"][0]["name"], "Alpha")
        self.assertEqual(snapshot["rows"][0]["scores"], [10, 15])
        self.assertEqual(snapshot["rows"][0]["total"], 25)
