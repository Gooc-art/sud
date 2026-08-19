from __future__ import annotations

import unittest

from godmod.collectors.places import PlacesCollector
from godmod.models import SearchRequest, ServiceQuery


class FakeGooglePlacesApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], str]] = []

    def search_text_with_retry(self, payload: dict[str, object], *, field_mask: str):
        self.calls.append((payload, field_mask))
        return {
            "places": [
                {
                    "id": "place-1",
                    "displayName": {"text": "Nails Studio Салехард", "languageCode": "ru"},
                    "formattedAddress": "ул. Ленина, 10, Салехард, ЯНАО, Россия",
                    "businessStatus": "OPERATIONAL",
                    "googleMapsUri": "https://maps.google.com/?cid=123",
                    "location": {"latitude": 66.53, "longitude": 66.61},
                    "internationalPhoneNumber": "+7 900 000-00-00",
                    "websiteUri": "https://nails.example.com",
                    "primaryType": "beauty_salon",
                    "primaryTypeDisplayName": {"text": "Салон красоты", "languageCode": "ru"},
                    "rating": 4.7,
                    "userRatingCount": 128,
                    "priceLevel": "PRICE_LEVEL_MODERATE",
                    "regularOpeningHours": {
                        "openNow": True,
                        "weekdayDescriptions": ["пн-пт: 10:00-20:00"],
                    },
                    "types": ["beauty_salon", "establishment"],
                }
            ]
        }


class PlacesCollectorTests(unittest.TestCase):
    def test_collect_builds_candidates_from_google_places_text_search(self) -> None:
        api_client = FakeGooglePlacesApiClient()
        collector = PlacesCollector(api_client=api_client)
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр", markers=["запись"])],
            period_days=90,
            platforms=["places"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertEqual(len(search_log), 7)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(api_client.calls[0][0]["languageCode"], "ru")
        self.assertEqual(api_client.calls[0][0]["regionCode"], "RU")
        self.assertEqual(api_client.calls[0][0]["pageSize"], 10)
        candidate = candidates[0]
        self.assertEqual(candidate.platform, "places")
        self.assertEqual(candidate.account_name, "Nails Studio Салехард")
        self.assertEqual(candidate.account_url, "https://maps.google.com/?cid=123")
        self.assertEqual(candidate.username_or_id, "place-1")
        self.assertEqual(candidate.geo_coordinates, "66.53, 66.61")
        self.assertEqual(candidate.business_categories, "Салон красоты, beauty_salon, establishment")
        self.assertEqual(candidate.rating_details, "4.7 (128 отзывов)")
        self.assertEqual(candidate.working_hours, "открыто сейчас; пн-пт: 10:00-20:00")
        self.assertEqual(candidate.price_details, "средний чек")
        self.assertEqual(candidate.api_address, "ул. Ленина, 10, Салехард, ЯНАО, Россия")
        self.assertTrue(candidate.description.startswith("Карточка Google Places."))
        self.assertIn("Адрес: ул. Ленина, 10", candidate.description)
        self.assertIn("Рейтинг: 4.7 (128 отзывов)", candidate.description)
        self.assertIn("Часы: открыто сейчас; пн-пт: 10:00-20:00", candidate.description)
        self.assertIn("Координаты: 66.53, 66.61", candidate.description)
        self.assertIn("Телефон: +7 900 000-00-00", candidate.description)
        self.assertIn("Сайт: https://nails.example.com", candidate.description)
        self.assertIn("Цены: средний чек", candidate.description)
        self.assertIn("+7 900 000-00-00", candidate.contacts["phone"])

    def test_collect_skips_when_places_platform_is_not_requested(self) -> None:
        collector = PlacesCollector(api_client=FakeGooglePlacesApiClient())
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertEqual(candidates, [])
        self.assertEqual(search_log, [])


if __name__ == "__main__":
    unittest.main()
