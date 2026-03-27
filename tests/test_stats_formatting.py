import unittest

from app.utils.formatting import (
    format_detailed_season_rows,
    format_leaderboard_entries,
    format_user_profile_text,
    split_text_chunks,
)


class StatsFormattingTests(unittest.TestCase):
    def test_format_user_profile_text_escapes_html_and_includes_metrics(self):
        text = format_user_profile_text(
            {
                "full_name": "Alpha <One>",
                "rank_title": "Новичок & лидер",
                "total_points": 42,
                "rank_pos": 3,
                "played": 5,
                "avg_score": 8.4,
                "perfects": 1,
                "exacts": 2,
                "current_streak": 3,
                "max_streak": 4,
            }
        )

        self.assertIn("Alpha &lt;One&gt;", text)
        self.assertIn("Новичок &amp; лидер", text)
        self.assertIn("🏅 Очки: <b>42</b>", text)
        self.assertIn("🏆 Макс. серия: <b>4</b>", text)

    def test_format_leaderboard_entries_uses_medals_and_limit(self):
        text = format_leaderboard_entries(
            [
                {"name": "Alpha", "points": 20, "played": 2, "perfects": 1},
                {"name": "Beta", "points": 15, "played": 3, "perfects": 0},
                {"name": "Gamma", "points": 10, "played": 4, "perfects": 0},
            ],
            limit=2,
        )

        self.assertIn("🥇 <b>Alpha</b> — 🏅 20 • 🏓 2 • 🎯 1", text)
        self.assertIn("🥈 <b>Beta</b> — 🏅 15 • 🏓 3", text)
        self.assertNotIn("Gamma", text)

    def test_format_detailed_season_rows_wraps_score_tokens(self):
        blocks = format_detailed_season_rows(
            ["Cup 1", "Long Cup 2", "Cup 3"],
            [{"name": "Alpha", "scores": [10, 8, None], "total": 18}],
            max_line_length=20,
        )

        self.assertEqual(len(blocks), 1)
        self.assertIn("🥇 <b>Alpha</b> — <b>18</b>", blocks[0])
        self.assertIn("Cup 1: 10", blocks[0])
        self.assertIn("Long Cup 2: 8", blocks[0])
        self.assertIn("Cup 3: -", blocks[0])

    def test_split_text_chunks_breaks_large_sections(self):
        first = "A" * 3900
        second = "B" * 3900

        chunks = split_text_chunks(f"{first}\n\n{second}", limit=4000)

        self.assertEqual(chunks, [first, second])
