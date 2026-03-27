import unittest

from app.db.models import Player
from app.keyboards.inline import get_paginated_players_kb, is_player_active


class InlineKeyboardTests(unittest.TestCase):
    def test_is_player_active_treats_none_as_active(self):
        self.assertTrue(
            is_player_active(Player(id=1, full_name="Alpha", is_active=None))
        )
        self.assertTrue(
            is_player_active(Player(id=2, full_name="Beta", is_active=True))
        )
        self.assertFalse(
            is_player_active(Player(id=3, full_name="Gamma", is_active=False))
        )

    def test_get_paginated_players_kb_hides_inactive_players_by_default(self):
        keyboard = get_paginated_players_kb(
            players=[
                Player(id=1, full_name="Active", current_rating=100, is_active=True),
                Player(id=2, full_name="Archived", current_rating=200, is_active=False),
            ],
            action="add_player",
            tournament_id=10,
            show_back_to_menu=True,
        )

        texts = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("[100] Active", texts)
        self.assertNotIn("[200] Archived", texts)

    def test_get_paginated_players_kb_can_include_inactive_players(self):
        keyboard = get_paginated_players_kb(
            players=[
                Player(id=1, full_name="Active", current_rating=100, is_active=True),
                Player(id=2, full_name="Archived", current_rating=200, is_active=False),
            ],
            action="remove_player",
            tournament_id=10,
            show_back_to_menu=True,
            include_inactive=True,
        )

        texts = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("[100] Active", texts)
        self.assertIn("[200] Archived", texts)
