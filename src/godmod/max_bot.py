from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .access_control import (
    approve_phone_access,
    deny_phone_access,
    extract_phone,
    is_access_protected,
    is_authorized_user,
    load_authorized_users,
    normalize_phone,
    normalize_user_id,
    request_phone_access,
)
from .bot import handle_update, log_runtime_source_warnings, open_commerce_wizard
from .bot_state import ensure_wizard_state, get_wizard_state
from .max_api import MaxApiError, MaxBotClient
from .max_target_state import remember_last_max_target, runtime_output_dir
from .models import SearchRequest, ServiceQuery
from .report_lock import format_report_busy_message, release_report_run, try_acquire_report_run
from .settings import AppSettings
from .sud_export import COURTS


MAX_LONG_POLL_UPDATE_TYPES = ["bot_started", "message_created", "message_callback"]
SUD_MAX_DAYS = int(os.environ.get("SUD_MAX_DAYS", "45"))
SUD_EXPORT_TIMEOUT_SECONDS = int(os.environ.get("SUD_EXPORT_TIMEOUT_SECONDS", str(4 * 60 * 60)))
MAX_SCREEN_STATE_FILE = "max_screen_ids.json"
MAX_UPDATE_TRACE_FILE = "max_update_trace.jsonl"
MAX_ADMIN_TARGET_ALIASES = {
    "+79129111119": "23325864",
    "79129111119": "23325864",
}


@dataclass(slots=True)
class SudSession:
    step: str = ""
    date_from: date | None = None
    date_to: date | None = None
    court: str | None = None
    last_job_id: str | None = None
    message_id: int | str | None = None


@dataclass(slots=True)
class SudJob:
    id: str
    chat_id: int | str
    date_from: date
    date_to: date
    court: str | None
    outdir: Path
    output_dir: Path
    lock_id: str
    status: str = "queued"
    rows: int = 0
    error: str = ""


SUD_SESSIONS: dict[tuple[int | str, int | str], SudSession] = {}
SUD_JOBS: dict[str, SudJob] = {}
MAX_SCREEN_IDS: dict[tuple[int | str, int | str], int | str] = {}
USER_MAX_SCREEN_IDS: dict[int | str, int | str] = {}
_LOCK_FILE_HANDLE = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Godmod MAX bot")
    parser.add_argument("--dotenv", default=".env", help="Path to .env file")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = AppSettings.from_env(args.dotenv)
    if not settings.max_bot_token:
        raise SystemExit("MAX_BOT_TOKEN is not set. Put it into .env or environment.")

    acquire_long_poll_lock(settings)
    client = MaxBotClient(settings.max_bot_token, base_url=os.environ.get("MAX_API_BASE", "https://platform-api.max.ru"))
    try:
        client.clear_commands()
    except MaxApiError as exc:
        print(f"MAX command menu clear warning: {exc}")
    log_runtime_source_warnings(settings)
    print("Godmod MAX bot is running...")
    poll_updates(client, settings)


def acquire_long_poll_lock(settings: AppSettings) -> None:
    global _LOCK_FILE_HANDLE
    path = Path(
        os.environ.get("GODMOD_MAX_LOCK_FILE")
        or os.environ.get("SUD_MAX_LOCK_FILE")
        or str(runtime_output_dir(settings) / "runtime" / "max-bot.lock")
    ).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_FILE_HANDLE = path.open("w")
    try:
        fcntl.flock(_LOCK_FILE_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _LOCK_FILE_HANDLE.close()
        _LOCK_FILE_HANDLE = None
        raise SystemExit("another godmod.max_bot instance is already running")
    _LOCK_FILE_HANDLE.write(str(os.getpid()))
    _LOCK_FILE_HANDLE.flush()


def poll_updates(client: MaxBotClient, settings: AppSettings) -> None:
    marker: int | None = None
    while True:
        try:
            payload = client.get_updates(marker=marker, timeout=25, types=MAX_LONG_POLL_UPDATE_TYPES)
            updates = payload.get("updates", [])
            if isinstance(updates, list):
                for update in updates:
                    if isinstance(update, dict):
                        handle_max_update(client, settings, update)
            next_marker = payload.get("marker")
            if isinstance(next_marker, int):
                marker = next_marker
        except MaxApiError as exc:
            print(f"MAX API error: {exc}")
            time.sleep(3)
        except KeyboardInterrupt:
            print("MAX bot stopped.")
            return


def handle_max_update(client: MaxBotClient, settings: AppSettings, update: dict[str, Any]) -> None:
    normalized_update = normalize_max_update(update)
    if normalized_update is None:
        return

    chat_id, user_id = _normalized_ids(normalized_update)
    if chat_id is None or user_id is None:
        return
    if not _is_allowed_max_target(settings, chat_id, user_id):
        if _is_access_callback(normalized_update) and _handle_max_access_update(client, settings, normalized_update):
            _trace_max_update(settings, update, normalized_update, handler="access")
            return
        client.send_message(chat_id, "Этот чат не разрешён для запуска отчётов.")
        _trace_max_update(settings, update, normalized_update, handler="denied")
        return
    try:
        remember_last_max_target(
            settings,
            chat_id=chat_id,
            user_id=user_id,
            update_type=str(update.get("update_type") or update.get("type") or ""),
        )
    except OSError as exc:
        print(f"MAX target state warning: {exc}")

    if _handle_max_access_update(client, settings, normalized_update):
        _trace_max_update(settings, update, normalized_update, handler="access")
        return
    if handle_max_home_update(client, settings, normalized_update):
        _trace_max_update(settings, update, normalized_update, handler="max_home")
        return
    if handle_sud_update(client, settings, normalized_update):
        _trace_max_update(settings, update, normalized_update, handler="sud")
        return
    normalized_update = _prepare_shared_max_update(client, settings, normalized_update)
    handle_update(client, settings, normalized_update)
    _remember_shared_max_screen(settings, normalized_update)
    _trace_max_update(settings, update, normalized_update, handler="shared")


def handle_max_home_update(client: MaxBotClient, settings: AppSettings, update: dict[str, Any]) -> bool:
    chat_id, user_id = _normalized_ids(update)
    if chat_id is None or user_id is None:
        return False
    action, callback_id = _max_home_action(update)
    message_id = (
        _max_screen_target(client, settings, chat_id, user_id, update)
        if callback_id
        else _remembered_max_screen(settings, chat_id, user_id)
    )
    action_key = _max_action_key(action)
    command_name = _max_command_name(action)
    if action == "max:main" or action_key in {"старт", "начать", "start", "сброс", "cancel"} or command_name in {"/start", "/cancel"}:
        known_message_ids = _known_max_screen_ids_for_user(settings, user_id)
        if message_id is not None:
            known_message_ids.append(message_id)
        _clear_flow_screens(client, chat_id, user_id, keep_message_id=None)
        for known_message_id in dict.fromkeys(known_message_ids):
            if known_message_id != message_id:
                _delete_message_safely(client, chat_id, known_message_id)
        _forget_all_max_screens_for_user(settings, user_id)
        _remember_max_screen(settings, chat_id, user_id, _upsert_max_home(client, chat_id, message_id=message_id))
        if callback_id:
            client.answer_callback_query(callback_id, text="Принято")
        return True
    if action == "max:commerce" or action_key in {"выгрузка по коммерции", "🏢 выгрузка по коммерции", "города"} or command_name == "/cities":
        if is_access_protected(settings) and not is_authorized_user(settings, user_id):
            client.send_message(chat_id, "Доступ закрыт. Отправьте /access <код>.")
            if callback_id:
                client.answer_callback_query(callback_id, text="Доступ закрыт.", show_alert=True)
            return True
        _clear_flow_screens(client, chat_id, user_id, keep_message_id=message_id)
        open_commerce_wizard(client, settings, chat_id, user_id, wizard_message_id=message_id)
        state = get_wizard_state(chat_id, user_id)
        if state is not None:
            _remember_max_screen(settings, chat_id, user_id, state.wizard_message_id)
        if callback_id:
            client.answer_callback_query(callback_id, text="Принято")
        return True
    if action == "max:help" or action_key in {"помощь", "help", "ℹ️ помощь"} or command_name == "/help":
        _clear_flow_screens(client, chat_id, user_id, keep_message_id=message_id)
        _remember_max_screen(
            settings,
            chat_id,
            user_id,
            _upsert_max_home(
                client,
                chat_id,
                text="Выберите тип выгрузки. Коммерция собирает бизнесы и исполнителей, суды собирают судебные заседания ЯНАО.",
                message_id=message_id,
            ),
        )
        if callback_id:
            client.answer_callback_query(callback_id, text="Принято")
        return True
    return False


def _max_action_key(action: str) -> str:
    return " ".join(action.strip().casefold().split())


def _max_command_name(action: str) -> str | None:
    token = action.strip().split(maxsplit=1)[0] if action.strip() else ""
    if not token.startswith("/"):
        return None
    return token.split("@", 1)[0].casefold()


def handle_sud_update(client: MaxBotClient, settings: AppSettings, update: dict[str, Any]) -> bool:
    chat_id, user_id = _normalized_ids(update)
    if chat_id is None or user_id is None:
        return False
    text, callback_id = _sud_action(update)
    session = SUD_SESSIONS.setdefault((chat_id, user_id), SudSession())
    message_id = (
        _max_screen_target(client, settings, chat_id, user_id, update)
        if callback_id
        else _remembered_max_screen(settings, chat_id, user_id)
    )
    if callback_id and message_id is not None and session.message_id is None:
        session.message_id = message_id
    if session.message_id is None:
        session.message_id = message_id
    if not _should_handle_sud_action(text, callback_id, session):
        return False
    if is_access_protected(settings) and not is_authorized_user(settings, user_id):
        client.send_message(chat_id, "Доступ закрыт. Отправьте /access <код>.")
        if callback_id:
            client.answer_callback_query(callback_id, text="Доступ закрыт.", show_alert=True)
        return True

    try:
        _apply_sud_action(client, settings, chat_id, user_id, session, text)
        _remember_max_screen(settings, chat_id, user_id, session.message_id)
        if callback_id:
            client.answer_callback_query(callback_id, text="Принято")
    except ValueError as exc:
        if callback_id:
            client.answer_callback_query(callback_id, text=str(exc), show_alert=True)
        else:
            client.send_message(chat_id, str(exc), reply_markup=_sud_main_markup())
    return True


def _should_handle_sud_action(action: str, callback_id: str | None, session: SudSession) -> bool:
    if action in {"Выгрузка по судам", "⚖️ Выгрузка по судам", "/sud"} or action.startswith("sud:"):
        return True
    if callback_id:
        return False
    if action.startswith("/"):
        return False
    return session.step in {"from", "to"}


def _sud_action(update: dict[str, Any]) -> tuple[str, str | None]:
    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        return str(callback_query.get("data") or ""), str(callback_query.get("id") or "")
    message = _as_dict(update.get("message")) or _as_dict(update.get("edited_message"))
    return str(message.get("text") or "").strip(), None


def _sud_message_id(update: dict[str, Any]) -> int | str | None:
    callback_query = _as_dict(update.get("callback_query"))
    if callback_query:
        message = _as_dict(callback_query.get("message"))
    else:
        message = _as_dict(update.get("message")) or _as_dict(update.get("edited_message"))
    if not message:
        return None
    message_id = message.get("message_id")
    return message_id if isinstance(message_id, int) or (isinstance(message_id, str) and message_id) else None


def _max_home_action(update: dict[str, Any]) -> tuple[str, str | None]:
    callback_query = _as_dict(update.get("callback_query"))
    if callback_query:
        return str(callback_query.get("data") or ""), str(callback_query.get("id") or "")
    message = _as_dict(update.get("message")) or _as_dict(update.get("edited_message"))
    return str(message.get("text") or "").strip(), None


def _max_home_message_id(update: dict[str, Any]) -> int | str | None:
    return _sud_message_id(update)


def _handle_max_access_update(client: MaxBotClient, settings: AppSettings, update: dict[str, Any]) -> bool:
    if not _max_access_enabled(settings):
        return False
    chat_id, user_id = _normalized_ids(update)
    if chat_id is None or user_id is None:
        return False
    action, callback_id = _max_home_action(update)
    if action.startswith("access:approve:") or action.startswith("access:deny:"):
        target_user_id = action.split(":", 2)[2]
        approved = action.startswith("access:approve:")
        request_payload = approve_phone_access(settings, target_user_id) if approved else deny_phone_access(settings, target_user_id)
        if request_payload is None:
            text = "Заявка уже обработана или не найдена."
        else:
            target_chat_id = str(request_payload.get("chat_id") or "")
            phone = str(request_payload.get("phone") or "")
            text = f"Заявка {'разрешена' if approved else 'отклонена'}: {phone} / {target_user_id}."
            if target_chat_id:
                if approved:
                    _show_access_granted_home(client, settings, target_chat_id, target_user_id)
                else:
                    client.send_message(target_chat_id, "Доступ отклонён администратором.")
        if callback_id:
            client.answer_callback_query(callback_id, text=text, show_alert=True)
        if not _resolve_access_admin_message(client, update, chat_id, text):
            client.send_message(chat_id, text)
        return True
    if _is_max_authorized_user(settings, user_id):
        return False
    if _max_command_name(action) == "/access":
        return False
    phone = _verified_access_phone_from_update(settings, update)
    if phone:
        request_payload = request_phone_access(settings, user_id=user_id, chat_id=chat_id, phone=phone)
        admin_text = (
            "Новая заявка на доступ.\n"
            f"Пользователь: {request_payload['user_id']}\n"
            f"Чат: {request_payload['chat_id']}\n"
            f"Телефон: {request_payload['phone']}"
        )
        sent_admin_notifications = 0
        for admin_user_id in _max_access_admin_targets(settings):
            try:
                client.send_message(admin_user_id, admin_text, reply_markup=_access_admin_markup(str(request_payload["user_id"])))
                sent_admin_notifications += 1
            except MaxApiError as exc:
                print(f"MAX access admin notification failed for {admin_user_id}: {exc}")
        if sent_admin_notifications == 0:
            client.send_message(chat_id, "Номер получен, но администратору не удалось отправить заявку. Сообщите оператору.")
            return True
        client.send_message(chat_id, "Номер получен. Заявка отправлена администратору.")
        if callback_id:
            client.answer_callback_query(callback_id, text="Заявка отправлена")
        return True
    client.send_message(chat_id, "Доступ закрыт. Нажмите кнопку и поделитесь контактом MAX.", reply_markup=_access_request_contact_markup())
    if callback_id:
        client.answer_callback_query(callback_id, text="Доступ закрыт.", show_alert=True)
    return True


def _max_access_enabled(settings: AppSettings) -> bool:
    return is_access_protected(settings) or bool(settings.access_admin_user_ids)


def _is_max_authorized_user(settings: AppSettings, user_id: int | str) -> bool:
    if _is_max_access_admin(settings, user_id):
        return True
    if is_access_protected(settings):
        return is_authorized_user(settings, user_id)
    if not settings.access_admin_user_ids:
        return True
    return normalize_user_id(user_id) in load_authorized_users(settings)


def _is_max_access_admin(settings: AppSettings, user_id: int | str) -> bool:
    normalized = normalize_user_id(user_id)
    raw = str(user_id).removeprefix("user:")
    admin_targets = set(_max_access_admin_targets(settings))
    return bool({raw, f"user:{raw}", normalized}.intersection(admin_targets))


def _max_access_admin_targets(settings: AppSettings) -> list[str]:
    targets: list[str] = []
    for value in settings.access_admin_user_ids:
        target = MAX_ADMIN_TARGET_ALIASES.get(value, value)
        if target.startswith("chat:") or target.startswith("user:") or target.isdigit():
            targets.append(target)
    return list(dict.fromkeys(targets))


def _is_access_callback(update: dict[str, Any]) -> bool:
    action, callback_id = _max_home_action(update)
    return bool(callback_id) and action.startswith(("access:approve:", "access:deny:"))


def _verified_access_phone_from_update(settings: AppSettings, update: dict[str, Any]) -> str | None:
    message = _as_dict(update.get("message")) or _as_dict(update.get("edited_message"))
    contact = _as_dict(message.get("contact"))
    if not _valid_max_contact_hash(contact, settings.max_bot_token or ""):
        return None
    return _contact_phone(contact)


def _valid_max_contact_hash(contact: dict[str, Any], bot_token: str) -> bool:
    vcf_info = contact.get("vcf_info")
    contact_hash = contact.get("hash")
    if not isinstance(vcf_info, str) or not isinstance(contact_hash, str) or not bot_token:
        return False
    normalized_vcf = vcf_info.replace("\\r\\n", "\r\n")
    expected = hmac.new(bot_token.encode("utf-8"), normalized_vcf.encode("utf-8"), hashlib.sha256).digest()
    return any(hmac.compare_digest(candidate, expected) for candidate in _contact_hash_candidates(contact_hash))


def _contact_hash_candidates(value: str) -> list[bytes]:
    token = value.strip()
    candidates: list[bytes] = []
    try:
        candidates.append(bytes.fromhex(token))
    except ValueError:
        pass
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            candidates.append(decoder(token + "=" * (-len(token) % 4)))
        except (ValueError, binascii.Error):
            pass
    return candidates


def _access_request_contact_markup() -> dict[str, Any]:
    return {"inline_keyboard": [[{"type": "request_contact", "text": "Поделиться контактом"}]]}


def _access_admin_markup(user_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Разрешить", "callback_data": f"access:approve:{user_id}"},
                {"text": "❌ Отказать", "callback_data": f"access:deny:{user_id}"},
            ]
        ]
    }


def _show_access_granted_home(client: MaxBotClient, settings: AppSettings, chat_id: str, user_id: str) -> None:
    _forget_all_max_screens_for_user(settings, user_id)
    message_id = _upsert_max_home(client, chat_id, text="Доступ разрешён. Что нужно выгрузить?")
    _remember_max_screen(settings, chat_id, user_id, message_id)


def _resolve_access_admin_message(client: MaxBotClient, update: dict[str, Any], chat_id: int | str, text: str) -> bool:
    message_id = _max_home_message_id(update)
    if message_id is None:
        return False
    try:
        client.delete_message(chat_id, message_id)
        client.send_message(chat_id, text)
        return True
    except MaxApiError:
        try:
            client.edit_message_text(chat_id, message_id, text)
            return True
        except MaxApiError:
            return False


def _prepare_shared_max_update(client: MaxBotClient, settings: AppSettings, update: dict[str, Any]) -> dict[str, Any]:
    chat_id, user_id = _normalized_ids(update)
    if chat_id is None or user_id is None:
        return update
    current_message_id = _remembered_max_screen(settings, chat_id, user_id)
    if current_message_id is None:
        return update
    state = ensure_wizard_state(
        chat_id,
        user_id,
        default_top_n=settings.runtime.default_top_n,
        wizard_message_id=current_message_id,
    )
    state.wizard_message_id = current_message_id
    callback_query = _as_dict(update.get("callback_query"))
    if callback_query and str(callback_query.get("data") or "").startswith("wiz:"):
        clicked_message_id = _max_home_message_id(update)
        if clicked_message_id is not None and clicked_message_id != current_message_id:
            _delete_message_safely(client, chat_id, clicked_message_id)
        message = _as_dict(callback_query.get("message"))
        message["message_id"] = current_message_id
        callback_query["message"] = message
    return update


def _remember_shared_max_screen(settings: AppSettings, update: dict[str, Any]) -> None:
    chat_id, user_id = _normalized_ids(update)
    if chat_id is None or user_id is None:
        return
    state = get_wizard_state(chat_id, user_id)
    if state is not None:
        _remember_max_screen(settings, chat_id, user_id, state.wizard_message_id)


def _max_screen_target(
    client: MaxBotClient,
    settings: AppSettings,
    chat_id: int | str,
    user_id: int | str,
    update: dict[str, Any],
) -> int | str | None:
    clicked_message_id = _max_home_message_id(update)
    current_message_id = _remembered_max_screen(settings, chat_id, user_id)
    if clicked_message_id is not None and current_message_id is not None and clicked_message_id != current_message_id:
        _delete_message_safely(client, chat_id, clicked_message_id)
        return current_message_id
    return clicked_message_id or current_message_id


def _remembered_max_screen(settings: AppSettings, chat_id: int | str, user_id: int | str) -> int | str | None:
    _load_max_screen_state(settings)
    return (
        MAX_SCREEN_IDS.get((chat_id, user_id))
        or MAX_SCREEN_IDS.get((str(chat_id), str(user_id)))
    )


def _remember_max_screen(settings: AppSettings, chat_id: int | str, user_id: int | str, message_id: int | str | None) -> None:
    if message_id is not None:
        MAX_SCREEN_IDS[(chat_id, user_id)] = message_id
        USER_MAX_SCREEN_IDS[user_id] = message_id
        _save_max_screen_state(settings)


def _known_max_screen_ids_for_user(settings: AppSettings, user_id: int | str) -> list[int | str]:
    _load_max_screen_state(settings)
    user_keys = {user_id, str(user_id)}
    message_ids: list[int | str] = []
    for pair, message_id in MAX_SCREEN_IDS.items():
        if pair[1] in user_keys and _is_max_message_id(message_id):
            message_ids.append(message_id)
    for key in (user_id, str(user_id)):
        message_id = USER_MAX_SCREEN_IDS.get(key)
        if _is_max_message_id(message_id):
            message_ids.append(message_id)
    return message_ids


def _forget_all_max_screens_for_user(settings: AppSettings, user_id: int | str) -> None:
    user_keys = {user_id, str(user_id)}
    for pair in list(MAX_SCREEN_IDS):
        if pair[1] in user_keys:
            MAX_SCREEN_IDS.pop(pair, None)
    for key in list(USER_MAX_SCREEN_IDS):
        if key in user_keys:
            USER_MAX_SCREEN_IDS.pop(key, None)
    _save_max_screen_state(settings)


def _load_max_screen_state(settings: AppSettings) -> None:
    path = _max_screen_state_path(settings)
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    for key, value in _as_dict(payload.get("screen_by_pair")).items():
        if isinstance(key, str) and _is_max_message_id(value):
            chat_id, sep, user_id = key.partition("|")
            if sep:
                MAX_SCREEN_IDS.setdefault((chat_id, user_id), value)
    for key, value in _as_dict(payload.get("screen_by_user")).items():
        if isinstance(key, str) and _is_max_message_id(value):
            USER_MAX_SCREEN_IDS.setdefault(key, value)


def _save_max_screen_state(settings: AppSettings) -> None:
    path = _max_screen_state_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "screen_by_pair": {f"{chat_id}|{user_id}": message_id for (chat_id, user_id), message_id in MAX_SCREEN_IDS.items()},
                    "screen_by_user": {str(user_id): message_id for user_id, message_id in USER_MAX_SCREEN_IDS.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"MAX screen state warning: {exc}")


def _max_screen_state_path(settings: AppSettings) -> Path:
    return runtime_output_dir(settings) / "runtime" / MAX_SCREEN_STATE_FILE


def _max_update_trace_path(settings: AppSettings) -> Path:
    return runtime_output_dir(settings) / "runtime" / MAX_UPDATE_TRACE_FILE


def _trace_max_update(
    settings: AppSettings,
    raw_update: dict[str, Any],
    normalized_update: dict[str, Any],
    *,
    handler: str,
) -> None:
    chat_id, user_id = _normalized_ids(normalized_update)
    action, callback_id = _max_home_action(normalized_update)
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "raw_update_type": str(raw_update.get("update_type") or raw_update.get("type") or ""),
        "handler": handler,
        "chat_id": chat_id,
        "user_id": user_id,
        "message_id": _max_home_message_id(normalized_update),
        "callback": bool(callback_id),
        "action": _trace_action_label(action),
        "remembered_screen": _remembered_max_screen(settings, chat_id, user_id) if chat_id is not None and user_id is not None else None,
    }
    path = _max_update_trace_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"MAX update trace warning: {exc}")


def _trace_action_label(action: str) -> str:
    key = _max_action_key(action)
    if key in {
        "старт",
        "начать",
        "start",
        "сброс",
        "cancel",
        "города",
        "помощь",
        "help",
        "выгрузка по коммерции",
        "🏢 выгрузка по коммерции",
        "выгрузка по судам",
        "⚖️ выгрузка по судам",
    }:
        return key
    command = _max_command_name(action)
    if command is not None:
        return command
    if action.startswith(("max:", "sud:", "wiz:")):
        return action
    return "text" if action else ""


def _upsert_max_home(
    client: MaxBotClient,
    chat_id: int | str,
    *,
    text: str = "Что нужно выгрузить?",
    message_id: int | str | None = None,
) -> int | str | None:
    if message_id is not None:
        try:
            result = client.edit_message_text(chat_id, message_id, text, reply_markup=_max_home_markup())
            return _message_id_from_result(result) or message_id
        except MaxApiError as exc:
            if "message is not modified" in str(exc):
                return message_id
    sent = client.send_message(chat_id, text, reply_markup=_max_home_markup())
    return _message_id_from_result(sent)


def _message_id_from_result(result: object) -> int | str | None:
    if not isinstance(result, dict):
        return None
    message_id = result.get("message_id")
    return message_id if _is_max_message_id(message_id) else None


def _is_max_message_id(value: object) -> bool:
    return isinstance(value, int) or (isinstance(value, str) and bool(value))


def _max_home_markup() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🏢 Выгрузка по коммерции", "callback_data": "max:commerce"}],
            [{"text": "⚖️ Выгрузка по судам", "callback_data": "sud:main"}],
            [{"text": "ℹ️ Помощь", "callback_data": "max:help"}],
        ]
    }


def _clear_flow_screens(
    client: MaxBotClient,
    chat_id: int | str,
    user_id: int | str,
    *,
    keep_message_id: int | str | None,
) -> None:
    state = get_wizard_state(chat_id, user_id)
    if state is not None and state.wizard_message_id is not None and state.wizard_message_id != keep_message_id:
        _delete_message_safely(client, chat_id, state.wizard_message_id)
        state.wizard_message_id = None
    session = SUD_SESSIONS.pop((chat_id, user_id), None)
    if session is not None and session.message_id is not None and session.message_id != keep_message_id:
        _delete_message_safely(client, chat_id, session.message_id)


def _delete_message_safely(client: MaxBotClient, chat_id: int | str, message_id: int | str) -> None:
    try:
        client.delete_message(chat_id, message_id)
    except MaxApiError:
        return


def _apply_sud_action(
    client: MaxBotClient,
    settings: AppSettings,
    chat_id: int | str,
    user_id: int | str,
    session: SudSession,
    action: str,
) -> None:
    if action in {"Выгрузка по судам", "⚖️ Выгрузка по судам", "/sud", "sud:main"}:
        session.step = "period"
        _upsert_sud_message(client, chat_id, session, "Выгрузка по судебным заседаниям ЯНАО. Выберите период.", _sud_period_markup())
        return
    if action == "sud:month":
        session.date_from, session.date_to = _last_full_month()
        session.court = None
        session.step = "court"
        _upsert_sud_message(client, chat_id, session, _sud_period_text(session) + "\nВыберите суд.", _sud_court_markup())
        return
    if action == "sud:week":
        session.date_from, session.date_to = _last_full_week()
        session.court = None
        session.step = "court"
        _upsert_sud_message(client, chat_id, session, _sud_period_text(session) + "\nВыберите суд.", _sud_court_markup())
        return
    if action == "sud:custom":
        session.step = "from"
        session.date_from = None
        session.date_to = None
        _upsert_sud_message(client, chat_id, session, "Введите дату начала в формате ДД.ММ.ГГГГ.", _sud_back_markup())
        return
    if action.startswith("sud:court:"):
        if session.date_from is None or session.date_to is None:
            raise ValueError("Сначала выберите период.")
        court = action.removeprefix("sud:court:")
        session.court = None if court == "all" else court
        if session.court is not None and session.court not in COURTS:
            raise ValueError("Выбранный суд больше недоступен.")
        session.step = "confirm"
        _upsert_sud_message(client, chat_id, session, _sud_confirm_text(session), _sud_confirm_markup())
        return
    if action == "sud:choose_court":
        if session.date_from is None or session.date_to is None:
            raise ValueError("Сначала выберите период.")
        session.step = "court"
        _upsert_sud_message(client, chat_id, session, _sud_period_text(session) + "\nВыберите суд.", _sud_court_markup())
        return
    if action == "sud:run":
        if session.step != "confirm":
            raise ValueError("Этот запуск уже неактуален. Откройте новую судебную выгрузку.")
        _start_sud_job(client, settings, chat_id, user_id, session)
        return
    if action == "sud:status":
        job = SUD_JOBS.get(session.last_job_id or "")
        text = "Судебных задач пока нет." if job is None else f"Последняя задача: {job.status}. Записей: {job.rows}. Ошибка: {job.error or '-'}"
        _upsert_sud_message(client, chat_id, session, text, _sud_main_markup())
        return
    if action == "sud:cancel":
        _upsert_sud_message(client, chat_id, session, "Судебная выгрузка отменена.", _sud_main_markup())
        SUD_SESSIONS.pop((chat_id, user_id), None)
        return
    if session.step == "from":
        parsed = _parse_ru_date(action)
        if parsed is None:
            raise ValueError("Не понял дату. Введите в формате ДД.ММ.ГГГГ.")
        session.date_from = parsed
        session.step = "to"
        _upsert_sud_message(client, chat_id, session, "Введите дату окончания в формате ДД.ММ.ГГГГ.", _sud_back_markup())
        return
    if session.step == "to":
        parsed = _parse_ru_date(action)
        if parsed is None:
            raise ValueError("Не понял дату. Введите в формате ДД.ММ.ГГГГ.")
        if session.date_from is not None and parsed < session.date_from:
            raise ValueError("Дата окончания не может быть раньше даты начала.")
        session.date_to = parsed
        session.step = "court"
        _upsert_sud_message(client, chat_id, session, _sud_period_text(session) + "\nВыберите суд.", _sud_court_markup())
        return
    _upsert_sud_message(client, chat_id, session, "Выберите действие.", _sud_main_markup())


def _start_sud_job(
    client: MaxBotClient,
    settings: AppSettings,
    chat_id: int | str,
    user_id: int | str,
    session: SudSession,
) -> None:
    if session.date_from is None or session.date_to is None:
        raise ValueError("Сначала выберите период.")
    days = (session.date_to - session.date_from).days + 1
    if days < 1:
        raise ValueError("Период указан некорректно.")
    if days > SUD_MAX_DAYS:
        raise ValueError(f"Период слишком большой. Максимум: {SUD_MAX_DAYS} дней.")
    lock, busy_run = try_acquire_report_run(
        settings.runtime.output_dir,
        chat_id=chat_id,
        user_id=user_id,
        request=SearchRequest(
            cities=["ЯНАО"],
            services=[ServiceQuery(name="судебные заседания")],
            period_days=days,
            platforms=[],
            top_n=0,
            report_mode="all",
        ),
    )
    if lock is None:
        if busy_run is not None:
            client.send_message(
                chat_id,
                format_report_busy_message(busy_run, same_user=str(busy_run.user_id).endswith(str(user_id))),
                reply_markup=_sud_status_markup(),
            )
        return
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    job = SudJob(
        id=job_id,
        chat_id=chat_id,
        date_from=session.date_from,
        date_to=session.date_to,
        court=session.court,
        outdir=settings.runtime.output_dir / "sud" / job_id,
        output_dir=settings.runtime.output_dir,
        lock_id=lock.lock_id,
    )
    SUD_JOBS[job.id] = job
    session.last_job_id = job.id
    session.step = "running"
    _upsert_sud_message(
        client,
        chat_id,
        session,
        f"Принял, собираю судебную выгрузку за {job.date_from:%d.%m.%Y}-{job.date_to:%d.%m.%Y}. Суд: {_court_name(job.court)}.",
        _sud_status_markup(),
    )
    threading.Thread(target=_run_sud_job, args=(client, job), daemon=True).start()


def _run_sud_job(client: MaxBotClient, job: SudJob) -> None:
    job.status = "running"
    cmd = [
        sys.executable,
        "-m",
        "godmod.sud_export",
        "--from",
        job.date_from.isoformat(),
        "--to",
        job.date_to.isoformat(),
        "--outdir",
        str(job.outdir),
        "--timeout",
        "30",
        "--workers",
        "6",
    ]
    if job.court:
        cmd += ["--court", job.court]
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=SUD_EXPORT_TIMEOUT_SECONDS)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip())
        job.rows = _sud_rows_count(job.outdir / "report.csv")
        job.status = "done"
        client.send_message(job.chat_id, f"Судебная выгрузка готова. Суд: {_court_name(job.court)}. Записей: {job.rows}.")
        for name, caption in (("report.xlsx", "Excel-отчёт по судам."), ("report.pdf", "PDF-версия по судам.")):
            path = job.outdir / name
            if path.exists():
                client.send_document(job.chat_id, path, caption=caption)
        log = job.outdir / "run_log.csv"
        if log.exists() and log.stat().st_size > 64:
            client.send_document(job.chat_id, log, caption="Лог судебной выгрузки.")
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.error = str(exc)[:1000]
        client.send_message(job.chat_id, f"Судебная выгрузка не завершилась: {job.error}", reply_markup=_sud_status_markup())
    finally:
        release_report_run(job.output_dir, job.lock_id)


def _upsert_sud_message(
    client: MaxBotClient,
    chat_id: int | str,
    session: SudSession,
    text: str,
    reply_markup: dict[str, Any] | None,
) -> None:
    if session.message_id is not None:
        try:
            client.edit_message_text(chat_id, session.message_id, text, reply_markup=reply_markup)
            return
        except MaxApiError as exc:
            if "message is not modified" in str(exc):
                return
            session.message_id = None
    sent = client.send_message(chat_id, text, reply_markup=reply_markup)
    message_id = sent.get("message_id") if isinstance(sent, dict) else None
    if isinstance(message_id, int) or (isinstance(message_id, str) and message_id):
        session.message_id = message_id


def _sud_period_markup() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "📅 За прошлый месяц", "callback_data": "sud:month"}], [{"text": "🗓️ За прошлую неделю", "callback_data": "sud:week"}], [{"text": "✏️ Задать период", "callback_data": "sud:custom"}], [{"text": "📊 Статус выгрузки", "callback_data": "sud:status"}], [{"text": "⬅️ Назад в главное меню", "callback_data": "max:main"}]]}


def _sud_court_markup() -> dict[str, Any]:
    rows = [[{"text": "⚖️ Все суды ЯНАО", "callback_data": "sud:court:all"}]]
    rows.extend([[{"text": name.replace(" городской суд", ""), "callback_data": f"sud:court:{host}"}] for host, name in COURTS.items()])
    rows.append([{"text": "⬅️ Назад", "callback_data": "sud:main"}, {"text": "В главное меню", "callback_data": "max:main"}])
    return {"inline_keyboard": rows}


def _sud_confirm_markup() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "▶️ Запустить выгрузку", "callback_data": "sud:run"}], [{"text": "Изменить период", "callback_data": "sud:main"}, {"text": "Изменить суд", "callback_data": "sud:choose_court"}], [{"text": "⬅️ Назад в главное меню", "callback_data": "max:main"}]]}


def _sud_status_markup() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "📊 Статус выгрузки", "callback_data": "sud:status"}], [{"text": "⚖️ Новая выгрузка по судам", "callback_data": "sud:main"}], [{"text": "⬅️ Назад в главное меню", "callback_data": "max:main"}]]}


def _sud_main_markup() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "⚖️ Выгрузка по судам", "callback_data": "sud:main"}], [{"text": "📊 Статус выгрузки", "callback_data": "sud:status"}], [{"text": "⬅️ Назад в главное меню", "callback_data": "max:main"}]]}


def _sud_back_markup() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "sud:main"}, {"text": "В главное меню", "callback_data": "max:main"}]]}


def _sud_period_text(session: SudSession) -> str:
    if session.date_from is None or session.date_to is None:
        return "Период не выбран."
    return f"Период: {session.date_from:%d.%m.%Y}-{session.date_to:%d.%m.%Y}."


def _sud_confirm_text(session: SudSession) -> str:
    return f"Проверьте параметры:\n{_sud_period_text(session)}\nСуд: {_court_name(session.court)}"


def _court_name(host: str | None) -> str:
    return COURTS.get(host, "Все суды ЯНАО") if host else "Все суды ЯНАО"


def _last_full_week(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(days=7)
    return start, start + timedelta(days=6)


def _last_full_month(today: date | None = None) -> tuple[date, date]:
    first_this_month = (today or date.today()).replace(day=1)
    end = first_this_month - timedelta(days=1)
    return end.replace(day=1), end


def _parse_ru_date(text: str) -> date | None:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _sud_rows_count(csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    with csv_path.open(encoding="utf-8-sig", errors="replace") as file:
        return max(0, sum(1 for _ in file) - 1)


def normalize_max_update(update: dict[str, Any]) -> dict[str, Any] | None:
    update_type = str(update.get("update_type") or update.get("type") or "")
    if update_type == "bot_started":
        user = _as_dict(update.get("user"))
        user_id = _user_id(user)
        if user_id is None:
            return None
        return {
            "message": {
                "chat": {"id": _user_target(user_id)},
                "from": {"id": user_id},
                "text": "/start",
            }
        }

    if update_type == "message_created":
        message = _as_dict(update.get("message"))
        return _message_update(message)

    if update_type == "message_callback":
        callback = _as_dict(update.get("callback"))
        if not callback:
            callback = update
        message = _as_dict(callback.get("message")) or _as_dict(update.get("message"))
        user = _as_dict(callback.get("user")) or _as_dict(callback.get("sender")) or _as_dict(message.get("sender"))
        user_id = _user_id(user)
        callback_id = _string_identifier(callback.get("callback_id") or callback.get("id"))
        payload = _callback_payload(
            callback.get("payload")
            if callback.get("payload") is not None
            else callback.get("data")
        )
        chat_id = _chat_target(message, user_id)
        message_id = _message_id(message)
        if user_id is None or callback_id is None or payload is None or chat_id is None:
            return None
        normalized_message: dict[str, Any] = {"chat": {"id": chat_id}}
        if message_id is not None:
            normalized_message["message_id"] = message_id
        return {
            "callback_query": {
                "id": callback_id,
                "data": payload,
                "from": {"id": user_id},
                "message": normalized_message,
            }
        }

    return None


def _message_update(message: dict[str, Any]) -> dict[str, Any] | None:
    user = _as_dict(message.get("sender")) or _as_dict(message.get("user"))
    user_id = _user_id(user)
    chat_id = _chat_target(message, user_id)
    text = _message_text(message)
    contact = _message_contact(message)
    phone = _contact_phone(contact)
    if user_id is None or chat_id is None or (not text and not phone):
        return None
    normalized_message: dict[str, Any] = {
        "chat": {"id": chat_id},
        "from": {"id": user_id},
        "text": text or phone or "",
    }
    if contact:
        normalized_message["contact"] = contact
    message_id = _message_id(message)
    if message_id is not None:
        normalized_message["message_id"] = message_id
    return {"message": normalized_message}


def _message_text(message: dict[str, Any]) -> str | None:
    body = _as_dict(message.get("body"))
    for value in (body.get("text"), message.get("text")):
        if isinstance(value, str) and value:
            return value
    return None


def _message_contact(message: dict[str, Any]) -> dict[str, Any]:
    body = _as_dict(message.get("body"))
    for container in (body, message):
        contact = _as_dict(container.get("contact"))
        if contact:
            return _normalize_contact_payload(contact)
        if isinstance(container.get("phone"), str):
            return {"phone_number": container["phone"]}
    for container in (body, message):
        for attachment in container.get("attachments", []) if isinstance(container.get("attachments"), list) else []:
            attachment_data = _as_dict(attachment)
            if attachment_data.get("type") == "contact":
                return _normalize_contact_payload(_as_dict(attachment_data.get("payload")))
    return {}


def _normalize_contact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    contact = {key: value for key, value in payload.items() if key in {"hash", "vcf_info", "vcf_phone", "phone_number", "phone"}}
    phone = _contact_phone(contact)
    if phone:
        contact["phone_number"] = phone
    return contact


def _contact_phone(contact: dict[str, Any]) -> str | None:
    for value in (contact.get("phone_number"), contact.get("phone"), contact.get("vcf_phone")):
        if isinstance(value, str):
            normalized = normalize_phone(value)
            if re.fullmatch(r"\+7\d{10}", normalized):
                return normalized
            extracted = extract_phone(value)
            if extracted:
                return extracted
    vcf_info = contact.get("vcf_info")
    if isinstance(vcf_info, str):
        normalized_vcf = vcf_info.replace("\\r\\n", "\r\n")
        match = re.search(r"TEL[^:\r\n]*:([^\r\n]+)", normalized_vcf)
        if match:
            phone = normalize_phone(match.group(1))
            if re.fullmatch(r"\+7\d{10}", phone):
                return phone
            return extract_phone(match.group(1))
    return None


def _message_id(message: dict[str, Any]) -> int | str | None:
    body = _as_dict(message.get("body"))
    for value in (body.get("mid"), body.get("message_id"), message.get("message_id"), message.get("mid"), message.get("id")):
        if isinstance(value, int) or (isinstance(value, str) and value):
            return value
    return None


def _chat_target(message: dict[str, Any], user_id: int | str | None) -> str | None:
    recipient = _as_dict(message.get("recipient"))
    chat = _as_dict(message.get("chat"))
    for value in (recipient.get("chat_id"), chat.get("chat_id"), chat.get("id"), message.get("chat_id")):
        if isinstance(value, int) or (isinstance(value, str) and value):
            return f"chat:{value}"
    if user_id is not None:
        return _user_target(user_id)
    return None


def _user_target(user_id: int | str) -> str:
    return f"user:{user_id}"


def _user_id(user: dict[str, Any]) -> int | str | None:
    for value in (user.get("user_id"), user.get("id")):
        if isinstance(value, int) or (isinstance(value, str) and value):
            return value
    return None


def _string_identifier(value: object) -> str | None:
    if isinstance(value, str):
        token = value.strip()
        return token or None
    if isinstance(value, int):
        return str(value)
    return None


def _callback_payload(value: object) -> str | None:
    if isinstance(value, str):
        token = value.strip()
        return token or None
    if isinstance(value, dict):
        for key in ("payload", "data", "callback_data", "value"):
            candidate = _string_identifier(value.get(key))
            if candidate is not None:
                return candidate
    return None


def _normalized_ids(update: dict[str, Any]) -> tuple[int | str | None, int | str | None]:
    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        message = _as_dict(callback_query.get("message"))
        sender = _as_dict(callback_query.get("from"))
        return message.get("chat", {}).get("id") if isinstance(message.get("chat"), dict) else None, _user_id(sender)

    message = _as_dict(update.get("message")) or _as_dict(update.get("edited_message"))
    chat = _as_dict(message.get("chat"))
    sender = _as_dict(message.get("from"))
    return chat.get("id"), _user_id(sender)


def _is_allowed_max_target(settings: AppSettings, chat_id: int | str, user_id: int | str) -> bool:
    if not settings.max_allowed_chat_ids:
        return True
    candidates = {str(chat_id), str(user_id)}
    for value in (chat_id, user_id):
        if isinstance(value, str) and ":" in value:
            candidates.add(value.split(":", 1)[1])
    return bool(candidates.intersection(settings.max_allowed_chat_ids))


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    main()
