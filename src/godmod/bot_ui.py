from __future__ import annotations

from typing import Any

from .request_options import ALL_SERVICES_CALLBACK_DATA, ALL_SERVICES_LABEL, format_period_label


def build_city_keyboard(cities: list[str], *, columns: int = 2) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = []
    current_row: list[dict[str, str]] = []
    for index, city in enumerate(cities):
        current_row.append({"text": city, "callback_data": city_callback_data(index)})
        if len(current_row) >= columns:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return {"inline_keyboard": rows}


def build_service_keyboard(services: list[str], *, columns: int = 2) -> dict[str, Any]:
    effective_columns = _resolve_columns(services, default=columns)
    rows: list[list[dict[str, str]]] = [
        [{"text": ALL_SERVICES_LABEL, "callback_data": ALL_SERVICES_CALLBACK_DATA}]
    ]
    current_row: list[dict[str, str]] = []
    for index, service in enumerate(services):
        current_row.append(
            {
                "text": _format_service_button_text(service),
                "callback_data": service_callback_data(index),
            }
        )
        if len(current_row) >= effective_columns:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([{"text": "Ввести вручную", "callback_data": "service:manual"}])
    rows.append([{"text": "Сменить город", "callback_data": "flow:cities"}])
    return {"inline_keyboard": rows}


def build_period_keyboard(periods: list[int], *, columns: int = 3) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = []
    current_row: list[dict[str, str]] = []
    for index, period in enumerate(periods):
        current_row.append(
            {
                "text": format_period_label(period),
                "callback_data": period_callback_data(index),
            }
        )
        if len(current_row) >= max(1, columns):
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([{"text": "Изменить услуги", "callback_data": "flow:services"}])
    rows.append([{"text": "Сменить город", "callback_data": "flow:cities"}])
    return {"inline_keyboard": rows}


def build_report_mode_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Все исполнители", "callback_data": report_mode_callback_data("all")},
                {"text": "Только официальные", "callback_data": report_mode_callback_data("official_only")},
            ],
            [{"text": "Изменить период", "callback_data": "flow:period"}],
            [{"text": "Изменить услуги", "callback_data": "flow:services"}],
            [{"text": "Сменить город", "callback_data": "flow:cities"}],
        ]
    }


def build_main_menu_keyboard() -> dict[str, Any]:
    return {
        "keyboard": [
            [{"text": "Старт"}, {"text": "Города"}],
            [{"text": "Помощь"}, {"text": "Сброс"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def build_force_reply(placeholder: str = "Введите услуги через запятую") -> dict[str, Any]:
    return {
        "force_reply": True,
        "input_field_placeholder": placeholder,
        "selective": True,
    }


def city_callback_data(index: int) -> str:
    return f"city:{index}"


def service_callback_data(index: int) -> str:
    return f"service:{index}"


def period_callback_data(index: int) -> str:
    return f"period:{index}"


def report_mode_callback_data(mode: str) -> str:
    return f"mode:{mode}"


def parse_city_callback(data: str, cities: list[str]) -> str | None:
    prefix = "city:"
    if not data.startswith(prefix):
        return None
    index_text = data.removeprefix(prefix)
    if not index_text.isdigit():
        return None
    index = int(index_text)
    if 0 <= index < len(cities):
        return cities[index]
    return None


def parse_service_callback(data: str, services: list[str]) -> str | None:
    if data == ALL_SERVICES_CALLBACK_DATA:
        return ALL_SERVICES_LABEL
    prefix = "service:"
    if not data.startswith(prefix):
        return None
    index_text = data.removeprefix(prefix)
    if not index_text.isdigit():
        return None
    index = int(index_text)
    if 0 <= index < len(services):
        return services[index]
    return None


def parse_period_callback(data: str, periods: list[int]) -> int | None:
    prefix = "period:"
    if not data.startswith(prefix):
        return None
    index_text = data.removeprefix(prefix)
    if not index_text.isdigit():
        return None
    index = int(index_text)
    if 0 <= index < len(periods):
        return periods[index]
    return None


def parse_report_mode_callback(data: str) -> str | None:
    prefix = "mode:"
    if not data.startswith(prefix):
        return None
    mode = data.removeprefix(prefix)
    if mode in {"all", "official_only"}:
        return mode
    return None


def _resolve_columns(labels: list[str], *, default: int) -> int:
    if any(len(label.strip()) > 12 for label in labels):
        return 1
    return max(1, default)


def _format_service_button_text(service: str) -> str:
    label = service.strip()
    return label[:1].upper() + label[1:] if label else service
