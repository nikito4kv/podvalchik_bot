import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiogram import types
from aiogram.exceptions import TelegramNetworkError

from app.utils import telegram_media


class TelegramMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_or_update_photo_retries_send_and_cleans_up_loading_message(
        self,
    ):
        bot = AsyncMock()
        sent_message = object()
        bot.send_photo = AsyncMock(
            side_effect=[
                TelegramNetworkError(method=Mock(), message="Request timeout error"),
                sent_message,
            ]
        )
        bot.delete_message = AsyncMock()
        loading_message = SimpleNamespace(
            content_type=types.ContentType.TEXT,
            message_id=42,
        )

        with (
            patch.object(telegram_media.config, "tg_media_request_timeout", 123),
            patch.object(telegram_media.config, "tg_media_max_attempts", 2),
            patch.object(telegram_media.config, "tg_media_retry_backoff_seconds", 0),
            patch("app.utils.telegram_media.asyncio.sleep", new=AsyncMock()),
        ):
            result = await telegram_media.send_or_update_photo(
                bot=bot,
                chat_id=99,
                photo_bytes=b"png-bytes",
                filename="stats.png",
                caption="caption",
                message_to_edit=loading_message,
            )

        self.assertIs(result, sent_message)
        self.assertEqual(bot.send_photo.await_count, 2)
        bot.delete_message.assert_awaited_once_with(chat_id=99, message_id=42)
        first_call = bot.send_photo.await_args_list[0].kwargs
        self.assertEqual(first_call["request_timeout"], 123)
        self.assertEqual(first_call["caption"], "caption")
        self.assertEqual(first_call["photo"].filename, "stats.png")

    async def test_send_or_update_photo_edits_existing_photo_message(self):
        bot = AsyncMock()
        bot.send_photo = AsyncMock()
        bot.edit_message_media = AsyncMock(return_value=True)
        bot.delete_message = AsyncMock()
        photo_message = SimpleNamespace(
            content_type=types.ContentType.PHOTO,
            message_id=77,
        )

        with patch.object(telegram_media.config, "tg_media_request_timeout", 150):
            result = await telegram_media.send_or_update_photo(
                bot=bot,
                chat_id=55,
                photo_bytes=b"leaderboard",
                filename="leaderboard.png",
                caption="<b>caption</b>",
                reply_markup=None,
                message_to_edit=photo_message,
            )

        self.assertTrue(result)
        bot.send_photo.assert_not_awaited()
        bot.delete_message.assert_not_awaited()
        bot.edit_message_media.assert_awaited_once()
        edit_call = bot.edit_message_media.await_args.kwargs
        self.assertEqual(edit_call["chat_id"], 55)
        self.assertEqual(edit_call["message_id"], 77)
        self.assertEqual(edit_call["request_timeout"], 150)
        self.assertEqual(edit_call["media"].caption, "<b>caption</b>")
        self.assertEqual(edit_call["media"].media.filename, "leaderboard.png")
