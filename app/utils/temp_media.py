import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter

import aiohttp

from app.config import config


LOGGER = logging.getLogger(__name__)


class TempMediaUploadError(RuntimeError):
    pass


@dataclass(slots=True)
class TempMediaUploadResult:
    key: str
    url: str
    expires_at: int


def temp_media_enabled() -> bool:
    return bool(config.temp_media_enabled)


def _validate_temp_media_config() -> tuple[str, str]:
    if not config.temp_media_upload_url:
        raise TempMediaUploadError("TEMP_MEDIA_UPLOAD_URL is not configured")
    if not config.temp_media_upload_token:
        raise TempMediaUploadError("TEMP_MEDIA_UPLOAD_TOKEN is not configured")
    return config.temp_media_upload_url, config.temp_media_upload_token


async def upload_temp_media(
    media_bytes: bytes,
    filename: str,
    content_type: str = "image/png",
) -> TempMediaUploadResult:
    upload_url, upload_token = _validate_temp_media_config()
    max_attempts = max(1, config.tg_media_max_attempts)
    backoff_seconds = max(0.0, config.tg_media_retry_backoff_seconds)
    timeout = aiohttp.ClientTimeout(total=max(1, config.temp_media_upload_timeout))

    headers = {
        "Authorization": f"Bearer {upload_token}",
        "Content-Type": content_type,
        "X-Filename": filename,
        "X-TTL-Seconds": str(max(1, config.temp_media_ttl_seconds)),
    }

    for attempt in range(1, max_attempts + 1):
        started = perf_counter()
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    upload_url,
                    data=media_bytes,
                    headers=headers,
                ) as response:
                    payload = await response.json(content_type=None)
                    if response.status >= 400:
                        raise TempMediaUploadError(
                            f"Temp media upload failed with status {response.status}: {payload}"
                        )
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ValueError,
            TempMediaUploadError,
        ) as exc:
            duration_ms = (perf_counter() - started) * 1000
            LOGGER.warning(
                "telegram.temp_media.upload.network_error attempt=%s/%s size_bytes=%s duration_ms=%.3f timeout_s=%s error=%s",
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

        if (
            not isinstance(payload, dict)
            or not payload.get("url")
            or not payload.get("key")
        ):
            raise TempMediaUploadError(
                f"Unexpected temp media response payload: {payload}"
            )

        duration_ms = (perf_counter() - started) * 1000
        result = TempMediaUploadResult(
            key=str(payload["key"]),
            url=str(payload["url"]),
            expires_at=int(payload.get("expires_at", 0)),
        )
        LOGGER.info(
            "telegram.temp_media.upload.complete key=%s size_bytes=%s duration_ms=%.3f expires_at=%s",
            result.key,
            len(media_bytes),
            duration_ms,
            result.expires_at,
        )
        return result

    raise TempMediaUploadError("Temp media upload failed")
