from __future__ import annotations

import unittest

from godmod.bot_ui import (
    build_city_keyboard,
    build_force_reply,
    build_main_menu_keyboard,
    build_period_keyboard,
    build_report_mode_keyboard,
    build_service_keyboard,
    parse_city_callback,
    parse_period_callback,
    parse_report_mode_callback,
    parse_service_callback,
)
from godmod.bot_commands import parse_command
from godmod.request_options import ALL_SERVICES_LABEL


class BotUiTests(unittest.TestCase):
    def test_build_city_keyboard_contains_buttons(self) -> None:
        keyboard = build_city_keyboard(["Салехард", "Новый Уренгой", "Ноябрьск"], columns=2)
        self.assertIn("inline_keyboard", keyboard)
        self.assertEqual(keyboard["inline_keyboard"][0][0]["text"], "Салехард")
        self.assertEqual(keyboard["inline_keyboard"][0][0]["callback_data"], "city:0")

    def test_parse_city_callback_returns_city(self) -> None:
        city = parse_city_callback("city:1", ["Салехард", "Новый Уренгой", "Ноябрьск"])
        self.assertEqual(city, "Новый Уренгой")

    def test_parse_city_callback_rejects_invalid_data(self) -> None:
        city = parse_city_callback("noop:1", ["Салехард"])
        self.assertIsNone(city)

    def test_parse_cities_and_cancel_commands(self) -> None:
        self.assertEqual(parse_command("/cities").name, "cities")
        self.assertEqual(parse_command("/cancel").name, "cancel")

    def test_build_main_menu_keyboard_contains_start_button(self) -> None:
        keyboard = build_main_menu_keyboard()
        self.assertEqual(keyboard["keyboard"][0][0]["text"], "Старт")
        self.assertEqual(keyboard["keyboard"][0][1]["text"], "Города")
        self.assertEqual(keyboard["keyboard"][1][0]["text"], "Помощь")
        self.assertEqual(keyboard["keyboard"][1][1]["text"], "Сброс")
        labels = {button["text"] for row in keyboard["keyboard"] for button in row}
        self.assertNotIn("Выгрузка по коммерции", labels)
        self.assertNotIn("Выгрузка по судам", labels)

    def test_build_service_keyboard_contains_buttons(self) -> None:
        keyboard = build_service_keyboard(["маникюр", "ремонт", "фотограф"], columns=2)
        self.assertEqual(keyboard["inline_keyboard"][0][0]["text"], ALL_SERVICES_LABEL)
        self.assertEqual(keyboard["inline_keyboard"][1][0]["text"], "Маникюр")
        self.assertEqual(keyboard["inline_keyboard"][1][0]["callback_data"], "service:0")
        self.assertEqual(keyboard["inline_keyboard"][-2][0]["callback_data"], "service:manual")
        self.assertEqual(keyboard["inline_keyboard"][-1][0]["callback_data"], "flow:cities")

    def test_build_service_keyboard_uses_single_column_for_long_labels(self) -> None:
        keyboard = build_service_keyboard(["автоэлектрик", "грузоперевозки"], columns=2)
        self.assertEqual(len(keyboard["inline_keyboard"][1]), 1)
        self.assertEqual(keyboard["inline_keyboard"][1][0]["text"], "Автоэлектрик")

    def test_build_period_keyboard_contains_periods_and_flows(self) -> None:
        keyboard = build_period_keyboard([30, 60, 90, 0], columns=3)
        self.assertEqual(keyboard["inline_keyboard"][0][0]["text"], "30 дней")
        self.assertEqual(keyboard["inline_keyboard"][0][0]["callback_data"], "period:0")
        self.assertEqual(keyboard["inline_keyboard"][1][0]["text"], "За всё время")
        self.assertEqual(keyboard["inline_keyboard"][1][0]["callback_data"], "period:3")
        self.assertEqual(keyboard["inline_keyboard"][-2][0]["callback_data"], "flow:services")
        self.assertEqual(keyboard["inline_keyboard"][-1][0]["callback_data"], "flow:cities")

    def test_build_report_mode_keyboard_contains_modes(self) -> None:
        keyboard = build_report_mode_keyboard()
        self.assertEqual(keyboard["inline_keyboard"][0][0]["callback_data"], "mode:all")
        self.assertEqual(keyboard["inline_keyboard"][0][1]["callback_data"], "mode:official_only")
        self.assertEqual(keyboard["inline_keyboard"][1][0]["callback_data"], "flow:period")

    def test_build_force_reply_contains_placeholder(self) -> None:
        reply_markup = build_force_reply()
        self.assertTrue(reply_markup["force_reply"])
        self.assertIn("Введите услуги", reply_markup["input_field_placeholder"])

    def test_parse_service_callback_returns_service(self) -> None:
        service = parse_service_callback("service:1", ["маникюр", "ремонт", "фотограф"])
        self.assertEqual(service, "ремонт")

    def test_parse_service_callback_returns_all_services_label(self) -> None:
        service = parse_service_callback("service:all", ["маникюр", "ремонт", "фотограф"])
        self.assertEqual(service, ALL_SERVICES_LABEL)

    def test_parse_period_callback_returns_period(self) -> None:
        period = parse_period_callback("period:3", [30, 60, 90, 0])
        self.assertEqual(period, 0)

    def test_parse_report_mode_callback_returns_mode(self) -> None:
        self.assertEqual(parse_report_mode_callback("mode:official_only"), "official_only")
        self.assertEqual(parse_report_mode_callback("mode:all"), "all")
        self.assertIsNone(parse_report_mode_callback("mode:unknown"))

    def test_parse_plain_start_button_text(self) -> None:
        command = parse_command("Старт")
        assert command is not None
        self.assertEqual(command.name, "start")

    def test_parse_plain_menu_button_texts(self) -> None:
        self.assertEqual(parse_command("Города").name, "cities")
        self.assertEqual(parse_command("Помощь").name, "help")
        self.assertEqual(parse_command("Сброс").name, "cancel")


if __name__ == "__main__":
    unittest.main()
