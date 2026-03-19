import asyncio
import logging
from time import perf_counter

from aiogram import Bot, types
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import BufferedInputFile

from app.config import config


LOGGER = logging.getLogger(__name__)


def _build_photo(photo_bytes: bytes, filename: str) -> BufferedInputFile:
    return BufferedInputFile(photo_bytes, filename=filename)


async def _run_media_call_with_retry(
    operation_name: str,
    operation,
    *,
    chat_id: int,
    size_bytes: int,
    message_id: int | None = None,
):
    max_attempts = max(1, config.tg_media_max_attempts)
    backoff_seconds = max(0.0, config.tg_media_retry_backoff_seconds)
    timeout_seconds = config.tg_media_request_timeout

    for attempt in range(1, max_attempts + 1):
        started = perf_counter()
        try:
            result = await operation(timeout_seconds)
        except TelegramNetworkError as exc:
            duration_ms = (perf_counter() - started) * 1000
            LOGGER.warning(
                "telegram.media.%s.network_error chat_id=%s message_id=%s attempt=%s/%s size_bytes=%s duration_ms=%.3f timeout_s=%s proxy_enabled=%s error=%s",
                operation_name,
                chat_id,
                message_id,
                attempt,
                max_attempts,
                size_bytes,
                duration_ms,
                timeout_seconds,
                bool(config.tg_api_server),
                exc,
            )
            if attempt >= max_attempts:
                raise
            await asyncio.sleep(backoff_seconds * attempt)
            continue

        duration_ms = (perf_counter() - started) * 1000
        LOGGER.info(
            "telegram.media.%s.complete chat_id=%s message_id=%s attempt=%s/%s size_bytes=%s duration_ms=%.3f timeout_s=%s proxy_enabled=%s",
            operation_name,
            chat_id,
            message_id,
            attempt,
            max_attempts,
            size_bytes,
            duration_ms,
            timeout_seconds,
            bool(config.tg_api_server),
        )
        return result


async def send_photo_with_retry(
    bot: Bot,
    chat_id: int,
    photo_bytes: bytes,
    filename: str,
    caption: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    parse_mode: str = "HTML",
):
    async def operation(request_timeout: int):
        return await bot.send_photo(
            chat_id=chat_id,
            photo=_build_photo(photo_bytes, filename),
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            request_timeout=request_timeout,
        )

    return await _run_media_call_with_retry(
        "send_photo",
        operation,
        chat_id=chat_id,
        size_bytes=len(photo_bytes),
    )


async def edit_message_photo_with_retry(
    bot: Bot,
    chat_id: int,
    message_id: int,
    photo_bytes: bytes,
    filename: str,
    caption: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    parse_mode: str = "HTML",
):
    async def operation(request_timeout: int):
        return await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=types.InputMediaPhoto(
                media=_build_photo(photo_bytes, filename),
                caption=caption,
                parse_mode=parse_mode,
            ),
            reply_markup=reply_markup,
            request_timeout=request_timeout,
        )

    return await _run_media_call_with_retry(
        "edit_message_media",
        operation,
        chat_id=chat_id,
        size_bytes=len(photo_bytes),
        message_id=message_id,
    )


async def send_or_update_photo(
    bot: Bot,
    chat_id: int,
    photo_bytes: bytes,
    filename: str,
    caption: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    message_to_edit: types.Message | None = None,
    parse_mode: str = "HTML",
):
    if message_to_edit and message_to_edit.content_type == types.ContentType.PHOTO:
        return await edit_message_photo_with_retry(
            bot=bot,
            chat_id=chat_id,
            message_id=message_to_edit.message_id,
            photo_bytes=photo_bytes,
            filename=filename,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

    sent_message = await send_photo_with_retry(
        bot=bot,
        chat_id=chat_id,
        photo_bytes=photo_bytes,
        filename=filename,
        caption=caption,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )

    if message_to_edit:
        try:
            await bot.delete_message(
                chat_id=chat_id,
                message_id=message_to_edit.message_id,
            )
        except Exception as exc:
            LOGGER.warning(
                "telegram.media.cleanup_failed chat_id=%s message_id=%s error=%s",
                chat_id,
                message_to_edit.message_id,
                exc,
            )

    return sent_message
