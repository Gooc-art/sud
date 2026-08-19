from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .markers import (
    DEFAULT_COMMERCIAL_MARKERS,
    DEFAULT_NOISE_MARKERS,
    HARD_NOISE_MARKERS,
    PET_GROOMING_MARKERS,
    PROVIDER_APPOINTMENT_MARKERS,
    SERVICE_RETAIL_MARKERS,
    SERVICE_TRAINING_MARKERS,
)


DEFAULT_RULE_CONFIG_PATH = Path("data/marker_rules.json")


@dataclass(slots=True)
class RuleConfig:
    commercial_markers: list[str] = field(default_factory=lambda: list(DEFAULT_COMMERCIAL_MARKERS))
    noise_markers: list[str] = field(default_factory=lambda: list(DEFAULT_NOISE_MARKERS))
    hard_noise_markers: list[str] = field(default_factory=lambda: list(HARD_NOISE_MARKERS))
    provider_appointment_markers: list[str] = field(default_factory=lambda: list(PROVIDER_APPOINTMENT_MARKERS))
    service_retail_markers: list[str] = field(default_factory=lambda: list(SERVICE_RETAIL_MARKERS))
    service_training_markers: list[str] = field(default_factory=lambda: list(SERVICE_TRAINING_MARKERS))
    pet_grooming_markers: list[str] = field(default_factory=lambda: list(PET_GROOMING_MARKERS))
    exclusion_markers: list[str] = field(
        default_factory=lambda: [
            "личный блог",
            "не услуги",
            "для души",
            "хобби",
        ]
    )
    commercial_marker_groups: dict[str, list[str]] = field(
        default_factory=lambda: {
            "prices": ["₽", "руб", "стоимость", "цена", "прайс", "1000р"],
            "booking": ["запись", "записаться", "окна", "свободно", "в личные сообщения", "dm"],
            "status": ["мастер", "студия", "салон", "услуги", "принимаю", "работаю"],
            "contacts": ["телефон", "+7", "8-", "whatsapp", "telegram", "пишите"],
            "reviews": ["отзыв", "спасибо за работу", "благодарность"],
        }
    )
    service_alias_overrides: dict[str, list[str]] = field(default_factory=dict)
    service_discovery_hint_overrides: dict[str, list[str]] = field(default_factory=dict)
    city_alias_overrides: dict[str, list[str]] = field(default_factory=dict)


def default_rule_config() -> RuleConfig:
    return RuleConfig()


def load_rule_config(path: str | Path | None) -> RuleConfig:
    if path is None:
        return default_rule_config()

    config_path = Path(path)
    if not config_path.exists():
        return default_rule_config()

    raw_data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        return default_rule_config()

    defaults = default_rule_config()
    return RuleConfig(
        commercial_markers=_string_list(raw_data.get("commercial_markers"), defaults.commercial_markers),
        noise_markers=_string_list(raw_data.get("noise_markers"), defaults.noise_markers),
        hard_noise_markers=_string_list(raw_data.get("hard_noise_markers"), defaults.hard_noise_markers),
        provider_appointment_markers=_string_list(
            raw_data.get("provider_appointment_markers"),
            defaults.provider_appointment_markers,
        ),
        service_retail_markers=_string_list(raw_data.get("service_retail_markers"), defaults.service_retail_markers),
        service_training_markers=_string_list(
            raw_data.get("service_training_markers"),
            defaults.service_training_markers,
        ),
        pet_grooming_markers=_string_list(raw_data.get("pet_grooming_markers"), defaults.pet_grooming_markers),
        exclusion_markers=_string_list(raw_data.get("exclusion_markers"), defaults.exclusion_markers),
        commercial_marker_groups=_string_map_of_lists(
            raw_data.get("commercial_marker_groups"),
            defaults.commercial_marker_groups,
        ),
        service_alias_overrides=_string_map_of_lists(
            raw_data.get("service_alias_overrides"),
            defaults.service_alias_overrides,
        ),
        service_discovery_hint_overrides=_string_map_of_lists(
            raw_data.get("service_discovery_hint_overrides"),
            defaults.service_discovery_hint_overrides,
        ),
        city_alias_overrides=_string_map_of_lists(
            raw_data.get("city_alias_overrides"),
            defaults.city_alias_overrides,
        ),
    )


def save_rule_config(path: str | Path, config: RuleConfig) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")


def merge_rule_config_alias_overrides(
    path: str | Path,
    *,
    service_alias_overrides: dict[str, list[str]] | None = None,
    service_discovery_hint_overrides: dict[str, list[str]] | None = None,
    city_alias_overrides: dict[str, list[str]] | None = None,
) -> RuleConfig:
    config = load_rule_config(path)
    config.service_alias_overrides = _merge_string_map_lists(config.service_alias_overrides, service_alias_overrides or {})
    config.service_discovery_hint_overrides = _merge_string_map_lists(
        config.service_discovery_hint_overrides,
        service_discovery_hint_overrides or {},
    )
    config.city_alias_overrides = _merge_string_map_lists(config.city_alias_overrides, city_alias_overrides or {})
    save_rule_config(path, config)
    return config


def _string_list(value: object, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    items = [str(item).strip() for item in value if str(item).strip()]
    return items or list(default)


def _string_map_of_lists(value: object, default: dict[str, list[str]]) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {key: list(items) for key, items in default.items()}
    result: dict[str, list[str]] = {}
    for key, items in value.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        result[normalized_key] = _string_list(items, default.get(normalized_key, []))
    return result or {key: list(items) for key, items in default.items()}


def _merge_string_map_lists(base: dict[str, list[str]], updates: dict[str, list[str]]) -> dict[str, list[str]]:
    merged = {key: list(values) for key, values in base.items()}
    for key, values in updates.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        existing = merged.setdefault(normalized_key, [])
        for value in values:
            normalized_value = str(value).strip()
            if normalized_value and normalized_value not in existing:
                existing.append(normalized_value)
    return merged
