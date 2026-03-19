import asyncio
import logging
from time import perf_counter

from aiogram import Bot, types
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import BufferedInputFile

from app.config import config
from app.utils.temp_media import (
    TempMediaUploadError,
    schedule_temp_media_delete,
    temp_media_enabled,
    upload_temp_media,
)


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
    delivery_mode: str = "multipart",
    media_key: str | None = None,
    provider: str = "telegram",
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
                "telegram.media.%s.network_error chat_id=%s message_id=%s attempt=%s/%s size_bytes=%s duration_ms=%.3f timeout_s=%s proxy_enabled=%s delivery_mode=%s provider=%s media_key=%s error=%s",
                operation_name,
                chat_id,
                message_id,
                attempt,
                max_attempts,
                size_bytes,
                duration_ms,
                timeout_seconds,
                bool(config.tg_api_server),
                delivery_mode,
                provider,
                media_key,
                exc,
            )
            if attempt >= max_attempts:
                raise
            await asyncio.sleep(backoff_seconds * attempt)
            continue

        duration_ms = (perf_counter() - started) * 1000
        LOGGER.info(
            "telegram.media.%s.complete chat_id=%s message_id=%s attempt=%s/%s size_bytes=%s duration_ms=%.3f timeout_s=%s proxy_enabled=%s delivery_mode=%s provider=%s media_key=%s",
            operation_name,
            chat_id,
            message_id,
            attempt,
            max_attempts,
            size_bytes,
            duration_ms,
            timeout_seconds,
            bool(config.tg_api_server),
            delivery_mode,
            provider,
            media_key,
        )
        return result


async def _notify_media_failure(
    bot: Bot,
    chat_id: int,
    message_to_edit: types.Message | None,
):
    text = "⚠️ Не удалось отправить изображение. Попробуйте еще раз чуть позже."
    if message_to_edit is not None:
        try:
            if message_to_edit.content_type == types.ContentType.PHOTO:
                await message_to_edit.edit_caption(caption=text, reply_markup=None)
            else:
                await message_to_edit.edit_text(text)
            return
        except Exception as exc:
            LOGGER.warning(
                "telegram.media.failure_notice_edit_failed chat_id=%s message_id=%s error=%s",
                chat_id,
                message_to_edit.message_id,
                exc,
            )
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as exc:
        LOGGER.warning(
            "telegram.media.failure_notice_send_failed chat_id=%s error=%s",
            chat_id,
            exc,
        )


async def _prepare_photo_reference(photo_bytes: bytes, filename: str):
    if temp_media_enabled():
        uploaded_media = await upload_temp_media(photo_bytes, filename)
        schedule_temp_media_delete(uploaded_media)
        return uploaded_media.url, "url", uploaded_media.key, uploaded_media.provider
    return _build_photo(photo_bytes, filename), "multipart", None, "telegram"


async def send_photo_with_retry(
    bot: Bot,
    chat_id: int,
    photo_bytes: bytes,
    filename: str,
    caption: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    parse_mode: str = "HTML",
):
    (
        photo_reference,
        delivery_mode,
        media_key,
        provider,
    ) = await _prepare_photo_reference(
        photo_bytes,
        filename,
    )

    async def operation(request_timeout: int):
        return await bot.send_photo(
            chat_id=chat_id,
            photo=photo_reference,
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
        delivery_mode=delivery_mode,
        media_key=media_key,
        provider=provider,
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
    (
        photo_reference,
        delivery_mode,
        media_key,
        provider,
    ) = await _prepare_photo_reference(
        photo_bytes,
        filename,
    )

    async def operation(request_timeout: int):
        return await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=types.InputMediaPhoto(
                media=photo_reference,
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
        delivery_mode=delivery_mode,
        media_key=media_key,
        provider=provider,
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
    try:
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
    except (TelegramNetworkError, TempMediaUploadError):
        await _notify_media_failure(
            bot=bot,
            chat_id=chat_id,
            message_to_edit=message_to_edit,
        )
        raise
