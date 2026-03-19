import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlparse

import requests

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


def _build_user_agent() -> str:
    user_agent = config.temp_media_user_agent.strip() or "PodvalchikBot/1.0"
    if "forecast_podvalchik_bot" in user_agent or "t.me/" in user_agent:
        return user_agent
    return f"{user_agent} (+https://t.me/forecast_podvalchik_bot)"


def _build_form_data(
    media_bytes: bytes, filename: str
) -> dict[str, tuple[str, bytes, str]]:
    return {
        "file": (filename, media_bytes, "image/png"),
    }


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
    timeout_seconds = max(1, config.temp_media_upload_timeout)
    headers = {
        "User-Agent": _build_user_agent(),
    }

    for attempt in range(1, max_attempts + 1):
        started = perf_counter()
        try:
            response = await asyncio.to_thread(
                requests.post,
                upload_url,
                files=_build_form_data(media_bytes, filename),
                data={"secret": ""},
                headers=headers,
                timeout=timeout_seconds,
            )
            body = response.text.strip()
            if response.status_code >= 400:
                raise TempMediaUploadError(
                    f"Temp media upload failed with status {response.status_code}: {body}"
                )
            if not body.startswith("https://"):
                raise TempMediaUploadError(
                    f"Unexpected temp media response body: {body}"
                )
            delete_token = response.headers.get("X-Token")
        except (
            asyncio.TimeoutError,
            requests.RequestException,
            TempMediaUploadError,
        ) as exc:
            duration_ms = (perf_counter() - started) * 1000
            LOGGER.warning(
                "telegram.temp_media.upload.network_error provider=0x0st attempt=%s/%s size_bytes=%s duration_ms=%.3f timeout_s=%s error=%s",
                attempt,
                max_attempts,
                len(media_bytes),
                duration_ms,
                timeout_seconds,
                repr(exc),
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

    timeout_seconds = max(1, config.temp_media_upload_timeout)
    headers = {
        "User-Agent": _build_user_agent(),
    }
    started = perf_counter()

    try:
        response = await asyncio.to_thread(
            requests.post,
            upload_result.url,
            data={"token": upload_result.delete_token, "delete": ""},
            headers=headers,
            timeout=timeout_seconds,
        )
        response_text = response.text.strip()
        if response.status_code >= 400:
            raise TempMediaUploadError(
                f"Temp media delete failed with status {response.status_code}: {response_text}"
            )
    except (
        asyncio.TimeoutError,
        requests.RequestException,
        TempMediaUploadError,
    ) as exc:
        duration_ms = (perf_counter() - started) * 1000
        LOGGER.warning(
            "telegram.temp_media.delete.failed provider=%s key=%s duration_ms=%.3f error=%s",
            upload_result.provider,
            upload_result.key,
            duration_ms,
            repr(exc),
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
