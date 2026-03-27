import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from aiogram import types
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

from app.handlers.stats import (
    answer_callback_safe,
    daily_date_selection_kb,
    leaderboard_daily_modes_kb,
    leaderboard_kb,
)


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


class StatsKeyboardTests(unittest.TestCase):
    def test_leaderboard_menu_keyboard_shows_all_rating_options(self):
        keyboard = leaderboard_kb("menu")

        buttons = [button for row in keyboard.inline_keyboard for button in row]
        callback_data = {button.callback_data for button in buttons}

        self.assertEqual(
            callback_data,
            {
                "leaderboard:season",
                "leaderboard:global",
                "leaderboard:daily:menu",
                "leaderboard:history:list",
            },
        )

    def test_daily_modes_keyboard_returns_to_rating_menu(self):
        keyboard = leaderboard_daily_modes_kb()

        buttons = [button for row in keyboard.inline_keyboard for button in row]
        back_button = next(
            button for button in buttons if button.callback_data == "leaderboard:menu"
        )

        self.assertEqual(back_button.text, "↩️ К выбору рейтинга")

    def test_daily_date_selection_cancel_returns_to_daily_menu(self):
        keyboard = daily_date_selection_kb()

        buttons = [button for row in keyboard.inline_keyboard for button in row]
        cancel_button = next(button for button in buttons if button.text == "❌ Отмена")

        self.assertEqual(cancel_button.callback_data, "leaderboard:daily:menu")
