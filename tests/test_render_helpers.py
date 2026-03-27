import unittest
from types import SimpleNamespace

from app.db.models import TournamentStatus
from app.handlers.render_helpers import (
    build_forecast_card_text,
    build_history_details_text,
    get_forecast_view_flags,
)


class RenderHelpersTests(unittest.TestCase):
    def test_build_forecast_card_text_formats_and_escapes_values(self):
        players_map = {
            1: SimpleNamespace(full_name="A & B", current_rating=1200),
            2: SimpleNamespace(full_name="C <D>", current_rating=None),
            3: SimpleNamespace(full_name="E", current_rating=999),
        }

        text = build_forecast_card_text(
            tournament_name="Cup <Final>",
            tournament_date_str="01.02.2026",
            player_ids=[1, 2, 3, 99],
            players_map=players_map,
            escape_html=True,
        )

        self.assertIn("Cup &lt;Final&gt;", text)
        self.assertIn("🥇 A &amp; B (1200)", text)
        self.assertIn("🥈 C &lt;D&gt;", text)
        self.assertIn("🥉 E (999)", text)
        self.assertIn("4. Неизвестный игрок", text)

    def test_get_forecast_view_flags_respects_status_and_admin(self):
        allow_edit, is_admin, show_others = get_forecast_view_flags(
            tournament_status=TournamentStatus.OPEN,
            user_id=10,
            admin_ids={99},
        )
        self.assertTrue(allow_edit)
        self.assertFalse(is_admin)
        self.assertFalse(show_others)

        allow_edit, is_admin, show_others = get_forecast_view_flags(
            tournament_status=TournamentStatus.OPEN,
            user_id=99,
            admin_ids={99},
        )
        self.assertTrue(allow_edit)
        self.assertTrue(is_admin)
        self.assertTrue(show_others)

        allow_edit, is_admin, show_others = get_forecast_view_flags(
            tournament_status=TournamentStatus.FINISHED,
            user_id=10,
            admin_ids={99},
        )
        self.assertFalse(allow_edit)
        self.assertFalse(is_admin)
        self.assertTrue(show_others)

    def test_build_history_details_text_formats_hits_and_bonus(self):
        players_map = {
            10: SimpleNamespace(full_name="Winner <One>"),
            20: SimpleNamespace(full_name="Runner & Up"),
        }

        text = build_history_details_text(
            tournament_name="Final & Cup",
            tournament_date_str="02.03.2026",
            pred_ids=[10, 20],
            results={"10": 1, "20": 2},
            players_map=players_map,
            points_earned=25,
        )

        self.assertIn("Final &amp; Cup", text)
        self.assertIn("Winner &lt;One&gt;", text)
        self.assertIn("Runner &amp; Up", text)
        self.assertIn("(🎯 Точно!)", text)
        self.assertIn("БОНУС: +15 очков за идеальный прогноз", text)
        self.assertIn("<b>💰 Итого очков:</b> 25", text)
