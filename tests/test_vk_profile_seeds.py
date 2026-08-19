from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from godmod.vk_profile_seeds import VkProfileSeedEntry, load_vk_profile_seed_store, merge_vk_profile_seed_entries


class VkProfileSeedStoreTests(unittest.TestCase):
    def test_load_seed_store_matches_service_aliases(self) -> None:
        payload = {
            "entries": [
                {
                    "city": "Салехард",
                    "service": "маникюр",
                    "service_aliases": ["ногтевой сервис", "nail master"],
                    "urls": ["https://vk.com/loft_shd"],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vk_profile_seeds.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            store = load_vk_profile_seed_store(path)

        self.assertEqual(store.urls_for("Салехард", "маникюр"), ["https://vk.com/loft_shd"])
        self.assertEqual(store.urls_for("Салехард", "ногти"), ["https://vk.com/loft_shd"])
        self.assertEqual(store.urls_for("Салехард", "ногтевой сервис"), ["https://vk.com/loft_shd"])
        self.assertEqual(store.urls_for("Салехард", "nail master"), ["https://vk.com/loft_shd"])
        self.assertEqual(store.urls_for("Ноябрьск", "маникюр"), [])

    def test_merge_seed_entries_deduplicates_urls_and_aliases(self) -> None:
        payload = {
            "entries": [
                {
                    "city": "Салехард",
                    "service": "маникюр",
                    "service_aliases": ["ногтевой сервис"],
                    "urls": ["https://vk.com/loft_shd"],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vk_profile_seeds.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            store = merge_vk_profile_seed_entries(
                path,
                [
                    VkProfileSeedEntry(
                        city="Салехард",
                        service="маникюр",
                        service_aliases=["Ногтевой сервис", "nail studio"],
                        urls=["https://vk.ru/loft_shd/", "https://m.vk.com/cherry"],
                    )
                ],
            )

        self.assertEqual(len(store.entries), 1)
        self.assertEqual(store.entries[0].service_aliases, ["ногтевой сервис", "nail studio"])
        self.assertEqual(store.entries[0].urls, ["https://vk.com/loft_shd", "https://vk.com/cherry"])

    def test_project_seed_file_contains_salehard_lashes_and_barbershops(self) -> None:
        store = load_vk_profile_seed_store("data/vk_profile_seeds.json")

        self.assertIn("https://vk.com/mari.beauty_studio", store.urls_for("Салехард", "ресницы"))
        self.assertIn("https://vk.com/oldboy.salekhard", store.urls_for("Салехард", "барбершоп"))
        self.assertIn("https://vk.com/neft_barber_shd", store.urls_for("Салехард", "барбер"))


if __name__ == "__main__":
    unittest.main()
