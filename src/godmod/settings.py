from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import RuntimeConfig
from .env import load_dotenv
from .rule_config import DEFAULT_RULE_CONFIG_PATH, load_rule_config


@dataclass(slots=True)
class AppSettings:
    telegram_bot_token: str | None
    telegram_allowed_chat_ids: list[int]
    telegram_api_id: int | None
    telegram_api_hash: str | None
    telegram_user_session: str | None
    vk_api_token: str | None
    vk_service_token: str | None
    vk_community_token: str | None
    vk_profile_seeds_path: Path | None
    google_places_api_key: str | None
    runtime: RuntimeConfig
    use_mock_data: bool
    max_bot_token: str | None = None
    max_api_base: str = "https://platform-api.max.ru"
    max_allowed_chat_ids: list[str] = field(default_factory=list)
    vk_full_recall: bool = False
    yandex_maps_api_key: str | None = None
    twogis_api_key: str | None = None
    telegram_profile_seeds_path: Path | None = None
    telegram_ephemeral_message_ttl_seconds: int = 20
    max_health_alert_chat_id: str | None = None
    mac_runner_dir: Path | None = None
    mac_healthcheck_enabled: bool = True
    mac_healthcheck_interval_min: int = 5
    mac_health_log_stale_min: int = 15
    mac_health_disk_min_gb: int = 10
    mac_health_alert_cooldown_min: int = 30
    mac_health_alert_mode: str = "daily"
    mac_daily_report_enabled: bool = True
    mac_daily_report_hour: int = 8
    mac_daily_report_minute: int = 0
    mac_daily_report_timezone: str = "Asia/Yekaterinburg"
    max_api_health_timeout_seconds: int = 10
    bot_access_code: str | None = None
    access_admin_user_ids: list[str] = field(default_factory=list)
    commerce_access_code: str | None = None

    @classmethod
    def from_env(cls, dotenv_path: str | Path = ".env") -> "AppSettings":
        env_file = load_dotenv(dotenv_path)

        def get(name: str, default: str | None = None) -> str | None:
            return os.environ.get(name, env_file.get(name, default))

        def first(*names: str, default: str | None = None) -> str | None:
            for name in names:
                value = get(name)
                if value is not None and value.strip():
                    return value
            return default

        output_dir = Path(get("GODMOD_OUTPUT_DIR", "output") or "output")
        cache_dir = Path(get("GODMOD_CACHE_DIR", str(output_dir / "cache")) or str(output_dir / "cache"))
        cache_enabled = (get("GODMOD_CACHE_ENABLED", "true") or "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        vk_wall_cache_ttl_hours = int(get("GODMOD_VK_WALL_CACHE_TTL_HOURS", "24") or "24")
        vk_owner_cache_ttl_hours = int(get("GODMOD_VK_OWNER_CACHE_TTL_HOURS", "72") or "72")
        vk_city_cache_ttl_hours = int(get("GODMOD_VK_CITY_CACHE_TTL_HOURS", "720") or "720")
        twogis_search_cache_ttl_hours = int(get("GODMOD_TWOGIS_SEARCH_CACHE_TTL_HOURS", "6") or "6")
        period_days = int(get("GODMOD_DEFAULT_PERIOD_DAYS", "60") or "60")
        top_n = int(get("GODMOD_DEFAULT_TOP_N", "20") or "20")
        raw_profile_seeds_path = get("GODMOD_VK_PROFILE_SEEDS_PATH", "data/vk_profile_seeds.json")
        profile_seeds_path = Path(raw_profile_seeds_path) if raw_profile_seeds_path else None
        raw_telegram_profile_seeds_path = get("GODMOD_TELEGRAM_PROFILE_SEEDS_PATH", "data/telegram_profile_seeds.json")
        telegram_profile_seeds_path = Path(raw_telegram_profile_seeds_path) if raw_telegram_profile_seeds_path else None
        raw_rule_config_path = get("GODMOD_RULE_CONFIG_PATH", str(DEFAULT_RULE_CONFIG_PATH))
        rule_config_path = Path(raw_rule_config_path) if raw_rule_config_path else None
        rule_config = load_rule_config(rule_config_path)
        vk_full_recall = (get("GODMOD_VK_FULL_RECALL", "false") or "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        mac_healthcheck_enabled = (get("GODMOD_MAC_HEALTHCHECK_ENABLED", "true") or "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        mac_daily_report_enabled = (get("GODMOD_MAC_DAILY_REPORT_ENABLED", "true") or "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        allowed_chat_ids = _parse_chat_ids(get("TELEGRAM_ALLOWED_CHAT_IDS", ""))
        max_allowed_chat_ids = _parse_text_ids(get("MAX_ALLOWED_CHAT_IDS", ""))
        use_mock_data = (get("GODMOD_USE_MOCK_DATA", "false") or "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        ephemeral_message_ttl_seconds = int(get("TELEGRAM_EPHEMERAL_MESSAGE_TTL_SECONDS", "20") or "20")
        raw_mac_runner_dir = get("GODMOD_MAC_RUNNER_DIR", "$HOME/actions-runner/godmod-prod")
        mac_runner_dir = _expand_path(raw_mac_runner_dir) if raw_mac_runner_dir else None
        mac_healthcheck_interval_min = int(get("GODMOD_MAC_HEALTHCHECK_INTERVAL_MIN", "5") or "5")
        mac_health_log_stale_min = int(get("GODMOD_MAC_HEALTH_LOG_STALE_MIN", "15") or "15")
        mac_health_disk_min_gb = int(get("GODMOD_MAC_HEALTH_DISK_MIN_GB", "10") or "10")
        mac_health_alert_cooldown_min = int(get("GODMOD_MAC_HEALTH_ALERT_COOLDOWN_MIN", "30") or "30")
        mac_health_alert_mode = _parse_mac_health_alert_mode(get("GODMOD_MAC_HEALTH_ALERT_MODE"))
        mac_daily_report_hour = int(get("GODMOD_MAC_DAILY_REPORT_HOUR", "8") or "8")
        mac_daily_report_minute = int(get("GODMOD_MAC_DAILY_REPORT_MINUTE", "0") or "0")
        mac_daily_report_timezone = (get("GODMOD_MAC_DAILY_REPORT_TIMEZONE", "Asia/Yekaterinburg") or "Asia/Yekaterinburg").strip()
        max_api_health_timeout_seconds = int(get("GODMOD_MAX_API_HEALTH_TIMEOUT_SECONDS", "10") or "10")
        bot_access_code = (get("GODMOD_BOT_ACCESS_CODE") or "").strip() or None
        commerce_access_code = (first("GODMOD_COMMERCE_ACCESS_CODE", "SUD_COMMERCE_ACCESS_CODE") or "").strip() or None
        access_admin_user_ids = _parse_text_ids(first("GODMOD_ACCESS_ADMIN_USER_IDS", "SUD_ADMIN_USER_IDS", default="6393482"))

        return cls(
            telegram_bot_token=(get("TELEGRAM_BOT_TOKEN") or "").strip() or None,
            telegram_allowed_chat_ids=allowed_chat_ids,
            telegram_api_id=_parse_optional_int(get("TELEGRAM_API_ID")),
            telegram_api_hash=(get("TELEGRAM_API_HASH") or "").strip() or None,
            telegram_user_session=(get("TELEGRAM_USER_SESSION") or "").strip() or None,
            max_bot_token=(first("MAX_BOT_TOKEN", "MAX_TOKEN") or "").strip() or None,
            max_allowed_chat_ids=max_allowed_chat_ids,
            vk_api_token=(get("VK_API_TOKEN") or "").strip() or None,
            vk_service_token=(get("VK_SERVICE_TOKEN") or "").strip() or None,
            vk_community_token=(get("VK_COMMUNITY_TOKEN") or "").strip() or None,
            vk_profile_seeds_path=profile_seeds_path,
            google_places_api_key=(get("GOOGLE_PLACES_API_KEY") or "").strip() or None,
            runtime=RuntimeConfig(
                output_dir=output_dir,
                cache_dir=cache_dir,
                cache_enabled=cache_enabled,
                vk_wall_cache_ttl_hours=vk_wall_cache_ttl_hours,
                vk_owner_cache_ttl_hours=vk_owner_cache_ttl_hours,
                vk_city_cache_ttl_hours=vk_city_cache_ttl_hours,
                twogis_search_cache_ttl_hours=twogis_search_cache_ttl_hours,
                default_period_days=period_days,
                default_top_n=top_n,
                rule_config_path=rule_config_path,
                rule_config=rule_config,
            ),
            use_mock_data=use_mock_data,
            max_api_base=(first("MAX_API_BASE", default="https://platform-api.max.ru") or "https://platform-api.max.ru").strip(),
            vk_full_recall=vk_full_recall,
            yandex_maps_api_key=(get("YANDEX_MAPS_API_KEY") or "").strip() or None,
            twogis_api_key=(get("TWOGIS_API_KEY") or "").strip() or None,
            telegram_profile_seeds_path=telegram_profile_seeds_path,
            telegram_ephemeral_message_ttl_seconds=max(0, ephemeral_message_ttl_seconds),
            max_health_alert_chat_id=(get("MAX_HEALTH_ALERT_CHAT_ID") or "").strip() or None,
            mac_runner_dir=mac_runner_dir,
            mac_healthcheck_enabled=mac_healthcheck_enabled,
            mac_healthcheck_interval_min=max(1, mac_healthcheck_interval_min),
            mac_health_log_stale_min=max(1, mac_health_log_stale_min),
            mac_health_disk_min_gb=max(1, mac_health_disk_min_gb),
            mac_health_alert_cooldown_min=max(1, mac_health_alert_cooldown_min),
            mac_health_alert_mode=mac_health_alert_mode,
            mac_daily_report_enabled=mac_daily_report_enabled,
            mac_daily_report_hour=min(23, max(0, mac_daily_report_hour)),
            mac_daily_report_minute=min(59, max(0, mac_daily_report_minute)),
            mac_daily_report_timezone=mac_daily_report_timezone or "Asia/Yekaterinburg",
            max_api_health_timeout_seconds=max(1, max_api_health_timeout_seconds),
            bot_access_code=bot_access_code,
            access_admin_user_ids=access_admin_user_ids,
            commerce_access_code=commerce_access_code,
        )

    @property
    def telegram_mtproto_ready(self) -> bool:
        return bool(self.telegram_api_id and self.telegram_api_hash and self.telegram_user_session)

    @property
    def google_places_ready(self) -> bool:
        return bool(self.google_places_api_key)

    @property
    def twogis_ready(self) -> bool:
        return bool(self.twogis_api_key)

    @property
    def yandex_maps_requested(self) -> bool:
        return bool(self.yandex_maps_api_key)


def _parse_chat_ids(raw_value: str | None) -> list[int]:
    if not raw_value:
        return []
    values: list[int] = []
    for item in raw_value.split(","):
        token = item.strip()
        if not token:
            continue
        values.append(int(token))
    return values


def _expand_path(raw_value: str) -> Path:
    home = str(Path.home())
    value = raw_value.replace("${HOME}", home).replace("$HOME", home)
    return Path(os.path.expandvars(value)).expanduser()


def _parse_text_ids(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _parse_optional_int(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    token = raw_value.strip()
    if not token:
        return None
    return int(token)


def _parse_mac_health_alert_mode(raw_value: str | None) -> str:
    token = (raw_value or "daily").strip().lower()
    if token in {"daily", "changes", "off"}:
        return token
    return "daily"
