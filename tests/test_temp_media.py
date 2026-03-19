import unittest
from unittest.mock import patch

from app.utils import temp_media


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def json(self, content_type=None):
        return self._payload


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def post(self, url, data, headers):
        self.calls.append({"url": url, "data": data, "headers": headers})
        return self.response


class TempMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_temp_media_returns_signed_url_payload(self):
        response = _FakeResponse(
            {
                "key": "temp/123/file.png",
                "url": "https://worker.example/temp-media/temp/123/file.png?sig=abc",
                "expires_at": 123,
            }
        )
        session = _FakeSession(response)

        with (
            patch.object(
                temp_media.config,
                "temp_media_upload_url",
                "https://worker.example/temp-media",
            ),
            patch.object(temp_media.config, "temp_media_upload_token", "secret"),
            patch.object(temp_media.config, "temp_media_upload_timeout", 15),
            patch.object(temp_media.config, "temp_media_ttl_seconds", 300),
            patch.object(temp_media.config, "tg_media_max_attempts", 1),
            patch("app.utils.temp_media.aiohttp.ClientSession", return_value=session),
        ):
            result = await temp_media.upload_temp_media(
                b"png-bytes",
                "stats.png",
            )

        self.assertEqual(result.key, "temp/123/file.png")
        self.assertEqual(
            result.url,
            "https://worker.example/temp-media/temp/123/file.png?sig=abc",
        )
        self.assertEqual(result.expires_at, 123)
        self.assertEqual(session.calls[0]["url"], "https://worker.example/temp-media")
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(session.calls[0]["headers"]["X-TTL-Seconds"], "300")
