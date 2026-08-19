from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from godmod.config import RuntimeConfig
from godmod.ops_health import (
    _determine_alert_action,
    _determine_notification_action,
    build_mac_ops_health_payload,
    format_mac_ops_health_summary,
    maybe_send_mac_ops_alert,
    write_mac_ops_health_snapshot,
)
from godmod.settings import AppSettings


class OpsHealthTests(unittest.TestCase):
    def _settings(self, output_dir: Path) -> AppSettings:
        return AppSettings(
            telegram_bot_token=None,
            telegram_allowed_chat_ids=[],
            telegram_api_id=None,
            telegram_api_hash=None,
            telegram_user_session=None,
            vk_api_token=None,
            vk_service_token="vk-service",
            vk_community_token=None,
            vk_profile_seeds_path=None,
            google_places_api_key=None,
            runtime=RuntimeConfig(output_dir=output_dir, cache_dir=output_dir / "cache"),
            use_mock_data=False,
            max_bot_token="max-token",
            max_allowed_chat_ids=[],
            max_health_alert_chat_id="chat:ops",
            mac_runner_dir=Path("/Users/goocbk.ru/actions-runner/godmod-prod"),
            mac_healthcheck_enabled=True,
            mac_healthcheck_interval_min=5,
            mac_health_log_stale_min=15,
            mac_health_disk_min_gb=10,
            mac_health_alert_cooldown_min=30,
            max_api_health_timeout_seconds=5,
        )

    def test_build_mac_ops_health_payload_collects_checks_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir) / "output")
            now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)

            with (
                patch("godmod.ops_health._launchd_service_status", return_value={"healthy": True, "summary": "ok"}),
                patch("godmod.ops_health._runner_status", return_value={"healthy": False, "summary": "runner down"}),
                patch("godmod.ops_health._max_api_status", return_value={"healthy": True, "summary": "HTTP 200"}),
                patch("godmod.ops_health._disk_status", return_value={"healthy": True, "summary": "disk ok"}),
                patch("godmod.ops_health._log_freshness_status", return_value={"healthy": False, "summary": "logs stale"}),
                patch(
                    "godmod.ops_health._latest_report_payload",
                    return_value={"available": True, "generated_at": "2026-04-19T11:55:00+00:00", "ranked_accounts": 7},
                ),
                patch("godmod.ops_health._host_metrics", return_value={"load_average": [0.1, 0.2, 0.3]}),
            ):
                payload = build_mac_ops_health_payload(settings, now=now)

        self.assertEqual(payload["overall_status"], "degraded")
        self.assertEqual(payload["overall_status_label"], "деградация")
        self.assertEqual(payload["failing_checks"], ["runner", "logs"])
        self.assertEqual(payload["failing_checks_label"], ["runner", "логи"])
        self.assertEqual(payload["alerting"]["target_chat_id"], "chat:ops")
        self.assertEqual(payload["alerting"]["mode"], "daily")
        self.assertEqual(payload["alerting"]["daily_schedule"]["timezone"], "Asia/Yekaterinburg")
        self.assertEqual(payload["latest_report"]["ranked_accounts"], 7)
        self.assertEqual(payload["host"]["load_average"], [0.1, 0.2, 0.3])

    def test_build_mac_ops_health_payload_uses_runtime_target_when_env_target_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir) / "output")
            settings.max_health_alert_chat_id = None
            now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)

            with (
                patch("godmod.ops_health._launchd_service_status", return_value={"healthy": True, "summary": "ok"}),
                patch("godmod.ops_health._runner_status", return_value={"healthy": True, "summary": "ok"}),
                patch("godmod.ops_health._max_api_status", return_value={"healthy": True, "summary": "HTTP 200"}),
                patch("godmod.ops_health._disk_status", return_value={"healthy": True, "summary": "disk ok"}),
                patch("godmod.ops_health._log_freshness_status", return_value={"healthy": True, "summary": "logs ok"}),
                patch("godmod.ops_health._latest_report_payload", return_value={"available": False}),
                patch("godmod.ops_health._host_metrics", return_value={}),
                patch("godmod.ops_health.resolve_max_alert_target", return_value="user:777"),
            ):
                payload = build_mac_ops_health_payload(settings, now=now)

        self.assertTrue(payload["alerting"]["enabled"])
        self.assertEqual(payload["alerting"]["target_chat_id"], "user:777")
        self.assertEqual(payload["alerting"]["target_source"], "runtime")

    def test_determine_alert_action_respects_cooldown_and_recovery(self) -> None:
        now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
        degraded_payload = {"overall_status": "degraded", "failing_checks": ["runner"]}
        healthy_payload = {"overall_status": "healthy", "failing_checks": []}

        self.assertEqual(
            _determine_alert_action({}, degraded_payload, current_time=now, cooldown_minutes=30),
            "degraded",
        )
        self.assertIsNone(
            _determine_alert_action(
                {
                    "overall_status": "degraded",
                    "failing_checks": ["runner"],
                    "last_alert_at": (now - timedelta(minutes=10)).isoformat(),
                },
                degraded_payload,
                current_time=now,
                cooldown_minutes=30,
            )
        )
        self.assertEqual(
            _determine_alert_action(
                {
                    "overall_status": "degraded",
                    "failing_checks": ["runner"],
                    "last_alert_at": (now - timedelta(minutes=45)).isoformat(),
                },
                degraded_payload,
                current_time=now,
                cooldown_minutes=30,
            ),
            "degraded",
        )
        self.assertEqual(
            _determine_alert_action(
                {
                    "overall_status": "degraded",
                    "failing_checks": ["runner"],
                    "last_alert_at": (now - timedelta(minutes=10)).isoformat(),
                },
                healthy_payload,
                current_time=now,
                cooldown_minutes=30,
            ),
            "recovered",
        )

    def test_determine_notification_action_sends_daily_status_once_after_ekb_schedule(self) -> None:
        settings = self._settings(Path("/tmp/output"))
        payload = {"overall_status": "healthy", "failing_checks": []}

        before_schedule = _determine_notification_action(
            settings,
            {},
            payload,
            current_time=datetime.fromisoformat("2026-04-19T02:59:00+00:00"),
        )
        first_after_schedule = _determine_notification_action(
            settings,
            {},
            payload,
            current_time=datetime.fromisoformat("2026-04-19T03:01:00+00:00"),
        )
        repeated_same_day = _determine_notification_action(
            settings,
            {"last_daily_status_at": "2026-04-19T03:01:00+00:00"},
            payload,
            current_time=datetime.fromisoformat("2026-04-19T08:30:00+00:00"),
        )

        self.assertIsNone(before_schedule)
        self.assertEqual(first_after_schedule, "daily_status")
        self.assertIsNone(repeated_same_day)

    def test_write_mac_ops_health_snapshot_writes_latest_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            settings = self._settings(output_dir)
            payload = {
                "generated_at": "2026-04-19T12:00:00+00:00",
                "overall_status": "healthy",
                "failing_checks": [],
            }

            snapshot_path = write_mac_ops_health_snapshot(settings, payload)

            latest_path = output_dir / "health" / "mac_health_latest.json"
            self.assertTrue(snapshot_path.exists())
            self.assertTrue(latest_path.exists())
            self.assertEqual(json.loads(latest_path.read_text(encoding="utf-8"))["overall_status"], "healthy")

    def test_log_freshness_stays_healthy_when_service_is_running_but_logs_are_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            stdout_log = output_dir / "stdout.log"
            stdout_log.write_text("boot\n", encoding="utf-8")
            old_now = datetime(2026, 4, 19, 12, 20, tzinfo=UTC)
            old_ts = datetime(2026, 4, 19, 12, 0, tzinfo=UTC).timestamp()
            stdout_log.touch()
            Path(stdout_log).stat()
            import os

            os.utime(stdout_log, (old_ts, old_ts))

            from godmod.ops_health import _log_freshness_status

            payload = _log_freshness_status(
                stdout_log,
                output_dir / "stderr.log",
                stale_minutes=15,
                now=old_now,
                service_running=True,
            )

        self.assertTrue(payload["healthy"])
        self.assertEqual(payload["summary"], "logs are quiet while service is running (1200s)")
        self.assertEqual(payload["summary_ru"], "логов давно не было, но сервис работает (1200 сек.)")

    def test_force_alert_sends_snapshot_to_runtime_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            settings = self._settings(output_dir)
            settings.max_health_alert_chat_id = None
            payload = {
                "generated_at": "2026-04-19T12:00:00+00:00",
                "overall_status": "healthy",
                "failing_checks": [],
                "checks": {},
                "host": {},
                "latest_report": {"available": False},
            }
            snapshot_path = write_mac_ops_health_snapshot(settings, payload)

            with (
                patch("godmod.ops_health.resolve_max_alert_target", return_value="chat:last"),
                patch("godmod.ops_health.MaxBotClient") as client_cls,
            ):
                result = maybe_send_mac_ops_alert(settings, payload, snapshot_path, force_alert=True)

        self.assertEqual(result["action"], "test")
        self.assertTrue(result["sent"])
        client_cls.assert_called_once_with("max-token", timeout=5)
        client_cls.return_value.send_document.assert_called_once()
        self.assertEqual(client_cls.return_value.send_document.call_args.args[0], "chat:last")
        self.assertEqual(client_cls.return_value.send_document.call_args.args[1], snapshot_path)

    def test_daily_status_sends_once_after_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            settings = self._settings(output_dir)
            payload = {
                "generated_at": "2026-04-19T05:01:00+00:00",
                "overall_status": "healthy",
                "failing_checks": [],
                "checks": {},
                "host": {},
                "latest_report": {"available": False},
            }
            snapshot_path = write_mac_ops_health_snapshot(settings, payload)

            with patch("godmod.ops_health.MaxBotClient") as client_cls:
                result = maybe_send_mac_ops_alert(
                    settings,
                    payload,
                    snapshot_path,
                    now=datetime.fromisoformat("2026-04-19T03:01:00+00:00"),
                )

        self.assertEqual(result["action"], "daily_status")
        self.assertTrue(result["sent"])
        client_cls.return_value.send_document.assert_called_once()

    def test_format_mac_ops_health_summary_uses_russian_labels(self) -> None:
        payload = {
            "overall_status": "healthy",
            "checks": {
                "bot_launchd": {"healthy": True, "summary": "service is running"},
                "runner": {"healthy": True, "summary": "runner service is healthy"},
                "max_api": {"healthy": True, "summary": "HTTP 404"},
                "disk": {"healthy": True, "summary": "free=174.97GB total=228.27GB threshold=10GB"},
                "logs": {"healthy": True, "summary": "last log update 9s ago"},
            },
            "host": {"hostname": "192.168.0.17"},
            "latest_report": {"available": True, "generated_at": "2026-04-18T11:54:45+00:00", "ranked_accounts": 0},
            "failing_checks": [],
        }

        summary = format_mac_ops_health_summary(
            payload,
            snapshot_path=Path("/tmp/mac_health.json"),
            alert_result={"action": "test"},
        )

        self.assertIn("Состояние mac mini: норма", summary)
        self.assertIn("Хост: 192.168.0.17", summary)
        self.assertIn("MAX-бот launchd: ок сервис запущен", summary)
        self.assertIn("Runner: ок runner работает", summary)
        self.assertIn("Диск: ок свободно=174.97GB всего=228.27GB порог=10GB", summary)
        self.assertIn("Логи: ок последнее обновление логов 9 сек. назад", summary)
        self.assertIn("Действие alert-контура: тестовое уведомление", summary)


if __name__ == "__main__":
    unittest.main()
