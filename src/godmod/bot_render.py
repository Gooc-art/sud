from __future__ import annotations

from typing import Any

from .bot_callbacks import (
    build_category_callback,
    build_category_services_callback,
    build_city_callback,
    build_edit_callback,
    build_mode_callback,
    build_nav_callback,
    build_period_callback,
    build_service_callback,
)
from .bot_state import WizardState
from .markers import normalize_slug
from .request_options import (
    ALL_SERVICES_LABEL,
    format_period_label,
    service_selection_section_by_token,
    service_selection_sections,
    summarize_services,
)
from .settings import AppSettings


def render_wizard(state: WizardState, settings: AppSettings) -> tuple[str, dict[str, Any] | None]:
    if state.step == "select_city":
        return _render_select_city(state, settings)
    if state.step == "select_service":
        return _render_select_service(state, settings)
    if state.step == "manual_service_input":
        return _render_manual_service_input(state, settings)
    if state.step == "select_period":
        return _render_select_period(state, settings)
    if state.step == "select_mode":
        return _render_select_mode(state, settings)
    if state.step == "confirm":
        return _render_confirm(state, settings)
    if state.step == "running":
        return _render_running(state, settings)
    if state.step == "done":
        return _render_done(state, settings)
    return _render_select_city(state, settings)


def report_mode_label(report_mode: str | None) -> str:
    labels = {
        "all": "все исполнители",
        "official_only": "только официальные",
    }
    if report_mode is None:
        return "не выбран"
    return labels.get(report_mode, report_mode)


def _render_select_city(state: WizardState, settings: AppSettings) -> tuple[str, dict[str, Any]]:
    text = "\n".join(
        [
            "Подготовлю выгрузку по бизнесам и исполнителям ЯНАО.",
            "",
            "Шаг 1 из 5. Выберите город.",
            "",
            f"Доступно городов: {len(settings.runtime.cities)}.",
            ", ".join(settings.runtime.cities),
            "",
            *_summary_lines(state, settings),
            "",
            "После выбора города бот предложит сферу, период, режим и отдельное подтверждение запуска.",
        ]
    )
    rows = _grid_buttons(
        [
            {"text": city, "callback_data": build_city_callback(city)}
            for city in settings.runtime.cities
        ],
        columns=2,
    )
    rows.append([{"text": "Сброс", "callback_data": build_nav_callback("reset")}])
    return text, {"inline_keyboard": rows}


def _render_select_service(state: WizardState, settings: AppSettings) -> tuple[str, dict[str, Any]]:
    sections = service_selection_sections(settings.runtime.popular_services)
    selected_section = None
    if state.service_category:
        selected_section = service_selection_section_by_token(
            settings.runtime.popular_services,
            normalize_slug(state.service_category),
        )
    text = "\n".join(
        [
            "Шаг 2 из 5. Выберите сферу деятельности.",
            "",
            *_summary_lines(state, settings),
            "",
            "Каталог сгруппирован по темам: сначала можно открыть нужный раздел, а затем выбрать конкретную сферу.",
            f"Открытый раздел: {selected_section[0] if selected_section else 'не выбран'}",
            "Если нужен весь открытый раздел, используйте кнопку «Все услуги раздела».",
            "",
            *[f"{title}: {_section_preview(services)}" for title, services in sections],
            "",
            f"Всего сфер: {len(settings.runtime.popular_services)}.",
            ", ".join(settings.runtime.popular_services),
            "",
            "Можно выбрать раздел, одну сферу, все сферы деятельности или перейти к ручному вводу.",
        ]
    )
    rows: list[list[dict[str, str]]] = [
        [{"text": ALL_SERVICES_LABEL, "callback_data": build_service_callback("all")}]
    ]
    category_buttons = []
    for title, _ in sections:
        button_text = title if state.service_category != title else f"[{title}]"
        category_buttons.append({"text": button_text, "callback_data": build_category_callback(title)})
    rows.extend(_grid_buttons(category_buttons, columns=_category_columns(sections)))
    if selected_section is not None:
        rows.append(
            [
                {
                    "text": "Все услуги раздела",
                    "callback_data": build_category_services_callback(selected_section[0]),
                }
            ]
        )
        rows.append([{"text": "Показать все разделы", "callback_data": build_category_callback("all")}])
        service_buttons = [
            {"text": _format_service_button_text(service), "callback_data": build_service_callback(service)}
            for service in selected_section[1]
        ]
        rows.extend(_grid_buttons(service_buttons, columns=_service_columns(selected_section[1])))
    rows.append([{"text": "Ввести вручную", "callback_data": build_nav_callback("manual")}])
    rows.append(
        [
            {"text": "Назад", "callback_data": build_nav_callback("back")},
            {"text": "Сброс", "callback_data": build_nav_callback("reset")},
        ]
    )
    return text, {"inline_keyboard": rows}


def _render_manual_service_input(state: WizardState, settings: AppSettings) -> tuple[str, dict[str, Any]]:
    text = "\n".join(
        [
            "Шаг 2 из 5. Отправьте сферу деятельности текстом.",
            "",
            *_summary_lines(state, settings),
            "",
            "Отправьте одним сообщением список услуг или ниш через запятую.",
            "Пример: маникюр, педикюр, косметолог",
        ]
    )
    markup = {
        "inline_keyboard": [
            [
                {"text": "Назад", "callback_data": build_nav_callback("back")},
                {"text": "Сброс", "callback_data": build_nav_callback("reset")},
            ]
        ]
    }
    return text, markup


def _render_select_period(state: WizardState, settings: AppSettings) -> tuple[str, dict[str, Any]]:
    text = "\n".join(
        [
            "Шаг 3 из 5. Выберите период.",
            "",
            *_summary_lines(state, settings),
            "",
            "Кнопка «За всё время» собирает всю доступную историю в рамках лимитов источников.",
        ]
    )
    period_buttons = [
        {"text": format_period_label(period), "callback_data": build_period_callback(period)}
        for period in settings.runtime.period_options
    ]
    rows = _grid_buttons(period_buttons, columns=3)
    rows.append(
        [
            {"text": "Назад", "callback_data": build_nav_callback("back")},
            {"text": "Сброс", "callback_data": build_nav_callback("reset")},
        ]
    )
    return text, {"inline_keyboard": rows}


def _render_select_mode(state: WizardState, settings: AppSettings) -> tuple[str, dict[str, Any]]:
    text = "\n".join(
        [
            "Шаг 4 из 5. Выберите режим отчёта.",
            "",
            *_summary_lines(state, settings),
            "",
            "Можно посмотреть весь рынок или оставить только профили со средними и сильными официальными признаками.",
        ]
    )
    markup = {
        "inline_keyboard": [
            [
                {"text": "Все исполнители", "callback_data": build_mode_callback("all")},
                {"text": "Только официальные", "callback_data": build_mode_callback("official_only")},
            ],
            [
                {"text": "Назад", "callback_data": build_nav_callback("back")},
                {"text": "Сброс", "callback_data": build_nav_callback("reset")},
            ],
        ]
    }
    return text, markup


def _render_confirm(state: WizardState, settings: AppSettings) -> tuple[str, dict[str, Any]]:
    text = "\n".join(
        [
            "Шаг 5 из 5. Проверьте параметры и подтвердите запуск.",
            "",
            *_summary_lines(state, settings),
            "",
            "После запуска бот соберёт XLSX, PDF и технические листы для проверки качества.",
            "",
            f"Лимит строк: {state.top_n}",
        ]
    )
    markup = {
        "inline_keyboard": [
            [{"text": "Запустить", "callback_data": build_nav_callback("confirm")}],
            [
                {"text": "Изменить город", "callback_data": build_edit_callback("city")},
                {"text": "Изменить услуги", "callback_data": build_edit_callback("service")},
            ],
            [
                {"text": "Изменить период", "callback_data": build_edit_callback("period")},
                {"text": "Изменить режим", "callback_data": build_edit_callback("mode")},
            ],
            [{"text": "Сброс", "callback_data": build_nav_callback("reset")}],
        ]
    }
    return text, markup


def _render_running(state: WizardState, settings: AppSettings) -> tuple[str, dict[str, Any] | None]:
    text = "\n".join(
        [
            "Идёт сборка отчёта.",
            "",
            *_summary_lines(state, settings),
            "",
            "Сейчас выполняю:",
            "1. Ищу профили и business-card карточки",
            "2. Проверяю город, услугу и антишумовые признаки",
            "3. Считаю метрики и обогащаю данные",
            "4. Собираю Excel и PDF",
        ]
    )
    return text, None


def _render_done(state: WizardState, settings: AppSettings) -> tuple[str, dict[str, Any]]:
    text = "\n".join(
        [
            "Отчёт готов.",
            "",
            *_summary_lines(state, settings),
            "",
            "Файлы уже отправлены отдельными сообщениями. Можно повторить запуск или изменить отдельный параметр.",
        ]
    )
    markup = {
        "inline_keyboard": [
            [{"text": "Повторить", "callback_data": build_nav_callback("repeat")}],
            [
                {"text": "Сменить период", "callback_data": build_edit_callback("period")},
                {"text": "Сменить услугу", "callback_data": build_edit_callback("service")},
            ],
            [{"text": "Новый поиск", "callback_data": build_nav_callback("reset")}],
        ]
    }
    return text, markup


def _summary_lines(state: WizardState, settings: AppSettings) -> list[str]:
    services_label = "ожидает выбора"
    if state.services:
        services_label = summarize_services(state.services, settings.runtime.popular_services)
    period_label = "ожидает выбора"
    if state.period_days is not None:
        period_label = format_period_label(state.period_days)
    city_label = state.city or "ожидает выбора"
    mode_label = report_mode_label(state.report_mode) if state.report_mode is not None else "ожидает выбора"
    return [
        "Текущий выбор:",
        f"Город: {city_label}",
        f"Сфера: {services_label}",
        f"Период: {period_label}",
        f"Режим: {mode_label}",
    ]


def _grid_buttons(buttons: list[dict[str, str]], *, columns: int) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    current_row: list[dict[str, str]] = []
    for button in buttons:
        current_row.append(button)
        if len(current_row) >= max(columns, 1):
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return rows


def _service_columns(services: list[str]) -> int:
    if any(len(service.strip()) > 12 for service in services):
        return 1
    return 2


def _category_columns(sections: list[tuple[str, list[str]]]) -> int:
    if any(len(title.strip()) > 15 for title, _ in sections):
        return 1
    return 2


def _section_preview(services: list[str], *, limit: int = 3) -> str:
    preview = [_format_service_button_text(service).lower() for service in services[:limit]]
    if len(services) > limit:
        preview.append("и ещё")
    return ", ".join(preview)


def _format_service_button_text(service: str) -> str:
    label = service.strip()
    return label[:1].upper() + label[1:] if label else service
