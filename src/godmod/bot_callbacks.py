from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .markers import normalize_slug


WIZARD_CALLBACK_NAMESPACE = "wiz"
WIZARD_CALLBACK_VERSION = "v1"

WizardActionKind = Literal["city", "category", "service", "period", "mode", "nav", "edit"]


@dataclass(slots=True)
class WizardAction:
    kind: WizardActionKind
    value: str


def build_city_callback(city: str) -> str:
    return build_wizard_callback("city", normalize_slug(city))


def build_service_callback(service: str) -> str:
    return build_wizard_callback("service", normalize_slug(service))


def build_category_callback(category: str) -> str:
    return build_wizard_callback("category", normalize_slug(category))


def build_category_services_callback(category: str) -> str:
    return build_wizard_callback("category", f"services:{normalize_slug(category)}")


def build_period_callback(period_days: int) -> str:
    return build_wizard_callback("period", str(period_days))


def build_mode_callback(report_mode: str) -> str:
    return build_wizard_callback("mode", report_mode)


def build_nav_callback(action: str) -> str:
    return build_wizard_callback("nav", action)


def build_edit_callback(field: str) -> str:
    return build_wizard_callback("edit", field)


def build_wizard_callback(kind: WizardActionKind, value: str) -> str:
    return f"{WIZARD_CALLBACK_NAMESPACE}:{WIZARD_CALLBACK_VERSION}:{kind}:{value}"


def parse_wizard_callback(data: str) -> WizardAction | None:
    parts = data.split(":", 3)
    if len(parts) != 4:
        return None
    namespace, version, kind, value = parts
    if namespace != WIZARD_CALLBACK_NAMESPACE or version != WIZARD_CALLBACK_VERSION:
        return None
    if kind not in {"city", "category", "service", "period", "mode", "nav", "edit"}:
        return None
    if not value:
        return None
    return WizardAction(kind=kind, value=value)
