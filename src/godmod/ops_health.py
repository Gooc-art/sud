from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from typing import Any
from urllib import error, request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .max_api import MaxApiError, MaxBotClient
from .max_target_state import resolve_max_alert_target, runtime_output_dir
from .operator_reports import find_latest_report_snapshot
from .settings import AppSettings


MAX_BOT_LAUNCHD_LABEL = "com.godmod.max-bot"
MAX_HEALTH_STATE_FILE = "mac_health_state.json"
MAX_HEALTH_LATEST_FILE = "mac_health_latest.json"
DEFAULT_REPORT_TIMEZONE = "Asia/Yekaterinburg"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect mac mini health snapshot for Godmod MAX bot")
    parser.add_argument("--dotenv", default=".env", help="Path to .env file")
    parser.add_argument("--force-alert", action="store_true", help="Send a test MAX alert even if health is currently OK")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = AppSettings.from_env(args.dotenv)
    payload = build_mac_ops_health_payload(settings)
    snapshot_path = write_mac_ops_health_snapshot(settings, payload)
    alert_result = maybe_send_mac_ops_alert(settings, payload, snapshot_path, force_alert=args.force_alert)
    print(format_mac_ops_health_summary(payload, snapshot_path=snapshot_path, alert_result=alert_result))


def build_mac_ops_health_payload(settings: AppSettings, *, now: datetime | None = None) -> dict[str, object]:
    current_time = now or datetime.now(UTC)
    deploy_dir = _resolve_runtime_path(Path.cwd())
    output_dir = runtime_output_dir(settings, base_dir=deploy_dir)
    runner_dir = _resolve_runtime_path(settings.mac_runner_dir or Path.home() / "actions-runner/godmod-prod")
    health_dir = output_dir / "health"
    launchd_log_dir = output_dir / "launchd"
    alert_target = resolve_max_alert_target(settings)

    bot_launchd = _launchd_service_status(MAX_BOT_LAUNCHD_LABEL)
    runner = _runner_status(runner_dir)
    max_api = _max_api_status(settings.max_api_health_timeout_seconds)
    disk = _disk_status(deploy_dir, settings.mac_health_disk_min_gb)
    logs = _log_freshness_status(
        launchd_log_dir / "godmod-max-bot.stdout.log",
        launchd_log_dir / "godmod-max-bot.stderr.log",
        stale_minutes=settings.mac_health_log_stale_min,
        now=current_time,
        service_running=bool(bot_launchd.get("healthy")),
    )
    latest_report = _latest_report_payload(output_dir)
    host_metrics = _host_metrics(deploy_dir)

    checks = {
        "bot_launchd": bot_launchd,
        "runner": runner,
        "max_api": max_api,
        "disk": disk,
        "logs": logs,
    }
    failing_checks = [name for name, status in checks.items() if not bool(status.get("healthy"))]
    overall_status = "healthy" if not failing_checks else "degraded"
    alerting = {
        "enabled": bool(settings.max_bot_token and alert_target),
        "target_chat_id": alert_target or "",
        "configured_target_chat_id": settings.max_health_alert_chat_id or "",
        "target_source": "env" if settings.max_health_alert_chat_id else ("runtime" if alert_target else ""),
        "mode": settings.mac_health_alert_mode,
        "cooldown_minutes": settings.mac_health_alert_cooldown_min,
        "daily_schedule": {
            "timezone": settings.mac_daily_report_timezone or DEFAULT_REPORT_TIMEZONE,
            "hour": settings.mac_daily_report_hour,
            "minute": settings.mac_daily_report_minute,
        },
    }

    return {
        "generated_at": current_time.isoformat(),
        "overall_status": overall_status,
        "overall_status_label": _overall_status_label(overall_status),
        "failing_checks": failing_checks,
        "failing_checks_label": [_check_label(name) for name in failing_checks],
        "host": {
            "hostname": socket.gethostname(),
            "user": os.environ.get("USER", ""),
            "deploy_dir": str(deploy_dir),
            "runner_dir": str(runner_dir),
            "output_dir": str(output_dir),
            "health_dir": str(health_dir),
            **host_metrics,
        },
        "checks": checks,
        "latest_report": latest_report,
        "alerting": alerting,
    }


def write_mac_ops_health_snapshot(settings: AppSettings, payload: dict[str, object]) -> Path:
    output_dir = runtime_output_dir(settings, base_dir=_resolve_runtime_path(Path.cwd()))
    health_dir = output_dir / "health"
    health_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _compact_timestamp(payload.get("generated_at"))
    snapshot_path = health_dir / f"{timestamp}_mac_health.json"
    latest_path = health_dir / MAX_HEALTH_LATEST_FILE
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    snapshot_path.write_text(encoded, encoding="utf-8")
    latest_path.write_text(encoded, encoding="utf-8")
    return snapshot_path


def maybe_send_mac_ops_alert(
    settings: AppSettings,
    payload: dict[str, object],
    snapshot_path: Path,
    *,
    now: datetime | None = None,
    force_alert: bool = False,
) -> dict[str, object]:
    current_time = now or datetime.now(UTC)
    output_dir = runtime_output_dir(settings, base_dir=_resolve_runtime_path(Path.cwd()))
    health_dir = output_dir / "health"
    health_dir.mkdir(parents=True, exist_ok=True)
    state_path = health_dir / MAX_HEALTH_STATE_FILE
    previous_state = _load_state_payload(state_path)
    target_chat_id = resolve_max_alert_target(settings)
    action = "test" if force_alert else _determine_notification_action(
        settings,
        previous_state,
        payload,
        current_time=current_time,
    )
    result: dict[str, object] = {
        "action": action,
        "sent": False,
        "state_path": str(state_path),
        "target_chat_id": target_chat_id or "",
    }

    new_state = {
        "generated_at": payload.get("generated_at", current_time.isoformat()),
        "overall_status": payload.get("overall_status", "unknown"),
        "failing_checks": list(payload.get("failing_checks", [])) if isinstance(payload.get("failing_checks"), list) else [],
        "last_alert_at": previous_state.get("last_alert_at", ""),
        "last_recovery_at": previous_state.get("last_recovery_at", ""),
        "last_daily_status_at": previous_state.get("last_daily_status_at", ""),
    }

    if action == "degraded":
        new_state["last_alert_at"] = current_time.isoformat()
    elif action == "recovered":
        new_state["last_recovery_at"] = current_time.isoformat()
    elif action == "daily_status":
        new_state["last_daily_status_at"] = current_time.isoformat()

    if action and settings.max_bot_token and target_chat_id:
        client = MaxBotClient(settings.max_bot_token, timeout=settings.max_api_health_timeout_seconds)
        caption = format_mac_ops_health_summary(payload, snapshot_path=snapshot_path, alert_result={"action": action, "sent": False})
        try:
            client.send_document(target_chat_id, snapshot_path, caption=caption)
            result["sent"] = True
        except MaxApiError as exc:
            result["error"] = str(exc)
    elif action:
        result["error"] = "MAX alerting is not configured."

    state_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def format_mac_ops_health_summary(
    payload: dict[str, object],
    *,
    snapshot_path: Path,
    alert_result: dict[str, object] | None = None,
) -> str:
    checks = payload.get("checks", {})
    latest_report = payload.get("latest_report", {})
    host = payload.get("host", {})
    overall_status = str(payload.get("overall_status", "unknown"))
    status_label = "норма" if overall_status == "healthy" else "деградация"
    lines = [
        f"Состояние mac mini: {status_label}",
        f"Хост: {host.get('hostname', 'unknown')}",
        f"MAX-бот launchd: {_health_icon(checks, 'bot_launchd')} {_check_summary(checks, 'bot_launchd')}",
        f"Runner: {_health_icon(checks, 'runner')} {_check_summary(checks, 'runner')}",
        f"MAX API: {_health_icon(checks, 'max_api')} {_check_summary(checks, 'max_api')}",
        f"Диск: {_health_icon(checks, 'disk')} {_check_summary(checks, 'disk')}",
        f"Логи: {_health_icon(checks, 'logs')} {_check_summary(checks, 'logs')}",
        f"Снимок: {snapshot_path}",
    ]
    if isinstance(latest_report, dict) and latest_report.get("available"):
        lines.append(
            "Последний отчёт: "
            f"{latest_report.get('generated_at', 'нет данных')} | "
            f"строк={latest_report.get('ranked_accounts', 0)}"
        )
    else:
        lines.append("Последний отчёт: ещё не найден.")
    if alert_result and alert_result.get("action"):
        lines.append(f"Действие alert-контура: {_alert_action_label(str(alert_result.get('action')))}")
    failing = payload.get("failing_checks", [])
    if isinstance(failing, list) and failing:
        lines.append(f"Сбои: {', '.join(str(item) for item in failing)}")
    return "\n".join(lines)


def _health_icon(checks: object, key: str) -> str:
    if not isinstance(checks, dict):
        return "?"
    check = checks.get(key, {})
    if not isinstance(check, dict):
        return "?"
    return "ок" if check.get("healthy") else "сбой"


def _check_summary(checks: object, key: str) -> str:
    if not isinstance(checks, dict):
        return "нет данных"
    check = checks.get(key, {})
    if not isinstance(check, dict):
        return "нет данных"
    return _localize_check_summary(str(check.get("summary", "нет данных")))


def _localize_check_summary(summary: str) -> str:
    token = summary.strip()
    if not token:
        return "нет данных"
    simple_map = {
        "ok": "ок",
        "service is running": "сервис запущен",
        "runner service is healthy": "runner работает",
        "disk ok": "диск в норме",
        "logs ok": "логи свежие",
        "logs stale": "логи устарели",
        "runner down": "runner недоступен",
        "launchd service is unavailable": "launchd-сервис недоступен",
        "MAX alerting is not configured.": "MAX alerting не настроен.",
    }
    if token in simple_map:
        return simple_map[token]
    if token.startswith("last log update ") and token.endswith("s ago"):
        seconds = token.removeprefix("last log update ").removesuffix("s ago")
        return f"последнее обновление логов {seconds} сек. назад"
    if token.startswith("logs are quiet while service is running (") and token.endswith("s)"):
        seconds = token.removeprefix("logs are quiet while service is running (").removesuffix("s)")
        return f"логов давно не было, но сервис работает ({seconds} сек.)"
    if token.startswith("free=") and " total=" in token and " threshold=" in token:
        normalized = token.replace("free=", "свободно=").replace(" total=", " всего=").replace(" threshold=", " порог=")
        return normalized
    if token.startswith("network error: "):
        return token.replace("network error: ", "сетевая ошибка: ", 1)
    return token


def _alert_action_label(action: str) -> str:
    return {
        "degraded": "зафиксирована деградация",
        "recovered": "зафиксировано восстановление",
        "daily_status": "ежедневный статус",
        "test": "тестовое уведомление",
    }.get(action, action)


def _overall_status_label(status: str) -> str:
    return {
        "healthy": "норма",
        "degraded": "деградация",
    }.get(status, status)


def _check_label(name: str) -> str:
    return {
        "bot_launchd": "MAX-бот launchd",
        "runner": "runner",
        "max_api": "MAX API",
        "disk": "диск",
        "logs": "логи",
    }.get(name, name)


def _launchd_service_status(label: str) -> dict[str, object]:
    domain = f"gui/{os.getuid()}"
    completed = _run_command(["launchctl", "print", f"{domain}/{label}"])
    output = completed["output"].lower()
    healthy = bool(completed["ok"]) and "could not find service" not in output and (
        "state = running" in output or "pid =" in output or "active count =" in output
    )
    summary = "service is running" if healthy else (completed["output"][:200] or "launchd service is unavailable")
    return {
        "healthy": healthy,
        "summary": summary,
        "summary_ru": _localize_check_summary(summary),
        "command": f"launchctl print {domain}/{label}",
        "output": completed["output"],
    }


def _runner_status(runner_dir: Path) -> dict[str, object]:
    svc_path = runner_dir / "svc.sh"
    if not svc_path.exists():
        return {
            "healthy": False,
            "summary": f"runner service script not found: {svc_path}",
            "command": "",
            "output": "",
        }
    completed = _run_command(["bash", str(svc_path), "status"], cwd=runner_dir)
    output = completed["output"].lower()
    stopped_markers = ("stopped", "not installed", "not running", "uninstall")
    healthy = bool(completed["ok"]) and not any(marker in output for marker in stopped_markers)
    summary = "runner service is healthy" if healthy else (completed["output"][:200] or "runner service is unhealthy")
    return {
        "healthy": healthy,
        "summary": summary,
        "summary_ru": _localize_check_summary(summary),
        "command": f"bash {svc_path} status",
        "output": completed["output"],
    }


def _max_api_status(timeout_seconds: int) -> dict[str, object]:
    req = request.Request("https://platform-api.max.ru", headers={"User-Agent": "godmod-healthcheck"}, method="HEAD")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            code = getattr(response, "status", 200)
        return {
            "healthy": True,
            "summary": f"HTTP {code}",
            "summary_ru": f"HTTP {code}",
            "command": "HEAD https://platform-api.max.ru",
            "output": "",
        }
    except error.HTTPError as exc:
        return {
            "healthy": exc.code < 500,
            "summary": f"HTTP {exc.code}",
            "summary_ru": f"HTTP {exc.code}",
            "command": "HEAD https://platform-api.max.ru",
            "output": str(exc),
        }
    except OSError as exc:
        summary = f"network error: {exc}"
        return {
            "healthy": False,
            "summary": summary,
            "summary_ru": f"сетевая ошибка: {exc}",
            "command": "HEAD https://platform-api.max.ru",
            "output": str(exc),
        }


def _disk_status(path: Path, minimum_free_gb: int) -> dict[str, object]:
    usage = shutil.disk_usage(path)
    free_gb = round(usage.free / 1024**3, 2)
    total_gb = round(usage.total / 1024**3, 2)
    healthy = free_gb >= minimum_free_gb
    return {
        "healthy": healthy,
        "summary": f"free={free_gb}GB total={total_gb}GB threshold={minimum_free_gb}GB",
        "summary_ru": _localize_check_summary(f"free={free_gb}GB total={total_gb}GB threshold={minimum_free_gb}GB"),
        "path": str(path),
        "free_gb": free_gb,
        "total_gb": total_gb,
    }


def _log_freshness_status(
    stdout_log: Path,
    stderr_log: Path,
    *,
    stale_minutes: int,
    now: datetime,
    service_running: bool,
) -> dict[str, object]:
    candidates = [path for path in (stdout_log, stderr_log) if path.exists()]
    if not candidates:
        summary = "launchd logs are missing"
        return {
            "healthy": False,
            "summary": summary,
            "summary_ru": "launchd-логи отсутствуют",
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
        }
    latest_mtime = max(path.stat().st_mtime for path in candidates)
    last_seen = datetime.fromtimestamp(latest_mtime, tz=UTC)
    age_seconds = max(0, int((now - last_seen).total_seconds()))
    if age_seconds <= stale_minutes * 60:
        summary = f"last log update {age_seconds}s ago"
        healthy = True
    elif service_running:
        summary = f"logs are quiet while service is running ({age_seconds}s)"
        healthy = True
    else:
        summary = f"last log update {age_seconds}s ago"
        healthy = False
    return {
        "healthy": healthy,
        "summary": summary,
        "summary_ru": _localize_check_summary(summary),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
        "last_log_at": last_seen.isoformat(),
        "stale_minutes": stale_minutes,
    }


def _latest_report_payload(output_dir: Path) -> dict[str, object]:
    snapshot = find_latest_report_snapshot(output_dir)
    if snapshot is None:
        return {"available": False}
    payload = snapshot.manifest_payload
    request_payload = payload.get("request", {})
    counts_payload = payload.get("counts", {})
    return {
        "available": True,
        "generated_at": str(payload.get("generated_at", "")),
        "workbook": str(snapshot.workbook),
        "manifest": str(snapshot.manifest) if snapshot.manifest is not None else "",
        "pdf": str(snapshot.pdf) if snapshot.pdf is not None else "",
        "cities": list(request_payload.get("cities", [])) if isinstance(request_payload, dict) else [],
        "services": list(request_payload.get("services", [])) if isinstance(request_payload, dict) else [],
        "ranked_accounts": int(counts_payload.get("ranked_accounts", 0)) if isinstance(counts_payload, dict) else 0,
    }


def _host_metrics(deploy_dir: Path) -> dict[str, object]:
    load_values = ()
    try:
        load_values = tuple(round(value, 2) for value in os.getloadavg())
    except OSError:
        load_values = ()
    memory_output = _run_command(["memory_pressure", "-Q"])
    if not memory_output["ok"]:
        memory_output = _run_command(["vm_stat"])
    return {
        "cwd": str(Path.cwd()),
        "load_average": list(load_values),
        "memory_pressure": memory_output["output"][:500],
        "python": shutil.which("python3") or "",
        "deploy_dir_exists": deploy_dir.exists(),
    }


def _run_command(command: list[str], *, cwd: Path | None = None, timeout: int = 15) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except OSError as exc:
        return {"ok": False, "returncode": None, "output": str(exc)}
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part).strip()
    return {"ok": completed.returncode == 0, "returncode": completed.returncode, "output": output}


def _determine_alert_action(
    previous_state: dict[str, object],
    payload: dict[str, object],
    *,
    current_time: datetime,
    cooldown_minutes: int,
) -> str | None:
    previous_status = str(previous_state.get("overall_status", ""))
    previous_failures = tuple(sorted(str(item) for item in previous_state.get("failing_checks", []) if str(item)))
    current_status = str(payload.get("overall_status", ""))
    current_failures = tuple(sorted(str(item) for item in payload.get("failing_checks", []) if str(item)))
    if current_status != "healthy":
        if previous_status != current_status or previous_failures != current_failures:
            return "degraded"
        last_alert_at = _parse_iso_datetime(previous_state.get("last_alert_at"))
        if last_alert_at is None:
            return "degraded"
        if current_time - last_alert_at >= timedelta(minutes=cooldown_minutes):
            return "degraded"
        return None
    if previous_status and previous_status != "healthy":
        return "recovered"
    return None


def _determine_notification_action(
    settings: AppSettings,
    previous_state: dict[str, object],
    payload: dict[str, object],
    *,
    current_time: datetime,
) -> str | None:
    if settings.mac_health_alert_mode == "off":
        return None
    if settings.mac_health_alert_mode == "changes":
        return _determine_alert_action(
            previous_state,
            payload,
            current_time=current_time,
            cooldown_minutes=settings.mac_health_alert_cooldown_min,
        )
    if _should_send_daily_status(
        previous_state,
        current_time=current_time,
        timezone_name=settings.mac_daily_report_timezone or DEFAULT_REPORT_TIMEZONE,
        schedule_hour=settings.mac_daily_report_hour,
        schedule_minute=settings.mac_daily_report_minute,
    ):
        return "daily_status"
    return None


def _should_send_daily_status(
    previous_state: dict[str, object],
    *,
    current_time: datetime,
    timezone_name: str,
    schedule_hour: int,
    schedule_minute: int,
) -> bool:
    timezone = _resolve_timezone(timezone_name)
    local_time = current_time.astimezone(timezone)
    scheduled_time = local_time.replace(hour=schedule_hour, minute=schedule_minute, second=0, microsecond=0)
    if local_time < scheduled_time:
        return False
    last_daily_status_at = _parse_iso_datetime(previous_state.get("last_daily_status_at"))
    if last_daily_status_at is None:
        return True
    return last_daily_status_at.astimezone(timezone).date() != local_time.date()


def _load_state_payload(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or DEFAULT_REPORT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_REPORT_TIMEZONE)


def _resolve_runtime_path(path: Path, *, base_dir: Path | None = None) -> Path:
    if path.is_absolute():
        return path
    root = base_dir or Path.cwd()
    return (root / path).resolve()


def _compact_timestamp(value: object) -> str:
    if isinstance(value, str):
        token = value.replace("-", "").replace(":", "").replace("T", "_").replace("+0000", "").replace("+00:00", "")
        token = token.replace("Z", "").replace(".", "")
        if token:
            return token[:15]
    return datetime.now().strftime("%Y%m%d_%H%M%S")


if __name__ == "__main__":
    main()
