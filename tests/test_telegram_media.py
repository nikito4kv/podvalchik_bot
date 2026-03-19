import unittest
from types import SimpleNamespace
from typing import cast
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
            patch.object(telegram_media.config, "temp_media_enabled", False),
            patch("app.utils.telegram_media.asyncio.sleep", new=AsyncMock()),
        ):
            result = await telegram_media.send_or_update_photo(
                bot=bot,
                chat_id=99,
                photo_bytes=b"png-bytes",
                filename="stats.png",
                caption="caption",
                message_to_edit=cast(types.Message, loading_message),
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
                message_to_edit=cast(types.Message, photo_message),
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

    async def test_send_or_update_photo_uses_temp_media_url_when_enabled(self):
        bot = AsyncMock()
        bot.send_photo = AsyncMock(return_value=True)
        bot.delete_message = AsyncMock()
        loading_message = SimpleNamespace(
            content_type=types.ContentType.TEXT,
            message_id=7,
        )

        upload_result = SimpleNamespace(
            url="https://0x0.st/abc123.png/leaderboard.png",
            key="abc123.png/leaderboard.png",
            provider="0x0st",
            delete_token="delete-token",
        )

        with (
            patch.object(telegram_media.config, "temp_media_enabled", True),
            patch(
                "app.utils.telegram_media.upload_temp_media",
                new=AsyncMock(return_value=upload_result),
            ),
            patch(
                "app.utils.telegram_media.schedule_temp_media_delete"
            ) as schedule_delete,
        ):
            await telegram_media.send_or_update_photo(
                bot=bot,
                chat_id=55,
                photo_bytes=b"leaderboard",
                filename="leaderboard.png",
                caption="caption",
                message_to_edit=cast(types.Message, loading_message),
            )

        call = bot.send_photo.await_args.kwargs
        self.assertEqual(
            call["photo"],
            "https://0x0.st/abc123.png/leaderboard.png",
        )
        bot.delete_message.assert_awaited_once_with(chat_id=55, message_id=7)
        schedule_delete.assert_called_once_with(upload_result)

    async def test_send_or_update_photo_replaces_loading_message_on_temp_media_failure(
        self,
    ):
        bot = AsyncMock()
        loading_message = SimpleNamespace(
            content_type=types.ContentType.TEXT,
            message_id=99,
            edit_text=AsyncMock(),
        )

        with (
            patch.object(telegram_media.config, "temp_media_enabled", True),
            patch(
                "app.utils.telegram_media.upload_temp_media",
                new=AsyncMock(
                    side_effect=telegram_media.TempMediaUploadError("upload failed")
                ),
            ),
        ):
            with self.assertRaises(telegram_media.TempMediaUploadError):
                await telegram_media.send_or_update_photo(
                    bot=bot,
                    chat_id=55,
                    photo_bytes=b"leaderboard",
                    filename="leaderboard.png",
                    caption="caption",
                    message_to_edit=cast(types.Message, loading_message),
                )

        loading_message.edit_text.assert_awaited_once()
