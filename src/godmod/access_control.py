from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from .settings import AppSettings


def access_state_path(output_dir: Path) -> Path:
    return output_dir / "runtime" / "bot_access_state.json"


def is_access_protected(settings: AppSettings) -> bool:
    return bool(settings.bot_access_code)


def is_authorized_user(settings: AppSettings, user_id: int | str) -> bool:
    if not is_access_protected(settings):
        return True
    return normalize_user_id(user_id) in load_authorized_users(settings)


def verify_access_code(settings: AppSettings, code: str | None) -> bool:
    secret = (settings.bot_access_code or "").strip()
    candidate = (code or "").strip()
    return bool(secret) and candidate == secret


def authorize_user(
    settings: AppSettings,
    *,
    user_id: int | str,
    chat_id: int | str,
    now: datetime | None = None,
) -> dict[str, object]:
    timestamp = now or datetime.now(UTC)
    path = access_state_path(settings.runtime.output_dir)
    payload = _load_payload(path)
    authorized_users = _authorized_users_from_payload(payload)
    normalized_user_id = normalize_user_id(user_id)
    authorized_users.add(normalized_user_id)
    payload["authorized_users"] = sorted(authorized_users)
    payload["last_authorized_user_id"] = normalized_user_id
    payload["last_authorized_chat_id"] = str(chat_id)
    payload["updated_at"] = timestamp.isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def request_phone_access(
    settings: AppSettings,
    *,
    user_id: int | str,
    chat_id: int | str,
    phone: str,
    now: datetime | None = None,
) -> dict[str, object]:
    normalized_user_id = normalize_user_id(user_id)
    timestamp = now or datetime.now(UTC)
    path = access_state_path(settings.runtime.output_dir)
    payload = _load_payload(path)
    pending = _dict_payload(payload.get("pending_phone_requests"))
    denied = _dict_payload(payload.get("denied_phone_requests"))
    request_payload = {
        "user_id": normalized_user_id,
        "chat_id": str(chat_id),
        "phone": normalize_phone(phone),
        "requested_at": timestamp.isoformat(),
    }
    pending[normalized_user_id] = request_payload
    denied.pop(normalized_user_id, None)
    payload["pending_phone_requests"] = pending
    payload["denied_phone_requests"] = denied
    payload["last_phone_request_user_id"] = normalized_user_id
    payload["updated_at"] = timestamp.isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return request_payload


def approve_phone_access(settings: AppSettings, user_id: int | str, *, now: datetime | None = None) -> dict[str, object] | None:
    normalized_user_id = normalize_user_id(user_id)
    timestamp = now or datetime.now(UTC)
    path = access_state_path(settings.runtime.output_dir)
    payload = _load_payload(path)
    pending = _dict_payload(payload.get("pending_phone_requests"))
    request_payload = pending.pop(normalized_user_id, None)
    if not isinstance(request_payload, dict):
        return None
    authorized_users = _authorized_users_from_payload(payload)
    authorized_users.add(normalized_user_id)
    payload["authorized_users"] = sorted(authorized_users)
    payload["pending_phone_requests"] = pending
    payload["last_authorized_user_id"] = normalized_user_id
    payload["last_authorized_chat_id"] = str(request_payload.get("chat_id") or "")
    payload["updated_at"] = timestamp.isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return request_payload


def deny_phone_access(settings: AppSettings, user_id: int | str, *, now: datetime | None = None) -> dict[str, object] | None:
    normalized_user_id = normalize_user_id(user_id)
    timestamp = now or datetime.now(UTC)
    path = access_state_path(settings.runtime.output_dir)
    payload = _load_payload(path)
    pending = _dict_payload(payload.get("pending_phone_requests"))
    request_payload = pending.pop(normalized_user_id, None)
    if not isinstance(request_payload, dict):
        return None
    denied = _dict_payload(payload.get("denied_phone_requests"))
    denied[normalized_user_id] = {**request_payload, "denied_at": timestamp.isoformat()}
    payload["pending_phone_requests"] = pending
    payload["denied_phone_requests"] = denied
    payload["updated_at"] = timestamp.isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return request_payload


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"
    return value.strip()


def extract_phone(value: str) -> str | None:
    match = re.search(r"(?:\+7|8)[\s\-()]*\d[\d\s\-()]{8,}", value)
    if not match:
        return None
    phone = normalize_phone(match.group(0))
    return phone if re.fullmatch(r"\+7\d{10}", phone) else None


def load_authorized_users(settings: AppSettings) -> set[str]:
    path = access_state_path(settings.runtime.output_dir)
    payload = _load_payload(path)
    return _authorized_users_from_payload(payload)


def _authorized_users_from_payload(payload: dict[str, object]) -> set[str]:
    raw_users = payload.get("authorized_users", [])
    if not isinstance(raw_users, list):
        return set()
    results: set[str] = set()
    for item in raw_users:
        if isinstance(item, str) and item.strip():
            results.add(item.strip())
    return results


def normalize_user_id(user_id: int | str) -> str:
    token = str(user_id).strip()
    if token.startswith("user:"):
        return token
    return f"user:{token}"


def _dict_payload(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _load_payload(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
