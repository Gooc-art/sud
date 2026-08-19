from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from godmod.access_control import is_authorized_user, request_phone_access
from godmod.config import RuntimeConfig
from godmod.bot_state import WIZARD_STATES, ensure_wizard_state
from godmod.export.reports import ReportArtifacts
from godmod.max_api import MaxApiError, MaxBotClient
from godmod.max_bot import (
    MAX_SCREEN_IDS,
    SUD_JOBS,
    SUD_SESSIONS,
    USER_MAX_SCREEN_IDS,
    SudJob,
    SudSession,
    _run_sud_job,
    handle_max_update,
    normalize_max_update,
)
from godmod.settings import AppSettings


def _max_contact_attachment(phone: str, token: str = "max-token", *, valid_hash: bool = True) -> dict:
    vcf_info = f"BEGIN:VCARD\r\nVERSION:3.0\r\nTEL;TYPE=cell:{phone}\r\nFN:Test User\r\nEND:VCARD\r\n"
    digest = hmac.new(token.encode("utf-8"), vcf_info.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "type": "contact",
        "payload": {
            "vcf_info": vcf_info,
            "vcf_phone": phone,
            "hash": digest if valid_hash else "bad-hash",
        },
    }


def _max_official_contact_attachment(phone: str, token: str = "max-token") -> dict:
    vcf_info = f"BEGIN:VCARD\\r\\nVERSION:3.0\\r\\nTEL;TYPE=cell:{phone}\\r\\nFN:Test User\\r\\nEND:VCARD\\r\\n"
    hash_vcf = vcf_info.replace("\\r\\n", "\r\n")
    digest = hmac.new(token.encode("utf-8"), hash_vcf.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "type": "contact",
        "payload": {
            "vcf_info": vcf_info,
            "hash": digest,
        },
    }


class MaxBotUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        MAX_SCREEN_IDS.clear()
        USER_MAX_SCREEN_IDS.clear()
        WIZARD_STATES.clear()
        SUD_SESSIONS.clear()
        SUD_JOBS.clear()
        Path("output/runtime/max_screen_ids.json").unlink(missing_ok=True)
        Path("output/runtime/max_update_trace.jsonl").unlink(missing_ok=True)

    def tearDown(self) -> None:
        MAX_SCREEN_IDS.clear()
        USER_MAX_SCREEN_IDS.clear()
        WIZARD_STATES.clear()
        SUD_SESSIONS.clear()
        SUD_JOBS.clear()
        Path("output/runtime/max_screen_ids.json").unlink(missing_ok=True)
        Path("output/runtime/max_update_trace.jsonl").unlink(missing_ok=True)

    def test_normalize_bot_started_opens_start_flow(self) -> None:
        update = {
            "update_type": "bot_started",
            "user": {"user_id": 123},
        }

        normalized = normalize_max_update(update)

        self.assertEqual(
            normalized,
            {
                "message": {
                    "chat": {"id": "user:123"},
                    "from": {"id": 123},
                    "text": "/start",
                }
            },
        )

    def test_normalize_message_created_uses_max_body_and_chat(self) -> None:
        update = {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 123},
                "recipient": {"chat_id": 456},
                "body": {"mid": "mid-1", "text": "Старт"},
            },
        }

        normalized = normalize_max_update(update)

        self.assertEqual(
            normalized,
            {
                "message": {
                    "chat": {"id": "chat:456"},
                    "from": {"id": 123},
                    "text": "Старт",
                    "message_id": "mid-1",
                }
            },
        )

    def test_normalize_message_callback_maps_payload_to_callback_query(self) -> None:
        update = {
            "update_type": "message_callback",
            "callback": {
                "callback_id": "cb-1",
                "payload": "wiz:v1:nav:confirm",
                "user": {"user_id": 123},
                "message": {
                    "recipient": {"chat_id": 456},
                    "body": {"mid": "mid-1"},
                },
            },
        }

        normalized = normalize_max_update(update)

        self.assertEqual(
            normalized,
            {
                "callback_query": {
                    "id": "cb-1",
                    "data": "wiz:v1:nav:confirm",
                    "from": {"id": 123},
                    "message": {
                        "chat": {"id": "chat:456"},
                        "message_id": "mid-1",
                    },
                }
            },
        )

    def test_normalize_message_callback_accepts_numeric_id_and_nested_payload(self) -> None:
        update = {
            "update_type": "message_callback",
            "callback": {
                "id": 42,
                "payload": {"data": "wiz:v1:city:салехард"},
                "user": {"user_id": 123},
                "message": {
                    "recipient": {"chat_id": 456},
                    "body": {"mid": "mid-2"},
                },
            },
        }

        normalized = normalize_max_update(update)

        self.assertEqual(
            normalized,
            {
                "callback_query": {
                    "id": "42",
                    "data": "wiz:v1:city:салехард",
                    "from": {"id": 123},
                    "message": {
                        "chat": {"id": "chat:456"},
                        "message_id": "mid-2",
                    },
                }
            },
        )

    def test_handle_max_update_denies_unlisted_target(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output")),
            use_mock_data=False,
            max_bot_token="max-token",
            max_allowed_chat_ids=["chat:999"],
        )
        client = Mock()

        handle_max_update(
            client,
            settings,
            {
                "update_type": "message_created",
                "message": {
                    "sender": {"user_id": 123},
                    "recipient": {"chat_id": 456},
                    "body": {"mid": "mid-1", "text": "Старт"},
                },
            },
        )

        client.send_message.assert_called_once_with("chat:456", "Этот чат не разрешён для запуска отчётов.")

    def test_handle_max_update_passes_regular_text_to_shared_bot_handler(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output")),
            use_mock_data=False,
            max_bot_token="max-token",
            max_allowed_chat_ids=["456"],
        )
        client = Mock()
        update = {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 123},
                "recipient": {"chat_id": 456},
                "body": {"mid": "mid-1", "text": "нестандартная услуга"},
            },
        }

        with patch("godmod.max_bot.handle_update") as handle_update, patch(
            "godmod.max_bot.remember_last_max_target"
        ) as remember_last_max_target:
            handle_max_update(client, settings, update)

        remember_last_max_target.assert_called_once_with(
            settings,
            chat_id="chat:456",
            user_id=123,
            update_type="message_created",
        )
        handle_update.assert_called_once()
        self.assertEqual(handle_update.call_args.args[2]["message"]["chat"]["id"], "chat:456")

    def test_bot_started_does_not_send_user_target_home_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"message": {"body": {"mid": "home-1"}}})

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "bot_started",
                    "user": {"user_id": 123},
                },
            )

        client._request_json.assert_called_once()
        self.assertEqual(client._request_json.call_args.args[:2], ("POST", "messages"))
        body = client._request_json.call_args.kwargs["json_body"]
        labels = [button["text"] for row in body["attachments"][0]["payload"]["buttons"] for button in row]
        self.assertEqual(labels, ["🏢 Выгрузка по коммерции", "⚖️ Выгрузка по судам", "ℹ️ Помощь"])

    def test_repeated_start_replaces_remembered_max_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(
            side_effect=[
                {"message": {"body": {"mid": "home-1"}}},
                {"success": True},
                {"message": {"body": {"mid": "home-2"}}},
            ]
        )

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(client, settings, {"update_type": "bot_started", "user": {"user_id": 123}})
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "user-start-1", "text": "Старт"},
                    },
                },
            )

        calls = client._request_json.call_args_list
        self.assertEqual(calls[0].args[:2], ("POST", "messages"))
        self.assertEqual(calls[0].kwargs["query"], {"user_id": "123"})
        self.assertEqual(calls[1].args[:2], ("DELETE", "messages"))
        self.assertEqual(calls[1].kwargs["query"], {"message_id": "home-1"})
        self.assertEqual(calls[2].args[:2], ("POST", "messages"))
        self.assertEqual(calls[2].kwargs["query"], {"chat_id": "456"})

    def test_repeated_bot_started_edits_remembered_user_home_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        MAX_SCREEN_IDS[("user:123", 123)] = "home-1"
        USER_MAX_SCREEN_IDS[123] = "home-1"
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"message": {"body": {"mid": "home-1"}}})

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(client, settings, {"update_type": "bot_started", "user": {"user_id": 123}})

        client._request_json.assert_called_once()
        self.assertEqual(client._request_json.call_args.args[:2], ("PUT", "messages"))
        self.assertEqual(client._request_json.call_args.kwargs["query"], {"message_id": "home-1"})
        self.assertEqual(MAX_SCREEN_IDS[("user:123", 123)], "home-1")
        self.assertEqual(USER_MAX_SCREEN_IDS[123], "home-1")

    def test_commerce_button_opens_one_wizard_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(
            side_effect=[
                {"message": {"body": {"mid": "home-1"}}},
                {"success": True},
            ]
        )

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-commerce",
                        "payload": "max:commerce",
                        "user": {"user_id": 123},
                        "message": {
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "home-1"},
                        },
                    },
                },
            )

        edit_call = client._request_json.call_args_list[0]
        self.assertEqual(edit_call.args[:2], ("PUT", "messages"))
        body = edit_call.kwargs["json_body"]
        buttons = body["attachments"][0]["payload"]["buttons"]
        labels = [button["text"] for row in buttons for button in row]
        self.assertNotIn("Выгрузка по коммерции", labels)
        self.assertNotIn("Выгрузка по судам", labels)
        self.assertIn("📍 Салехард", labels)
        self.assertIn("⬅️ Назад в главное меню", labels)

    def test_text_commerce_reuses_remembered_max_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        MAX_SCREEN_IDS[("chat:456", 123)] = "home-1"
        USER_MAX_SCREEN_IDS[123] = "home-1"
        client._request_json = Mock(return_value={"message": {"body": {"mid": "home-1"}}})

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "user-commerce-1", "text": "Выгрузка по коммерции"},
                    },
                },
            )

        self.assertEqual(client._request_json.call_args.args[:2], ("PUT", "messages"))
        self.assertEqual(client._request_json.call_args.kwargs["query"], {"message_id": "home-1"})

    def test_start_ignores_user_only_persisted_max_screen_after_restart(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        Path("output/runtime").mkdir(parents=True, exist_ok=True)
        Path("output/runtime/max_screen_ids.json").write_text(
            '{"screen_by_pair": {}, "screen_by_user": {"123": "home-1"}}',
            encoding="utf-8",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"message": {"body": {"mid": "home-1"}}})

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "user-start-1", "text": "Старт"},
                    },
                },
            )

        calls = client._request_json.call_args_list
        self.assertEqual(calls[0].args[:2], ("DELETE", "messages"))
        self.assertEqual(calls[0].kwargs["query"], {"message_id": "home-1"})
        self.assertEqual(calls[1].args[:2], ("POST", "messages"))
        self.assertEqual(calls[1].kwargs["query"], {"chat_id": "456"})

    def test_case_variant_start_is_handled_by_max_home_router(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"message": {"body": {"mid": "home-1"}}})

        with patch("godmod.max_bot.handle_update") as handle_update, patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "user-start-1", "text": "/START@GodmodBot"},
                    },
                },
            )

        handle_update.assert_not_called()
        self.assertEqual(client._request_json.call_args.args[:2], ("POST", "messages"))
        body = client._request_json.call_args.kwargs["json_body"]
        labels = [button["text"] for row in body["attachments"][0]["payload"]["buttons"] for button in row]
        self.assertEqual(labels, ["🏢 Выгрузка по коммерции", "⚖️ Выгрузка по судам", "ℹ️ Помощь"])

    def test_begin_text_is_handled_by_max_home_router(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"message": {"body": {"mid": "home-1"}}})

        with patch("godmod.max_bot.handle_update") as handle_update, patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "user-start-1", "text": "Начать"},
                    },
                },
            )

        handle_update.assert_not_called()
        body = client._request_json.call_args.kwargs["json_body"]
        labels = [button["text"] for row in body["attachments"][0]["payload"]["buttons"] for button in row]
        self.assertEqual(labels, ["🏢 Выгрузка по коммерции", "⚖️ Выгрузка по судам", "ℹ️ Помощь"])

    def test_start_deletes_stale_user_screen_and_edits_current_chat_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        MAX_SCREEN_IDS[("chat:456", 123)] = "chat-home"
        MAX_SCREEN_IDS[("user:123", 123)] = "user-home"
        USER_MAX_SCREEN_IDS[123] = "user-home"
        client = MaxBotClient("max-token")
        client._request_json = Mock(side_effect=[{"success": True}, {"message": {"body": {"mid": "chat-home"}}}])

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "user-start-1", "text": "Начать"},
                    },
                },
            )

        calls = client._request_json.call_args_list
        self.assertEqual(calls[0].args[:2], ("DELETE", "messages"))
        self.assertEqual(calls[0].kwargs["query"], {"message_id": "user-home"})
        self.assertEqual(calls[1].args[:2], ("PUT", "messages"))
        self.assertEqual(calls[1].kwargs["query"], {"message_id": "chat-home"})
        self.assertNotIn("user-home", set(MAX_SCREEN_IDS.values()) | set(USER_MAX_SCREEN_IDS.values()))
        self.assertEqual(set(MAX_SCREEN_IDS.values()), {"chat-home"})
        self.assertEqual(set(USER_MAX_SCREEN_IDS.values()), {"chat-home"})

    def test_max_update_trace_records_start_handler_and_target(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"message": {"body": {"mid": "home-1"}}})

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(client, settings, {"update_type": "bot_started", "user": {"user_id": 123}})

        record = json.loads(Path("output/runtime/max_update_trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(record["raw_update_type"], "bot_started")
        self.assertEqual(record["handler"], "max_home")
        self.assertEqual(record["chat_id"], "user:123")
        self.assertEqual(record["user_id"], 123)
        self.assertEqual(record["action"], "/start")

    def test_shared_max_transient_message_has_no_menu_buttons(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"message": {"body": {"mid": "transient-1"}}})

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "user-unknown-1", "text": "/unknown"},
                    },
                },
            )

        body = client._request_json.call_args.kwargs["json_body"]
        self.assertNotIn("attachments", body)

    def test_stale_max_menu_callback_deletes_old_and_replaces_current_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(
            side_effect=[
                {"success": True},
                {"success": True},
                {"message": {"body": {"mid": "home-2"}}},
                {"success": True},
            ]
        )
        MAX_SCREEN_IDS[("chat:456", 123)] = "current-1"
        USER_MAX_SCREEN_IDS[123] = "current-1"

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-main",
                        "payload": "max:main",
                        "user": {"user_id": 123},
                        "message": {
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "old-menu-1"},
                        },
                    },
                },
            )

        calls = client._request_json.call_args_list
        self.assertIn(("DELETE", "messages", {"message_id": "old-menu-1"}), [(call.args[0], call.args[1], call.kwargs["query"]) for call in calls])
        self.assertIn(("PUT", "messages", {"message_id": "current-1"}), [(call.args[0], call.args[1], call.kwargs["query"]) for call in calls])
        self.assertNotIn(("POST", "messages", {"chat_id": "456"}), [(call.args[0], call.args[1], call.kwargs["query"]) for call in calls])

    def test_back_to_main_replaces_current_flow_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(side_effect=[{"message": {"body": {"mid": "flow-1"}}}, {"success": True}])

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-main",
                        "payload": "max:main",
                        "user": {"user_id": 123},
                        "message": {
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "flow-1"},
                        },
                    },
                },
            )

        client._request_json.assert_any_call(
            "PUT",
            "messages",
            query={"message_id": "flow-1"},
            json_body=unittest.mock.ANY,
        )
        body = client._request_json.call_args_list[0].kwargs["json_body"]
        labels = [button["text"] for row in body["attachments"][0]["payload"]["buttons"] for button in row]
        self.assertEqual(labels, ["🏢 Выгрузка по коммерции", "⚖️ Выгрузка по судам", "ℹ️ Помощь"])

    def test_handle_max_update_handles_court_button_before_shared_handler(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output")),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = Mock()

        with patch("godmod.max_bot.handle_update") as handle_update, patch(
            "godmod.max_bot.remember_last_max_target"
        ):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "mid-1", "text": "Выгрузка по судам"},
                    },
                },
            )

        handle_update.assert_not_called()
        client.send_message.assert_called_once()
        self.assertEqual(client.send_message.call_args.args[0], "chat:456")
        self.assertIn("судебным заседаниям", client.send_message.call_args.args[1])

    def test_court_flow_reuses_one_sud_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output")),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = Mock()
        client.send_message.return_value = {"message_id": "sud-1"}

        with patch("godmod.max_bot.handle_update"), patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "user-1", "text": "Выгрузка по судам"},
                    },
                },
            )
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-1",
                        "payload": "sud:month",
                        "user": {"user_id": 123},
                        "message": {
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "sud-1"},
                        },
                    },
                },
            )

        client.send_message.assert_called_once()
        client.edit_message_text.assert_called_once()
        self.assertEqual(client.edit_message_text.call_args.args[:2], ("chat:456", "sud-1"))

    def test_handle_max_update_keeps_regular_wizard_callbacks_shared(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output")),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = Mock()

        with patch("godmod.max_bot.handle_update") as handle_update, patch(
            "godmod.max_bot.remember_last_max_target"
        ):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-1",
                        "payload": "wiz:v1:nav:confirm",
                        "user": {"user_id": 123},
                        "message": {
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "mid-1"},
                        },
                    },
                },
            )

        handle_update.assert_called_once()

    def test_max_wizard_callback_edits_current_screen_without_posting_city_menu(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард", "Ноябрьск"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"success": True})
        MAX_SCREEN_IDS[("chat:456", 123)] = "current-1"
        USER_MAX_SCREEN_IDS[123] = "current-1"

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-city",
                        "payload": "wiz:v1:city:салехард",
                        "user": {"user_id": 123},
                        "message": {
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "current-1"},
                        },
                    },
                },
            )

        api_calls = [(call.args[0], call.args[1], call.kwargs.get("query")) for call in client._request_json.call_args_list]
        self.assertIn(("PUT", "messages", {"message_id": "current-1"}), api_calls)
        self.assertNotIn(("POST", "messages", {"chat_id": "456"}), api_calls)

    def test_max_confirm_replaces_confirm_buttons_with_running_screen_and_main_menu(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        state = ensure_wizard_state("chat:456", 123, default_top_n=20, wizard_message_id="current-1")
        state.city = "Салехард"
        state.services = ["маникюр"]
        state.period_days = 30
        state.report_mode = "all"
        state.step = "confirm"
        MAX_SCREEN_IDS[("chat:456", 123)] = "current-1"
        USER_MAX_SCREEN_IDS[123] = "current-1"
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"success": True})

        with patch("godmod.max_bot.remember_last_max_target"), patch(
            "godmod.bot.generate_report",
            return_value=ReportArtifacts(workbook=Path("output/test.xlsx"), pdf=None, manifest=Path("output/test.json")),
        ), patch("godmod.bot._send_report_artifacts"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-confirm",
                        "payload": "wiz:v1:nav:confirm",
                        "user": {"user_id": 123},
                        "message": {
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "current-1"},
                        },
                    },
                },
            )

        running_edit = client._request_json.call_args_list[0]
        self.assertEqual(running_edit.args[:2], ("PUT", "messages"))
        self.assertEqual(running_edit.kwargs["query"], {"message_id": "current-1"})
        body = running_edit.kwargs["json_body"]
        self.assertIn("Идёт сборка отчёта.", body["text"])
        buttons = body["attachments"][0]["payload"]["buttons"]
        self.assertEqual(buttons, [[{"type": "callback", "text": "⬅️ Назад в главное меню", "payload": "max:main"}]])

    def test_stale_max_wizard_callback_deletes_old_screen_and_edits_current_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард", "Ноябрьск"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"success": True})
        MAX_SCREEN_IDS[("chat:456", 123)] = "current-1"
        USER_MAX_SCREEN_IDS[123] = "current-1"

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-city",
                        "payload": "wiz:v1:city:салехард",
                        "user": {"user_id": 123},
                        "message": {
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "old-city-menu"},
                        },
                    },
                },
            )

        api_calls = [(call.args[0], call.args[1], call.kwargs.get("query")) for call in client._request_json.call_args_list]
        self.assertIn(("DELETE", "messages", {"message_id": "old-city-menu"}), api_calls)
        self.assertIn(("PUT", "messages", {"message_id": "current-1"}), api_calls)
        self.assertNotIn(("POST", "messages", {"chat_id": "456"}), api_calls)

    def test_chat_pair_screen_wins_over_user_screen(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард", "Ноябрьск"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"success": True})
        MAX_SCREEN_IDS[("chat:456", 123)] = "old-city-menu"
        USER_MAX_SCREEN_IDS[123] = "current-home"

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-city",
                        "payload": "wiz:v1:city:салехард",
                        "user": {"user_id": 123},
                        "message": {
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "old-city-menu"},
                        },
                    },
                },
            )

        api_calls = [(call.args[0], call.args[1], call.kwargs.get("query")) for call in client._request_json.call_args_list]
        self.assertIn(("PUT", "messages", {"message_id": "old-city-menu"}), api_calls)
        self.assertNotIn(("PUT", "messages", {"message_id": "current-home"}), api_calls)
        self.assertNotIn(("POST", "messages", {"chat_id": "456"}), api_calls)

    def test_text_reset_replaces_persisted_max_screen_after_restart(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output"), cities=["Салехард"]),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        Path("output/runtime").mkdir(parents=True, exist_ok=True)
        Path("output/runtime/max_screen_ids.json").write_text(
            '{"screen_by_pair": {}, "screen_by_user": {"123": "current-1"}}',
            encoding="utf-8",
        )
        client = MaxBotClient("max-token")
        client._request_json = Mock(return_value={"message": {"body": {"mid": "current-1"}}})

        with patch("godmod.max_bot.remember_last_max_target"):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "user-reset-1", "text": "Сброс"},
                    },
                },
            )

        api_calls = [(call.args[0], call.args[1], call.kwargs.get("query")) for call in client._request_json.call_args_list]
        self.assertIn(("DELETE", "messages", {"message_id": "current-1"}), api_calls)
        self.assertIn(("POST", "messages", {"chat_id": "456"}), api_calls)

    def test_handle_max_update_starts_court_job_on_confirm(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output")),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = Mock()
        SUD_SESSIONS[("chat:456", 123)] = session = SudSession()
        session.date_from = date(2026, 7, 1)
        session.date_to = date(2026, 7, 2)
        session.court = "salehardsky--ynao.sudrf.ru"
        session.step = "confirm"

        with patch("godmod.max_bot.handle_update") as handle_update, patch(
            "godmod.max_bot.remember_last_max_target"
        ), patch("godmod.max_bot.try_acquire_report_run", return_value=(Mock(lock_id="lock-1"), None)), patch(
            "godmod.max_bot.threading.Thread"
        ) as thread_cls:
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-2",
                        "payload": "sud:run",
                        "user": {"user_id": 123},
                        "message": {
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "mid-1"},
                        },
                    },
                },
            )

        handle_update.assert_not_called()
        thread_cls.assert_called_once()
        thread_cls.return_value.start.assert_called_once()
        self.assertEqual(len(SUD_JOBS), 1)

    def test_handle_max_update_blocks_court_flow_without_access_code(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output")),
            use_mock_data=False,
            max_bot_token="max-token",
            bot_access_code="secret",
        )
        client = Mock()

        with patch("godmod.max_bot.handle_update") as handle_update, patch(
            "godmod.max_bot.remember_last_max_target"
        ):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "mid-1", "text": "Выгрузка по судам"},
                    },
                },
            )

        handle_update.assert_not_called()
        self.assertIn("Доступ закрыт", client.send_message.call_args.args[1])

    def test_handle_max_update_sends_verified_contact_access_request_to_admins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=Path(tmp) / "output"),
                use_mock_data=False,
                max_bot_token="max-token",
                bot_access_code="secret",
                access_admin_user_ids=["23325864"],
            )
            client = Mock()

            with patch("godmod.max_bot.handle_update") as handle_update, patch("godmod.max_bot.remember_last_max_target"):
                handle_max_update(
                    client,
                    settings,
                    {
                        "update_type": "message_created",
                        "message": {
                            "sender": {"user_id": 123},
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "mid-1", "attachments": [_max_contact_attachment("79991234567")]},
                        },
                    },
                )

            handle_update.assert_not_called()
            targets = [call.args[0] for call in client.send_message.call_args_list]
            self.assertIn("23325864", targets)
            self.assertIn("chat:456", targets)
            admin_call = next(call for call in client.send_message.call_args_list if call.args[0] == "23325864")
            self.assertIn("Телефон: +79991234567", admin_call.args[1])
            self.assertEqual(admin_call.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "access:approve:user:123")
            self.assertEqual(admin_call.kwargs["reply_markup"]["inline_keyboard"][0][0]["text"], "✅ Разрешить")
            self.assertEqual(admin_call.kwargs["reply_markup"]["inline_keyboard"][0][1]["text"], "❌ Отказать")

    def test_handle_max_update_rejects_plain_text_phone_for_access_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=Path(tmp) / "output"),
                use_mock_data=False,
                max_bot_token="max-token",
                access_admin_user_ids=["23325864"],
            )
            client = Mock()

            with patch("godmod.max_bot.handle_update") as handle_update, patch("godmod.max_bot.remember_last_max_target"):
                handle_max_update(
                    client,
                    settings,
                    {
                        "update_type": "message_created",
                        "message": {
                            "sender": {"user_id": 123},
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "mid-1", "text": "+7 999 123-45-67"},
                        },
                    },
                )

            handle_update.assert_not_called()
            targets = [call.args[0] for call in client.send_message.call_args_list]
            self.assertEqual(targets, ["chat:456"])
            self.assertFalse((Path(tmp) / "output" / "runtime" / "bot_access_state.json").exists())
            self.assertEqual(client.send_message.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["type"], "request_contact")

    def test_handle_max_update_rejects_contact_with_bad_hash_for_access_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=Path(tmp) / "output"),
                use_mock_data=False,
                max_bot_token="max-token",
                access_admin_user_ids=["23325864"],
            )
            client = Mock()

            with patch("godmod.max_bot.handle_update") as handle_update, patch("godmod.max_bot.remember_last_max_target"):
                handle_max_update(
                    client,
                    settings,
                    {
                        "update_type": "message_created",
                        "message": {
                            "sender": {"user_id": 123},
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "mid-1", "attachments": [_max_contact_attachment("79991234567", valid_hash=False)]},
                        },
                    },
                )

            handle_update.assert_not_called()
            targets = [call.args[0] for call in client.send_message.call_args_list]
            self.assertEqual(targets, ["chat:456"])
            self.assertFalse((Path(tmp) / "output" / "runtime" / "bot_access_state.json").exists())

    def test_handle_max_update_requests_phone_when_admin_access_has_no_secret_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=Path(tmp) / "output"),
                use_mock_data=False,
                max_bot_token="max-token",
                bot_access_code=None,
                access_admin_user_ids=["23325864"],
            )
            client = Mock()

            with patch("godmod.max_bot.handle_update") as handle_update, patch("godmod.max_bot.remember_last_max_target"):
                handle_max_update(
                    client,
                    settings,
                    {
                        "update_type": "bot_started",
                        "user": {"user_id": 123},
                    },
                )

            handle_update.assert_not_called()
            client.send_message.assert_called_once()
            self.assertEqual(client.send_message.call_args.args[:2], ("user:123", "Доступ закрыт. Нажмите кнопку и поделитесь контактом MAX."))
            self.assertEqual(client.send_message.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["type"], "request_contact")

    def test_handle_max_update_allows_access_admin_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=Path(tmp) / "output"),
                use_mock_data=False,
                max_bot_token="max-token",
                access_admin_user_ids=["23325864"],
            )
            client = Mock()

            with (
                patch("godmod.max_bot.handle_update") as handle_update,
                patch("godmod.max_bot.open_commerce_wizard") as open_commerce_wizard,
                patch("godmod.max_bot.remember_last_max_target"),
            ):
                handle_max_update(
                    client,
                    settings,
                    {
                        "update_type": "message_created",
                        "message": {
                            "sender": {"user_id": 23325864},
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "mid-1", "text": "Выгрузка по коммерции"},
                        },
                    },
                )

            handle_update.assert_not_called()
            open_commerce_wizard.assert_called_once()
            self.assertFalse(any("Доступ закрыт" in call.args[1] for call in client.send_message.call_args_list))

    def test_handle_max_update_maps_known_admin_phone_to_user_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=Path(tmp) / "output"),
                use_mock_data=False,
                max_bot_token="max-token",
                access_admin_user_ids=["+79129111119", "+79320588150"],
            )
            client = Mock()

            with patch("godmod.max_bot.handle_update") as handle_update, patch("godmod.max_bot.remember_last_max_target"):
                handle_max_update(
                    client,
                    settings,
                    {
                        "update_type": "message_created",
                        "message": {
                            "sender": {"user_id": 123},
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "mid-1", "attachments": [_max_contact_attachment("79991234567")]},
                        },
                    },
                )

            handle_update.assert_not_called()
            targets = [call.args[0] for call in client.send_message.call_args_list]
            self.assertIn("23325864", targets)
            self.assertNotIn("+79320588150", targets)

    def test_handle_max_update_accepts_official_vcf_contact_without_phone_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=Path(tmp) / "output"),
                use_mock_data=False,
                max_bot_token="max-token",
                access_admin_user_ids=["23325864"],
            )
            client = Mock()

            with patch("godmod.max_bot.handle_update") as handle_update, patch("godmod.max_bot.remember_last_max_target"):
                handle_max_update(
                    client,
                    settings,
                    {
                        "update_type": "message_created",
                        "message": {
                            "sender": {"user_id": 123},
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "mid-1", "attachments": [_max_official_contact_attachment("79991234567")]},
                        },
                    },
                )

            handle_update.assert_not_called()
            targets = [call.args[0] for call in client.send_message.call_args_list]
            self.assertIn("23325864", targets)
            admin_call = next(call for call in client.send_message.call_args_list if call.args[0] == "23325864")
            self.assertIn("Телефон: +79991234567", admin_call.args[1])

    def test_handle_max_update_reads_contact_from_message_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=Path(tmp) / "output"),
                use_mock_data=False,
                max_bot_token="max-token",
                access_admin_user_ids=["23325864"],
            )
            client = Mock()

            with patch("godmod.max_bot.handle_update") as handle_update, patch("godmod.max_bot.remember_last_max_target"):
                handle_max_update(
                    client,
                    settings,
                    {
                        "update_type": "message_created",
                        "message": {
                            "sender": {"user_id": 123},
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "mid-1"},
                            "attachments": [_max_official_contact_attachment("79991234567")],
                        },
                    },
                )

            handle_update.assert_not_called()
            targets = [call.args[0] for call in client.send_message.call_args_list]
            self.assertIn("23325864", targets)

    def test_handle_max_update_reports_admin_notification_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=Path(tmp) / "output"),
                use_mock_data=False,
                max_bot_token="max-token",
                access_admin_user_ids=["23325864"],
            )
            client = Mock()
            client.send_message.side_effect = [MaxApiError("not found"), {"message_id": "m-user"}]

            with patch("godmod.max_bot.handle_update") as handle_update, patch("godmod.max_bot.remember_last_max_target"):
                handle_max_update(
                    client,
                    settings,
                    {
                        "update_type": "message_created",
                        "message": {
                            "sender": {"user_id": 123},
                            "recipient": {"chat_id": 456},
                            "body": {"mid": "mid-1", "attachments": [_max_official_contact_attachment("79991234567")]},
                        },
                    },
                )

            handle_update.assert_not_called()
            self.assertEqual(client.send_message.call_args.args[0], "chat:456")
            self.assertIn("не удалось отправить заявку", client.send_message.call_args.args[1])

    def test_handle_max_update_approves_phone_access_from_admin_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=output_dir),
                use_mock_data=False,
                max_bot_token="max-token",
                max_allowed_chat_ids=["chat:reports"],
                bot_access_code="secret",
            )
            request_phone_access(settings, user_id=123, chat_id="chat:456", phone="+7 999 123-45-67")
            client = Mock()

            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-1",
                        "payload": "access:approve:user:123",
                        "user": {"user_id": 999},
                        "message": {
                            "recipient": {"chat_id": 777},
                            "body": {"mid": "admin-mid"},
                        },
                    },
                },
            )

            self.assertTrue(is_authorized_user(settings, 123))
            client.answer_callback_query.assert_called_once()
            client.delete_message.assert_called_once_with("chat:777", "admin-mid")
            self.assertEqual(client.send_message.call_args_list[0].args[:2], ("chat:456", "Доступ разрешён. Что нужно выгрузить?"))
            self.assertEqual(client.send_message.call_args_list[1].args[:2], ("chat:777", "Заявка разрешена: +79991234567 / user:123."))
            user_call = client.send_message.call_args_list[0]
            buttons = user_call.kwargs["reply_markup"]["inline_keyboard"]
            self.assertEqual(buttons[0][0]["callback_data"], "max:commerce")

    def test_handle_max_update_denies_phone_access_and_resolves_admin_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=output_dir),
                use_mock_data=False,
                max_bot_token="max-token",
                max_allowed_chat_ids=["chat:reports"],
                bot_access_code="secret",
            )
            request_phone_access(settings, user_id=123, chat_id="chat:456", phone="+7 999 123-45-67")
            client = Mock()

            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-1",
                        "payload": "access:deny:user:123",
                        "user": {"user_id": 999},
                        "message": {
                            "recipient": {"chat_id": 777},
                            "body": {"mid": "admin-mid"},
                        },
                    },
                },
            )

            self.assertFalse(is_authorized_user(settings, 123))
            client.answer_callback_query.assert_called_once()
            client.delete_message.assert_called_once_with("chat:777", "admin-mid")
            self.assertEqual(client.send_message.call_args_list[0].args[:2], ("chat:456", "Доступ отклонён администратором."))
            self.assertEqual(client.send_message.call_args_list[1].args[:2], ("chat:777", "Заявка отклонена: +79991234567 / user:123."))

    def test_handle_max_update_falls_back_to_edit_when_access_admin_message_delete_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            settings = AppSettings(
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
                runtime=RuntimeConfig(output_dir=output_dir),
                use_mock_data=False,
                max_bot_token="max-token",
                max_allowed_chat_ids=["chat:reports"],
                bot_access_code="secret",
            )
            request_phone_access(settings, user_id=123, chat_id="chat:456", phone="+7 999 123-45-67")
            client = Mock()
            client.delete_message.side_effect = MaxApiError("delete failed")

            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_callback",
                    "callback": {
                        "callback_id": "cb-1",
                        "payload": "access:approve:user:123",
                        "user": {"user_id": 999},
                        "message": {
                            "recipient": {"chat_id": 777},
                            "body": {"mid": "admin-mid"},
                        },
                    },
                },
            )

            client.edit_message_text.assert_called_once_with("chat:777", "admin-mid", "Заявка разрешена: +79991234567 / user:123.")

    def test_run_sud_job_uses_longer_cli_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            job = SudJob(
                id="job-1",
                chat_id="chat:456",
                date_from=date(2026, 7, 1),
                date_to=date(2026, 7, 2),
                court=None,
                outdir=outdir,
                output_dir=outdir,
                lock_id="lock-1",
            )
            client = Mock()

            def fake_run(cmd, **kwargs):  # noqa: ANN001
                (outdir / "report.csv").write_text("h\nrow\n", encoding="utf-8")
                return Mock(returncode=0, stdout="", stderr="")

            with patch("godmod.max_bot.subprocess.run", side_effect=fake_run) as run, patch("godmod.max_bot.release_report_run"):
                _run_sud_job(client, job)

            cmd = run.call_args.args[0]
            self.assertIn("--timeout", cmd)
            self.assertEqual(cmd[cmd.index("--timeout") + 1], "30")
            self.assertIn("--workers", cmd)
            self.assertEqual(cmd[cmd.index("--workers") + 1], "6")
            self.assertEqual(job.status, "done")

    def test_active_court_session_does_not_trap_commerce_button(self) -> None:
        settings = AppSettings(
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
            runtime=RuntimeConfig(output_dir=Path("output")),
            use_mock_data=False,
            max_bot_token="max-token",
        )
        client = Mock()
        SUD_SESSIONS[("chat:456", 123)] = session = SudSession()
        session.step = "running"

        with patch("godmod.max_bot.handle_update") as handle_update, patch(
            "godmod.max_bot.remember_last_max_target"
        ):
            handle_max_update(
                client,
                settings,
                {
                    "update_type": "message_created",
                    "message": {
                        "sender": {"user_id": 123},
                        "recipient": {"chat_id": 456},
                        "body": {"mid": "mid-1", "text": "Выгрузка по коммерции"},
                    },
                },
            )

        handle_update.assert_not_called()
        client.send_message.assert_called_once()
        self.assertIn("Выберите город", client.send_message.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
