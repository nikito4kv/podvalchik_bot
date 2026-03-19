import unittest
from unittest.mock import Mock, patch

from app.utils import temp_media


class _FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self.text = body
        self.status = status
        self.status_code = status
        self.headers = headers or {}


class TempMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_temp_media_returns_url_and_delete_token(self):
        response = _FakeResponse(
            "https://0x0.st/abc123.png/leaderboard.png",
            headers={"X-Token": "delete-token"},
        )
        post_mock = Mock(return_value=response)

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
            patch("app.utils.temp_media.requests.post", post_mock),
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
        self.assertEqual(post_mock.call_args.kwargs["files"]["file"][0], "stats.png")
        self.assertEqual(post_mock.call_args.args[0], "https://0x0.st")

    async def test_delete_temp_media_posts_delete_token(self):
        response = _FakeResponse("deleted")
        post_mock = Mock(return_value=response)
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
            patch("app.utils.temp_media.requests.post", post_mock),
        ):
            await temp_media.delete_temp_media(upload_result)

        self.assertEqual(
            post_mock.call_args.args[0],
            "https://0x0.st/abc123.png/leaderboard.png",
        )
        self.assertEqual(post_mock.call_args.kwargs["data"]["token"], "delete-token")
