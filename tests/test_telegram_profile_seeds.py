from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from godmod.telegram_profile_seeds import (
    TelegramProfileSeedEntry,
    load_telegram_profile_seed_store,
    merge_telegram_profile_seed_entries,
    telegram_seed_url,
)


class TelegramProfileSeedStoreTests(unittest.TestCase):
    def test_load_seed_store_matches_service_aliases(self) -> None:
        payload = {
            "entries": [
                {
                    "city": "Салехард",
                    "service": "маникюр",
                    "service_aliases": ["ногтевой сервис", "nail master"],
                    "urls": ["https://t.me/loft_shd"],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "telegram_profile_seeds.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            store = load_telegram_profile_seed_store(path)

        self.assertEqual(store.urls_for("Салехард", "маникюр"), ["https://t.me/loft_shd"])
        self.assertEqual(store.urls_for("Салехард", "ногти"), ["https://t.me/loft_shd"])
        self.assertEqual(store.urls_for("Салехард", "nail master"), ["https://t.me/loft_shd"])
        self.assertEqual(store.urls_for("Ноябрьск", "маникюр"), [])

    def test_merge_seed_entries_deduplicates_urls_and_aliases(self) -> None:
        payload = {
            "entries": [
                {
                    "city": "Салехард",
                    "service": "маникюр",
                    "service_aliases": ["ногтевой сервис"],
                    "urls": ["https://t.me/loft_shd"],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "telegram_profile_seeds.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            store = merge_telegram_profile_seed_entries(
                path,
                [
                    TelegramProfileSeedEntry(
                        city="Салехард",
                        service="маникюр",
                        service_aliases=["Ногтевой сервис", "nail studio"],
                        urls=["https://t.me/loft_shd/", "https://t.me/cherry"],
                    )
                ],
            )

        self.assertEqual(len(store.entries), 1)
        self.assertEqual(store.entries[0].service_aliases, ["ногтевой сервис", "nail studio"])
        self.assertEqual(store.entries[0].urls, ["https://t.me/loft_shd", "https://t.me/cherry"])

    def test_telegram_seed_url_normalizes_handles_and_links(self) -> None:
        self.assertEqual(telegram_seed_url("@dobro_salehard"), "https://t.me/dobro_salehard")
        self.assertEqual(telegram_seed_url("https://t.me/dobro_salehard/"), "https://t.me/dobro_salehard")
        self.assertEqual(telegram_seed_url("t.me/dobro_salehard"), "https://t.me/dobro_salehard")
        self.assertIsNone(telegram_seed_url("not-a-telegram-contact"))

    def test_project_seed_file_contains_salehard_business_channels(self) -> None:
        store = load_telegram_profile_seed_store(Path("data/telegram_profile_seeds.json"))

        self.assertIn("https://t.me/edasalechard", store.urls_for("Салехард", "общепит"))
        self.assertIn("https://t.me/warim1994", store.urls_for("Салехард", "доставка еды"))
        self.assertIn("https://t.me/glazapolzettt", store.urls_for("Салехард", "маникюр"))


if __name__ == "__main__":
    unittest.main()
