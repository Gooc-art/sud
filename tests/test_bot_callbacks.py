from __future__ import annotations

import unittest

from godmod.bot_callbacks import (
    build_category_callback,
    build_city_callback,
    build_edit_callback,
    build_mode_callback,
    build_nav_callback,
    build_period_callback,
    build_service_callback,
    parse_wizard_callback,
)


class BotCallbackTests(unittest.TestCase):
    def test_build_and_parse_city_callback(self) -> None:
        data = build_city_callback("Салехард")
        action = parse_wizard_callback(data)

        self.assertEqual(data, "wiz:v1:city:салехард")
        self.assertIsNotNone(action)
        self.assertEqual(action.kind, "city")
        self.assertEqual(action.value, "салехард")

    def test_build_and_parse_other_callback_types(self) -> None:
        self.assertEqual(parse_wizard_callback(build_category_callback("Красота и уход")).kind, "category")
        self.assertEqual(parse_wizard_callback(build_service_callback("маникюр")).kind, "service")
        self.assertEqual(parse_wizard_callback(build_period_callback(90)).value, "90")
        self.assertEqual(parse_wizard_callback(build_mode_callback("official_only")).kind, "mode")
        self.assertEqual(parse_wizard_callback(build_nav_callback("confirm")).kind, "nav")
        self.assertEqual(parse_wizard_callback(build_edit_callback("period")).kind, "edit")

    def test_parse_wizard_callback_rejects_unknown_payload(self) -> None:
        self.assertIsNone(parse_wizard_callback("period:3"))
        self.assertIsNone(parse_wizard_callback("wiz:v1:unknown:value"))
        self.assertIsNone(parse_wizard_callback("wiz:v1:city:"))


if __name__ == "__main__":
    unittest.main()
