import unittest
from unittest.mock import patch

from app.utils.detailed_stats_generator import generate_detailed_season_image
from app.utils.image_generator import (
    generate_leaderboard_image,
    generate_user_profile_image,
)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ImageRenderingTests(unittest.TestCase):
    def test_generate_leaderboard_image_returns_png(self):
        image = generate_leaderboard_image(
            "TOP",
            [
                {
                    "user_id": 1,
                    "name": "Alpha One",
                    "points": 42,
                    "played": 3,
                    "perfects": 1,
                    "league_emoji": "👶",
                }
            ],
        )

        self.assertTrue(image.getvalue().startswith(PNG_SIGNATURE))

    def test_generate_user_profile_image_survives_missing_assets(self):
        with (
            patch("app.utils.render_assets.resolve_font_path", return_value=None),
            patch("app.utils.render_assets.resolve_logo_path", return_value=None),
        ):
            image = generate_user_profile_image(
                {
                    "full_name": "Alpha One",
                    "rank_title": "Новичок",
                    "total_points": 42,
                    "rank_pos": 1,
                    "played": 3,
                    "avg_score": 14.0,
                    "perfects": 1,
                    "exacts": 2,
                    "current_streak": 2,
                    "max_streak": 3,
                }
            )

        self.assertTrue(image.getvalue().startswith(PNG_SIGNATURE))

    def test_generate_detailed_season_image_survives_missing_assets(self):
        with (
            patch("app.utils.render_assets.resolve_font_path", return_value=None),
            patch("app.utils.render_assets.resolve_logo_path", return_value=None),
        ):
            image = generate_detailed_season_image(
                "Season 1",
                ["Cup 1", "Cup 2"],
                [{"name": "Alpha One", "scores": [10, 15], "total": 25}],
            )

        self.assertTrue(image.getvalue().startswith(PNG_SIGNATURE))
