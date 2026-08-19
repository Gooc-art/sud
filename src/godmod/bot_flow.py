from __future__ import annotations

from .bot_callbacks import WizardAction
from .bot_state import WizardState
from .markers import normalize_slug
from .request_options import expand_service_names, service_selection_section_by_token
from .settings import AppSettings


def apply_action(state: WizardState, action: WizardAction, settings: AppSettings) -> WizardState:
    if action.kind == "city":
        city = _match_token(action.value, settings.runtime.cities)
        if city is None:
            raise ValueError("Выбранный город больше недоступен.")
        state.city = city
        state.service_category = None
        state.services = []
        state.period_days = None
        state.report_mode = None
        state.step = "select_service"
        state.touch()
        return state

    if action.kind == "category":
        if not state.city:
            raise ValueError("Сначала выберите город.")
        if action.value.startswith("services:"):
            section = service_selection_section_by_token(settings.runtime.popular_services, action.value.removeprefix("services:"))
            if section is None:
                raise ValueError("Раздел услуг больше недоступен.")
            state.service_category = section[0]
            state.services = list(section[1])
            state.period_days = None
            state.report_mode = None
            state.step = "select_period"
            state.touch()
            return state
        if action.value == "all":
            state.service_category = None
            state.step = "select_service"
            state.touch()
            return state
        section = service_selection_section_by_token(settings.runtime.popular_services, action.value)
        if section is None:
            raise ValueError("Раздел услуг больше недоступен.")
        state.service_category = section[0]
        state.step = "select_service"
        state.touch()
        return state

    if action.kind == "service":
        if not state.city:
            raise ValueError("Сначала выберите город.")
        if action.value == "all":
            state.services = list(settings.runtime.popular_services)
        else:
            service = _match_token(action.value, settings.runtime.popular_services)
            if service is None:
                raise ValueError("Выбранная услуга больше недоступна.")
            state.services = expand_service_names([service], settings.runtime.popular_services)
        state.period_days = None
        state.report_mode = None
        state.step = "select_period"
        state.touch()
        return state

    if action.kind == "period":
        if not state.city or not state.services:
            raise ValueError("Сначала выберите город и услугу.")
        try:
            period_days = int(action.value)
        except ValueError as exc:
            raise ValueError("Период указан некорректно.") from exc
        if period_days not in settings.runtime.period_options:
            raise ValueError("Выбранный период больше недоступен.")
        state.period_days = period_days
        state.report_mode = None
        state.step = "select_mode"
        state.touch()
        return state

    if action.kind == "mode":
        if not state.city or not state.services or state.period_days is None:
            raise ValueError("Сначала выберите город, услугу и период.")
        if action.value not in {"all", "official_only"}:
            raise ValueError("Режим отчёта больше недоступен.")
        state.report_mode = action.value
        state.step = "confirm"
        state.touch()
        return state

    if action.kind == "edit":
        _apply_edit(state, action.value)
        state.touch()
        return state

    if action.kind == "nav":
        _apply_nav(state, action.value)
        state.touch()
        return state

    raise ValueError("Неизвестное действие.")


def apply_manual_services_input(state: WizardState, text: str, settings: AppSettings) -> WizardState:
    if state.step != "manual_service_input" or not state.city:
        raise ValueError("Сейчас ручной ввод услуг не ожидается.")
    services = expand_service_names(_split_csv(text), settings.runtime.popular_services)
    if not services:
        raise ValueError("Нужно отправить хотя бы одну услугу через запятую.")
    state.service_category = None
    state.services = services
    state.period_days = None
    state.report_mode = None
    state.step = "select_period"
    state.touch()
    return state


def can_confirm(state: WizardState) -> bool:
    return bool(state.city and state.services and state.report_mode) and state.period_days is not None


def _apply_edit(state: WizardState, field: str) -> None:
    if field == "city":
        state.step = "select_city"
        return
    if field == "service":
        if not state.city:
            raise ValueError("Сначала выберите город.")
        state.step = "select_service"
        return
    if field == "period":
        if not state.city or not state.services:
            raise ValueError("Сначала выберите город и услугу.")
        state.step = "select_period"
        return
    if field == "mode":
        if not state.city or not state.services or state.period_days is None:
            raise ValueError("Сначала выберите город, услугу и период.")
        state.step = "select_mode"
        return
    raise ValueError("Не удалось открыть выбранный шаг.")


def _apply_nav(state: WizardState, action: str) -> None:
    if action == "manual":
        if not state.city:
            raise ValueError("Сначала выберите город.")
        state.step = "manual_service_input"
        return
    if action == "reset":
        state.step = "select_city"
        state.city = None
        state.service_category = None
        state.services = []
        state.period_days = None
        state.report_mode = None
        return
    if action == "repeat":
        if not can_confirm(state):
            raise ValueError("Для повтора сначала соберите полный сценарий.")
        state.step = "confirm"
        return
    if action == "back":
        state.step = _previous_step(state.step)
        return
    if action == "confirm":
        if not can_confirm(state):
            raise ValueError("Сначала заполните все параметры отчёта.")
        return
    raise ValueError("Неизвестная навигационная кнопка.")


def _previous_step(step: str) -> str:
    mapping = {
        "select_city": "select_city",
        "select_service": "select_city",
        "manual_service_input": "select_service",
        "select_period": "select_service",
        "select_mode": "select_period",
        "confirm": "select_mode",
        "running": "confirm",
        "done": "confirm",
    }
    return mapping.get(step, "select_city")


def _match_token(token: str, values: list[str]) -> str | None:
    for value in values:
        if normalize_slug(value) == token:
            return value
    return None


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
