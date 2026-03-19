import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlparse

import aiohttp

from app.config import config


LOGGER = logging.getLogger(__name__)


class TempMediaUploadError(RuntimeError):
    pass


@dataclass(slots=True)
class TempMediaUploadResult:
    key: str
    url: str
    delete_token: str | None
    provider: str = "0x0st"


def temp_media_enabled() -> bool:
    return bool(config.temp_media_enabled)


def _upload_url() -> str:
    upload_url = config.temp_media_upload_url.strip()
    if not upload_url:
        raise TempMediaUploadError("TEMP_MEDIA_UPLOAD_URL is not configured")
    return upload_url


def _build_form_data(media_bytes: bytes, filename: str) -> aiohttp.FormData:
    form = aiohttp.FormData()
    form.add_field(
        "file",
        media_bytes,
        filename=filename,
        content_type="image/png",
    )
    form.add_field("secret", "")
    return form


def _extract_key(file_url: str) -> str:
    parsed = urlparse(file_url)
    return parsed.path.lstrip("/") or file_url


async def upload_temp_media(
    media_bytes: bytes,
    filename: str,
) -> TempMediaUploadResult:
    upload_url = _upload_url()
    max_attempts = max(1, config.tg_media_max_attempts)
    backoff_seconds = max(0.0, config.tg_media_retry_backoff_seconds)
    timeout = aiohttp.ClientTimeout(total=max(1, config.temp_media_upload_timeout))
    headers = {
        "User-Agent": config.temp_media_user_agent,
    }

    for attempt in range(1, max_attempts + 1):
        started = perf_counter()
        try:
            async with aiohttp.ClientSession(
                timeout=timeout, headers=headers
            ) as session:
                async with session.post(
                    upload_url,
                    data=_build_form_data(media_bytes, filename),
                ) as response:
                    body = (await response.text()).strip()
                    if response.status >= 400:
                        raise TempMediaUploadError(
                            f"Temp media upload failed with status {response.status}: {body}"
                        )
                    if not body.startswith("https://"):
                        raise TempMediaUploadError(
                            f"Unexpected temp media response body: {body}"
                        )
                    delete_token = response.headers.get("X-Token")
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            TempMediaUploadError,
        ) as exc:
            duration_ms = (perf_counter() - started) * 1000
            LOGGER.warning(
                "telegram.temp_media.upload.network_error provider=0x0st attempt=%s/%s size_bytes=%s duration_ms=%.3f timeout_s=%s error=%s",
                attempt,
                max_attempts,
                len(media_bytes),
                duration_ms,
                config.temp_media_upload_timeout,
                exc,
            )
            if attempt >= max_attempts:
                raise TempMediaUploadError("Temp media upload failed") from exc
            await asyncio.sleep(backoff_seconds * attempt)
            continue

        duration_ms = (perf_counter() - started) * 1000
        result = TempMediaUploadResult(
            key=_extract_key(body),
            url=body,
            delete_token=delete_token,
        )
        LOGGER.info(
            "telegram.temp_media.upload.complete provider=%s key=%s size_bytes=%s duration_ms=%.3f has_delete_token=%s",
            result.provider,
            result.key,
            len(media_bytes),
            duration_ms,
            bool(result.delete_token),
        )
        return result

    raise TempMediaUploadError("Temp media upload failed")


async def delete_temp_media(upload_result: TempMediaUploadResult) -> None:
    if not upload_result.delete_token:
        LOGGER.warning(
            "telegram.temp_media.delete.skipped provider=%s key=%s reason=missing_delete_token",
            upload_result.provider,
            upload_result.key,
        )
        return

    timeout = aiohttp.ClientTimeout(total=max(1, config.temp_media_upload_timeout))
    headers = {
        "User-Agent": config.temp_media_user_agent,
    }
    form = aiohttp.FormData()
    form.add_field("token", upload_result.delete_token)
    form.add_field("delete", "")
    started = perf_counter()

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.post(upload_result.url, data=form) as response:
                response_text = (await response.text()).strip()
                if response.status >= 400:
                    raise TempMediaUploadError(
                        f"Temp media delete failed with status {response.status}: {response_text}"
                    )
    except (aiohttp.ClientError, asyncio.TimeoutError, TempMediaUploadError) as exc:
        duration_ms = (perf_counter() - started) * 1000
        LOGGER.warning(
            "telegram.temp_media.delete.failed provider=%s key=%s duration_ms=%.3f error=%s",
            upload_result.provider,
            upload_result.key,
            duration_ms,
            exc,
        )
        return

    duration_ms = (perf_counter() - started) * 1000
    LOGGER.info(
        "telegram.temp_media.delete.complete provider=%s key=%s duration_ms=%.3f",
        upload_result.provider,
        upload_result.key,
        duration_ms,
    )


def schedule_temp_media_delete(upload_result: TempMediaUploadResult) -> None:
    delay_seconds = max(1, config.temp_media_delete_after_seconds)
    LOGGER.info(
        "telegram.temp_media.delete.scheduled provider=%s key=%s delay_seconds=%s has_delete_token=%s",
        upload_result.provider,
        upload_result.key,
        delay_seconds,
        bool(upload_result.delete_token),
    )

    async def _delete_later() -> None:
        await asyncio.sleep(delay_seconds)
        await delete_temp_media(upload_result)

    asyncio.create_task(_delete_later())
