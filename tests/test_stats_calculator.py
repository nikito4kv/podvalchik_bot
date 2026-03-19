import os
import tempfile
import unittest
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, Forecast, Tournament, TournamentStatus, User
from app.utils.stats_calculator import (
    calculate_user_tournament_streaks,
    recalculate_user_streaks,
)


class StatsCalculatorTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_calculate_user_tournament_streaks_resets_after_gap(self):
        async with self.session_maker() as session:
            session.add(User(id=1, username="alpha", full_name="Alpha"))
            session.add_all(
                [
                    Tournament(
                        id=1,
                        name="T1",
                        date=date(2026, 1, 1),
                        status=TournamentStatus.FINISHED,
                    ),
                    Tournament(
                        id=2,
                        name="T2",
                        date=date(2026, 1, 8),
                        status=TournamentStatus.FINISHED,
                    ),
                    Tournament(
                        id=3,
                        name="T3",
                        date=date(2026, 1, 15),
                        status=TournamentStatus.FINISHED,
                    ),
                    Tournament(
                        id=4,
                        name="T4",
                        date=date(2026, 1, 22),
                        status=TournamentStatus.OPEN,
                    ),
                    Tournament(
                        id=5,
                        name="Draft",
                        date=date(2026, 1, 29),
                        status=TournamentStatus.DRAFT,
                    ),
                ]
            )
            session.add_all(
                [
                    Forecast(
                        user_id=1,
                        tournament_id=1,
                        prediction_data=[1, 2, 3],
                        points_earned=1,
                    ),
                    Forecast(
                        user_id=1,
                        tournament_id=2,
                        prediction_data=[1, 2, 3],
                        points_earned=1,
                    ),
                    Forecast(
                        user_id=1,
                        tournament_id=4,
                        prediction_data=[1, 2, 3],
                        points_earned=1,
                    ),
                    Forecast(
                        user_id=1,
                        tournament_id=5,
                        prediction_data=[1, 2, 3],
                        points_earned=1,
                    ),
                ]
            )
            await session.commit()

            current_streak, max_streak = await calculate_user_tournament_streaks(
                session, 1
            )

        self.assertEqual((current_streak, max_streak), (1, 2))

    async def test_recalculate_user_streaks_requires_explicit_commit(self):
        async with self.session_maker() as session:
            session.add(
                User(
                    id=1,
                    username="alpha",
                    full_name="Alpha",
                    streak_days=0,
                    max_streak=0,
                )
            )
            session.add_all(
                [
                    Tournament(
                        id=1,
                        name="T1",
                        date=date(2026, 1, 1),
                        status=TournamentStatus.FINISHED,
                    ),
                    Tournament(
                        id=2,
                        name="T2",
                        date=date(2026, 1, 8),
                        status=TournamentStatus.FINISHED,
                    ),
                ]
            )
            session.add_all(
                [
                    Forecast(
                        user_id=1, tournament_id=1, prediction_data=[1], points_earned=1
                    ),
                    Forecast(
                        user_id=1, tournament_id=2, prediction_data=[1], points_earned=1
                    ),
                ]
            )
            await session.commit()

        async with self.session_maker() as session:
            current_streak, max_streak = await recalculate_user_streaks(session, 1)
            user = await session.get(User, 1)

            self.assertEqual((current_streak, max_streak), (2, 2))
            self.assertEqual(user.streak_days, 2)
            self.assertEqual(user.max_streak, 2)

            await session.rollback()

        async with self.session_maker() as session:
            user = await session.get(User, 1)
            self.assertEqual(user.streak_days, 0)
            self.assertEqual(user.max_streak, 0)
