from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
import signal
import threading
from typing import Any

from .config import RuntimeConfig
from .export.reports import write_report_artifacts_with_timing
from .markers import (
    configure_marker_alias_overrides,
    normalize_slug,
    normalize_text,
    service_discovery_hints,
    service_search_terms,
    service_profile_terms,
    twogis_category_hints,
)
from .models import RankedAccount, SearchRequest, ServiceQuery
from .pipeline import run_pipeline
from .request_options import service_selection_sections
from .telegram_profile_seeds import TelegramProfileSeedStore
from .vk_profile_seeds import VkProfileSeedStore


def build_smoke_matrix_payload(
    *,
    cities: list[str],
    services: list[str],
    platforms: list[str],
    period_days: int,
    top_n: int,
    report_mode: str,
    collector: Any,
    config: RuntimeConfig,
    write_reports: bool = False,
    reports_dir: Path | None = None,
    checkpoint_path: Path | None = None,
    case_timeout_seconds: int = 0,
    runtime_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    requested_keys = {(city, service) for city in cities for service in services}
    checkpoint_payload = _load_checkpoint_payload(checkpoint_path)
    if (
        checkpoint_payload is not None
        and write_reports
        and reports_dir is None
        and isinstance(checkpoint_payload.get("request"), dict)
    ):
        checkpoint_reports_dir = str(checkpoint_payload["request"].get("reports_dir", ""))
        if checkpoint_reports_dir:
            reports_dir = Path(checkpoint_reports_dir)
    cases: list[dict[str, Any]] = [
        case
        for case in _load_checkpoint_cases(
            checkpoint_payload,
            platforms=platforms,
            period_days=period_days,
            top_n=top_n,
            report_mode=report_mode,
            write_reports=write_reports,
            case_timeout_seconds=case_timeout_seconds,
        )
        if (str(case.get("city", "")), str(case.get("service", ""))) in requested_keys
    ]
    completed_keys = {
        (str(case.get("city", "")), str(case.get("service", "")))
        for case in cases
        if isinstance(case, dict)
    }
    total_cases = len(cities) * len(services)
    if write_reports:
        if reports_dir is None:
            reports_dir = config.output_dir / f"smoke_matrix_reports_{started_at.strftime('%Y%m%d_%H%M%S')}"
        reports_dir.mkdir(parents=True, exist_ok=True)

    for city in cities:
        for service in services:
            if (city, service) in completed_keys:
                continue
            case = _run_smoke_case(
                city=city,
                service=service,
                platforms=platforms,
                period_days=period_days,
                top_n=top_n,
                report_mode=report_mode,
                collector=collector,
                config=config,
                write_reports=write_reports,
                reports_dir=reports_dir,
                case_timeout_seconds=case_timeout_seconds,
            )
            cases.append(case)
            completed_keys.add((city, service))
            if checkpoint_path is not None:
                write_smoke_matrix_payload(
                    _smoke_matrix_payload(
                        started_at=started_at,
                        cases=cases,
                        cities=cities,
                        services=services,
                        platforms=platforms,
                        period_days=period_days,
                        top_n=top_n,
                        report_mode=report_mode,
                        write_reports=write_reports,
                        reports_dir=reports_dir,
                        total_cases=total_cases,
                        checkpoint_path=checkpoint_path,
                        is_complete=len(cases) >= total_cases,
                        case_timeout_seconds=case_timeout_seconds,
                        runtime_diagnostics=runtime_diagnostics,
                    ),
                    checkpoint_path,
                )

    return _smoke_matrix_payload(
        started_at=started_at,
        cases=cases,
        cities=cities,
        services=services,
        platforms=platforms,
        period_days=period_days,
        top_n=top_n,
        report_mode=report_mode,
        write_reports=write_reports,
        reports_dir=reports_dir,
        total_cases=total_cases,
        checkpoint_path=checkpoint_path,
        is_complete=len(cases) >= total_cases,
        case_timeout_seconds=case_timeout_seconds,
        runtime_diagnostics=runtime_diagnostics,
    )


def _smoke_matrix_payload(
    *,
    started_at: datetime,
    cases: list[dict[str, Any]],
    cities: list[str],
    services: list[str],
    platforms: list[str],
    period_days: int,
    top_n: int,
    report_mode: str,
    write_reports: bool,
    reports_dir: Path | None,
    total_cases: int,
    checkpoint_path: Path | None,
    is_complete: bool,
    case_timeout_seconds: int,
    runtime_diagnostics: dict[str, Any] | None,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC)
    return {
        "generated_at": generated_at.isoformat(),
        "started_at": started_at.isoformat(),
        "duration_seconds": round((generated_at - started_at).total_seconds(), 3),
        "request": {
            "cities": cities,
            "services": services,
            "period_days": period_days,
            "platforms": platforms,
            "top_n": top_n,
            "report_mode": report_mode,
            "write_reports": write_reports,
            "reports_dir": str(reports_dir) if reports_dir is not None else "",
            "case_timeout_seconds": case_timeout_seconds,
            "runtime_diagnostics": runtime_diagnostics or {},
        },
        "checkpoint": {
            "enabled": checkpoint_path is not None,
            "path": str(checkpoint_path) if checkpoint_path is not None else "",
            "completed_cases": len(cases),
            "total_cases": total_cases,
            "is_complete": is_complete,
        },
        "summary": _summary(cases),
        "cases": cases,
    }


def write_smoke_matrix_payload(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def load_smoke_matrix_payload(path: Path) -> dict[str, Any]:
    raw_data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        raise ValueError("Smoke matrix payload must be a JSON object.")
    return raw_data


def _load_checkpoint_payload(checkpoint_path: Path | None) -> dict[str, Any] | None:
    if checkpoint_path is None or not checkpoint_path.exists():
        return None
    try:
        return load_smoke_matrix_payload(checkpoint_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _load_checkpoint_cases(
    payload: dict[str, Any] | None,
    *,
    platforms: list[str],
    period_days: int,
    top_n: int,
    report_mode: str,
    write_reports: bool,
    case_timeout_seconds: int,
) -> list[dict[str, Any]]:
    if payload is None or not _checkpoint_request_compatible(
        payload,
        platforms=platforms,
        period_days=period_days,
        top_n=top_n,
        report_mode=report_mode,
        write_reports=write_reports,
        case_timeout_seconds=case_timeout_seconds,
    ):
        return []
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        return []
    return [case for case in cases if isinstance(case, dict)]


def _checkpoint_request_compatible(
    payload: dict[str, Any],
    *,
    platforms: list[str],
    period_days: int,
    top_n: int,
    report_mode: str,
    write_reports: bool,
    case_timeout_seconds: int,
) -> bool:
    request = payload.get("request", {})
    if not isinstance(request, dict):
        return False
    saved_platforms = request.get("platforms", [])
    if not isinstance(saved_platforms, list):
        return False
    return (
        sorted(str(platform) for platform in saved_platforms) == sorted(platforms)
        and request.get("period_days") == period_days
        and request.get("top_n") == top_n
        and request.get("report_mode") == report_mode
        and request.get("write_reports") is write_reports
    )


def build_smoke_matrix_action_plan_payload(
    payload: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> dict[str, Any]:
    actions = [_action_for_case(case) for case in payload.get("cases", []) if isinstance(case, dict)]
    actions = [action for action in actions if action is not None]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(source_path) if source_path is not None else "",
        "request": payload.get("request", {}),
        "summary": _action_summary(actions),
        "actions": actions,
    }


def build_service_keyword_audit_payload(
    *,
    services: list[str],
    cities: list[str],
    config: RuntimeConfig,
    vk_seed_store: VkProfileSeedStore | None = None,
    telegram_seed_store: TelegramProfileSeedStore | None = None,
) -> dict[str, Any]:
    configure_marker_alias_overrides(config.rule_config)
    sections_by_service = {
        service: title
        for title, section_services in service_selection_sections(config.popular_services)
        for service in section_services
    }
    known_service_terms = _known_service_terms(config.popular_services)
    rows: list[dict[str, Any]] = []
    for service in services:
        vk_seed_counts_by_city: dict[str, int] = {}
        vk_seed_missing_cities: list[str] = []
        telegram_seed_counts_by_city: dict[str, int] = {}
        telegram_seed_missing_cities: list[str] = []
        for city in cities:
            vk_urls = vk_seed_store.urls_for(city, service) if vk_seed_store is not None else []
            vk_seed_counts_by_city[city] = len(vk_urls)
            if not vk_urls:
                vk_seed_missing_cities.append(city)
            telegram_urls = telegram_seed_store.urls_for(city, service) if telegram_seed_store is not None else []
            telegram_seed_counts_by_city[city] = len(telegram_urls)
            if not telegram_urls:
                telegram_seed_missing_cities.append(city)
        rows.append(
            {
                "service": service,
                "section": sections_by_service.get(service, "Другие направления"),
                "profile_terms": service_profile_terms(service),
                "search_terms": service_search_terms(service),
                "discovery_hints": service_discovery_hints(service),
                "twogis_category_hints": twogis_category_hints(service),
                "vk_seed_urls_total": sum(vk_seed_counts_by_city.values()),
                "vk_seed_counts_by_city": vk_seed_counts_by_city,
                "vk_seed_missing_cities": vk_seed_missing_cities,
                "telegram_seed_urls_total": sum(telegram_seed_counts_by_city.values()),
                "telegram_seed_counts_by_city": telegram_seed_counts_by_city,
                "telegram_seed_missing_cities": telegram_seed_missing_cities,
            }
        )
    vk_unknown_seed_entries = _unknown_seed_entries("vk", vk_seed_store, known_service_terms)
    telegram_unknown_seed_entries = _unknown_seed_entries("telegram", telegram_seed_store, known_service_terms)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "services_total": len(rows),
            "cities_total": len(cities),
            "services_with_vk_seeds": sum(1 for row in rows if row["vk_seed_urls_total"] > 0),
            "services_without_vk_seeds": sum(1 for row in rows if row["vk_seed_urls_total"] == 0),
            "vk_seed_urls_total": sum(row["vk_seed_urls_total"] for row in rows),
            "services_with_alias_overrides": sum(
                1
                for row in rows
                if row["service"] in config.rule_config.service_alias_overrides
            ),
            "services_with_discovery_overrides": sum(
                1
                for row in rows
                if row["service"] in config.rule_config.service_discovery_hint_overrides
            ),
            "services_with_telegram_seeds": sum(1 for row in rows if row["telegram_seed_urls_total"] > 0),
            "services_without_telegram_seeds": sum(1 for row in rows if row["telegram_seed_urls_total"] == 0),
            "telegram_seed_urls_total": sum(row["telegram_seed_urls_total"] for row in rows),
            "unknown_seed_entries_total": len(vk_unknown_seed_entries) + len(telegram_unknown_seed_entries),
            "unknown_vk_seed_entries_total": len(vk_unknown_seed_entries),
            "unknown_telegram_seed_entries_total": len(telegram_unknown_seed_entries),
        },
        "services": rows,
        "unknown_seed_entries": [
            *vk_unknown_seed_entries,
            *telegram_unknown_seed_entries,
        ],
    }


class SmokeCaseTimeoutError(TimeoutError):
    pass


def _run_pipeline_with_timeout(
    request: SearchRequest,
    *,
    collector: Any,
    config: RuntimeConfig,
    timeout_seconds: int,
):
    if timeout_seconds <= 0 or threading.current_thread() is not threading.main_thread():
        return run_pipeline(request, collector=collector, config=config)

    def _handle_timeout(signum, frame):  # noqa: ARG001
        raise SmokeCaseTimeoutError(
            f"case timed out after {timeout_seconds} seconds: "
            f"{request.cities[0]} / {request.services[0].name}"
        )

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return run_pipeline(request, collector=collector, config=config)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def _run_smoke_case(
    *,
    city: str,
    service: str,
    platforms: list[str],
    period_days: int,
    top_n: int,
    report_mode: str,
    collector: Any,
    config: RuntimeConfig,
    write_reports: bool,
    reports_dir: Path | None,
    case_timeout_seconds: int = 0,
) -> dict[str, Any]:
    request = SearchRequest(
        cities=[city],
        services=[ServiceQuery(name=service)],
        period_days=period_days,
        platforms=platforms,
        top_n=top_n,
        report_mode=report_mode,
    )
    base: dict[str, Any] = {
        "city": city,
        "service": service,
        "platforms": platforms,
        "status": "failed",
        "counts": {
            "ranked_accounts": 0,
            "raw_candidates": 0,
            "filter_debug": 0,
            "search_log": 0,
        },
        "platform_failures": [],
        "silent_platforms": [],
        "top_urls": [],
        "raw_urls": [],
        "filter_reasons": [],
        "search_queries": [],
        "search_sources": {},
        "discovery_modes": {},
        "vk_profile_search": {
            "attempted": False,
            "groups_search_queries": 0,
            "users_search_queries": 0,
            "fallback_errors": [],
        },
        "artifacts": {},
        "error": "",
    }
    case_started_at = datetime.now(UTC)
    try:
        bundle = _run_pipeline_with_timeout(
            request,
            collector=collector,
            config=config,
            timeout_seconds=case_timeout_seconds,
        ).bundle
        collected_at = datetime.now(UTC)
    except SmokeCaseTimeoutError as exc:
        base["error"] = str(exc)
        return base
    except Exception as exc:  # noqa: BLE001
        base["error"] = str(exc)
        return base

    platform_failures = _platform_failures(bundle.report_meta.get("platform_failures", []))
    observed_platforms = {
        *[candidate.platform for candidate in bundle.raw_candidates],
        *[entry.platform for entry in bundle.search_log],
        *[str(item.get("platform", "")) for item in platform_failures],
    }
    silent_platforms = [platform for platform in platforms if platform not in observed_platforms]
    base.update(
        {
            "status": _case_status(
                ranked_accounts=len(bundle.ranked_accounts),
                platform_failures=platform_failures,
                silent_platforms=silent_platforms,
            ),
            "counts": {
                "ranked_accounts": len(bundle.ranked_accounts),
                "raw_candidates": len(bundle.raw_candidates),
                "filter_debug": len(bundle.filter_debug),
                "search_log": len(bundle.search_log),
            },
            "platform_failures": platform_failures,
            "silent_platforms": silent_platforms,
            "top_urls": _top_urls(bundle.ranked_accounts),
            "raw_urls": _raw_urls(bundle.raw_candidates),
            "filter_reasons": _filter_reason_summary(bundle.filter_debug),
            "search_queries": _search_queries(bundle.search_log),
            "search_sources": _search_source_summary(bundle.search_log),
            "discovery_modes": _discovery_mode_summary(bundle.search_log),
            "vk_profile_search": _vk_profile_search_summary(bundle.search_log),
        }
    )
    if write_reports and reports_dir is not None:
        workbook_path = reports_dir / f"{normalize_slug(city)}__{normalize_slug(service)}.xlsx"
        try:
            artifacts = write_report_artifacts_with_timing(
                bundle,
                workbook_path,
                started_at=case_started_at,
                collected_at=collected_at,
                report_origin="smoke_matrix",
            )
            base["artifacts"] = {
                "workbook": str(artifacts.workbook),
                "pdf": str(artifacts.pdf) if artifacts.pdf is not None else "",
                "manifest": str(artifacts.manifest) if artifacts.manifest is not None else "",
                "pdf_error": artifacts.pdf_error or "",
            }
        except Exception as exc:  # noqa: BLE001
            base["status"] = "failed"
            base["error"] = f"report export failed: {exc}"
    return base


def _case_status(
    *,
    ranked_accounts: int,
    platform_failures: list[dict[str, str]],
    silent_platforms: list[str],
) -> str:
    if ranked_accounts > 0:
        if platform_failures or silent_platforms:
            return "ok_with_warnings"
        return "ok"
    if platform_failures or silent_platforms:
        return "empty_with_warnings"
    return "empty"


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_city = _group_summary(cases, "city")
    by_service = _group_summary(cases, "service")
    statuses = defaultdict(int)
    for case in cases:
        statuses[case["status"]] += 1
    empty_cases = [
        _case_ref(case)
        for case in cases
        if case["status"] in {"empty", "empty_with_warnings", "failed"}
    ]
    warning_cases = [
        _case_ref(case)
        for case in cases
        if case["platform_failures"] or case["silent_platforms"]
    ]
    return {
        "cases_total": len(cases),
        "cases_with_result": sum(1 for case in cases if case["counts"]["ranked_accounts"] > 0),
        "cases_without_result": sum(1 for case in cases if case["counts"]["ranked_accounts"] == 0),
        "statuses": dict(sorted(statuses.items())),
        "ranked_accounts_total": sum(case["counts"]["ranked_accounts"] for case in cases),
        "raw_candidates_total": sum(case["counts"]["raw_candidates"] for case in cases),
        "platform_failures_total": sum(len(case["platform_failures"]) for case in cases),
        "silent_platforms_total": sum(len(case["silent_platforms"]) for case in cases),
        "empty_cases": empty_cases,
        "warning_cases": warning_cases,
        "by_city": by_city,
        "by_service": by_service,
    }


def _group_summary(cases: list[dict[str, Any]], field: str) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for case in cases:
        key = str(case[field])
        item = grouped.setdefault(
            key,
            {
                "cases_total": 0,
                "cases_with_result": 0,
                "cases_without_result": 0,
                "ranked_accounts_total": 0,
                "raw_candidates_total": 0,
                "warnings_total": 0,
            },
        )
        item["cases_total"] += 1
        if case["counts"]["ranked_accounts"] > 0:
            item["cases_with_result"] += 1
        else:
            item["cases_without_result"] += 1
        item["ranked_accounts_total"] += case["counts"]["ranked_accounts"]
        item["raw_candidates_total"] += case["counts"]["raw_candidates"]
        if case["platform_failures"] or case["silent_platforms"]:
            item["warnings_total"] += 1
    return dict(sorted(grouped.items()))


def _case_ref(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "city": case["city"],
        "service": case["service"],
        "status": case["status"],
        "ranked_accounts": case["counts"]["ranked_accounts"],
        "raw_candidates": case["counts"]["raw_candidates"],
        "platform_failures": case["platform_failures"],
        "silent_platforms": case["silent_platforms"],
        "error": case["error"],
    }


def _top_urls(ranked_accounts: list[RankedAccount], *, limit: int = 5) -> list[str]:
    urls: list[str] = []
    for item in ranked_accounts:
        url = item.candidate.account_url
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _raw_urls(raw_candidates: list[Any], *, limit: int = 5) -> list[str]:
    urls: list[str] = []
    for candidate in raw_candidates:
        url = getattr(candidate, "account_url", "")
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _filter_reason_summary(filter_debug: list[Any], *, limit: int = 5) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for item in filter_debug:
        stage = str(getattr(item, "decision_stage", ""))
        reason = str(getattr(item, "reason", ""))
        key = (stage, reason)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    return [
        {
            "decision_stage": stage,
            "reason": reason,
            "count": count,
        }
        for (stage, reason), count in ordered[:limit]
    ]


def _search_queries(search_log: list[Any], *, limit: int = 10) -> list[str]:
    queries: list[str] = []
    for entry in search_log:
        query = getattr(entry, "query", "")
        if query and query not in queries:
            queries.append(query)
        if len(queries) >= limit:
            break
    return queries




def _search_source_summary(search_log: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in search_log:
        source = str(getattr(entry, "source", "")).strip() or "unknown"
        counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items()))


def _discovery_mode_summary(search_log: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in search_log:
        mode = str(getattr(entry, "discovery_mode", "")).strip() or "unknown"
        counts[mode] = counts.get(mode, 0) + 1
    return dict(sorted(counts.items()))


def _vk_profile_search_summary(search_log: list[Any]) -> dict[str, Any]:
    fallback_errors: list[str] = []
    groups_search_queries = 0
    users_search_queries = 0
    for entry in search_log:
        source = str(getattr(entry, "source", "")).strip()
        if source == "vk.groups.search":
            groups_search_queries += 1
        elif source == "vk.users.search":
            users_search_queries += 1
        elif source == "vk.profile_search.error":
            detail = str(getattr(entry, "details", "")).strip() or str(getattr(entry, "query", "")).strip()
            if detail and detail not in fallback_errors:
                fallback_errors.append(detail)
    return {
        "attempted": groups_search_queries > 0 or users_search_queries > 0 or bool(fallback_errors),
        "groups_search_queries": groups_search_queries,
        "users_search_queries": users_search_queries,
        "fallback_errors": fallback_errors[:3],
    }


def _platform_failures(raw_value: object) -> list[dict[str, str]]:
    if not isinstance(raw_value, list):
        return []
    result: list[dict[str, str]] = []
    for item in raw_value:
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform", "")).strip()
        error = str(item.get("error", "")).strip()
        if platform or error:
            result.append({"platform": platform, "error": error})
    return result


def _known_service_terms(services: list[str]) -> set[str]:
    terms: set[str] = set()
    for service in services:
        for term in service_search_terms(service):
            normalized_term = normalize_text(term)
            if normalized_term:
                terms.add(normalized_term)
    return terms


def _unknown_seed_entries(
    platform: str,
    seed_store: VkProfileSeedStore | TelegramProfileSeedStore | None,
    known_service_terms: set[str],
) -> list[dict[str, Any]]:
    if seed_store is None:
        return []

    result: list[dict[str, Any]] = []
    for entry in seed_store.entries:
        seed_terms = {
            normalize_text(term)
            for term in [entry.service, *entry.service_aliases]
            if normalize_text(term)
        }
        if seed_terms & known_service_terms:
            continue
        result.append(
            {
                "platform": platform,
                "city": entry.city,
                "service": entry.service,
                "service_aliases": list(entry.service_aliases),
                "urls_total": len(entry.urls),
                "sample_urls": list(entry.urls[:5]),
                "reason": "Seed service is not covered by the configured popular services or service aliases.",
            }
        )
    return result


def _action_for_case(case: dict[str, Any]) -> dict[str, Any] | None:
    city = str(case.get("city", "")).strip()
    service = str(case.get("service", "")).strip()
    counts = case.get("counts", {}) if isinstance(case.get("counts"), dict) else {}
    ranked = _int_value(counts.get("ranked_accounts"))
    raw = _int_value(counts.get("raw_candidates"))
    platform_failures = case.get("platform_failures", [])
    silent_platforms = case.get("silent_platforms", [])
    filter_reasons = case.get("filter_reasons", [])
    base = {
        "city": city,
        "service": service,
        "status": case.get("status", ""),
        "ranked_accounts": ranked,
        "raw_candidates": raw,
        "top_urls": case.get("top_urls", []),
        "raw_urls": case.get("raw_urls", []),
        "filter_reasons": filter_reasons,
        "search_queries": case.get("search_queries", []),
        "search_sources": case.get("search_sources", {}),
        "discovery_modes": case.get("discovery_modes", {}),
        "vk_profile_search": case.get("vk_profile_search", {}),
    }

    if case.get("error"):
        return {
            **base,
            "action_type": "manual-review",
            "priority": "high",
            "reason": f"Pipeline case failed: {case.get('error')}",
            "suggested_next_step": "Проверить traceback/collector и повторить кейс после исправления runtime-ошибки.",
        }
    if platform_failures:
        return {
            **base,
            "platform_failures": platform_failures,
            "action_type": "api-failure",
            "priority": "high",
            "reason": "Одна или несколько платформ завершились ошибкой.",
            "suggested_next_step": "Починить ключ/session/API-доступ и повторить smoke; alias/seeds не исправят runtime failure.",
        }
    if silent_platforms:
        return {
            **base,
            "silent_platforms": silent_platforms,
            "action_type": "platform-not-configured",
            "priority": "medium",
            "reason": "Платформа была запрошена, но не дала ни search_log, ни candidates, ни failure.",
            "suggested_next_step": "Проверить env/готовность платформы или убрать её из явного smoke-запроса.",
        }
    if ranked > 0:
        return None
    if raw == 0:
        return {
            **base,
            "action_type": "seed-or-discovery-needed",
            "priority": "high",
            "reason": "Нет raw-кандидатов: discovery не поднял профили.",
            "suggested_next_step": "Добавить known-good URL в curated VK/Telegram seeds и/или расширить discovery hints.",
        }

    if _has_filter_reason(filter_reasons, "city_filter"):
        return {
            **base,
            "action_type": "city-alias-or-seed-review",
            "priority": "high",
            "reason": "Raw-кандидаты есть, но часть отсечена city_filter.",
            "suggested_next_step": "Проверить raw URLs: для реальных городских профилей добавить city alias; нерелевантные оставить отсечёнными.",
        }
    if _has_filter_reason(filter_reasons, "service_filter"):
        return {
            **base,
            "action_type": "service-alias-needed",
            "priority": "high",
            "reason": "Raw-кандидаты есть, но профильный фильтр не увидел услугу.",
            "suggested_next_step": "Для real business добавить service_alias_overrides/service_discovery_hint_overrides во внешний rule config.",
        }
    return {
        **base,
        "action_type": "manual-review",
        "priority": "medium",
        "reason": "Raw-кандидаты есть, но причина пустой ranked-выдачи не классифицирована автоматически.",
        "suggested_next_step": "Открыть raw URLs и filter_reasons, затем решить: seed, service alias, city alias или оставить фильтр.",
    }


def _action_summary(actions: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for action in actions:
        action_type = str(action.get("action_type", ""))
        priority = str(action.get("priority", ""))
        by_type[action_type] = by_type.get(action_type, 0) + 1
        by_priority[priority] = by_priority.get(priority, 0) + 1
    return {
        "actions_total": len(actions),
        "by_type": dict(sorted(by_type.items())),
        "by_priority": dict(sorted(by_priority.items())),
    }


def _has_filter_reason(filter_reasons: object, stage: str) -> bool:
    if not isinstance(filter_reasons, list):
        return False
    for item in filter_reasons:
        if not isinstance(item, dict):
            continue
        if str(item.get("decision_stage", "")) == stage:
            return True
    return False


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
