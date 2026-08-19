from __future__ import annotations

import json
import socket
import unittest
from unittest.mock import Mock

from godmod.bot_commands import BOT_COMMANDS
from godmod.telegram_api import TelegramBotClient, _prefer_ipv4_results


class TelegramApiTests(unittest.TestCase):
    def test_set_my_commands_serializes_commands(self) -> None:
        client = TelegramBotClient("test-token")
        client._post_json = Mock(return_value={"result": True})

        result = client.set_my_commands(BOT_COMMANDS)

        self.assertTrue(result)
        client._post_json.assert_called_once_with(
            "setMyCommands",
            {"commands": json.dumps(BOT_COMMANDS, ensure_ascii=False)},
        )

    def test_delete_my_commands_calls_bot_api(self) -> None:
        client = TelegramBotClient("test-token")
        client._post_json = Mock(return_value={"result": True})

        result = client.delete_my_commands()

        self.assertTrue(result)
        client._post_json.assert_called_once_with("deleteMyCommands", {})

    def test_set_chat_menu_button_serializes_menu_button(self) -> None:
        client = TelegramBotClient("test-token")
        client._post_json = Mock(return_value={"result": True})

        result = client.set_chat_menu_button({"type": "commands"})

        self.assertTrue(result)
        client._post_json.assert_called_once_with(
            "setChatMenuButton",
            {"menu_button": json.dumps({"type": "commands"}, ensure_ascii=False)},
        )

    def test_delete_message_calls_bot_api(self) -> None:
        client = TelegramBotClient("test-token")
        client._post_json = Mock(return_value={"result": True})

        result = client.delete_message(11, 22)

        self.assertTrue(result)
        client._post_json.assert_called_once_with(
            "deleteMessage",
            {"chat_id": 11, "message_id": 22},
        )

    def test_prefer_ipv4_results_filters_target_host_when_ipv4_exists(self) -> None:
        ipv6_result = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0))
        ipv4_result = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("149.154.167.220", 443))

        result = _prefer_ipv4_results(
            "api.telegram.org",
            [ipv6_result, ipv4_result],
            hosts={"api.telegram.org"},
        )

        self.assertEqual(result, [ipv4_result])


if __name__ == "__main__":
    unittest.main()
