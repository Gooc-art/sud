from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import PostRecord


class VkDiskCache:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.owner_meta_dir = self.root_dir / "owner_meta"
        self.wall_dir = self.root_dir / "wall"
        self.city_dir = self.root_dir / "city"
        for directory in (self.owner_meta_dir, self.wall_dir, self.city_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def get_owner_meta(
        self,
        owner_id: int,
        *,
        max_age_hours: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        path = self.owner_meta_dir / f"{owner_id}.json"
        data = _read_json(path)
        if not isinstance(data, dict):
            return None
        if max_age_hours is not None and not _is_fresh(data.get("cached_at"), max_age_hours, now=now):
            return None
        if "payload" in data and isinstance(data["payload"], dict):
            return data["payload"]
        return data

    def set_owner_meta(self, owner_id: int, meta: dict[str, Any], *, cached_at: datetime | None = None) -> None:
        path = self.owner_meta_dir / f"{owner_id}.json"
        _write_json(
            path,
            {
                "cached_at": (cached_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
                "payload": meta,
            },
        )

    def get_wall_posts(
        self,
        cache_key: str,
        *,
        max_age_hours: int | None = None,
        now: datetime | None = None,
    ) -> list[PostRecord] | None:
        path = self.wall_dir / f"{_safe_name(cache_key)}.json"
        data = _read_json(path)
        if isinstance(data, dict):
            if max_age_hours is not None and not _is_fresh(data.get("cached_at"), max_age_hours, now=now):
                return None
            data = data.get("items")
        if not isinstance(data, list):
            return None
        posts: list[PostRecord] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            published_at = item.get("published_at")
            if not isinstance(published_at, str):
                continue
            posts.append(
                PostRecord(
                    url=str(item.get("url") or ""),
                    text=str(item.get("text") or ""),
                    published_at=datetime.fromisoformat(published_at),
                    likes=_optional_int(item.get("likes")),
                    comments=_optional_int(item.get("comments")),
                    reposts=_optional_int(item.get("reposts")),
                    views=_optional_int(item.get("views")),
                )
            )
        return posts

    def set_wall_posts(self, cache_key: str, posts: list[PostRecord], *, cached_at: datetime | None = None) -> None:
        path = self.wall_dir / f"{_safe_name(cache_key)}.json"
        _write_json(
            path,
            {
                "cached_at": (cached_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
                "items": [
                    {
                        "url": post.url,
                        "text": post.text,
                        "published_at": post.published_at.astimezone(UTC).isoformat(),
                        "likes": post.likes,
                        "comments": post.comments,
                        "reposts": post.reposts,
                        "views": post.views,
                    }
                    for post in posts
                ],
            },
        )

    def get_city_id(
        self,
        city: str,
        *,
        max_age_hours: int | None = None,
        now: datetime | None = None,
    ) -> int | None | type(Ellipsis):
        path = self.city_dir / f"{_safe_name(city)}.json"
        data = _read_json(path)
        if not isinstance(data, dict) or "city_id" not in data:
            return Ellipsis
        if max_age_hours is not None and not _is_fresh(data.get("cached_at"), max_age_hours, now=now):
            return Ellipsis
        return _optional_int(data.get("city_id"))

    def set_city_id(self, city: str, city_id: int | None, *, cached_at: datetime | None = None) -> None:
        path = self.city_dir / f"{_safe_name(city)}.json"
        _write_json(
            path,
            {
                "cached_at": (cached_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
                "city_id": city_id,
            },
        )


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.casefold())


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


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
