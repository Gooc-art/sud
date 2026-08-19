from __future__ import annotations

from pathlib import Path
import unittest

from godmod.bot_render import render_wizard
from godmod.bot_state import WizardState
from godmod.config import RuntimeConfig
from godmod.settings import AppSettings


class BotRenderTests(unittest.TestCase):
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

    def test_render_select_city_contains_semantic_callbacks(self) -> None:
        text, markup = render_wizard(WizardState(chat_id=1, user_id=2, top_n=20), self.settings)

        self.assertIn("Шаг 1 из 5", text)
        self.assertIn("Текущий выбор:", text)
        self.assertEqual(markup["inline_keyboard"][0][0]["callback_data"], "wiz:v1:city:салехард")

    def test_default_max_catalog_contains_restored_cities_and_spheres(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output")),
            use_mock_data=False,
        )

        _, city_markup = render_wizard(WizardState(chat_id=1, user_id=2, top_n=20), settings)
        city_buttons = [button["text"] for row in city_markup["inline_keyboard"] for button in row]
        self.assertIn("Тарко-Сале", city_buttons)
        self.assertIn("Красноселькуп", city_buttons)

        _, service_markup = render_wizard(
            WizardState(chat_id=1, user_id=2, step="select_service", city="Салехард", top_n=20),
            settings,
        )
        service_buttons = [button["text"] for row in service_markup["inline_keyboard"] for button in row]
        self.assertIn("Красота и уход", service_buttons)
        self.assertIn("Общепит", service_buttons)

    def test_render_select_service_mentions_sections_and_keeps_all_services_button(self) -> None:
        state = WizardState(chat_id=1, user_id=2, step="select_service", city="Салехард", top_n=20)

        text, markup = render_wizard(state, self.settings)

        self.assertIn("Каталог сгруппирован по темам", text)
        self.assertIn("Красота и уход", text)
        self.assertEqual(markup["inline_keyboard"][0][0]["text"], "Все сферы деятельности")

    def test_render_select_service_shows_selected_category_services(self) -> None:
        state = WizardState(
            chat_id=1,
            user_id=2,
            step="select_service",
            city="Салехард",
            service_category="Красота и уход",
            top_n=20,
        )

        text, markup = render_wizard(state, self.settings)

        self.assertIn("Открытый раздел: Красота и уход", text)
        self.assertEqual(markup["inline_keyboard"][1][0]["callback_data"], "wiz:v1:category:красота-и-уход")
        buttons = [button["text"] for row in markup["inline_keyboard"] for button in row]
        callbacks = [button["callback_data"] for row in markup["inline_keyboard"] for button in row]
        self.assertIn("Все услуги раздела", buttons)
        self.assertIn("wiz:v1:category:services:красота-и-уход", callbacks)
        self.assertIn("Маникюр", buttons)
        self.assertIn("Показать все разделы", buttons)

    def test_render_summary_labels_selected_category_services(self) -> None:
        state = WizardState(
            chat_id=1,
            user_id=2,
            step="select_period",
            city="Салехард",
            service_category="Красота и уход",
            services=["маникюр"],
            top_n=20,
        )

        text, _ = render_wizard(state, self.settings)

        self.assertIn("Сфера: Красота и уход: все услуги раздела", text)

    def test_render_confirm_contains_summary_and_confirm_button(self) -> None:
        state = WizardState(
            chat_id=1,
            user_id=2,
            step="confirm",
            city="Салехард",
            services=["маникюр"],
            period_days=0,
            report_mode="all",
            top_n=20,
        )

        text, markup = render_wizard(state, self.settings)

        self.assertIn("Шаг 5 из 5", text)
        self.assertIn("Период: За всё время", text)
        self.assertIn("XLSX, PDF", text)
        self.assertEqual(markup["inline_keyboard"][0][0]["callback_data"], "wiz:v1:nav:confirm")

    def test_render_running_returns_message_without_keyboard(self) -> None:
        state = WizardState(
            chat_id=1,
            user_id=2,
            step="running",
            city="Салехард",
            services=["маникюр"],
            period_days=90,
            report_mode="all",
        )

        text, markup = render_wizard(state, self.settings)

        self.assertIn("Идёт сборка отчёта", text)
        self.assertIn("Ищу профили и business-card карточки", text)
        self.assertIsNone(markup)


if __name__ == "__main__":
    unittest.main()
