from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from godmod.config import RuntimeConfig
from godmod.max_target_state import load_last_max_target, remember_last_max_target, resolve_max_alert_target
from godmod.settings import AppSettings


class MaxTargetStateTests(unittest.TestCase):
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
        )

    def test_remember_and_resolve_last_max_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir) / "output")
            now = datetime(2026, 4, 19, 16, 0, tzinfo=UTC)

            remember_last_max_target(
                settings,
                chat_id="chat:456",
                user_id=123,
                update_type="message_created",
                now=now,
            )

            payload = load_last_max_target(settings)
            target = resolve_max_alert_target(settings)

        self.assertEqual(payload["chat_id"], "chat:456")
        self.assertEqual(payload["user_id"], "user:123")
        self.assertEqual(payload["preferred_alert_target"], "chat:456")
        self.assertEqual(payload["update_type"], "message_created")
        self.assertEqual(payload["updated_at"], now.isoformat())
        self.assertEqual(target, "chat:456")


if __name__ == "__main__":
    unittest.main()
