from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from godmod.models import AccountCandidate, PostRecord
from godmod.scoring import score_candidate, score_candidates


class ScoringTests(unittest.TestCase):
    def test_commercial_account_scores_higher_than_personal_page(self) -> None:
        now = datetime.now(UTC)
        commercial = AccountCandidate(
            service="маникюр",
            city="Салехард",
            platform="vk",
            account_name="Маникюр Салехард",
            account_url="https://vk.com/salehard-nails",
            username_or_id="salehard-nails",
            description="Маникюр, прайс, запись в лс, отзывы клиентов",
            followers=500,
            posts=[
                PostRecord(
                    url="https://vk.com/salehard-nails/1",
                    text="Свободные окна, цена от 2300, запись в лс",
                    published_at=now - timedelta(days=2),
                    likes=20,
                    comments=5,
                    reposts=1,
                    views=300,
                )
            ],
        )
        personal = AccountCandidate(
            service="маникюр",
            city="Салехард",
            platform="vk",
            account_name="Личный блог",
            account_url="https://vk.com/blog",
            username_or_id="blog",
            description="Личная страница",
            followers=500,
            posts=[
                PostRecord(
                    url="https://vk.com/blog/1",
                    text="Сегодня гуляла по городу",
                    published_at=now - timedelta(days=2),
                    likes=2,
                    comments=0,
                    reposts=0,
                    views=20,
                )
            ],
        )
        commercial_rank = score_candidate(
            commercial,
            period_days=30,
            cities=["Салехард"],
            extra_markers=[],
            now=now,
        )
        personal_rank = score_candidate(
            personal,
            period_days=30,
            cities=["Салехард"],
            extra_markers=[],
            now=now,
        )
        self.assertGreater(commercial_rank.score.total, personal_rank.score.total)

    def test_abandoned_account_stays_in_results_but_sinks_to_bottom(self) -> None:
        now = datetime.now(UTC)
        active = AccountCandidate(
            service="ремонт",
            city="Салехард",
            platform="vk",
            account_name="Ремонт 24",
            account_url="https://vk.com/remont24",
            username_or_id="remont24",
            description="Ремонт квартир, цена, запись, отзывы",
            followers=300,
            posts=[
                PostRecord(
                    url="https://vk.com/remont24/1",
                    text="Окна на этой неделе, цена и запись в лс",
                    published_at=now - timedelta(days=3),
                    likes=10,
                    comments=2,
                    reposts=1,
                    views=120,
                )
            ],
        )
        abandoned = AccountCandidate(
            service="ремонт",
            city="Салехард",
            platform="vk",
            account_name="Старый ремонт",
            account_url="https://vk.com/old-remont",
            username_or_id="old-remont",
            description="Ремонт квартир",
            followers=200,
            posts=[
                PostRecord(
                    url="https://vk.com/old-remont/1",
                    text="Старая запись",
                    published_at=now - timedelta(days=120),
                    likes=1,
                    comments=0,
                    reposts=0,
                    views=10,
                )
            ],
        )

        ranked, _ = score_candidates(
            [abandoned, active],
            period_days=60,
            cities=["Салехард"],
            extra_markers_by_service={"ремонт": []},
            now=now,
        )

        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].candidate.account_name, "Ремонт 24")
        self.assertEqual(ranked[-1].candidate.account_name, "Старый ремонт")
        self.assertEqual(ranked[-1].activity_class, "заброшенный")

    def test_noise_heavy_public_gets_penalty_against_real_business(self) -> None:
        now = datetime.now(UTC)
        business = AccountCandidate(
            service="фотограф",
            city="Ноябрьск",
            platform="vk",
            account_name="Фотограф Ноябрьск",
            account_url="https://vk.com/photo-work",
            username_or_id="photo-work",
            description="Фотограф Ноябрьск, прайс, запись, отзывы",
            followers=400,
            posts=[
                PostRecord(
                    url="https://vk.com/photo-work/1",
                    text="Запись на съёмку открыта, цена от 5000, Ноябрьск",
                    published_at=now - timedelta(days=4),
                    likes=12,
                    comments=2,
                    reposts=0,
                    views=150,
                )
            ],
        )
        noisy = AccountCandidate(
            service="фотограф",
            city="Ноябрьск",
            platform="vk",
            account_name="Новости Ноябрьска",
            account_url="https://vk.com/news-no",
            username_or_id="news-no",
            description="Новости, объявления, афиша, чат города",
            followers=400,
            posts=[
                PostRecord(
                    url="https://vk.com/news-no/1",
                    text="Афиша, новости и объявления Ноябрьска",
                    published_at=now - timedelta(days=2),
                    likes=30,
                    comments=1,
                    reposts=2,
                    views=250,
                )
            ],
        )

        business_rank = score_candidate(
            business,
            period_days=30,
            cities=["Ноябрьск"],
            extra_markers=[],
            now=now,
        )
        noisy_rank = score_candidate(
            noisy,
            period_days=30,
            cities=["Ноябрьск"],
            extra_markers=[],
            now=now,
        )

        self.assertLess(noisy_rank.score.penalty, 0)
        self.assertGreater(business_rank.score.total, noisy_rank.score.total)

    def test_duplicate_detection_marks_same_phone_and_booking_link(self) -> None:
        now = datetime.now(UTC)
        left = AccountCandidate(
            service="маникюр",
            city="Салехард",
            platform="vk",
            account_name="Studio Left",
            account_url="https://vk.com/studio_left",
            username_or_id="studio_left",
            description="Маникюр, запись https://n1.yclients.com/, телефон +7 (900) 000-00-01",
            contacts={"phone": ["+7 (900) 000-00-01"]},
            posts=[
                PostRecord(
                    url="https://vk.com/studio_left/1",
                    text="Запись открыта",
                    published_at=now - timedelta(days=1),
                )
            ],
        )
        right = AccountCandidate(
            service="маникюр",
            city="Салехард",
            platform="vk",
            account_name="Studio Right",
            account_url="https://vk.com/studio_right",
            username_or_id="studio_right",
            description="Маникюр, запись https://n1.yclients.com/, телефон 8 900 000 00 01",
            contacts={"phone": ["8 900 000 00 01"]},
            posts=[
                PostRecord(
                    url="https://vk.com/studio_right/1",
                    text="Свободные окна",
                    published_at=now - timedelta(days=1),
                )
            ],
        )

        ranked, duplicates = score_candidates(
            [left, right],
            period_days=30,
            cities=["Салехард"],
            extra_markers_by_service={"маникюр": []},
            now=now,
        )

        self.assertTrue(duplicates)
        self.assertTrue(any("телефон" in item.reason.lower() or "ссылка для записи" in item.reason.lower() for item in duplicates))
        self.assertTrue(all(item.duplicate_group for item in ranked))

    def test_duplicate_detection_marks_cross_platform_same_website(self) -> None:
        now = datetime.now(UTC)
        vk_candidate = AccountCandidate(
            service="маникюр",
            city="Салехард",
            platform="vk",
            account_name="Loft Studio",
            account_url="https://vk.com/loft_studio",
            username_or_id="loft_studio",
            description="Маникюр, сайт https://loft-beauty.ru, запись открыта",
            posts=[
                PostRecord(
                    url="https://vk.com/loft_studio/1",
                    text="Запись открыта",
                    published_at=now - timedelta(days=1),
                )
            ],
        )
        places_candidate = AccountCandidate(
            service="маникюр",
            city="Салехард",
            platform="places",
            account_name="Loft Beauty",
            account_url="https://www.google.com/maps/place/loft",
            username_or_id="place_loft",
            description="Карточка Google Places. Сайт: https://loft-beauty.ru/contacts",
            posts=[],
        )

        ranked, duplicates = score_candidates(
            [vk_candidate, places_candidate],
            period_days=30,
            cities=["Салехард"],
            extra_markers_by_service={"маникюр": []},
            now=now,
        )

        self.assertTrue(
            any(
                "сайт" in item.reason.lower()
                or "телефон" in item.reason.lower()
                or "telegram" in item.reason.lower()
                for item in duplicates
            )
        )
        self.assertTrue(all(item.duplicate_group for item in ranked))

    def test_duplicate_detection_ignores_generic_social_platform_websites(self) -> None:
        now = datetime.now(UTC)
        left = AccountCandidate(
            service="маникюр",
            city="Салехард",
            platform="vk",
            account_name="Studio Left",
            account_url="https://vk.com/studio_left",
            username_or_id="studio_left",
            description="Маникюр, сайт https://vk.ru/studio_left, запись открыта",
            posts=[
                PostRecord(
                    url="https://vk.com/studio_left/1",
                    text="Запись открыта",
                    published_at=now - timedelta(days=1),
                )
            ],
        )
        right = AccountCandidate(
            service="маникюр",
            city="Салехард",
            platform="vk",
            account_name="Studio Right",
            account_url="https://vk.com/studio_right",
            username_or_id="studio_right",
            description="Маникюр, сайт https://vk.ru/studio_right, прайс и запись",
            posts=[
                PostRecord(
                    url="https://vk.com/studio_right/1",
                    text="Свободные окна",
                    published_at=now - timedelta(days=1),
                )
            ],
        )

        ranked, duplicates = score_candidates(
            [left, right],
            period_days=30,
            cities=["Салехард"],
            extra_markers_by_service={"маникюр": []},
            now=now,
        )

        self.assertEqual(duplicates, [])
        self.assertTrue(all(item.duplicate_group is None for item in ranked))

    def test_business_card_duplicate_enrichment_copies_2gis_contacts_price_and_address(self) -> None:
        now = datetime.now(UTC)
        vk_candidate = AccountCandidate(
            service="кофейня",
            city="Салехард",
            platform="vk",
            account_name="Coffee North",
            account_url="https://vk.com/coffee_north",
            username_or_id="coffee_north",
            description="Кофейня в Салехарде, запись и новости, сайт https://coffee-north.ru",
            contacts={"website": ["https://coffee-north.ru"]},
            posts=[
                PostRecord(
                    url="https://vk.com/coffee_north/1",
                    text="Свежая выпечка и кофе каждый день",
                    published_at=now - timedelta(days=1),
                )
            ],
        )
        twogis_candidate = AccountCandidate(
            service="кофейня",
            city="Салехард",
            platform="2gis",
            account_name="Coffee North",
            account_url="https://2gis.ru/search/coffee_north",
            username_or_id="coffee_north_2gis",
            description="Карточка 2GIS. Сайт: https://coffee-north.ru. Телефон: +7 900 111-22-33.",
            contacts={
                "phone": ["+7 900 111-22-33"],
                "website": ["https://coffee-north.ru"],
                "telegram": ["@coffee_north"],
            },
            api_address="Салехард, ул. Ленина, 15",
            business_categories="Кофейня, Десерты",
            rating_details="4.8 (87 отзывов)",
            working_hours="ежедневно, 08:00-22:00",
            price_details="есть данные по среднему чеку; Средний чек: 650 ₽",
            posts=[],
        )

        ranked, duplicates = score_candidates(
            [vk_candidate, twogis_candidate],
            period_days=30,
            cities=["Салехард"],
            extra_markers_by_service={"кофейня": []},
            now=now,
        )

        enriched_vk = next(item for item in ranked if item.candidate.platform == "vk")
        self.assertIn("+7 900 111-22-33", enriched_vk.candidate.contacts["phone"])
        self.assertIn("@coffee_north", enriched_vk.candidate.contacts["telegram"])
        self.assertEqual(enriched_vk.candidate.business_categories, "Кофейня, Десерты")
        self.assertEqual(enriched_vk.candidate.rating_details, "4.8 (87 отзывов)")
        self.assertEqual(enriched_vk.candidate.working_hours, "ежедневно, 08:00-22:00")
        self.assertEqual(enriched_vk.candidate.price_details, "есть данные по среднему чеку; Средний чек: 650 ₽")
        self.assertEqual(enriched_vk.candidate.api_address, "Салехард, ул. Ленина, 15")
        self.assertTrue(
            any(
                "сайт" in item.reason.lower()
                or "телефон" in item.reason.lower()
                or "telegram" in item.reason.lower()
                for item in duplicates
            )
        )

    def test_business_card_duplicate_enrichment_copies_google_places_price_and_coordinates(self) -> None:
        now = datetime.now(UTC)
        vk_candidate = AccountCandidate(
            service="кофейня",
            city="Салехард",
            platform="vk",
            account_name="Coffee North",
            account_url="https://vk.com/coffee_north",
            username_or_id="coffee_north",
            description="Кофейня в Салехарде, сайт https://coffee-north.ru",
            contacts={"website": ["https://coffee-north.ru"]},
            posts=[
                PostRecord(
                    url="https://vk.com/coffee_north/1",
                    text="Кофе и десерты каждый день",
                    published_at=now - timedelta(days=1),
                )
            ],
        )
        places_candidate = AccountCandidate(
            service="кофейня",
            city="Салехард",
            platform="places",
            account_name="Coffee North",
            account_url="https://maps.google.com/?cid=111",
            username_or_id="place_coffee_north",
            description="Карточка Google Places. Сайт: https://coffee-north.ru. Цены: средний чек.",
            contacts={
                "phone": ["+7 900 222-33-44"],
                "website": ["https://coffee-north.ru"],
            },
            api_address="Салехард, ул. Ленина, 15",
            geo_coordinates="66.53, 66.61",
            business_categories="Кофейня, cafe",
            rating_details="4.6 (43 отзывов)",
            working_hours="открыто сейчас; ежедневно: 08:00-22:00",
            price_details="средний чек",
            posts=[],
        )

        ranked, _ = score_candidates(
            [vk_candidate, places_candidate],
            period_days=30,
            cities=["Салехард"],
            extra_markers_by_service={"кофейня": []},
            now=now,
        )

        enriched_vk = next(item for item in ranked if item.candidate.platform == "vk")
        self.assertIn("+7 900 222-33-44", enriched_vk.candidate.contacts["phone"])
        self.assertEqual(enriched_vk.candidate.api_address, "Салехард, ул. Ленина, 15")
        self.assertEqual(enriched_vk.candidate.geo_coordinates, "66.53, 66.61")
        self.assertEqual(enriched_vk.candidate.business_categories, "Кофейня, cafe")
        self.assertEqual(enriched_vk.candidate.rating_details, "4.6 (43 отзывов)")
        self.assertEqual(enriched_vk.candidate.working_hours, "открыто сейчас; ежедневно: 08:00-22:00")
        self.assertEqual(enriched_vk.candidate.price_details, "средний чек")


if __name__ == "__main__":
    unittest.main()
