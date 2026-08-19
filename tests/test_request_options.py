from __future__ import annotations

import unittest

from godmod.config import DEFAULT_POPULAR_SERVICES
from godmod.request_options import (
    ALL_SERVICES_LABEL,
    ALL_TIME_PERIOD_DAYS,
    expand_service_names,
    format_period_label,
    service_selection_sections,
    summarize_services,
)


class RequestOptionsTests(unittest.TestCase):
    def test_expand_service_names_supports_all_services_token(self) -> None:
        expanded = expand_service_names(
            ["все сферы деятельности"],
            ["маникюр", "ремонт", "фотограф"],
        )
        self.assertEqual(expanded, ["маникюр", "ремонт", "фотограф"])

    def test_expand_service_names_keeps_custom_service_alongside_all_services(self) -> None:
        expanded = expand_service_names(
            ["все", "химчистка"],
            ["маникюр", "ремонт"],
        )
        self.assertEqual(expanded, ["маникюр", "ремонт", "химчистка"])

    def test_expand_service_names_expands_category_to_section_services(self) -> None:
        expanded = expand_service_names(
            ["Красота и уход"],
            ["маникюр", "педикюр", "ремонт"],
        )

        self.assertEqual(expanded, ["маникюр", "педикюр"])

    def test_format_period_label_supports_all_time(self) -> None:
        self.assertEqual(format_period_label(ALL_TIME_PERIOD_DAYS), "За всё время")

    def test_summarize_services_returns_all_services_label(self) -> None:
        summary = summarize_services(
            ["маникюр", "ремонт"],
            ["маникюр", "ремонт"],
        )
        self.assertEqual(summary, ALL_SERVICES_LABEL)

    def test_summarize_services_returns_category_label(self) -> None:
        summary = summarize_services(
            ["маникюр", "педикюр"],
            ["маникюр", "педикюр", "ремонт"],
        )

        self.assertEqual(summary, "Красота и уход: все услуги раздела")

    def test_default_popular_services_include_food_and_offline_businesses(self) -> None:
        self.assertIn("общепит", DEFAULT_POPULAR_SERVICES)
        self.assertIn("кафе", DEFAULT_POPULAR_SERVICES)
        self.assertIn("кофейня", DEFAULT_POPULAR_SERVICES)
        self.assertIn("ресторан", DEFAULT_POPULAR_SERVICES)
        self.assertIn("автосервис", DEFAULT_POPULAR_SERVICES)
        self.assertIn("клининг", DEFAULT_POPULAR_SERVICES)

    def test_service_selection_sections_group_services_for_wizard(self) -> None:
        sections = service_selection_sections(
            ["маникюр", "кофейня", "автосервис", "юрист", "редкая ниша"],
        )

        self.assertEqual(
            sections,
            [
                ("Красота и уход", ["маникюр"]),
                ("Общепит", ["кофейня"]),
                ("Автоуслуги", ["автосервис"]),
                ("Образование и офис", ["юрист"]),
                ("Другие направления", ["редкая ниша"]),
            ],
        )


if __name__ == "__main__":
    unittest.main()
