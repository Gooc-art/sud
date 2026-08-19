from __future__ import annotations

from pathlib import Path
import unittest

from godmod.bot_callbacks import WizardAction
from godmod.bot_flow import apply_action, apply_manual_services_input, can_confirm
from godmod.bot_state import WizardState
from godmod.config import RuntimeConfig
from godmod.settings import AppSettings


class BotFlowReducerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = AppSettings(
            telegram_bot_token="bot-token",
            telegram_allowed_chat_ids=[],
            telegram_api_id=None,
            telegram_api_hash=None,
            telegram_user_session=None,
            vk_api_token=None,
            vk_service_token="vk-service",
            vk_community_token=None,
            vk_profile_seeds_path=None,
            google_places_api_key=None,
            runtime=RuntimeConfig(
                output_dir=Path("output"),
                cities=["Салехард", "Новый Уренгой"],
                popular_services=["маникюр", "ремонт"],
                period_options=[30, 60, 90, 0],
            ),
            use_mock_data=False,
        )
        self.state = WizardState(chat_id=1, user_id=2, top_n=20)

    def test_apply_action_moves_through_main_steps(self) -> None:
        apply_action(self.state, WizardAction(kind="city", value="салехард"), self.settings)
        self.assertEqual(self.state.step, "select_service")
        self.assertEqual(self.state.city, "Салехард")

        apply_action(self.state, WizardAction(kind="service", value="маникюр"), self.settings)
        self.assertEqual(self.state.step, "select_period")
        self.assertEqual(self.state.services, ["маникюр"])

        apply_action(self.state, WizardAction(kind="period", value="0"), self.settings)
        self.assertEqual(self.state.step, "select_mode")
        self.assertEqual(self.state.period_days, 0)

        apply_action(self.state, WizardAction(kind="mode", value="all"), self.settings)
        self.assertEqual(self.state.step, "confirm")
        self.assertTrue(can_confirm(self.state))

    def test_apply_category_action_filters_service_step_without_leaving_it(self) -> None:
        apply_action(self.state, WizardAction(kind="city", value="салехард"), self.settings)

        apply_action(self.state, WizardAction(kind="category", value="красота-и-уход"), self.settings)

        self.assertEqual(self.state.step, "select_service")
        self.assertEqual(self.state.service_category, "Красота и уход")

    def test_apply_category_services_selects_only_section_services(self) -> None:
        apply_action(self.state, WizardAction(kind="city", value="салехард"), self.settings)

        apply_action(self.state, WizardAction(kind="category", value="services:красота-и-уход"), self.settings)

        self.assertEqual(self.state.step, "select_period")
        self.assertEqual(self.state.service_category, "Красота и уход")
        self.assertEqual(self.state.services, ["маникюр"])
        self.assertIsNone(self.state.period_days)
        self.assertIsNone(self.state.report_mode)

    def test_apply_manual_services_input_moves_to_period(self) -> None:
        apply_action(self.state, WizardAction(kind="city", value="салехард"), self.settings)
        apply_action(self.state, WizardAction(kind="nav", value="manual"), self.settings)

        apply_manual_services_input(self.state, "маникюр, ремонт", self.settings)

        self.assertEqual(self.state.step, "select_period")
        self.assertEqual(self.state.services, ["маникюр", "ремонт"])

    def test_apply_nav_back_and_reset(self) -> None:
        apply_action(self.state, WizardAction(kind="city", value="салехард"), self.settings)
        apply_action(self.state, WizardAction(kind="category", value="красота-и-уход"), self.settings)
        apply_action(self.state, WizardAction(kind="service", value="маникюр"), self.settings)
        apply_action(self.state, WizardAction(kind="period", value="90"), self.settings)

        apply_action(self.state, WizardAction(kind="nav", value="back"), self.settings)
        self.assertEqual(self.state.step, "select_period")

        apply_action(self.state, WizardAction(kind="nav", value="back"), self.settings)
        self.assertEqual(self.state.step, "select_service")

        apply_action(self.state, WizardAction(kind="nav", value="reset"), self.settings)
        self.assertEqual(self.state.step, "select_city")
        self.assertIsNone(self.state.city)
        self.assertIsNone(self.state.service_category)

    def test_apply_edit_opens_requested_step(self) -> None:
        self.state.city = "Салехард"
        self.state.services = ["маникюр"]
        self.state.period_days = 60
        self.state.report_mode = "official_only"
        self.state.step = "done"

        apply_action(self.state, WizardAction(kind="edit", value="period"), self.settings)

        self.assertEqual(self.state.step, "select_period")
        self.assertEqual(self.state.period_days, 60)


if __name__ == "__main__":
    unittest.main()
