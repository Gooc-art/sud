from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import SearchRequest
from .request_options import format_period_label


@dataclass(slots=True)
class ActiveReportRun:
    lock_id: str
    chat_id: str
    user_id: str
    started_at: datetime
    pid: int
    hostname: str
    cities: list[str]
    services: list[str]
    period_days: int
    report_mode: str


def report_lock_path(output_dir: Path) -> Path:
    return output_dir / "runtime" / "active_report_run.json"


def try_acquire_report_run(
    output_dir: Path,
    *,
    chat_id: int | str,
    user_id: int | str,
    request: SearchRequest,
    now: datetime | None = None,
) -> tuple[ActiveReportRun | None, ActiveReportRun | None]:
    path = report_lock_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = now or datetime.now(UTC)

    for _ in range(2):
        existing = read_active_report_run(output_dir)
        if existing is not None:
            if _is_stale(existing):
                _delete_lock_file(path)
            else:
                return None, existing

        payload = {
            "lock_id": str(uuid.uuid4()),
            "chat_id": str(chat_id),
            "user_id": _normalize_user_id(user_id),
            "started_at": timestamp.isoformat(),
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "cities": list(request.cities),
            "services": [service.name for service in request.services],
            "period_days": int(request.period_days),
            "report_mode": str(request.report_mode),
        }
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return _from_payload(payload), None

    return None, read_active_report_run(output_dir)


def read_active_report_run(output_dir: Path) -> ActiveReportRun | None:
    payload = _load_payload(report_lock_path(output_dir))
    if not payload:
        return None
    return _from_payload(payload)


def release_report_run(output_dir: Path, lock_id: str) -> None:
    path = report_lock_path(output_dir)
    payload = _load_payload(path)
    if not payload:
        return
    if str(payload.get("lock_id", "")) != lock_id:
        return
    _delete_lock_file(path)


def format_report_busy_message(run: ActiveReportRun, *, now: datetime | None = None, same_user: bool = False) -> str:
    timestamp = now or datetime.now(UTC)
    age_seconds = max(0, int((timestamp - run.started_at).total_seconds()))
    owner_label = "вами" if same_user else f"пользователем {run.user_id}"
    services_label = ", ".join(run.services[:3]) if run.services else "не указаны"
    if len(run.services) > 3:
        services_label += ", ..."
    cities_label = ", ".join(run.cities) if run.cities else "не указаны"
    return (
        "Сбор уже запущен.\n"
        f"Запуск занят {owner_label}.\n"
        f"Чат: {run.chat_id}\n"
        f"Старт: {run.started_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Идёт уже: {_format_duration(age_seconds)}\n"
        f"Города: {cities_label}\n"
        f"Услуги: {services_label}\n"
        f"Период: {format_period_label(run.period_days)}"
    )


def _from_payload(payload: dict[str, object]) -> ActiveReportRun | None:
    try:
        lock_id = str(payload["lock_id"])
        chat_id = str(payload["chat_id"])
        user_id = str(payload["user_id"])
        started_at = datetime.fromisoformat(str(payload["started_at"]))
        pid = int(payload["pid"])
        hostname = str(payload["hostname"])
        cities = [str(item) for item in payload.get("cities", []) if str(item)]
        services = [str(item) for item in payload.get("services", []) if str(item)]
        period_days = int(payload.get("period_days", 0))
        report_mode = str(payload.get("report_mode", "all"))
    except (KeyError, TypeError, ValueError):
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return ActiveReportRun(
        lock_id=lock_id,
        chat_id=chat_id,
        user_id=user_id,
        started_at=started_at,
        pid=pid,
        hostname=hostname,
        cities=cities,
        services=services,
        period_days=period_days,
        report_mode=report_mode,
    )


def _is_stale(run: ActiveReportRun) -> bool:
    if run.hostname != socket.gethostname():
        return False
    try:
        os.kill(run.pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _load_payload(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _delete_lock_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _normalize_user_id(user_id: int | str) -> str:
    token = str(user_id).strip()
    if token.startswith("user:"):
        return token
    return f"user:{token}"


def _format_duration(age_seconds: int) -> str:
    minutes, seconds = divmod(age_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}ч {minutes}м {seconds}с"
    if minutes:
        return f"{minutes}м {seconds}с"
    return f"{seconds}с"
