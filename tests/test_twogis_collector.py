from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from godmod.collectors.twogis import TwoGisCollector
from godmod.models import SearchRequest, ServiceQuery
from godmod.twogis_cache import TwoGisDiskCache


class FakeTwoGisApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], str]] = []

    def search_items_with_retry(self, params: dict[str, object], *, fields: str):
        self.calls.append((params, fields))
        return {
            "meta": {"code": 200},
            "result": {
                "items": [
                    {
                        "id": "141265769336625_test",
                        "type": "branch",
                        "name": "Nail Loft Новый Уренгой",
                        "point": {"lon": 76.6784, "lat": 66.0839},
                        "adm_div": [{"name": "Новый Уренгой", "type": "city"}],
                        "full_address_name": "Новый Уренгой, Ленинградский проспект, 5",
                        "address_name": "Ленинградский проспект, 5",
                        "rubrics": [{"name": "Ногтевые студии"}],
                        "reviews": {"general_rating": "4.8", "review_count": "14"},
                        "flags": {"has_avg_bill": True},
                        "attribute_groups": [
                            {
                                "name": "Food Service",
                                "attributes": [
                                    {"tag": "food_service_avg_price", "name": "Средний чек", "value": "1 500 ₽"}
                                ],
                            }
                        ],
                        "schedule": {"description": "ежедневно, 10:00-20:00"},
                        "itin": "8904012345",
                        "trade_license": "TL-89-001",
                        "employees_org_count": 12,
                        "fias_code": "fias-123",
                        "fns_code": "fns-89",
                        "okato": "71176000000",
                        "oktmo": "71951000001",
                        "contact_groups": [
                            {
                                "contacts": [
                                    {"type": "phone", "value": "+7 900 123-45-67"},
                                    {"type": "site", "url": "https://nail-loft.example.com"},
                                    {"type": "telegram", "value": "@nail_loft_nur"},
                                ]
                            }
                        ],
                    }
                ]
            },
        }


class TwoGisCollectorTests(unittest.TestCase):
    def test_collect_builds_candidates_from_2gis_places_api(self) -> None:
        api_client = FakeTwoGisApiClient()
        collector = TwoGisCollector(api_client=api_client)
        request = SearchRequest(
            cities=["Новый Уренгой"],
            services=[ServiceQuery(name="маникюр", markers=["запись"])],
            period_days=90,
            platforms=["2gis"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertTrue(search_log)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(api_client.calls[0][0]["locale"], "ru_RU")
        self.assertEqual(api_client.calls[0][0]["type"], "branch")
        self.assertEqual(api_client.calls[0][0]["page_size"], 10)
        candidate = candidates[0]
        self.assertEqual(candidate.platform, "2gis")
        self.assertEqual(candidate.account_name, "Nail Loft Новый Уренгой")
        self.assertEqual(candidate.api_city, "Новый Уренгой")
        self.assertEqual(candidate.api_address, "Новый Уренгой, Ленинградский проспект, 5")
        self.assertEqual(candidate.geo_coordinates, "76.6784, 66.0839")
        self.assertEqual(candidate.business_categories, "Ногтевые студии")
        self.assertEqual(candidate.rating_details, "4.8 (14 отзывов)")
        self.assertEqual(candidate.working_hours, "ежедневно, 10:00-20:00")
        self.assertTrue(candidate.description.startswith("Карточка 2GIS."))
        self.assertIn("Рейтинг: 4.8 (14 отзывов).", candidate.description)
        self.assertIn("График: ежедневно, 10:00-20:00.", candidate.description)
        self.assertIn("Цены: есть данные по среднему чеку; Средний чек: 1 500 ₽.", candidate.description)
        self.assertIn("Реквизиты: ИНН: 8904012345; Лицензия: TL-89-001.", candidate.description)
        self.assertIn("Служебные поля: ФИАС: fias-123; ФНС: fns-89; ОКАТО: 71176000000; ОКТМО: 71951000001.", candidate.description)
        self.assertIn("Сотрудников: 12.", candidate.description)
        self.assertIn("+7 900 123-45-67", candidate.contacts["phone"])
        self.assertIn("https://nail-loft.example.com", candidate.contacts["website"])
        self.assertIn("@nail_loft_nur", candidate.contacts["telegram"])
        self.assertEqual(candidate.price_details, "есть данные по среднему чеку; Средний чек: 1 500 ₽")
        self.assertEqual(candidate.official_requisites, "ИНН: 8904012345; Лицензия: TL-89-001")
        self.assertEqual(candidate.service_fields, "ФИАС: fias-123; ФНС: fns-89; ОКАТО: 71176000000; ОКТМО: 71951000001")
        self.assertEqual(candidate.employee_count, 12)

    def test_collect_skips_when_2gis_platform_is_not_requested(self) -> None:
        collector = TwoGisCollector(api_client=FakeTwoGisApiClient())
        request = SearchRequest(
            cities=["Новый Уренгой"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertEqual(candidates, [])
        self.assertEqual(search_log, [])

    def test_collect_clamps_page_size_to_api_limit(self) -> None:
        api_client = FakeTwoGisApiClient()
        collector = TwoGisCollector(api_client=api_client, page_size=25)
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="кофейня")],
            period_days=0,
            platforms=["2gis"],
            top_n=10,
        )

        collector.collect(request)

        self.assertEqual(api_client.calls[0][0]["page_size"], 10)

    def test_collect_reuses_cached_search_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "2gis-cache"
            api_client_first = FakeTwoGisApiClient()
            collector_first = TwoGisCollector(api_client=api_client_first, cache_dir=cache_dir)
            request = SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="кофейня")],
                period_days=0,
                platforms=["2gis"],
                top_n=10,
            )

            collector_first.collect(request)

            api_client_second = FakeTwoGisApiClient()
            collector_second = TwoGisCollector(api_client=api_client_second, cache_dir=cache_dir)
            candidates, _search_log = collector_second.collect(request)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(api_client_second.calls, [])
        self.assertGreater(collector_second.cache_stats["twogis_search_hits"], 0)

    def test_stale_search_cache_triggers_refetch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "2gis-cache"
            disk_cache = TwoGisDiskCache(cache_dir)
            params = {
                "q": "кофейня Салехард",
                "locale": "ru_RU",
                "type": "branch",
                "page_size": 10,
            }
            disk_cache.set_search_payload(
                params,
                {"meta": {"code": 200}, "result": {"items": []}},
                fields="items.address",
                cached_at=datetime.now(UTC) - timedelta(hours=10),
            )

            api_client = FakeTwoGisApiClient()
            collector = TwoGisCollector(
                api_client=api_client,
                cache_dir=cache_dir,
                fields="items.address",
                search_cache_ttl_hours=1,
            )
            request = SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="кофейня")],
                period_days=0,
                platforms=["2gis"],
                top_n=10,
            )

            collector.collect(request)

        self.assertGreater(len(api_client.calls), 0)
        self.assertEqual(api_client.calls[0][0]["q"], "кофейня Салехард")
        self.assertGreater(collector.cache_stats["twogis_search_misses"], 0)


if __name__ == "__main__":
    unittest.main()
