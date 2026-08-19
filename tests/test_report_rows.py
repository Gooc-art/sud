from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from godmod.models import (
    AccountCandidate,
    AccountMetrics,
    DuplicateReviewItem,
    FilterDebugItem,
    PostRecord,
    RankedAccount,
    ReportBundle,
    ScoreBreakdown,
    SearchLogEntry,
    SearchRequest,
    ServiceQuery,
)
from godmod.report_rows import build_report_rows


class ReportRowsTests(unittest.TestCase):
    def test_build_report_rows_returns_single_ranked_accounts_sheet(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        ranked_accounts = [
            RankedAccount(
                candidate=AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Studio One",
                    account_url="https://vk.com/studio1",
                    username_or_id="studio1",
                    description=(
                        "Маникюр в Салехарде. Адрес: ул. Ленина, 10. "
                        "Запись по телефону +7 900 000-00-00 и @studio1. "
                        "Круглосуточная онлайн запись https://n944117.yclients.com/"
                    ),
                    followers=1200,
                    posts=[
                        PostRecord(
                            url="https://vk.com/studio1?w=wall-1_1",
                            text="Маникюр Салехард, запись открыта",
                            published_at=now,
                        ),
                        PostRecord(
                            url="https://vk.com/studio1?w=wall-1_2",
                            text="Отзывы клиентов, Салехард",
                            published_at=now - timedelta(days=10),
                        ),
                        PostRecord(
                            url="https://vk.com/studio1?w=wall-1_3",
                            text="Ищем мастера в команду",
                            published_at=now - timedelta(days=45),
                        ),
                    ],
                    contacts={"phone": ["+7 900 000-00-00"], "telegram": ["@studio1"]},
                ),
                metrics=AccountMetrics(
                    posts_in_period=10,
                    last_post_at=now,
                    avg_likes=30,
                    avg_comments=4,
                    avg_reposts=1,
                    avg_views=250,
                    commercial_markers=["цены", "запись"],
                    city_signals=["Салехард"],
                    stability_ratio=0.8,
                ),
                score=ScoreBreakdown(3.0, 1.5, 2.0, 1.5, 1.0),
                evidence_posts=[],
                activity_class="сильный действующий аккаунт",
            )
        ]
        bundle = ReportBundle(
            request=SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="маникюр")],
                period_days=60,
                platforms=["vk"],
                top_n=20,
            ),
            ranked_accounts=ranked_accounts,
            search_log=[
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                )
            ],
            duplicates_review=[
                DuplicateReviewItem(
                    left_account_url="https://vk.com/studio1",
                    right_account_url="https://vk.com/studio2",
                    confidence="low",
                    reason="shared phone",
                )
            ],
            filter_debug=[
                FilterDebugItem(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    account_name="Объявления Салехард",
                    account_url="https://vk.com/ads_salehard",
                    username_or_id="ads_salehard",
                    description="Объявления, барахолка, новости Салехарда",
                    status="excluded",
                    decision_stage="service_filter",
                    reason="Профиль похож на объявления, чат или агрегатор: объявления.",
                    search_queries=["маникюр Салехард"],
                    posts_total=12,
                    posts_in_period=4,
                    score_total=5.8,
                    activity_class="умеренно активный",
                    city_signals=["Салехард"],
                    service_profile_hits=["маникюр"],
                    commercial_markers=["запись", "цены"],
                    noise_markers=["объявления"],
                    official_signals=[],
                )
            ],
        )

        rows = build_report_rows(bundle)

        self.assertEqual(
            list(rows),
            ["all_accounts", "summary", "account_review", "technical_details", "search_log", "raw_candidates", "filter_debug", "duplicates_review"],
        )
        self.assertEqual(rows["search_log"][0]["Источник discovery"], "не указан")
        self.assertEqual(rows["search_log"][0]["Режим discovery"], "не указан")
        self.assertEqual(rows["search_log"][0]["Поисковый запрос"], "маникюр Салехард")
        self.assertEqual(rows["search_log"][0]["Диагностика"], "нет")
        self.assertEqual(
            set(rows),
            {"all_accounts", "summary", "account_review", "technical_details", "search_log", "raw_candidates", "filter_debug", "duplicates_review"},
        )
        self.assertEqual(rows["raw_candidates"][0]["Город из API"], "нет данных")
        self.assertEqual(rows["raw_candidates"][0]["Источники discovery"], "нет")
        self.assertEqual(rows["raw_candidates"][0]["Постов собрано"], 3)
        self.assertEqual(rows["summary"][0]["Найдено аккаунтов"], 1)
        self.assertEqual(rows["summary"][0]["Студий/салонов"], 1)
        self.assertEqual(
            list(rows["all_accounts"][0]),
            [
                "id",
                "Название",
                "Площадка",
                "Тип",
                "Ссылка",
                "Город / локация",
                "Город из API",
                "Адрес (если есть)",
                "Координаты",
                "Категории",
                "Рейтинг / отзывы",
                "Часы работы",
                "Описание деятельности",
                "Ключевые слова услуг",
                "Подписчики",
                "Активность (постинг)",
                "Постов за 30 дней",
                "Средние лайки",
                "Средние комментарии",
                "Средние репосты",
                "ER, %",
                "Коммерческие маркеры",
                "Сотрудники",
                "Телефон",
                "Контакты администратора",
                "Ссылка для записи",
                "Цены / прайс",
                "Официальные реквизиты",
                "Служебные поля 2GIS",
                "Сотрудников (2GIS)",
                "Дата сбора",
                "Примечание",
            ],
        )
        self.assertEqual(rows["all_accounts"][0]["id"], "vk:studio1")
        self.assertEqual(rows["all_accounts"][0]["Название"], "Studio One")
        self.assertEqual(rows["all_accounts"][0]["Площадка"], "VK")
        self.assertEqual(rows["all_accounts"][0]["Тип"], "студия/салон")
        self.assertEqual(rows["all_accounts"][0]["Ссылка"], "https://vk.com/studio1")
        self.assertEqual(rows["all_accounts"][0]["Город / локация"], "Салехард")
        self.assertEqual(rows["all_accounts"][0]["Город из API"], "нет")
        self.assertEqual(rows["all_accounts"][0]["Адрес (если есть)"], "ул. Ленина, 10")
        self.assertEqual(rows["all_accounts"][0]["Координаты"], "нет")
        self.assertEqual(rows["all_accounts"][0]["Категории"], "нет")
        self.assertEqual(rows["all_accounts"][0]["Рейтинг / отзывы"], "нет")
        self.assertEqual(rows["all_accounts"][0]["Часы работы"], "нет")
        self.assertIn("Маникюр в Салехарде", rows["all_accounts"][0]["Описание деятельности"])
        self.assertEqual(rows["all_accounts"][0]["Ключевые слова услуг"], "маникюр, цены, запись")
        self.assertEqual(rows["all_accounts"][0]["Подписчики"], 1200)
        self.assertEqual(rows["all_accounts"][0]["Активность (постинг)"], "сильный действующий")
        self.assertEqual(rows["all_accounts"][0]["Постов за 30 дней"], 2)
        self.assertEqual(rows["all_accounts"][0]["Средние лайки"], 30)
        self.assertEqual(rows["all_accounts"][0]["Средние комментарии"], 4)
        self.assertEqual(rows["all_accounts"][0]["Средние репосты"], 1)
        self.assertEqual(rows["all_accounts"][0]["ER, %"], 2.92)
        self.assertEqual(rows["all_accounts"][0]["Коммерческие маркеры"], "цены, запись")
        self.assertEqual(rows["all_accounts"][0]["Сотрудники"], "несколько мастеров")
        self.assertIn("+7 900 000-00-00", rows["all_accounts"][0]["Телефон"])
        self.assertIn("+7 900 000-00-00", rows["all_accounts"][0]["Контакты администратора"])
        self.assertIn("@studio1", rows["all_accounts"][0]["Контакты администратора"])
        self.assertEqual(rows["all_accounts"][0]["Ссылка для записи"], "https://n944117.yclients.com/")
        self.assertEqual(rows["all_accounts"][0]["Цены / прайс"], "нет")
        self.assertEqual(rows["all_accounts"][0]["Официальные реквизиты"], "нет")
        self.assertEqual(rows["all_accounts"][0]["Служебные поля 2GIS"], "нет")
        self.assertEqual(rows["all_accounts"][0]["Сотрудников (2GIS)"], "нет")
        self.assertTrue(rows["all_accounts"][0]["Дата сбора"])
        self.assertIn("Студия/салон", rows["all_accounts"][0]["Примечание"])
        self.assertIn("Контакты", rows["account_review"][0])
        self.assertIn("Описание профиля", rows["account_review"][0])
        self.assertIn("Признаки услуги", rows["account_review"][0])
        self.assertIn("Подтверждающий пост 1", rows["account_review"][0])
        self.assertNotIn("Поисковые запросы", rows["all_accounts"][0])
        self.assertNotIn("Индекс вовлечённости", rows["all_accounts"][0])

    def test_build_report_rows_uses_matched_services_without_duplicating_account_rows(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        ranked_accounts = [
            RankedAccount(
                candidate=AccountCandidate(
                    service="маникюр",
                    matched_services=["маникюр", "педикюр"],
                    city="Салехард",
                    platform="vk",
                    account_name="Beauty Loft",
                    account_url="https://vk.com/beauty_loft",
                    username_or_id="beauty_loft",
                    description="Маникюр и педикюр, запись в лс, Салехард",
                    posts=[
                        PostRecord(
                            url="https://vk.com/beauty_loft/1",
                            text="Маникюр и педикюр, запись открыта",
                            published_at=now,
                        )
                    ],
                ),
                metrics=AccountMetrics(
                    posts_in_period=5,
                    last_post_at=now,
                    avg_likes=10,
                    avg_comments=1,
                    avg_reposts=0,
                    avg_views=100,
                    commercial_markers=["запись"],
                    city_signals=["Салехард"],
                    stability_ratio=0.7,
                ),
                score=ScoreBreakdown(2.0, 1.0, 1.0, 1.5, 0.7),
                evidence_posts=[],
                activity_class="действующий",
            )
        ]
        bundle = ReportBundle(
            request=SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="маникюр"), ServiceQuery(name="педикюр")],
                period_days=30,
                platforms=["vk"],
                top_n=20,
            ),
            ranked_accounts=ranked_accounts,
            search_log=[],
            duplicates_review=[],
        )

        rows = build_report_rows(bundle)

        self.assertEqual(len(rows["all_accounts"]), 1)
        self.assertEqual(rows["account_review"][0]["Услуга"], "маникюр, педикюр")
        self.assertEqual(rows["all_accounts"][0]["Ключевые слова услуг"], "маникюр, педикюр, запись")
        summary_services = {row["Услуга"] for row in rows["summary"]}
        self.assertEqual(summary_services, {"маникюр", "педикюр"})
        self.assertNotIn("Username / ID", rows["all_accounts"][0])
        self.assertIn("Поисковые запросы", rows["technical_details"][0])
        self.assertIn("Индекс вовлечённости", rows["technical_details"][0])
        self.assertIn("Username / ID", rows["technical_details"][0])
        self.assertIn("Официальные маркеры", rows["technical_details"][0])
        self.assertNotIn("top_accounts", rows)

    def test_build_report_rows_classifies_private_master(self) -> None:
        now = datetime(2026, 3, 22, 12, 0, tzinfo=UTC)
        bundle = ReportBundle(
            request=SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="маникюр")],
                period_days=60,
                platforms=["vk"],
                top_n=20,
            ),
            ranked_accounts=[
                RankedAccount(
                    candidate=AccountCandidate(
                        service="маникюр",
                        city="Салехард",
                        platform="vk",
                        account_name="Частный мастер Анна",
                        account_url="https://vk.com/anna_master",
                        username_or_id="anna_master",
                        description="Частный мастер по маникюру, принимаю лично на дому в Салехарде",
                        followers=350,
                    ),
                    metrics=AccountMetrics(
                        posts_in_period=5,
                        last_post_at=now,
                        avg_likes=10,
                        avg_comments=1,
                        avg_reposts=0,
                        avg_views=120,
                        commercial_markers=["запись", "цены"],
                        city_signals=["Салехард"],
                        stability_ratio=0.7,
                    ),
                    score=ScoreBreakdown(2.5, 1.1, 1.5, 1.5, 0.7),
                    evidence_posts=[],
                    activity_class="действующий",
                )
            ],
            search_log=[],
            duplicates_review=[],
        )

        rows = build_report_rows(bundle)

        self.assertEqual(rows["all_accounts"][0]["Тип"], "частный мастер")
        self.assertEqual(rows["all_accounts"][0]["Сотрудники"], "1 человек")
        self.assertIn("Частный мастер", rows["all_accounts"][0]["Примечание"])
        self.assertEqual(rows["account_review"][0]["Как работает"], "на дому")
        self.assertIn(rows["technical_details"][0]["Уверенность по типу"], {"средняя", "высокая"})

    def test_build_report_rows_keeps_search_log_diagnostics(self) -> None:
        bundle = ReportBundle(
            request=SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="маникюр")],
                period_days=90,
                platforms=["vk"],
                top_n=20,
            ),
            ranked_accounts=[],
            search_log=[
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="profile_search_batch:маникюр Салехард",
                    source="vk.profile_search.error",
                    discovery_mode="vk_user_token",
                    details="User authorization failed: invalid access_token (code=5); fallback=vk_service_token",
                )
            ],
            duplicates_review=[],
        )

        rows = build_report_rows(bundle)

        self.assertEqual(rows["search_log"][0]["Источник discovery"], "vk.profile_search.error")
        self.assertEqual(rows["search_log"][0]["Режим discovery"], "vk_user_token")
        self.assertIn("fallback=vk_service_token", rows["search_log"][0]["Диагностика"])

    def test_build_report_rows_marks_official_like_profiles(self) -> None:
        now = datetime(2026, 3, 22, 12, 0, tzinfo=UTC)
        bundle = ReportBundle(
            request=SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="ремонт")],
                period_days=60,
                platforms=["vk"],
                top_n=20,
            ),
            ranked_accounts=[
                RankedAccount(
                    candidate=AccountCandidate(
                        service="ремонт",
                        city="Салехард",
                        platform="vk",
                        account_name="ИП Иванов Ремонт",
                        account_url="https://vk.com/remont_ip",
                        username_or_id="remont_ip",
                        description="ИП Иванов, ИНН 8901000000, работаем по договору, сайт remont89.ru",
                        followers=200,
                    ),
                    metrics=AccountMetrics(
                        posts_in_period=4,
                        last_post_at=now,
                        avg_likes=7,
                        avg_comments=1,
                        avg_reposts=0,
                        avg_views=80,
                        commercial_markers=["цены", "запись"],
                        city_signals=["Салехард"],
                        stability_ratio=0.6,
                    ),
                    score=ScoreBreakdown(2.0, 0.9, 1.5, 1.5, 0.6),
                    evidence_posts=[],
                    activity_class="действующий",
                )
            ],
            search_log=[],
            duplicates_review=[],
        )

        rows = build_report_rows(bundle)

        self.assertIn("официальные признаки: сильные", rows["all_accounts"][0]["Примечание"])
        self.assertEqual(rows["account_review"][0]["Официальные признаки"], "сильные")
        self.assertIn("инн", rows["technical_details"][0]["Официальные маркеры"].casefold())

    def test_build_report_rows_labels_places_cards_without_social_posting_as_no_data(self) -> None:
        bundle = ReportBundle(
            request=SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="маникюр")],
                period_days=90,
                platforms=["places"],
                top_n=20,
            ),
            ranked_accounts=[
                RankedAccount(
                    candidate=AccountCandidate(
                        service="маникюр",
                        city="Салехард",
                        platform="places",
                        account_name="Nails Studio Салехард",
                        account_url="https://maps.google.com/?cid=123",
                        username_or_id="place-1",
                        description="Адрес: ул. Ленина, 10, Салехард. Телефон: +7 900 000-00-00.",
                        contacts={"phone": ["+7 900 000-00-00"]},
                    ),
                    metrics=AccountMetrics(
                        posts_in_period=0,
                        last_post_at=None,
                        avg_likes=None,
                        avg_comments=None,
                        avg_reposts=None,
                        avg_views=None,
                        commercial_markers=["телефон"],
                        city_signals=["Салехард"],
                        stability_ratio=0.0,
                    ),
                    score=ScoreBreakdown(0.0, 0.0, 0.7, 1.5, 0.0),
                    evidence_posts=[],
                    activity_class="заброшенный",
                )
            ],
            search_log=[],
            duplicates_review=[],
        )

        rows = build_report_rows(bundle)

        self.assertEqual(rows["all_accounts"][0]["Активность (постинг)"], "нет данных по постингу")
        self.assertEqual(rows["account_review"][0]["Площадка"], "Google Places")
        self.assertIn("Google Places", rows["all_accounts"][0]["Примечание"])

    def test_build_report_rows_labels_2gis_cards_without_social_posting_as_no_data(self) -> None:
        now = datetime(2026, 3, 22, 12, 0, tzinfo=UTC)
        bundle = ReportBundle(
            request=SearchRequest(
                cities=["Новый Уренгой"],
                services=[ServiceQuery(name="маникюр")],
                period_days=60,
                platforms=["2gis"],
                top_n=20,
            ),
            ranked_accounts=[
                RankedAccount(
                    candidate=AccountCandidate(
                        service="маникюр",
                        city="Новый Уренгой",
                        platform="2gis",
                        account_name="Nail Loft",
                        account_url="https://2gis.ru/search/branch-1",
                        username_or_id="branch-1",
                        description="Карточка 2GIS. Адрес: Новый Уренгой, Ленинградский проспект, 5.",
                        contacts={"phone": ["+7 900 123-45-67"]},
                        api_city="Новый Уренгой",
                        api_address="Новый Уренгой, Ленинградский проспект, 5",
                        geo_coordinates="76.6784, 66.0839",
                        business_categories="Ногтевые студии",
                        rating_details="4.8 (14 отзывов)",
                        working_hours="ежедневно, 10:00-20:00",
                        price_details="есть данные по среднему чеку; Средний чек: 1 500 ₽",
                        official_requisites="ИНН: 8904012345; Лицензия: TL-89-001",
                        service_fields="ФИАС: fias-123; ФНС: fns-89",
                        employee_count=12,
                    ),
                    metrics=AccountMetrics(
                        posts_in_period=0,
                        last_post_at=None,
                        avg_likes=None,
                        avg_comments=None,
                        avg_reposts=None,
                        avg_views=None,
                        commercial_markers=["маникюр"],
                        city_signals=["Новый Уренгой"],
                        stability_ratio=0.0,
                    ),
                    score=ScoreBreakdown(0.0, 0.0, 1.2, 1.0, 0.0),
                    evidence_posts=[],
                    activity_class="нет данных по постингу",
                )
            ],
            search_log=[
                SearchLogEntry(
                    city="Новый Уренгой",
                    service="маникюр",
                    platform="2gis",
                    query="маникюр Новый Уренгой",
                    source="2gis.places_api",
                    discovery_mode="2gis_places",
                )
            ],
            duplicates_review=[],
        )

        rows = build_report_rows(bundle)

        self.assertEqual(rows["all_accounts"][0]["Активность (постинг)"], "нет данных по постингу")
        self.assertEqual(rows["account_review"][0]["Площадка"], "2GIS")
        self.assertEqual(rows["all_accounts"][0]["Город из API"], "Новый Уренгой")
        self.assertEqual(rows["all_accounts"][0]["Координаты"], "76.6784, 66.0839")
        self.assertEqual(rows["all_accounts"][0]["Категории"], "Ногтевые студии")
        self.assertEqual(rows["all_accounts"][0]["Рейтинг / отзывы"], "4.8 (14 отзывов)")
        self.assertEqual(rows["all_accounts"][0]["Часы работы"], "ежедневно, 10:00-20:00")
        self.assertEqual(rows["all_accounts"][0]["Телефон"], "+7 900 123-45-67")
        self.assertEqual(rows["all_accounts"][0]["Цены / прайс"], "есть данные по среднему чеку; Средний чек: 1 500 ₽")
        self.assertEqual(rows["all_accounts"][0]["Официальные реквизиты"], "ИНН: 8904012345; Лицензия: TL-89-001")
        self.assertEqual(rows["all_accounts"][0]["Служебные поля 2GIS"], "ФИАС: fias-123; ФНС: fns-89")
        self.assertEqual(rows["all_accounts"][0]["Сотрудников (2GIS)"], 12)
        self.assertIn("Возможный телефон для записи", rows["account_review"][0]["Что проверить"])
        self.assertIn("Возможный телефон для записи", rows["all_accounts"][0]["Примечание"])
        self.assertIn("2GIS", rows["all_accounts"][0]["Примечание"])

    def test_build_report_rows_uses_api_address_for_enriched_social_account(self) -> None:
        now = datetime(2026, 3, 22, 12, 0, tzinfo=UTC)
        bundle = ReportBundle(
            request=SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="кофейня")],
                period_days=60,
                platforms=["vk", "2gis"],
                top_n=20,
            ),
            ranked_accounts=[
                RankedAccount(
                    candidate=AccountCandidate(
                        service="кофейня",
                        city="Салехард",
                        platform="vk",
                        account_name="Coffee North",
                        account_url="https://vk.com/coffee_north",
                        username_or_id="coffee_north",
                        description="Кофейня в Салехарде, свежая выпечка и кофе каждый день.",
                        contacts={"phone": ["+7 900 111-22-33"], "telegram": ["@coffee_north"]},
                        api_city="Салехард",
                        api_address="Салехард, ул. Ленина, 15",
                        geo_coordinates="66.53, 66.54",
                        business_categories="Кофейня, Десерты",
                        rating_details="4.8 (87 отзывов)",
                        working_hours="ежедневно, 08:00-22:00",
                        price_details="есть данные по среднему чеку; Средний чек: 650 ₽",
                        official_requisites="ИНН: 8904012345",
                        service_fields="ФИАС: fias-1",
                        employee_count=7,
                    ),
                    metrics=AccountMetrics(
                        posts_in_period=6,
                        last_post_at=now,
                        avg_likes=14,
                        avg_comments=1,
                        avg_reposts=0,
                        avg_views=150,
                        commercial_markers=["цены", "запись"],
                        city_signals=["Салехард"],
                        stability_ratio=0.8,
                    ),
                    score=ScoreBreakdown(2.4, 0.8, 1.4, 1.5, 0.8),
                    evidence_posts=[],
                    activity_class="действующий",
                    duplicate_reason="Совпадает сайт: coffee-north.ru",
                )
            ],
            search_log=[],
            duplicates_review=[],
        )

        rows = build_report_rows(bundle)

        self.assertEqual(rows["all_accounts"][0]["Адрес (если есть)"], "Салехард, ул. Ленина, 15")
        self.assertEqual(rows["all_accounts"][0]["Город из API"], "Салехард")
        self.assertEqual(rows["all_accounts"][0]["Координаты"], "66.53, 66.54")
        self.assertEqual(rows["all_accounts"][0]["Категории"], "Кофейня, Десерты")
        self.assertEqual(rows["all_accounts"][0]["Рейтинг / отзывы"], "4.8 (87 отзывов)")
        self.assertEqual(rows["all_accounts"][0]["Часы работы"], "ежедневно, 08:00-22:00")
        self.assertEqual(rows["all_accounts"][0]["Цены / прайс"], "есть данные по среднему чеку; Средний чек: 650 ₽")
        self.assertEqual(rows["all_accounts"][0]["Официальные реквизиты"], "ИНН: 8904012345")
        self.assertEqual(rows["all_accounts"][0]["Служебные поля 2GIS"], "ФИАС: fias-1")
        self.assertEqual(rows["all_accounts"][0]["Сотрудников (2GIS)"], 7)
        self.assertIn("+7 900 111-22-33", rows["all_accounts"][0]["Контакты администратора"])
        self.assertIn("Возможный телефон для записи", rows["all_accounts"][0]["Примечание"])

    def test_all_accounts_keeps_compact_values_while_review_stays_full(self) -> None:
        now = datetime(2026, 3, 22, 12, 0, tzinfo=UTC)
        long_description = (
            "Маникюр, педикюр, депиляция, лазерная эпиляция, массаж лица и тела, солярий, "
            "аппаратные процедуры, прайс, акции, запись, онлайн запись, отзывы клиентов, "
            "адрес Салехард, улица Ленина, 3, телефон +7 900 000-00-00."
        )
        bundle = ReportBundle(
            request=SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="маникюр")],
                period_days=90,
                platforms=["vk"],
                top_n=20,
            ),
            ranked_accounts=[
                RankedAccount(
                    candidate=AccountCandidate(
                        service="маникюр",
                        city="Салехард",
                        platform="vk",
                        account_name="Loft SHD",
                        account_url="https://vk.com/loft_shd",
                        username_or_id="loft_shd",
                        description=long_description,
                        followers=1500,
                        contacts={"phone": ["+7 900 000-00-00"], "telegram": ["@loft_shd"]},
                    ),
                    metrics=AccountMetrics(
                        posts_in_period=8,
                        last_post_at=now,
                        avg_likes=15,
                        avg_comments=2,
                        avg_reposts=1,
                        avg_views=180,
                        commercial_markers=["цены", "запись", "отзывы", "акции", "онлайн запись"],
                        city_signals=["Салехард"],
                        stability_ratio=0.8,
                    ),
                    score=ScoreBreakdown(2.7, 1.2, 1.8, 1.5, 0.8),
                    evidence_posts=[],
                    activity_class="действующий",
                )
            ],
            search_log=[],
            duplicates_review=[],
        )

        rows = build_report_rows(bundle)

        self.assertTrue(rows["all_accounts"][0]["Описание деятельности"].endswith("…"))
        self.assertLess(
            len(rows["all_accounts"][0]["Описание деятельности"]),
            len(rows["account_review"][0]["Описание профиля"]),
        )
        self.assertTrue(rows["all_accounts"][0]["Примечание"].endswith("…"))
        self.assertGreater(
            len(rows["account_review"][0]["Короткий вывод"]),
            len(rows["all_accounts"][0]["Примечание"]),
        )


if __name__ == "__main__":
    unittest.main()
