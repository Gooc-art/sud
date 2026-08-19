from __future__ import annotations

import unittest

from godmod.bot_state import WIZARD_STATES, ensure_wizard_state, get_wizard_state, reset_wizard_state


class BotStateTests(unittest.TestCase):
    def setUp(self) -> None:
        WIZARD_STATES.clear()

    def tearDown(self) -> None:
        WIZARD_STATES.clear()

    def test_ensure_wizard_state_uses_chat_and_user_pair(self) -> None:
        state_one = ensure_wizard_state(1, 10, default_top_n=20)
        state_two = ensure_wizard_state(1, 11, default_top_n=20)

        self.assertIsNot(state_one, state_two)
        self.assertIs(get_wizard_state(1, 10), state_one)
        self.assertIs(get_wizard_state(1, 11), state_two)

    def test_reset_wizard_state_clears_selection_but_keeps_message_binding(self) -> None:
        state = ensure_wizard_state(1, 10, default_top_n=20, wizard_message_id=77)
        state.step = "confirm"
        state.city = "Салехард"
        state.service_category = "Красота и уход"
        state.services = ["маникюр"]
        state.period_days = 90
        state.report_mode = "all"

        reset_wizard_state(state)

        self.assertEqual(state.step, "select_city")
        self.assertIsNone(state.city)
        self.assertIsNone(state.service_category)
        self.assertEqual(state.services, [])
        self.assertIsNone(state.period_days)
        self.assertIsNone(state.report_mode)
        self.assertEqual(state.wizard_message_id, 77)


if __name__ == "__main__":
    unittest.main()
