from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from godmod.rule_config import load_rule_config, merge_rule_config_alias_overrides


class RuleConfigTests(unittest.TestCase):
    def test_load_rule_config_reads_external_json(self) -> None:
        payload = {
            "commercial_markers": ["цена", "запись"],
            "exclusion_markers": ["личный блог"],
            "commercial_marker_groups": {"prices": ["цена"]},
            "service_alias_overrides": {"маникюр": ["ноготочки"]},
            "service_discovery_hint_overrides": {"маникюр": ["студия ногтей"]},
            "city_alias_overrides": {"Салехард": ["shd"]},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rules.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            config = load_rule_config(path)

        self.assertEqual(config.commercial_markers, ["цена", "запись"])
        self.assertEqual(config.exclusion_markers, ["личный блог"])
        self.assertEqual(config.commercial_marker_groups["prices"], ["цена"])
        self.assertEqual(config.service_alias_overrides["маникюр"], ["ноготочки"])
        self.assertEqual(config.service_discovery_hint_overrides["маникюр"], ["студия ногтей"])
        self.assertEqual(config.city_alias_overrides["Салехард"], ["shd"])

    def test_merge_rule_config_alias_overrides_appends_without_duplicates(self) -> None:
        payload = {
            "service_alias_overrides": {"маникюр": ["ноготочки"]},
            "service_discovery_hint_overrides": {"маникюр": ["студия ногтей"]},
            "city_alias_overrides": {"Салехард": ["shd"]},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rules.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            config = merge_rule_config_alias_overrides(
                path,
                service_alias_overrides={"маникюр": ["ноготочки", "nail zone"]},
                service_discovery_hint_overrides={"маникюр": ["студия ногтей", "мастер ногтей"]},
                city_alias_overrides={"Салехард": ["shd", "salehard89"]},
            )

        self.assertEqual(config.service_alias_overrides["маникюр"], ["ноготочки", "nail zone"])
        self.assertEqual(config.service_discovery_hint_overrides["маникюр"], ["студия ногтей", "мастер ногтей"])
        self.assertEqual(config.city_alias_overrides["Салехард"], ["shd", "salehard89"])


if __name__ == "__main__":
    unittest.main()
