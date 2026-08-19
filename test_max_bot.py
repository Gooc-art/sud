import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import max_bot
from godmod.config import DEFAULT_POPULAR_SERVICES, DEFAULT_YANAO_CITIES
from godmod.request_options import ALL_SERVICES_LABEL, expand_service_names
from godmod.settings import AppSettings


class MaxBotCompatibilityTests(unittest.TestCase):
    def test_wrapper_accepts_old_poll_flag(self):
        with patch.object(max_bot, "main", return_value=None) as main:
            with patch.object(sys, "argv", ["max_bot.py", "--poll"]):
                if "--poll" in sys.argv:
                    sys.argv.remove("--poll")
                max_bot.main()

        main.assert_called_once_with()

    def test_commerce_catalog_restored_from_godmod(self):
        self.assertIn("Тарко-Сале", DEFAULT_YANAO_CITIES)
        self.assertIn("общепит", DEFAULT_POPULAR_SERVICES)
        self.assertIn("салон красоты", DEFAULT_POPULAR_SERVICES)
        self.assertEqual(expand_service_names([ALL_SERVICES_LABEL], DEFAULT_POPULAR_SERVICES), DEFAULT_POPULAR_SERVICES)

    def test_settings_accept_old_max_env_names(self):
        env = {
            "MAX_TOKEN": "old-token",
            "SUD_ADMIN_USER_IDS": "42",
            "GODMOD_USE_MOCK_DATA": "false",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = AppSettings.from_env("/tmp/missing-sud-env")

        self.assertEqual(settings.max_bot_token, "old-token")
        self.assertEqual(settings.max_api_base, "https://platform-api.max.ru")
        self.assertEqual(settings.access_admin_user_ids, ["42"])
        self.assertFalse(settings.use_mock_data)


if __name__ == "__main__":
    unittest.main()
