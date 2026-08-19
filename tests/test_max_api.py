from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from godmod.max_api import MaxApiError, MaxBotClient, _reply_markup_to_attachments, _target_query


class MaxApiTests(unittest.TestCase):
    def test_target_query_supports_user_and_chat_targets(self) -> None:
        self.assertEqual(_target_query("user:123"), {"user_id": "123"})
        self.assertEqual(_target_query("chat:456"), {"chat_id": "456"})
        self.assertEqual(_target_query(789), {"user_id": 789})

    def test_inline_keyboard_markup_converts_to_max_attachment(self) -> None:
        attachments = _reply_markup_to_attachments(
            {
                "inline_keyboard": [
                    [
                        {"text": "Запустить", "callback_data": "wiz:v1:nav:confirm"},
                        {"text": "Сайт", "url": "https://example.com"},
                    ]
                ]
            }
        )

        self.assertEqual(
            attachments,
            [
                {
                    "type": "inline_keyboard",
                    "payload": {
                        "buttons": [
                            [
                                {"type": "callback", "text": "Запустить", "payload": "wiz:v1:nav:confirm"},
                                {"type": "link", "text": "Сайт", "url": "https://example.com"},
                            ]
                        ]
                    },
                }
            ],
        )

    def test_inline_keyboard_markup_adds_max_city_and_service_icons(self) -> None:
        attachments = _reply_markup_to_attachments(
            {
                "inline_keyboard": [
                    [{"text": "Салехард", "callback_data": "wiz:v1:city:салехард"}],
                    [{"text": "Все сферы деятельности", "callback_data": "wiz:v1:service:all"}],
                    [{"text": "Маникюр", "callback_data": "wiz:v1:service:маникюр"}],
                    [{"text": "[Красота и уход]", "callback_data": "wiz:v1:category:красота-и-уход"}],
                ]
            }
        )

        buttons = attachments[0]["payload"]["buttons"]
        self.assertEqual(
            buttons[0][0],
            {"type": "callback", "text": "📍 Салехард", "payload": "wiz:v1:city:салехард"},
        )
        self.assertEqual(
            buttons[1][0],
            {"type": "callback", "text": "🧭 Все сферы деятельности", "payload": "wiz:v1:service:all"},
        )
        self.assertEqual(
            buttons[2][0],
            {"type": "callback", "text": "💅 Маникюр", "payload": "wiz:v1:service:маникюр"},
        )
        self.assertEqual(
            buttons[3][0],
            {"type": "callback", "text": "💅 [Красота и уход]", "payload": "wiz:v1:category:красота-и-уход"},
        )

    def test_reply_keyboard_markup_is_ignored_for_max(self) -> None:
        attachments = _reply_markup_to_attachments(
            {
                "keyboard": [
                    [{"text": "Старт"}, {"text": "Города"}],
                    [{"text": "Помощь"}, {"text": "Сброс"}],
                ]
            }
        )

        self.assertEqual(attachments, [])

    def test_inline_keyboard_markup_accepts_max_message_buttons(self) -> None:
        attachments = _reply_markup_to_attachments(
            {"inline_keyboard": [[{"type": "message", "text": "Выгрузка по судам"}]]}
        )

        buttons = attachments[0]["payload"]["buttons"]
        self.assertEqual(buttons[0][0], {"type": "message", "text": "Выгрузка по судам"})

    def test_inline_keyboard_markup_accepts_request_contact_buttons(self) -> None:
        attachments = _reply_markup_to_attachments(
            {"inline_keyboard": [[{"type": "request_contact", "text": "Поделиться контактом"}]]}
        )

        buttons = attachments[0]["payload"]["buttons"]
        self.assertEqual(buttons[0][0], {"type": "request_contact", "text": "Поделиться контактом"})

    def test_send_message_posts_max_message_payload(self) -> None:
        client = MaxBotClient("max-token")
        client._request_json = Mock(
            return_value={"message": {"body": {"mid": "mid-1"}}}
        )

        result = client.send_message(
            "chat:42",
            "Текст",
            reply_markup={"inline_keyboard": [[{"text": "ОК", "callback_data": "ok"}]]},
        )

        self.assertEqual(result["message_id"], "mid-1")
        client._request_json.assert_called_once()
        _, path = client._request_json.call_args.args
        self.assertEqual(path, "messages")
        self.assertEqual(client._request_json.call_args.kwargs["query"], {"chat_id": "42"})
        body = client._request_json.call_args.kwargs["json_body"]
        self.assertEqual(body["text"], "Текст")
        self.assertEqual(body["attachments"][0]["type"], "inline_keyboard")

    def test_clear_commands_patches_empty_max_command_menu(self) -> None:
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"success": True})

        client.clear_commands()

        client._request_json.assert_called_once_with("PATCH", "me", json_body={"commands": []})

    def test_send_document_retries_until_uploaded_file_is_ready(self) -> None:
        client = MaxBotClient("max-token", upload_ready_delay_seconds=0)
        client.upload_file = Mock(return_value={"token": "file-token"})
        client._send_message_payload = Mock(
            side_effect=[
                MaxApiError("attachment.not.ready"),
                {"message_id": "mid-2"},
            ]
        )

        with patch("godmod.max_api.time.sleep") as sleep:
            result = client.send_document("user:7", Path("output/test.xlsx"), caption="Отчёт")

        self.assertEqual(result["message_id"], "mid-2")
        sleep.assert_called_once()
        self.assertEqual(client._send_message_payload.call_count, 2)

    def test_request_json_wraps_timeout_as_network_error(self) -> None:
        client = MaxBotClient("max-token")

        with patch("godmod.max_api.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(MaxApiError) as ctx:
                client.send_message("chat:42", "Текст")

        self.assertIn("Network error", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
