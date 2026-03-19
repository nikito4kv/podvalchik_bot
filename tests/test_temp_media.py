import unittest
from unittest.mock import patch

from app.utils import temp_media


class _FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self._body = body
        self.status = status
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def text(self):
        return self._body


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def post(self, url, data):
        self.calls.append({"url": url, "data": data})
        return self.response


class TempMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_temp_media_returns_url_and_delete_token(self):
        response = _FakeResponse(
            "https://0x0.st/abc123.png/leaderboard.png",
            headers={"X-Token": "delete-token"},
        )
        session = _FakeSession(response)

        with (
            patch.object(
                temp_media.config,
                "temp_media_upload_url",
                "https://0x0.st",
            ),
            patch.object(temp_media.config, "temp_media_upload_timeout", 15),
            patch.object(
                temp_media.config, "temp_media_user_agent", "PodvalchikBot/1.0"
            ),
            patch.object(temp_media.config, "tg_media_max_attempts", 1),
            patch("app.utils.temp_media.aiohttp.ClientSession", return_value=session),
        ):
            result = await temp_media.upload_temp_media(
                b"png-bytes",
                "stats.png",
            )

        self.assertEqual(result.key, "abc123.png/leaderboard.png")
        self.assertEqual(
            result.url,
            "https://0x0.st/abc123.png/leaderboard.png",
        )
        self.assertEqual(result.delete_token, "delete-token")
        self.assertEqual(session.calls[0]["url"], "https://0x0.st")

    async def test_delete_temp_media_posts_delete_token(self):
        response = _FakeResponse("deleted")
        session = _FakeSession(response)
        upload_result = temp_media.TempMediaUploadResult(
            key="abc123.png/leaderboard.png",
            url="https://0x0.st/abc123.png/leaderboard.png",
            delete_token="delete-token",
        )

        with (
            patch.object(temp_media.config, "temp_media_upload_timeout", 15),
            patch.object(
                temp_media.config, "temp_media_user_agent", "PodvalchikBot/1.0"
            ),
            patch("app.utils.temp_media.aiohttp.ClientSession", return_value=session),
        ):
            await temp_media.delete_temp_media(upload_result)

        self.assertEqual(
            session.calls[0]["url"],
            "https://0x0.st/abc123.png/leaderboard.png",
        )
