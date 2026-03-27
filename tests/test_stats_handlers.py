import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from aiogram import types
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

from app.handlers.stats import answer_callback_safe


class StatsHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_callback_safe_ignores_expired_query(self):
        callback = SimpleNamespace(
            answer=AsyncMock(
                side_effect=TelegramBadRequest(
                    method=Mock(),
                    message="query is too old and response timeout expired or query ID is invalid",
                )
            ),
            data="leaderboard:daily:today",
        )

        result = await answer_callback_safe(cast(types.CallbackQuery, callback))

        self.assertFalse(result)
        callback.answer.assert_awaited_once()

    async def test_answer_callback_safe_ignores_network_timeout(self):
        callback = SimpleNamespace(
            answer=AsyncMock(
                side_effect=TelegramNetworkError(
                    method=Mock(), message="Request timeout error"
                )
            ),
            data="leaderboard:global",
        )

        result = await answer_callback_safe(cast(types.CallbackQuery, callback), "done")

        self.assertFalse(result)
        callback.answer.assert_awaited_once_with("done")

    async def test_answer_callback_safe_returns_true_on_success(self):
        callback = SimpleNamespace(answer=AsyncMock(), data="leaderboard:season")

        result = await answer_callback_safe(
            cast(types.CallbackQuery, callback), "ok", show_alert=True
        )

        self.assertTrue(result)
        callback.answer.assert_awaited_once_with("ok", show_alert=True)

    async def test_answer_callback_safe_reraises_non_timeout_network_errors(self):
        callback = SimpleNamespace(
            answer=AsyncMock(
                side_effect=TelegramNetworkError(
                    method=Mock(), message="Connection reset by peer"
                )
            ),
            data="leaderboard:season",
        )

        with self.assertRaises(TelegramNetworkError):
            await answer_callback_safe(cast(types.CallbackQuery, callback))
