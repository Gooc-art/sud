from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from godmod.access_control import (
    approve_phone_access,
    authorize_user,
    deny_phone_access,
    extract_phone,
    is_authorized_user,
    load_authorized_users,
    normalize_phone,
    normalize_user_id,
    request_phone_access,
    verify_access_code,
)
from godmod.config import RuntimeConfig
from godmod.settings import AppSettings


class AccessControlTests(unittest.TestCase):
    def _settings(self, output_dir: Path) -> AppSettings:
        return AppSettings(
            telegram_bot_token="bot-token",
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
            bot_access_code="secret-pass",
        )

    def test_authorize_user_persists_access_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir) / "output")

            self.assertFalse(is_authorized_user(settings, 42))
            authorize_user(settings, user_id=42, chat_id=99)

            self.assertTrue(is_authorized_user(settings, 42))
            self.assertEqual(load_authorized_users(settings), {normalize_user_id(42)})

    def test_verify_access_code_requires_exact_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir) / "output")

            self.assertTrue(verify_access_code(settings, "secret-pass"))
            self.assertFalse(verify_access_code(settings, "wrong"))

    def test_phone_request_approve_authorizes_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir) / "output")

            request = request_phone_access(settings, user_id=42, chat_id="chat:99", phone="8 (912) 111-11-19")
            approved = approve_phone_access(settings, "user:42")

            self.assertEqual(request["phone"], "+79121111119")
            self.assertEqual(approved["chat_id"], "chat:99")
            self.assertTrue(is_authorized_user(settings, 42))

    def test_phone_request_deny_does_not_authorize_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir) / "output")

            request_phone_access(settings, user_id=42, chat_id="chat:99", phone="+7 932 058-81-50")
            denied = deny_phone_access(settings, 42)

            self.assertEqual(denied["phone"], "+79320588150")
            self.assertFalse(is_authorized_user(settings, 42))

    def test_extract_phone_normalizes_russian_number(self) -> None:
        self.assertEqual(extract_phone("мой номер 8 (912) 111-11-19"), "+79121111119")
        self.assertEqual(normalize_phone("+7 932 058-81-50"), "+79320588150")


if __name__ == "__main__":
    unittest.main()
