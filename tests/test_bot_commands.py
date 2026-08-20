from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from godmod.bot_commands import BOT_COMMANDS, parse_command
from godmod.settings import AppSettings


class BotCommandTests(unittest.TestCase):
    def test_bot_commands_include_start_and_report(self) -> None:
        names = [item["command"] for item in BOT_COMMANDS]
        self.assertIn("start", names)
        self.assertIn("report", names)

    def test_parse_report_command(self) -> None:
        command = parse_command("/report Салехард,Новый Уренгой | маникюр,ремонт | 60 | 20")
        assert command is not None
        self.assertEqual(command.name, "report")
        self.assertEqual(command.args["cities"], ["Салехард", "Новый Уренгой"])
        self.assertEqual(command.args["services"], ["маникюр", "ремонт"])
        self.assertEqual(command.args["period_days"], 60)
        self.assertEqual(command.args["top_n"], 20)
        self.assertEqual(command.args["report_mode"], "all")

    def test_parse_report_command_with_official_mode(self) -> None:
        command = parse_command("/report Салехард | маникюр | 60 | 20 | official")
        assert command is not None
        self.assertEqual(command.name, "report")
        self.assertEqual(command.args["report_mode"], "official_only")

    def test_parse_start_command_with_bot_mention(self) -> None:
        command = parse_command("/start@godmod_test_bot")
        assert command is not None
        self.assertEqual(command.name, "start")

    def test_parse_report_command_with_bot_mention(self) -> None:
        command = parse_command("/report@godmod_test_bot Салехард | маникюр | 60 | 20")
        assert command is not None
        self.assertEqual(command.name, "report")
        self.assertEqual(command.args["cities"], ["Салехард"])
        self.assertEqual(command.args["services"], ["маникюр"])
        self.assertEqual(command.args["period_days"], 60)
        self.assertEqual(command.args["top_n"], 20)

    def test_parse_report_command_accepts_all_time_and_all_services(self) -> None:
        command = parse_command("/report Салехард | все сферы деятельности | 0 | 20")
        assert command is not None
        self.assertEqual(command.name, "report")
        self.assertEqual(command.args["services"], ["все сферы деятельности"])
        self.assertEqual(command.args["period_days"], 0)

    def test_parse_report_command_accepts_all_time_text_token(self) -> None:
        command = parse_command("/report Салехард | маникюр | за всё время | 20")
        assert command is not None
        self.assertEqual(command.args["period_days"], 0)

    def test_parse_markupplan_command_uses_defaults(self) -> None:
        command = parse_command("/markupplan")
        assert command is not None
        self.assertEqual(command.name, "markupplan")
        self.assertEqual(command.args["group_by"], "city")
        self.assertEqual(command.args["batch_size"], 10)
        self.assertEqual(command.args["max_batches"], 0)

    def test_parse_markupplan_command_accepts_explicit_args(self) -> None:
        command = parse_command("/markupplan service | 5 | 2")
        assert command is not None
        self.assertEqual(command.name, "markupplan")
        self.assertEqual(command.args["group_by"], "service")
        self.assertEqual(command.args["batch_size"], 5)
        self.assertEqual(command.args["max_batches"], 2)

    def test_parse_health_command(self) -> None:
        command = parse_command("/health")
        assert command is not None
        self.assertEqual(command.name, "health")

    def test_parse_access_command(self) -> None:
        command = parse_command("/access secret-pass")
        assert command is not None
        self.assertEqual(command.name, "access")
        self.assertEqual(command.args["code"], "secret-pass")

    def test_parse_dailyreport_command_with_bot_mention(self) -> None:
        command = parse_command("/dailyreport@godmod_test_bot")
        assert command is not None
        self.assertEqual(command.name, "dailyreport")

    def test_parse_lastreport_command_with_bot_mention(self) -> None:
        command = parse_command("/lastreport@godmod_test_bot")
        assert command is not None
        self.assertEqual(command.name, "lastreport")

    def test_parse_invalid_report_command_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_command("/report Салехард | маникюр | -7 | 20")


class SettingsTests(unittest.TestCase):
    def test_load_settings_from_dotenv(self) -> None:
        content = "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_CHAT_IDS=1,2,3",
                "TELEGRAM_API_ID=123456",
                "TELEGRAM_API_HASH=hash-value",
                "TELEGRAM_USER_SESSION=session-value",
                "MAX_BOT_TOKEN=max-token",
                "MAX_ALLOWED_CHAT_IDS=chat:100,user:200,300",
                "GODMOD_OUTPUT_DIR=test-output",
                "GODMOD_DEFAULT_PERIOD_DAYS=45",
                "GODMOD_DEFAULT_TOP_N=12",
                "VK_SERVICE_TOKEN=service-token",
                "VK_COMMUNITY_TOKEN=community-token",
                "GODMOD_USE_MOCK_DATA=true",
                "TELEGRAM_EPHEMERAL_MESSAGE_TTL_SECONDS=7",
                "YANDEX_MAPS_API_KEY=yandex-key",
                "TWOGIS_API_KEY=twogis-key",
                "MAX_HEALTH_ALERT_CHAT_ID=chat:ops",
                "GODMOD_MAC_RUNNER_DIR=$HOME/actions-runner/godmod-prod",
                "GODMOD_MAC_HEALTHCHECK_ENABLED=true",
                "GODMOD_MAC_HEALTHCHECK_INTERVAL_MIN=3",
                "GODMOD_MAC_HEALTH_LOG_STALE_MIN=9",
                "GODMOD_MAC_HEALTH_DISK_MIN_GB=12",
                "GODMOD_MAC_HEALTH_ALERT_COOLDOWN_MIN=45",
                "GODMOD_MAC_HEALTH_ALERT_MODE=daily",
                "GODMOD_MAC_DAILY_REPORT_ENABLED=true",
                "GODMOD_MAC_DAILY_REPORT_HOUR=8",
                "GODMOD_MAC_DAILY_REPORT_MINUTE=15",
                "GODMOD_MAC_DAILY_REPORT_TIMEZONE=Asia/Yekaterinburg",
                "GODMOD_MAX_API_HEALTH_TIMEOUT_SECONDS=6",
                "GODMOD_BOT_ACCESS_CODE=secret-pass",
                "GODMOD_ACCESS_ADMIN_USER_IDS=6393482",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv = Path(temp_dir) / ".env"
            dotenv.write_text(content, encoding="utf-8")
            settings = AppSettings.from_env(dotenv)
            self.assertEqual(settings.telegram_bot_token, "test-token")
            self.assertEqual(settings.telegram_allowed_chat_ids, [1, 2, 3])
            self.assertEqual(settings.telegram_api_id, 123456)
            self.assertEqual(settings.telegram_api_hash, "hash-value")
            self.assertEqual(settings.telegram_user_session, "session-value")
            self.assertTrue(settings.telegram_mtproto_ready)
            self.assertEqual(settings.max_bot_token, "max-token")
            self.assertEqual(settings.max_allowed_chat_ids, ["chat:100", "user:200", "300"])
            self.assertEqual(settings.runtime.output_dir, Path("test-output"))
            self.assertEqual(settings.runtime.cache_dir, Path("test-output/cache"))
            self.assertTrue(settings.runtime.cache_enabled)
            self.assertEqual(settings.runtime.vk_wall_cache_ttl_hours, 24)
            self.assertEqual(settings.runtime.vk_owner_cache_ttl_hours, 72)
            self.assertEqual(settings.runtime.vk_city_cache_ttl_hours, 720)
            self.assertEqual(settings.runtime.default_period_days, 45)
            self.assertEqual(settings.runtime.default_top_n, 12)
            self.assertEqual(settings.vk_service_token, "service-token")
            self.assertEqual(settings.vk_community_token, "community-token")
            self.assertEqual(settings.vk_profile_seeds_path, Path("data/vk_profile_seeds.json"))
            self.assertEqual(settings.telegram_profile_seeds_path, Path("data/telegram_profile_seeds.json"))
            self.assertTrue(settings.use_mock_data)
            self.assertEqual(settings.telegram_ephemeral_message_ttl_seconds, 7)
            self.assertEqual(settings.yandex_maps_api_key, "yandex-key")
            self.assertTrue(settings.yandex_maps_requested)
            self.assertEqual(settings.twogis_api_key, "twogis-key")
            self.assertTrue(settings.twogis_ready)
            self.assertEqual(settings.max_health_alert_chat_id, "chat:ops")
            self.assertEqual(settings.mac_runner_dir, Path.home() / "actions-runner/godmod-prod")
            self.assertTrue(settings.mac_healthcheck_enabled)
            self.assertEqual(settings.mac_healthcheck_interval_min, 3)
            self.assertEqual(settings.mac_health_log_stale_min, 9)
            self.assertEqual(settings.mac_health_disk_min_gb, 12)
            self.assertEqual(settings.mac_health_alert_cooldown_min, 45)
            self.assertEqual(settings.mac_health_alert_mode, "daily")
            self.assertTrue(settings.mac_daily_report_enabled)
            self.assertEqual(settings.mac_daily_report_hour, 8)
            self.assertEqual(settings.mac_daily_report_minute, 15)
            self.assertEqual(settings.mac_daily_report_timezone, "Asia/Yekaterinburg")
            self.assertEqual(settings.max_api_health_timeout_seconds, 6)
            self.assertEqual(settings.bot_access_code, "secret-pass")
            self.assertEqual(settings.access_admin_user_ids, ["6393482"])

    def test_load_settings_reads_cache_overrides(self) -> None:
        content = "\n".join(
            [
                "GODMOD_OUTPUT_DIR=test-output",
                "GODMOD_CACHE_DIR=custom-cache",
                "GODMOD_CACHE_ENABLED=false",
                "GODMOD_VK_WALL_CACHE_TTL_HOURS=6",
                "GODMOD_VK_OWNER_CACHE_TTL_HOURS=12",
                "GODMOD_VK_CITY_CACHE_TTL_HOURS=240",
                "GODMOD_TWOGIS_SEARCH_CACHE_TTL_HOURS=8",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv = Path(temp_dir) / ".env"
            dotenv.write_text(content, encoding="utf-8")
            settings = AppSettings.from_env(dotenv)

        self.assertEqual(settings.runtime.cache_dir, Path("custom-cache"))
        self.assertFalse(settings.runtime.cache_enabled)
        self.assertEqual(settings.runtime.vk_wall_cache_ttl_hours, 6)
        self.assertEqual(settings.runtime.vk_owner_cache_ttl_hours, 12)
        self.assertEqual(settings.runtime.vk_city_cache_ttl_hours, 240)
        self.assertEqual(settings.runtime.twogis_search_cache_ttl_hours, 8)

    def test_load_settings_defaults_access_admin_to_current_admin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv = Path(temp_dir) / ".env"
            dotenv.write_text("MAX_BOT_TOKEN=max-token\n", encoding="utf-8")
            settings = AppSettings.from_env(dotenv)

        self.assertEqual(settings.access_admin_user_ids, ["6393482"])


if __name__ == "__main__":
    unittest.main()
