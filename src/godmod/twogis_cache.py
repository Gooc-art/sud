from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class TwoGisDiskCache:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.search_dir = self.root_dir / "search"
        self.search_dir.mkdir(parents=True, exist_ok=True)

    def get_search_payload(
        self,
        params: dict[str, object],
        *,
        fields: str,
        max_age_hours: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        path = self.search_dir / f"{_search_key(params, fields=fields)}.json"
        data = _read_json(path)
        if not isinstance(data, dict):
            return None
        if max_age_hours is not None and not _is_fresh(data.get("cached_at"), max_age_hours, now=now):
            return None
        payload = data.get("payload")
        return payload if isinstance(payload, dict) else None

    def set_search_payload(
        self,
        params: dict[str, object],
        payload: dict[str, Any],
        *,
        fields: str,
        cached_at: datetime | None = None,
    ) -> None:
        path = self.search_dir / f"{_search_key(params, fields=fields)}.json"
        _write_json(
            path,
            {
                "cached_at": (cached_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
                "payload": payload,
            },
        )


def _search_key(params: dict[str, object], *, fields: str) -> str:
    normalized = json.dumps({"params": params, "fields": fields}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_fresh(raw_cached_at: object, max_age_hours: int, *, now: datetime | None = None) -> bool:
    if not isinstance(raw_cached_at, str):
        return False
    try:
        cached_at = datetime.fromisoformat(raw_cached_at)
    except ValueError:
        return False
    current_time = now or datetime.now(UTC)
    age_seconds = (current_time - cached_at).total_seconds()
    return age_seconds <= max(max_age_hours, 0) * 3600
