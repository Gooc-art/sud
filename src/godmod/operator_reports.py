from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from collections import Counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(slots=True)
class LatestReportSnapshot:
    workbook: Path
    manifest: Path | None
    manifest_payload: dict[str, object]
    pdf: Path | None


def find_latest_report_snapshot(output_dir: Path) -> LatestReportSnapshot | None:
    output_path = Path(output_dir)
    manifest_candidate = _latest_manifest_from_run_history(output_path)
    if manifest_candidate is not None:
        manifest_path, manifest_payload = manifest_candidate
        snapshot = _snapshot_from_manifest(manifest_path, manifest_payload)
        if snapshot is not None:
            return snapshot

    manifest_candidates = sorted(output_path.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for manifest_path in manifest_candidates:
        manifest_payload = _load_manifest_payload(manifest_path)
        if manifest_payload is None:
            continue
        snapshot = _snapshot_from_manifest(manifest_path, manifest_payload)
        if snapshot is not None:
            return snapshot
    return None


def build_health_payload(
    *,
    output_dir: Path,
    cache_dir: Path,
    startup_at: datetime,
    platforms: list[str],
    use_mock_data: bool,
    allowed_chat_ids: list[int],
    rule_config_path: Path | None,
    yandex_maps_requested: bool,
) -> dict[str, object]:
    now = datetime.now(UTC)
    latest_report = find_latest_report_snapshot(output_dir)
    latest_report_payload = _health_latest_report_payload(latest_report)
    run_history_path = output_dir / "run_history.jsonl"
    validation_dataset_path = Path("data/validation_dataset.yanao_template.json")
    return {
        "generated_at": now.isoformat(),
        "startup_at": startup_at.astimezone(UTC).isoformat(),
        "uptime_seconds": int((now - startup_at.astimezone(UTC)).total_seconds()),
        "runtime": {
            "output_dir": str(output_dir),
            "cache_dir": str(cache_dir),
            "platforms": list(platforms),
            "use_mock_data": use_mock_data,
            "allowed_chat_ids": list(allowed_chat_ids),
            "rule_config_path": str(rule_config_path) if rule_config_path is not None else "",
            "yandex_maps_requested": yandex_maps_requested,
            "yandex_maps_export_enabled": False,
            "yandex_maps_block_reason": (
                "Yandex Organization Search API is not enabled for report export: "
                "official docs say only the basic license is available and saving/modifying received data is prohibited."
                if yandex_maps_requested
                else ""
            ),
        },
        "artifacts": {
            "run_history_path": str(run_history_path),
            "run_history_exists": run_history_path.exists(),
            "validation_dataset_path": str(validation_dataset_path),
            "validation_dataset_exists": validation_dataset_path.exists(),
        },
        "latest_report": latest_report_payload,
    }


def format_health_summary(payload: dict[str, object]) -> str:
    runtime = payload.get("runtime", {})
    latest_report = payload.get("latest_report", {})
    platforms = ", ".join(runtime.get("platforms", [])) if isinstance(runtime, dict) else ""
    uptime_seconds = int(payload.get("uptime_seconds", 0) or 0)
    lines = [
        "Health-снимок готов.",
        f"Аптайм: {format_duration(uptime_seconds)}",
        f"Платформы: {platforms or 'нет'}",
        f"Mock-режим: {'да' if _runtime_flag(runtime, 'use_mock_data') else 'нет'}",
    ]
    if isinstance(runtime, dict) and runtime.get("yandex_maps_requested"):
        lines.append("Яндекс Карты: ключ задан, но экспорт отключён лицензией.")
    if isinstance(latest_report, dict) and latest_report.get("available"):
        lines.extend(
            [
                f"Последний отчёт: {latest_report.get('generated_at', 'нет даты')}",
                f"Города: {', '.join(latest_report.get('cities', [])) or 'нет'}",
                f"Услуги: {', '.join(latest_report.get('services', [])) or 'нет'}",
                f"Строк: {latest_report.get('ranked_accounts', 0)}",
                f"PDF: {latest_report.get('pdf_status', 'unknown')}",
            ]
        )
    else:
        lines.append("Последний отчёт: ещё не найден.")
    return "\n".join(lines)


def format_last_report_caption(snapshot: LatestReportSnapshot) -> str:
    payload = snapshot.manifest_payload
    request = payload.get("request", {})
    counts = payload.get("counts", {})
    pdf_block = payload.get("pdf", {})
    cities = request.get("cities", []) if isinstance(request, dict) else []
    services = request.get("services", []) if isinstance(request, dict) else []
    generated_at = str(payload.get("generated_at", ""))
    return (
        "Последний отчёт из истории.\n"
        f"Дата: {generated_at or 'нет данных'}\n"
        f"Города: {', '.join(cities) or 'нет'}\n"
        f"Услуги: {', '.join(services) or 'нет'}\n"
        f"Строк: {counts.get('ranked_accounts', 0) if isinstance(counts, dict) else 0}\n"
        f"PDF: {pdf_block.get('status', 'unknown') if isinstance(pdf_block, dict) else 'unknown'}"
    )


def build_daily_report_payload(
    *,
    output_dir: Path,
    now: datetime | None = None,
    day_offset: int = 1,
    timezone_name: str | None = None,
) -> dict[str, object]:
    current_time = now or datetime.now().astimezone()
    local_time = current_time.astimezone(_resolve_timezone(timezone_name))
    target_date = local_time.date() - timedelta(days=max(0, day_offset))
    entries = _daily_run_history_entries(Path(output_dir), target_date=target_date, local_time=local_time)
    latest_report = find_latest_report_snapshot(Path(output_dir))

    duration_values = [value for value in (_entry_duration_seconds(item) for item in entries) if value is not None]
    collection_values = [value for value in (_entry_collection_duration_seconds(item) for item in entries) if value is not None]
    export_values = [value for value in (_entry_export_duration_seconds(item) for item in entries) if value is not None]
    ranked_counts = [_entry_count(item, "ranked_accounts") for item in entries]
    raw_counts = [_entry_count(item, "raw_candidates") for item in entries]
    empty_runs = sum(1 for item in entries if _entry_count(item, "ranked_accounts") == 0)
    non_empty_runs = sum(1 for item in entries if _entry_count(item, "ranked_accounts") > 0)
    platform_failure_runs = sum(1 for item in entries if _entry_platform_failures(item))
    city_counter: Counter[str] = Counter()
    service_counter: Counter[str] = Counter()
    platform_failure_counter: Counter[str] = Counter()
    origin_counter: Counter[str] = Counter()

    for item in entries:
        request = item.get("request", {})
        meta = item.get("meta", {})
        if isinstance(request, dict):
            city_counter.update(str(city) for city in request.get("cities", []) if str(city).strip())
            service_counter.update(str(service) for service in request.get("services", []) if str(service).strip())
        if isinstance(meta, dict):
            origin = str(meta.get("report_origin", "")).strip() or "unknown"
            origin_counter.update([origin])
        platform_failure_counter.update(_entry_platform_failures(item))

    first_run = entries[0] if entries else None
    last_run = entries[-1] if entries else None

    return {
        "generated_at": current_time.astimezone(UTC).isoformat(),
        "report_date": target_date.isoformat(),
        "report_date_label": target_date.strftime("%d.%m.%Y"),
        "timezone": timezone_name or str(local_time.tzinfo or ""),
        "window": {
            "start_local": f"{target_date.isoformat()}T00:00:00",
            "end_local": f"{target_date.isoformat()}T23:59:59",
        },
        "runs": {
            "total": len(entries),
            "non_empty": non_empty_runs,
            "empty": empty_runs,
            "with_platform_failures": platform_failure_runs,
            "total_ranked_accounts": sum(ranked_counts),
            "avg_ranked_accounts": round(sum(ranked_counts) / len(ranked_counts), 2) if ranked_counts else 0.0,
            "total_raw_candidates": sum(raw_counts),
            "avg_raw_candidates": round(sum(raw_counts) / len(raw_counts), 2) if raw_counts else 0.0,
            "runs_with_duration": len(duration_values),
            "total_duration_seconds": round(sum(duration_values), 3) if duration_values else 0.0,
            "avg_duration_seconds": round(sum(duration_values) / len(duration_values), 3) if duration_values else 0.0,
            "max_duration_seconds": round(max(duration_values), 3) if duration_values else 0.0,
            "runs_with_collection_duration": len(collection_values),
            "total_collection_duration_seconds": round(sum(collection_values), 3) if collection_values else 0.0,
            "avg_collection_duration_seconds": round(sum(collection_values) / len(collection_values), 3) if collection_values else 0.0,
            "max_collection_duration_seconds": round(max(collection_values), 3) if collection_values else 0.0,
            "runs_with_export_duration": len(export_values),
            "total_export_duration_seconds": round(sum(export_values), 3) if export_values else 0.0,
            "avg_export_duration_seconds": round(sum(export_values) / len(export_values), 3) if export_values else 0.0,
            "max_export_duration_seconds": round(max(export_values), 3) if export_values else 0.0,
            "first_run_at": str(first_run.get("generated_at", "")) if isinstance(first_run, dict) else "",
            "last_run_at": str(last_run.get("generated_at", "")) if isinstance(last_run, dict) else "",
        },
        "top_cities": [{"name": name, "count": count} for name, count in city_counter.most_common(5)],
        "top_services": [{"name": name, "count": count} for name, count in service_counter.most_common(5)],
        "platform_failures": [{"platform": name, "count": count} for name, count in platform_failure_counter.most_common()],
        "report_origins": [{"name": name, "count": count} for name, count in origin_counter.most_common()],
        "latest_run": _daily_latest_run_payload(last_run),
        "latest_report": _health_latest_report_payload(latest_report),
    }


def format_daily_report_summary(payload: dict[str, object]) -> str:
    runs = payload.get("runs", {})
    top_cities = payload.get("top_cities", [])
    top_services = payload.get("top_services", [])
    platform_failures = payload.get("platform_failures", [])
    report_origins = payload.get("report_origins", [])
    latest_run = payload.get("latest_run", {})
    lines = [
        f"Ежедневная сводка за {payload.get('report_date_label', 'нет даты')}",
        f"Выгрузок: {_payload_int(runs, 'total')}",
        f"С результатом: {_payload_int(runs, 'non_empty')} | пустых: {_payload_int(runs, 'empty')}",
        f"Со сбоями платформ: {_payload_int(runs, 'with_platform_failures')}",
        "Окно активности: "
        f"{_daily_time_label(runs, 'first_run_at')} → {_daily_time_label(runs, 'last_run_at')}",
        (
            "Сбор данных: "
            f"{format_duration(int(round(_payload_float(runs, 'total_collection_duration_seconds'))))} суммарно, "
            f"в среднем {format_duration(int(round(_payload_float(runs, 'avg_collection_duration_seconds'))))}"
        ),
        (
            "Экспорт файлов: "
            f"{format_duration(int(round(_payload_float(runs, 'total_export_duration_seconds'))))} суммарно, "
            f"в среднем {format_duration(int(round(_payload_float(runs, 'avg_export_duration_seconds'))))}"
        ),
        (
            "Полное время: "
            f"{format_duration(int(round(_payload_float(runs, 'total_duration_seconds'))))} суммарно, "
            f"максимум {format_duration(int(round(_payload_float(runs, 'max_duration_seconds'))))}"
        ),
        (
            "Данных собрано: "
            f"строк all_accounts={_payload_int(runs, 'total_ranked_accounts')}, "
            f"raw_candidates={_payload_int(runs, 'total_raw_candidates')}"
        ),
    ]
    if top_cities:
        lines.append("Топ городов: " + ", ".join(f"{item['name']} ({item['count']})" for item in top_cities[:3]))
    if top_services:
        lines.append("Топ услуг: " + ", ".join(f"{item['name']} ({item['count']})" for item in top_services[:3]))
    if report_origins:
        lines.append("Источники запусков: " + ", ".join(f"{item['name']} ({item['count']})" for item in report_origins[:4]))
    if platform_failures:
        lines.append("Сбои платформ: " + ", ".join(f"{item['platform']} ({item['count']})" for item in platform_failures))
    if isinstance(latest_run, dict) and latest_run.get("available"):
        lines.append(
            "Последняя выгрузка суток: "
            f"{latest_run.get('generated_at', 'нет данных')} | "
            f"строк={latest_run.get('ranked_accounts', 0)}"
        )
    return "\n".join(lines)


def format_duration(total_seconds: int) -> str:
    seconds = max(0, total_seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}ч")
    if minutes or hours:
        parts.append(f"{minutes}м")
    parts.append(f"{seconds}с")
    return " ".join(parts)


def _payload_int(payload: object, key: str) -> int:
    if not isinstance(payload, dict):
        return 0
    try:
        return int(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _payload_float(payload: object, key: str) -> float:
    if not isinstance(payload, dict):
        return 0.0
    try:
        return float(payload.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _latest_manifest_from_run_history(output_dir: Path) -> tuple[Path | None, dict[str, object]] | None:
    history_path = output_dir / "run_history.jsonl"
    if not history_path.exists():
        return None
    try:
        lines = history_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for raw_line in reversed(lines):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        workbook_raw = str(payload.get("workbook", "")).strip()
        if not workbook_raw:
            continue
        workbook = Path(workbook_raw)
        manifest_path = workbook.with_suffix(".json")
        if manifest_path.exists():
            manifest_payload = _load_manifest_payload(manifest_path)
            if manifest_payload is not None:
                return manifest_path, manifest_payload
        synthetic_payload = _synthetic_manifest_payload(payload)
        if synthetic_payload is not None:
            return manifest_path if manifest_path.exists() else None, synthetic_payload
    return None


def _load_manifest_payload(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if "workbook" not in payload or "request" not in payload:
        return None
    return payload


def _load_run_history_entries(output_dir: Path) -> list[dict[str, object]]:
    history_path = output_dir / "run_history.jsonl"
    if not history_path.exists():
        return []
    try:
        lines = history_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    results: list[dict[str, object]] = []
    for raw_line in lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            results.append(payload)
    return results


def _daily_run_history_entries(output_dir: Path, *, target_date: date, local_time: datetime) -> list[dict[str, object]]:
    local_tz = local_time.tzinfo
    entries: list[tuple[datetime, dict[str, object]]] = []
    for item in _load_run_history_entries(output_dir):
        generated_at = _parse_iso_datetime(item.get("generated_at"))
        if generated_at is None:
            continue
        local_generated = generated_at.astimezone(local_tz) if local_tz is not None else generated_at
        if local_generated.date() == target_date:
            entries.append((generated_at, item))
    entries.sort(key=lambda item: item[0])
    return [item for _, item in entries]


def _entry_count(entry: dict[str, object], key: str) -> int:
    counts = entry.get("counts", {})
    if not isinstance(counts, dict):
        return 0
    try:
        return int(counts.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _entry_meta_number(entry: dict[str, object], key: str) -> float | None:
    meta = entry.get("meta", {})
    if not isinstance(meta, dict):
        return None
    value = meta.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _entry_duration_seconds(entry: dict[str, object]) -> float | None:
    return _entry_meta_number(entry, "duration_seconds")


def _entry_collection_duration_seconds(entry: dict[str, object]) -> float | None:
    return _entry_meta_number(entry, "collection_duration_seconds")


def _entry_export_duration_seconds(entry: dict[str, object]) -> float | None:
    return _entry_meta_number(entry, "export_duration_seconds")


def _entry_platform_failures(entry: dict[str, object]) -> list[str]:
    meta = entry.get("meta", {})
    if not isinstance(meta, dict):
        return []
    failures = meta.get("platform_failures", [])
    if not isinstance(failures, list):
        return []
    results: list[str] = []
    for item in failures:
        if not isinstance(item, dict):
            continue
        token = str(item.get("platform", "")).strip()
        if token:
            results.append(token)
    return results


def _daily_latest_run_payload(entry: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(entry, dict):
        return {"available": False}
    request = entry.get("request", {})
    return {
        "available": True,
        "generated_at": str(entry.get("generated_at", "")),
        "cities": list(request.get("cities", [])) if isinstance(request, dict) else [],
        "services": list(request.get("services", [])) if isinstance(request, dict) else [],
        "ranked_accounts": _entry_count(entry, "ranked_accounts"),
        "raw_candidates": _entry_count(entry, "raw_candidates"),
        "duration_seconds": _entry_duration_seconds(entry) or 0.0,
        "collection_duration_seconds": _entry_collection_duration_seconds(entry) or 0.0,
        "export_duration_seconds": _entry_export_duration_seconds(entry) or 0.0,
    }


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    try:
        parsed = datetime.fromisoformat(token)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _daily_time_label(payload: dict[str, object], key: str) -> str:
    parsed = _parse_iso_datetime(payload.get(key))
    if parsed is None:
        return "нет данных"
    return parsed.astimezone().strftime("%H:%M")


def _resolve_timezone(timezone_name: str | None):
    if not timezone_name:
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo


def _snapshot_from_manifest(path: Path | None, payload: dict[str, object]) -> LatestReportSnapshot | None:
    workbook_raw = str(payload.get("workbook", ""))
    if not workbook_raw:
        return None
    workbook = Path(workbook_raw)
    if not workbook.exists():
        return None
    pdf = None
    pdf_block = payload.get("pdf", {})
    if isinstance(pdf_block, dict):
        pdf_path_raw = str(pdf_block.get("path", ""))
        if pdf_path_raw:
            candidate_pdf = Path(pdf_path_raw)
            if candidate_pdf.exists():
                pdf = candidate_pdf
    return LatestReportSnapshot(workbook=workbook, manifest=path, manifest_payload=payload, pdf=pdf)


def _synthetic_manifest_payload(history_entry: dict[str, object]) -> dict[str, object] | None:
    workbook = str(history_entry.get("workbook", ""))
    request = history_entry.get("request", {})
    counts = history_entry.get("counts", {})
    if not workbook or not isinstance(request, dict) or not isinstance(counts, dict):
        return None
    return {
        "generated_at": history_entry.get("generated_at", ""),
        "workbook": workbook,
        "pdf": history_entry.get("pdf", {}),
        "request": request,
        "counts": counts,
        "meta": history_entry.get("meta", {}),
    }


def _health_latest_report_payload(snapshot: LatestReportSnapshot | None) -> dict[str, object]:
    if snapshot is None:
        return {"available": False}
    payload = snapshot.manifest_payload
    request = payload.get("request", {})
    counts = payload.get("counts", {})
    pdf_block = payload.get("pdf", {})
    return {
        "available": True,
        "generated_at": str(payload.get("generated_at", "")),
        "workbook": str(snapshot.workbook),
        "manifest": str(snapshot.manifest) if snapshot.manifest is not None else "",
        "pdf": str(snapshot.pdf) if snapshot.pdf is not None else "",
        "pdf_status": str(pdf_block.get("status", "")) if isinstance(pdf_block, dict) else "",
        "cities": list(request.get("cities", [])) if isinstance(request, dict) else [],
        "services": list(request.get("services", [])) if isinstance(request, dict) else [],
        "ranked_accounts": int(counts.get("ranked_accounts", 0)) if isinstance(counts, dict) else 0,
    }


def _runtime_flag(runtime: object, key: str) -> bool:
    if not isinstance(runtime, dict):
        return False
    return bool(runtime.get(key))
