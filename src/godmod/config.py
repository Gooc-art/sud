from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .rule_config import RuleConfig, default_rule_config


DEFAULT_YANAO_CITIES = [
    "Салехард",
    "Новый Уренгой",
    "Ноябрьск",
    "Надым",
    "Муравленко",
    "Губкинский",
    "Лабытнанги",
    "Тарко-Сале",
    "Тазовский",
    "Яр-Сале",
    "Аксарка",
    "Харп",
    "Мужи",
    "Красноселькуп",
]

DEFAULT_POPULAR_SERVICES = [
    "маникюр",
    "педикюр",
    "салон красоты",
    "парикмахер",
    "барбершоп",
    "брови",
    "ресницы",
    "косметолог",
    "массаж",
    "общепит",
    "кафе",
    "кофейня",
    "ресторан",
    "пекарня",
    "доставка еды",
    "ремонт",
    "электрик",
    "сантехник",
    "фотограф",
    "автоэлектрик",
    "автосервис",
    "автомойка",
    "шиномонтаж",
    "грузоперевозки",
    "клининг",
    "химчистка",
    "репетитор",
    "стоматология",
    "фитнес",
    "юрист",
    "бухгалтер",
]

DEFAULT_PERIOD_OPTIONS = [30, 60, 90, 0]


@dataclass(slots=True)
class RuntimeConfig:
    output_dir: Path = Path("output")
    cache_dir: Path = Path("output/cache")
    cache_enabled: bool = True
    vk_wall_cache_ttl_hours: int = 24
    vk_owner_cache_ttl_hours: int = 72
    vk_city_cache_ttl_hours: int = 720
    twogis_search_cache_ttl_hours: int = 6
    report_prefix: str = "yanao_accounts"
    max_evidence_posts: int = 3
    default_period_days: int = 60
    default_top_n: int = 20
    rule_config_path: Path | None = None
    rule_config: RuleConfig = field(default_factory=default_rule_config)
    cities: list[str] = field(default_factory=lambda: list(DEFAULT_YANAO_CITIES))
    popular_services: list[str] = field(default_factory=lambda: list(DEFAULT_POPULAR_SERVICES))
    period_options: list[int] = field(default_factory=lambda: list(DEFAULT_PERIOD_OPTIONS))
