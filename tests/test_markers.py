from __future__ import annotations

import unittest

from godmod.config import RuntimeConfig
from godmod.markers import (
    city_hits,
    configure_marker_alias_overrides,
    extract_booking_links,
    extract_contacts,
    official_signal_hits,
    official_signal_level,
    service_profile_hits,
    service_search_query_plan,
    service_search_queries,
    telegram_search_queries,
    twogis_search_queries,
)
from godmod.rule_config import RuleConfig, load_rule_config


class MarkerTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_marker_alias_overrides(None)

    def test_city_hits_detects_yanao_city_aliases(self) -> None:
        hits = city_hits(
            ["Работаю в Н. Уренгой, запись открыта", "Хэштег #новыйуренгой"],
            ["Новый Уренгой", "Салехард"],
        )
        self.assertIn("Новый Уренгой", hits)

    def test_city_hits_detects_latin_translit_city_aliases(self) -> None:
        hits = city_hits(
            ["Manicure in Novy Urengoy", "Coffee in Salekhard", "Studio in Gubkinsky"],
            ["Новый Уренгой", "Салехард", "Губкинский"],
        )
        self.assertIn("Новый Уренгой", hits)
        self.assertIn("Салехард", hits)
        self.assertIn("Губкинский", hits)

    def test_city_hits_detects_generic_yamal_signal(self) -> None:
        hits = city_hits(
            ["Услуги по всему Ямалу и ЯНАО"],
            ["Салехард"],
        )
        self.assertIn("ЯНАО/Ямал", hits)

    def test_service_profile_hits_detect_service_in_profile(self) -> None:
        hits = service_profile_hits(
            ["Маникюр Салехард", "Запись в лс"],
            "маникюр",
        )
        self.assertIn("маникюр", hits)

    def test_service_profile_hits_support_extra_markers(self) -> None:
        hits = service_profile_hits(
            ["Nails Salehard", "Запись в лс"],
            "маникюр",
            ["nails"],
        )
        self.assertIn("nails", hits)

    def test_service_profile_hits_keep_food_profile_matching_precise(self) -> None:
        hits = service_profile_hits(
            ["Уютный ресторан в Салехарде"],
            "кофейня",
        )
        self.assertEqual(hits, [])

    def test_service_profile_hits_accepts_coffee_keyword_for_coffeehouse(self) -> None:
        hits = service_profile_hits(
            ["DO.BRO Кофе | Салехард"],
            "кофейня",
        )
        self.assertIn("кофе", hits)

    def test_service_search_queries_include_builtin_synonyms(self) -> None:
        queries = service_search_queries("маникюр", "Салехард", ["запись"])
        self.assertIn("маникюр Салехард", queries)
        self.assertIn("nails Салехард", queries)
        self.assertIn("ногти Салехард", queries)
        self.assertIn("мастер маникюра Салехард", queries)
        self.assertIn("студия маникюра Салехард", queries)
        self.assertIn("маникюр Салехард запись", queries)

    def test_service_search_query_plan_stages_exact_aliases_and_hints(self) -> None:
        batches = service_search_query_plan("маникюр", "Салехард", ["запись"])
        self.assertEqual(batches[0], ["маникюр Салехард"])
        self.assertEqual(batches[1], ["nails Салехард", "nail Салехард"])
        self.assertEqual(
            batches[2],
            ["ногти Салехард", "мастер маникюра Салехард", "студия маникюра Салехард"],
        )
        self.assertEqual(batches[3], ["маникюр Салехард запись"])

    def test_service_search_queries_expand_food_service_family(self) -> None:
        queries = service_search_queries("общепит", "Новый Уренгой", [])
        self.assertIn("общепит Новый Уренгой", queries)
        self.assertIn("кафе Новый Уренгой", queries)
        self.assertIn("кофейня Новый Уренгой", queries)
        self.assertIn("ресторан Новый Уренгой", queries)
        self.assertIn("еда Новый Уренгой", queries)
        self.assertIn("домашняя еда Новый Уренгой", queries)

    def test_service_profile_hits_match_generic_food_channels(self) -> None:
        hits = service_profile_hits(
            ["Еда Салехард", "Домашняя еда на вынос, выпечка, пироги"],
            "общепит",
        )
        self.assertTrue(any(hit in hits for hit in {"еда", "домашняя еда", "еда на вынос"}))

        delivery_hits = service_profile_hits(
            ["Восточная еда Салехард", "На заказ. На дому. Так же есть доставка."],
            "доставка еды",
        )
        self.assertTrue(any(hit in delivery_hits for hit in {"восточная еда", "доставка"}))

    def test_twogis_search_queries_expand_city_order_and_category_hints(self) -> None:
        queries = twogis_search_queries("маникюр", "Салехард", [])

        self.assertIn("маникюр Салехард", queries)
        self.assertIn("Салехард маникюр", queries)
        self.assertIn("nails Салехард", queries)
        self.assertIn("Салехард nails", queries)
        self.assertIn("ногтевая студия Салехард", queries)
        self.assertIn("Салехард ногтевая студия", queries)

    def test_telegram_search_queries_expand_city_order_aliases_and_hints(self) -> None:
        queries = telegram_search_queries("маникюр", "Салехард", ["запись"])

        self.assertIn("маникюр Салехард", queries)
        self.assertIn("Салехард маникюр", queries)
        self.assertIn("nails Салехард", queries)
        self.assertIn("Салехард nails", queries)
        self.assertIn("мастер маникюра Салехард", queries)
        self.assertIn("Салехард мастер маникюра", queries)
        self.assertIn("маникюр Салехард запись", queries)

    def test_telegram_search_queries_expand_food_generic_terms(self) -> None:
        queries = telegram_search_queries("общепит", "Салехард", [])

        self.assertIn("еда Салехард", queries)
        self.assertIn("Салехард еда", queries)
        self.assertIn("домашняя еда Салехард", queries)
        self.assertIn("Салехард домашняя еда", queries)

    def test_official_signals_detect_requisites_and_site(self) -> None:
        hits = official_signal_hits(
            ["ИП Иванова, ИНН 8901000000, работаем по договору, сайт studio89.ru"]
        )
        self.assertIn("ип", {hit.casefold().strip() for hit in hits})
        self.assertIn("инн", {hit.casefold().strip() for hit in hits})
        self.assertEqual(official_signal_level(hits), "сильные")

    def test_extract_booking_links_prefers_booking_url_over_generic_site(self) -> None:
        links = extract_booking_links(
            [
                "Сайт студии https://loft-beauty.ru\n"
                "Круглосуточная онлайн запись:\n"
                "https://n944117.yclients.com/"
            ]
        )
        self.assertEqual(links, ["https://n944117.yclients.com/"])

    def test_extract_contacts_includes_email_and_website(self) -> None:
        contacts = extract_contacts(
            [
                "Пишите: studio@example.com, сайт https://loft-beauty.ru, telegram @loftstudio",
            ]
        )
        self.assertEqual(contacts["email"], ["studio@example.com"])
        self.assertEqual(contacts["website"], ["https://loft-beauty.ru"])
        self.assertEqual(contacts["telegram"], ["@loftstudio"])

    def test_marker_overrides_extend_service_and_city_aliases(self) -> None:
        configure_marker_alias_overrides(
            RuleConfig(
                service_alias_overrides={"маникюр": ["ноготочки"]},
                service_discovery_hint_overrides={"маникюр": ["студия ноготочков"]},
                city_alias_overrides={"Салехард": ["shd"]},
            )
        )

        queries = service_search_queries("маникюр", "Салехард", [])
        city_matches = city_hits(["Лучшие ноготочки в SHD"], ["Салехард"])

        self.assertIn("ноготочки Салехард", queries)
        self.assertIn("студия ноготочков Салехард", queries)
        self.assertIn("Салехард", city_matches)

    def test_project_rule_config_accepts_barber_profile_aliases(self) -> None:
        configure_marker_alias_overrides(
            RuleConfig(
                service_alias_overrides={
                    "барбершоп": ["barber", "мужская стрижка", "опасное бритье", "борода"],
                },
                service_discovery_hint_overrides={
                    "барбершоп": ["barber", "мужская стрижка", "опасное бритье"],
                },
            )
        )

        hits = service_profile_hits(
            ["Нефть The Barber", "Мужская стрижка, борода, Салехард"],
            "барбершоп",
        )
        queries = service_search_queries("барбершоп", "Салехард", [])

        self.assertIn("barber", hits)
        self.assertIn("мужская стрижка", hits)
        self.assertIn("barber Салехард", queries)

    def test_project_rule_config_covers_popular_services_with_external_aliases(self) -> None:
        config = RuntimeConfig(rule_config=load_rule_config("data/marker_rules.json"))
        configure_marker_alias_overrides(config.rule_config)

        missing_aliases = [
            service
            for service in config.popular_services
            if service not in config.rule_config.service_alias_overrides
        ]
        missing_hints = [
            service
            for service in config.popular_services
            if service not in config.rule_config.service_discovery_hint_overrides
        ]

        self.assertEqual(missing_aliases, [])
        self.assertEqual(missing_hints, [])
        self.assertIn("lashmaker", service_profile_hits(["Lashmaker Салехард"], "ресницы"))
        self.assertIn("компьютерная диагностика авто Салехард", service_search_queries("автоэлектрик", "Салехард"))
        self.assertIn("кофе на вынос Салехард", service_search_queries("кофейня", "Салехард"))


if __name__ == "__main__":
    unittest.main()
