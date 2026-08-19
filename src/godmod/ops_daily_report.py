from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from .max_api import MaxApiError, MaxBotClient
from .max_target_state import resolve_max_alert_target, runtime_output_dir
from .operator_reports import build_daily_report_payload, format_daily_report_summary
from .settings import AppSettings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send daily MAX report summary for mac mini production bot")
    parser.add_argument("--dotenv", default=".env", help="Path to .env file")
    parser.add_argument("--day-offset", type=int, default=1, help="0=today, 1=yesterday")
    parser.add_argument("--force-send", action="store_true", help="Attempt to send the daily report even if there were no runs")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = AppSettings.from_env(args.dotenv)
    payload = build_daily_report_payload(
        output_dir=runtime_output_dir(settings),
        day_offset=max(0, args.day_offset),
        timezone_name=settings.mac_daily_report_timezone,
    )
    report_path = write_daily_report_snapshot(settings, payload)
    result = send_daily_report(settings, payload, report_path, force_send=args.force_send)
    print(format_daily_report_summary(payload))
    if result.get("target_chat_id"):
        print(f"Целевой чат: {result['target_chat_id']}")
    if result.get("sent"):
        print("Ежедневная сводка отправлена.")
    elif result.get("error"):
        print(f"Отправка пропущена: {result['error']}")


def write_daily_report_snapshot(settings: AppSettings, payload: dict[str, object]) -> Path:
    output_dir = runtime_output_dir(settings)
    health_dir = output_dir / "health"
    health_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = health_dir / f"{timestamp}_daily_report.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def send_daily_report(
    settings: AppSettings,
    payload: dict[str, object],
    report_path: Path,
    *,
    force_send: bool = False,
) -> dict[str, object]:
    target_chat_id = resolve_max_alert_target(settings)
    result = {"sent": False, "target_chat_id": target_chat_id or ""}
    if not settings.max_bot_token:
        result["error"] = "MAX_BOT_TOKEN is not configured."
        return result
    if not target_chat_id:
        result["error"] = "MAX alert target is not configured."
        return result
    if not force_send and int(payload.get("runs", {}).get("total", 0) if isinstance(payload.get("runs"), dict) else 0) == 0:
        result["error"] = "No runs in the selected window."
        return result
    client = MaxBotClient(settings.max_bot_token, timeout=settings.max_api_health_timeout_seconds)
    try:
        client.send_document(target_chat_id, report_path, caption=format_daily_report_summary(payload))
        result["sent"] = True
    except MaxApiError as exc:
        result["error"] = str(exc)
    return result


if __name__ == "__main__":
    main()
