from __future__ import annotations

import unittest

from godmod.bot import configured_platforms
from godmod.collectors.factory import ConfiguredCollector
from godmod.collectors.places import PlacesCollector
from godmod.collectors.telegram import TelegramCollector
from godmod.collectors.twogis import TwoGisCollector
from godmod.config import RuntimeConfig
from godmod.models import SearchRequest, SearchLogEntry, ServiceQuery
from godmod.settings import AppSettings


class _FailingCollector:
    def collect(self, request):
        raise RuntimeError("upstream unavailable")


class _StaticCollector:
    def __init__(self, payload, *, cache_stats=None, cache_ttls=None):
        self.payload = payload
        self.cache_stats = cache_stats or {}
        self.wall_cache_ttl_hours = (cache_ttls or {}).get("vk_wall_cache_ttl_hours", "")
        self.owner_cache_ttl_hours = (cache_ttls or {}).get("vk_owner_cache_ttl_hours", "")
        self.city_cache_ttl_hours = (cache_ttls or {}).get("vk_city_cache_ttl_hours", "")
        self.search_cache_ttl_hours = (cache_ttls or {}).get("twogis_search_cache_ttl_hours", "")

    def collect(self, request):
        return self.payload


class RuntimeIntegrationTests(unittest.TestCase):
    def test_configured_platforms_include_telegram_when_mtproto_ready(self) -> None:
        settings = AppSettings(
            telegram_bot_token="bot-token",
            telegram_allowed_chat_ids=[],
            telegram_api_id=123456,
            telegram_api_hash="hash",
            telegram_user_session="session",
            vk_api_token=None,
            vk_service_token="vk-service",
            vk_community_token=None,
            vk_profile_seeds_path=None,
            google_places_api_key=None,
            runtime=RuntimeConfig(),
            use_mock_data=False,
        )

        self.assertEqual(configured_platforms(settings), ["vk", "telegram"])

    def test_factory_returns_telegram_collector_when_ready(self) -> None:
        settings = AppSettings(
            telegram_bot_token="bot-token",
            telegram_allowed_chat_ids=[],
            telegram_api_id=123456,
            telegram_api_hash="hash",
            telegram_user_session="session",
            vk_api_token=None,
            vk_service_token="vk-service",
            vk_community_token=None,
            vk_profile_seeds_path=None,
            google_places_api_key=None,
            runtime=RuntimeConfig(),
            use_mock_data=False,
        )

        collector = ConfiguredCollector(settings)._collector_for_platform("telegram")

        self.assertIsInstance(collector, TelegramCollector)

    def test_factory_skips_platform_failure_and_keeps_other_results(self) -> None:
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
            runtime=RuntimeConfig(),
            use_mock_data=False,
        )

        class CollectorUnderTest(ConfiguredCollector):
            def _collector_for_platform(self, platform: str):
                if platform == "vk":
                    return _FailingCollector()
                if platform == "telegram":
                    return _StaticCollector(
                        (
                            ["telegram-account"],
                            [SearchLogEntry(city="Салехард", service="маникюр", platform="telegram", query="маникюр Салехард")],
                        ),
                        cache_stats={"wall_hits": 2},
                        cache_ttls={"vk_wall_cache_ttl_hours": 24},
                    )
                return None

        collector = CollectorUnderTest(settings)
        candidates, search_log = collector.collect(
            SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="маникюр")],
                period_days=30,
                platforms=["vk", "telegram"],
                top_n=10,
            )
        )

        self.assertEqual(candidates, ["telegram-account"])
        self.assertEqual(len(search_log), 2)
        self.assertEqual(search_log[0].platform, "vk")
        self.assertEqual(search_log[0].source, "vk.collector.error")
        self.assertEqual(search_log[0].details, "upstream unavailable")
        self.assertEqual(search_log[1].platform, "telegram")
        self.assertEqual(collector.platform_failures, [{"platform": "vk", "error": "upstream unavailable"}])
        self.assertEqual(collector.cache_stats, {"wall_hits": 2})
        self.assertEqual(
            collector.platform_metrics,
            [
                {
                    "platform": "vk",
                    "duration_seconds": collector.platform_metrics[0]["duration_seconds"],
                    "candidates": 0,
                    "search_log": 0,
                    "failed": True,
                },
                {
                    "platform": "telegram",
                    "duration_seconds": collector.platform_metrics[1]["duration_seconds"],
                    "candidates": 1,
                    "search_log": 1,
                    "failed": False,
                },
            ],
        )
        self.assertEqual(collector.cache_ttls["vk_wall_cache_ttl_hours"], 24)

    def test_factory_returns_empty_result_when_all_platforms_fail(self) -> None:
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
            runtime=RuntimeConfig(),
            use_mock_data=False,
        )

        class CollectorUnderTest(ConfiguredCollector):
            def _collector_for_platform(self, platform: str):
                return _FailingCollector()

        collector = CollectorUnderTest(settings)
        candidates, search_log = collector.collect(
            SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="маникюр")],
                period_days=30,
                platforms=["vk"],
                top_n=10,
            )
        )

        self.assertEqual(candidates, [])
        self.assertEqual(len(search_log), 1)
        self.assertEqual(search_log[0].platform, "vk")
        self.assertEqual(search_log[0].source, "vk.collector.error")
        self.assertEqual(search_log[0].details, "upstream unavailable")
        self.assertEqual(collector.platform_failures, [{"platform": "vk", "error": "upstream unavailable"}])

    def test_configured_platforms_include_places_when_google_key_is_present(self) -> None:
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
            google_places_api_key="google-key",
            runtime=RuntimeConfig(),
            use_mock_data=False,
        )

        self.assertEqual(configured_platforms(settings), ["vk", "places"])

    def test_factory_returns_places_collector_when_google_key_is_present(self) -> None:
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
            google_places_api_key="google-key",
            runtime=RuntimeConfig(),
            use_mock_data=False,
        )

        collector = ConfiguredCollector(settings)._collector_for_platform("places")

        self.assertIsInstance(collector, PlacesCollector)

    def test_configured_platforms_include_2gis_when_key_is_present(self) -> None:
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
            runtime=RuntimeConfig(),
            use_mock_data=False,
            twogis_api_key="twogis-key",
        )

        self.assertEqual(configured_platforms(settings), ["vk", "2gis"])

    def test_configured_platforms_include_all_ready_apis_for_any_service(self) -> None:
        settings = AppSettings(
            telegram_bot_token="bot-token",
            telegram_allowed_chat_ids=[],
            telegram_api_id=123456,
            telegram_api_hash="hash",
            telegram_user_session="session",
            vk_api_token="vk-user",
            vk_service_token="vk-service",
            vk_community_token=None,
            vk_profile_seeds_path=None,
            google_places_api_key="google-key",
            runtime=RuntimeConfig(),
            use_mock_data=False,
            twogis_api_key="twogis-key",
        )

        self.assertEqual(configured_platforms(settings), ["vk", "telegram", "places", "2gis"])

    def test_factory_returns_2gis_collector_when_key_is_present(self) -> None:
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
            runtime=RuntimeConfig(),
            use_mock_data=False,
            twogis_api_key="twogis-key",
        )

        collector = ConfiguredCollector(settings)._collector_for_platform("2gis")

        self.assertIsInstance(collector, TwoGisCollector)
        self.assertEqual(collector.search_cache_ttl_hours, 6)


if __name__ == "__main__":
    unittest.main()
