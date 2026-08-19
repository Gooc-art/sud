from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from .settings import AppSettings


MAX_LAST_TARGET_FILE = "max_last_target.json"


def remember_last_max_target(
    settings: AppSettings,
    *,
    chat_id: int | str,
    user_id: int | str,
    update_type: str,
    now: datetime | None = None,
) -> Path:
    current_time = now or datetime.now(UTC)
    target_path = max_last_target_path(settings)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": current_time.isoformat(),
        "chat_id": _normalize_target(chat_id),
        "user_id": _normalize_user_target(user_id),
        "preferred_alert_target": _normalize_target(chat_id) or _normalize_user_target(user_id) or "",
        "update_type": update_type,
    }
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_path


def load_last_max_target(settings: AppSettings) -> dict[str, Any]:
    target_path = max_last_target_path(settings)
    if not target_path.exists():
        return {}
    try:
        payload = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_max_alert_target(settings: AppSettings) -> str | None:
    if settings.max_health_alert_chat_id:
        return settings.max_health_alert_chat_id
    payload = load_last_max_target(settings)
    for key in ("preferred_alert_target", "chat_id", "user_id"):
        value = payload.get(key)
        if isinstance(value, str):
            token = value.strip()
            if token:
                return token
    return None


def max_last_target_path(settings: AppSettings, *, base_dir: Path | None = None) -> Path:
    return runtime_output_dir(settings, base_dir=base_dir) / "health" / MAX_LAST_TARGET_FILE


def runtime_output_dir(settings: AppSettings, *, base_dir: Path | None = None) -> Path:
    deploy_dir = (base_dir or Path.cwd()).expanduser()
    output_dir = settings.runtime.output_dir.expanduser()
    if not output_dir.is_absolute():
        output_dir = deploy_dir / output_dir
    return output_dir


def _normalize_target(value: int | str) -> str:
    token = str(value).strip()
    return token


def _normalize_user_target(value: int | str) -> str:
    token = str(value).strip()
    if not token:
        return ""
    if ":" in token:
        return token
    return f"user:{token}"
