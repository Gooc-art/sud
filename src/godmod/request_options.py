from __future__ import annotations

from collections.abc import Iterable, Sequence

from .markers import normalize_slug, normalize_text


ALL_TIME_PERIOD_DAYS = 0
ALL_TIME_PERIOD_LABEL = "За всё время"
ALL_SERVICES_LABEL = "Все сферы деятельности"
ALL_SERVICES_CALLBACK_DATA = "service:all"

_ALL_SERVICES_TOKENS = {
    normalize_text("all"),
    normalize_text("all services"),
    normalize_text("all_services"),
    normalize_text("все"),
    normalize_text("все услуги"),
    normalize_text("все сферы"),
    normalize_text("все сферы деятельности"),
    normalize_text("вся деятельность"),
}

_ALL_TIME_TOKENS = {
    normalize_text("all"),
    normalize_text("all_time"),
    normalize_text("all time"),
    normalize_text("0"),
    normalize_text("все"),
    normalize_text("весь"),
    normalize_text("все время"),
    normalize_text("всё время"),
    normalize_text("за все время"),
    normalize_text("за всё время"),
}

_SERVICE_SELECTION_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Красота и уход",
        (
            "маникюр",
            "педикюр",
            "салон красоты",
            "парикмахер",
            "барбершоп",
            "брови",
            "ресницы",
            "косметолог",
            "массаж",
        ),
    ),
    (
        "Общепит",
        (
            "общепит",
            "кафе",
            "кофейня",
            "ресторан",
            "пекарня",
            "доставка еды",
        ),
    ),
    (
        "Дом и ремонт",
        (
            "ремонт",
            "электрик",
            "сантехник",
            "клининг",
            "химчистка",
            "грузоперевозки",
        ),
    ),
    (
        "Автоуслуги",
        (
            "автоэлектрик",
            "автосервис",
            "автомойка",
            "шиномонтаж",
        ),
    ),
    (
        "Здоровье и спорт",
        (
            "стоматология",
            "фитнес",
        ),
    ),
    (
        "Образование и офис",
        (
            "репетитор",
            "фотограф",
            "юрист",
            "бухгалтер",
        ),
    ),
)


def is_all_services_token(value: str) -> bool:
    return normalize_text(value) in _ALL_SERVICES_TOKENS


def expand_service_names(raw_services: Iterable[str], available_services: Sequence[str]) -> list[str]:
    selected: list[str] = []
    values = [item.strip() for item in raw_services if item.strip()]
    if any(is_all_services_token(item) for item in values):
        selected.extend(available_services)
    for item in values:
        if is_all_services_token(item):
            continue
        section = service_selection_section_by_token(available_services, normalize_slug(item))
        if section is not None:
            selected.extend(section[1])
            continue
        selected.append(item)
    return _unique_preserve_order(selected)


def format_period_label(period_days: int) -> str:
    if is_all_time_period(period_days):
        return ALL_TIME_PERIOD_LABEL
    return f"{period_days} дней"


def is_all_time_period(period_days: int) -> bool:
    return period_days <= ALL_TIME_PERIOD_DAYS


def parse_period_value(value: str) -> int:
    token = value.strip()
    normalized = normalize_text(token)
    if normalized in _ALL_TIME_TOKENS:
        return ALL_TIME_PERIOD_DAYS

    period_days = int(token)
    if period_days < 0:
        raise ValueError("Период не может быть отрицательным.")
    return period_days


def summarize_services(services: Sequence[str], available_services: Sequence[str]) -> str:
    normalized_services = _unique_preserve_order(item.strip() for item in services if item.strip())
    normalized_available = _unique_preserve_order(item.strip() for item in available_services if item.strip())
    if normalized_services == normalized_available and normalized_services:
        return ALL_SERVICES_LABEL
    for title, section_services in service_selection_sections(normalized_available):
        if normalized_services == section_services and normalized_services:
            return f"{title}: все услуги раздела"
    return ", ".join(normalized_services)


def service_selection_sections(available_services: Sequence[str]) -> list[tuple[str, list[str]]]:
    ordered_services = _unique_preserve_order(item.strip() for item in available_services if item.strip())
    remaining = list(ordered_services)
    sections: list[tuple[str, list[str]]] = []
    for title, section_services in _SERVICE_SELECTION_SECTIONS:
        selected = [service for service in ordered_services if service in section_services]
        if not selected:
            continue
        sections.append((title, selected))
        remaining = [service for service in remaining if service not in selected]
    if remaining:
        sections.append(("Другие направления", remaining))
    return sections


def service_selection_section_by_token(
    available_services: Sequence[str],
    token: str,
) -> tuple[str, list[str]] | None:
    for title, services in service_selection_sections(available_services):
        if normalize_slug(title) == token:
            return title, services
    return None


def _unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
