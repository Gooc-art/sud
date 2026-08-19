from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .collectors.base import Collector
from .config import RuntimeConfig
from .markers import CITY_ALIAS_MAP, normalize_text, service_discovery_hints, service_search_terms
from .models import ReportBundle, SearchRequest, ServiceQuery
from .pipeline import run_pipeline
from .rule_config import RuleConfig
from .vk_profile_seeds import VkProfileSeedEntry, VkProfileSeedStore


@dataclass(slots=True)
class ValidationCase:
    name: str
    cities: list[str]
    services: list[str]
    period_days: int
    platforms: list[str]
    top_n: int = 20
    report_mode: str = "all"
    expected_relevant_urls: list[str] = field(default_factory=list)
    expected_irrelevant_urls: list[str] = field(default_factory=list)
    candidate_urls: list[str] = field(default_factory=list)
    raw_candidate_urls: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(slots=True)
class ValidationResult:
    case_name: str
    actual_urls: list[str]
    true_positives: list[str]
    false_positives: list[str]
    false_negatives: list[str]
    unlabeled_hits: list[str]
    precision: float
    recall: float


@dataclass(slots=True)
class ValidationSummary:
    cases_total: int
    true_positives: int
    false_positives: int
    false_negatives: int
    unlabeled_hits: int
    precision: float
    recall: float
    strict_precision: float


@dataclass(slots=True)
class VkSeedRecommendation:
    city: str
    service: str
    urls: list[str] = field(default_factory=list)
    source_cases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VkSeedRecommendationSkip:
    case_name: str
    reason: str


@dataclass(slots=True)
class ValidationCaseDiagnostic:
    case_name: str
    cities: list[str]
    services: list[str]
    platforms: list[str]
    precision: float
    recall: float
    true_positives: list[str]
    false_positives: list[str]
    false_negatives: list[str]
    unlabeled_hits: list[str]
    actual_urls: list[str]
    candidate_urls: list[str]
    raw_candidate_urls: list[str]
    seed_candidate_urls: list[str]
    seed_candidate_status: str
    notes: str = ""


@dataclass(slots=True)
class ValidationDiagnosticsSummary:
    cases_total: int
    cases_with_false_negatives: int
    cases_with_false_positives: int
    cases_with_unlabeled_hits: int
    ready_seed_cases: int
    seed_candidate_urls_total: int


@dataclass(slots=True)
class ValidationActionItem:
    case_name: str
    action_type: str
    priority: int
    cities: list[str]
    services: list[str]
    platforms: list[str]
    rationale: str
    urls: list[str] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    unlabeled_hits: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationActionSummary:
    report_path: str
    actions_total: int
    seed_actions: int
    aliases_actions: int
    city_alias_actions: int
    manual_review_actions: int


@dataclass(slots=True)
class ValidationDraftSuggestion:
    suggestion_type: str
    key: str
    cases: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass(slots=True)
class ValidationActionApplySummary:
    action_plan_path: str
    seed_entries_applied: int
    seed_urls_applied: int
    alias_drafts_total: int
    city_alias_drafts_total: int
    manual_review_drafts_total: int


@dataclass(slots=True)
class ServiceAliasPatchDraft:
    service: str
    target_synonyms: str
    target_hints: str
    existing_aliases: list[str] = field(default_factory=list)
    existing_discovery_hints: list[str] = field(default_factory=list)
    suggested_aliases: list[str] = field(default_factory=list)
    suggested_discovery_hints: list[str] = field(default_factory=list)
    cases: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CityAliasPatchDraft:
    city: str
    target: str
    existing_aliases: list[str] = field(default_factory=list)
    suggested_aliases: list[str] = field(default_factory=list)
    cases: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AliasPatchDraftSummary:
    action_apply_path: str
    service_alias_patches_total: int
    city_alias_patches_total: int
    manual_review_cases_total: int


@dataclass(slots=True)
class AliasPatchApplySummary:
    draft_path: str
    service_alias_services_total: int
    service_alias_values_total: int
    service_hint_services_total: int
    service_hint_values_total: int
    city_alias_cities_total: int
    city_alias_values_total: int


@dataclass(slots=True)
class ValidationCaseComparison:
    case_name: str
    cities: list[str]
    services: list[str]
    platforms: list[str]
    baseline_label: str
    candidate_label: str
    baseline_rule_config_path: str
    candidate_rule_config_path: str
    baseline_result: ValidationResult
    candidate_result: ValidationResult
    recall_delta: float
    precision_delta: float
    urls_added: list[str] = field(default_factory=list)
    urls_removed: list[str] = field(default_factory=list)
    improved: bool = False


@dataclass(slots=True)
class ValidationComparisonSummary:
    cases_total: int
    improved_cases: int
    unchanged_cases: int
    regressed_cases: int
    recall_delta_total: float
    precision_delta_total: float
    urls_added_total: int
    urls_removed_total: int


@dataclass(slots=True)
class ValidationComparisonActionItem:
    case_name: str
    action_type: str
    priority: int
    rationale: str
    cities: list[str]
    services: list[str]
    platforms: list[str]
    baseline_recall: float
    candidate_recall: float
    baseline_precision: float
    candidate_precision: float
    recall_delta: float
    precision_delta: float
    urls_added: list[str] = field(default_factory=list)
    urls_removed: list[str] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    unlabeled_hits: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationComparisonActionSummary:
    report_path: str
    actions_total: int
    regressions_total: int
    followup_gap_total: int
    accepted_improvements_total: int


@dataclass(slots=True)
class ValidationComparisonFollowupSummary:
    action_plan_path: str
    seed_entries_total: int
    seed_urls_total: int
    alias_drafts_total: int
    city_alias_drafts_total: int
    manual_review_drafts_total: int


@dataclass(slots=True)
class ValidationComparisonFollowupApplySummary:
    followup_path: str
    seed_entries_applied: int
    seed_urls_applied: int
    alias_drafts_total: int
    city_alias_drafts_total: int
    manual_review_drafts_total: int


@dataclass(slots=True)
class ValidationBootstrapSummary:
    output_path: str
    cases_total: int
    cities_total: int
    services_total: int
    cases_with_seed_urls: int
    seed_urls_total: int


@dataclass(slots=True)
class ValidationDatasetCoverageSummary:
    dataset_path: str
    cases_total: int
    cities_total: int
    services_total: int
    cases_with_relevant_urls: int
    cases_with_irrelevant_urls: int
    cases_with_candidate_urls: int
    pending_markup_cases: int


@dataclass(slots=True)
class ValidationMarkupBatch:
    batch_id: str
    group_by: str
    group_key: str
    priority: int
    cases_total: int
    cities: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    case_names: list[str] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ValidationMarkupPlanSummary:
    coverage_path: str
    group_by: str
    batch_size: int
    pending_cases_total: int
    pending_groups_total: int
    batches_total: int
    max_batches: int
    queued_cases_total: int
    remaining_cases_total: int


def load_validation_cases(path: str | Path) -> list[ValidationCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Validation dataset must be a JSON list.")
    cases: list[ValidationCase] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Validation case #{index} must be an object.")
        cases.append(
            ValidationCase(
                name=str(item.get("name") or f"case-{index}"),
                cities=[str(value) for value in item.get("cities", [])],
                services=[str(value) for value in item.get("services", [])],
                period_days=int(item.get("period_days", 60)),
                platforms=[str(value) for value in item.get("platforms", ["vk"])],
                top_n=int(item.get("top_n", 20)),
                report_mode=str(item.get("report_mode", "all")),
                expected_relevant_urls=[str(value) for value in item.get("expected_relevant_urls", [])],
                expected_irrelevant_urls=[str(value) for value in item.get("expected_irrelevant_urls", [])],
                candidate_urls=[str(value) for value in item.get("candidate_urls", [])],
                raw_candidate_urls=[str(value) for value in item.get("raw_candidate_urls", [])],
                notes=str(item.get("notes") or ""),
            )
        )
    return cases


def save_validation_cases(path: str | Path, cases: list[ValidationCase]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(case) for case in cases]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_validation_case(path: str | Path, case: ValidationCase) -> list[ValidationCase]:
    target = Path(path)
    cases = load_validation_cases(target) if target.exists() else []
    cases.append(case)
    save_validation_cases(target, cases)
    return cases


def bootstrap_validation_cases(
    *,
    output_path: str | Path,
    cities: list[str],
    services: list[str],
    seed_store: VkProfileSeedStore | None = None,
    platforms: list[str] | None = None,
    period_days: int = 60,
    top_n: int = 20,
    report_mode: str = "all",
    from_seeds_only: bool = False,
    include_empty_cases: bool = False,
) -> tuple[list[ValidationCase], ValidationBootstrapSummary]:
    normalized_platforms = list(platforms or ["vk"])
    cases: list[ValidationCase] = []
    case_keys: set[tuple[str, str]] = set()
    seeds = seed_store or VkProfileSeedStore()

    if from_seeds_only:
        iterable = [(entry.city, entry.service, list(entry.urls)) for entry in seeds.entries]
    else:
        iterable = [
            (city, service, seeds.urls_for(city, service))
            for city in cities
            for service in services
        ]

    for city, service, relevant_urls in iterable:
        city_key = _normalize_text_key(city)
        service_key = _normalize_text_key(service)
        if not city_key or not service_key:
            continue
        if (city_key, service_key) in case_keys:
            continue
        unique_urls = _unique_urls(relevant_urls)
        if not unique_urls and not include_empty_cases:
            continue
        case_keys.add((city_key, service_key))
        cases.append(
            ValidationCase(
                name=f"bootstrap_{_slugify_text(city)}_{_slugify_text(service)}",
                cities=[city],
                services=[service],
                period_days=period_days,
                platforms=list(normalized_platforms),
                top_n=top_n,
                report_mode=report_mode,
                expected_relevant_urls=unique_urls,
                notes="bootstrap from vk seeds/matrix",
            )
        )

    save_validation_cases(output_path, cases)
    summary = ValidationBootstrapSummary(
        output_path=str(output_path),
        cases_total=len(cases),
        cities_total=len({_normalize_text_key(case.cities[0]) for case in cases if case.cities}),
        services_total=len({_normalize_text_key(case.services[0]) for case in cases if case.services}),
        cases_with_seed_urls=sum(1 for case in cases if case.expected_relevant_urls),
        seed_urls_total=sum(len(case.expected_relevant_urls) for case in cases),
    )
    return cases, summary


def validation_dataset_coverage_payload(
    cases: list[ValidationCase],
    *,
    dataset_path: str | Path = "",
) -> dict[str, Any]:
    by_city: dict[str, dict[str, object]] = {}
    by_service: dict[str, dict[str, object]] = {}
    pending_cases: list[dict[str, object]] = []
    cases_with_relevant_urls = 0
    cases_with_irrelevant_urls = 0
    cases_with_candidate_urls = 0

    for case in cases:
        city = case.cities[0] if case.cities else ""
        service = case.services[0] if case.services else ""
        has_relevant = bool(case.expected_relevant_urls)
        has_irrelevant = bool(case.expected_irrelevant_urls)
        has_candidates = bool(case.candidate_urls or case.raw_candidate_urls)

        if has_relevant:
            cases_with_relevant_urls += 1
        if has_irrelevant:
            cases_with_irrelevant_urls += 1
        if has_candidates:
            cases_with_candidate_urls += 1

        city_bucket = by_city.setdefault(
            city,
            {
                "city": city,
                "cases_total": 0,
                "cases_with_relevant_urls": 0,
                "pending_markup_cases": 0,
            },
        )
        city_bucket["cases_total"] = int(city_bucket["cases_total"]) + 1
        if has_relevant:
            city_bucket["cases_with_relevant_urls"] = int(city_bucket["cases_with_relevant_urls"]) + 1

        service_bucket = by_service.setdefault(
            service,
            {
                "service": service,
                "cases_total": 0,
                "cases_with_relevant_urls": 0,
                "pending_markup_cases": 0,
            },
        )
        service_bucket["cases_total"] = int(service_bucket["cases_total"]) + 1
        if has_relevant:
            service_bucket["cases_with_relevant_urls"] = int(service_bucket["cases_with_relevant_urls"]) + 1

        if not has_relevant and not has_irrelevant:
            city_bucket["pending_markup_cases"] = int(city_bucket["pending_markup_cases"]) + 1
            service_bucket["pending_markup_cases"] = int(service_bucket["pending_markup_cases"]) + 1
            pending_cases.append(
                {
                    "name": case.name,
                    "cities": list(case.cities),
                    "services": list(case.services),
                    "platforms": list(case.platforms),
                    "notes": case.notes,
                }
            )

    pending_cases.sort(key=lambda item: (_normalize_text_key(item["cities"][0]) if item["cities"] else "", _normalize_text_key(item["services"][0]) if item["services"] else ""))
    city_rows = sorted(by_city.values(), key=lambda item: (int(item["pending_markup_cases"]), int(item["cases_total"])), reverse=True)
    service_rows = sorted(by_service.values(), key=lambda item: (int(item["pending_markup_cases"]), int(item["cases_total"])), reverse=True)

    summary = ValidationDatasetCoverageSummary(
        dataset_path=str(dataset_path),
        cases_total=len(cases),
        cities_total=len([key for key in by_city if key]),
        services_total=len([key for key in by_service if key]),
        cases_with_relevant_urls=cases_with_relevant_urls,
        cases_with_irrelevant_urls=cases_with_irrelevant_urls,
        cases_with_candidate_urls=cases_with_candidate_urls,
        pending_markup_cases=len(pending_cases),
    )
    return {
        "dataset_path": str(dataset_path),
        "summary": asdict(summary),
        "by_city": city_rows,
        "by_service": service_rows,
        "pending_cases": pending_cases,
    }


def load_validation_dataset_coverage(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Validation dataset coverage must be a JSON object.")
    if not isinstance(payload.get("pending_cases"), list):
        raise ValueError("Validation dataset coverage must include a pending_cases list.")
    return payload


def build_validation_markup_plan(
    coverage_payload: dict[str, Any],
    *,
    coverage_path: str | Path = "",
    group_by: str = "city",
    batch_size: int = 10,
    max_batches: int = 0,
) -> tuple[list[ValidationMarkupBatch], ValidationMarkupPlanSummary]:
    normalized_group_by = str(group_by or "city").strip().casefold()
    if normalized_group_by not in {"city", "service", "none"}:
        raise ValueError("group_by must be one of: city, service, none.")
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")
    if max_batches < 0:
        raise ValueError("max_batches cannot be negative.")

    raw_pending_cases = coverage_payload.get("pending_cases", [])
    pending_cases: list[dict[str, Any]] = [item for item in raw_pending_cases if isinstance(item, dict)]
    grouped_cases: dict[str, list[dict[str, Any]]] = {}

    for item in pending_cases:
        if normalized_group_by == "city":
            key = str((item.get("cities") or [""])[0] or "").strip() or "Без города"
        elif normalized_group_by == "service":
            key = str((item.get("services") or [""])[0] or "").strip() or "Без услуги"
        else:
            key = "all_pending_cases"
        grouped_cases.setdefault(key, []).append(item)

    group_rows: list[tuple[str, list[dict[str, Any]]]] = sorted(
        grouped_cases.items(),
        key=lambda item: (
            len(item[1]),
            _normalize_text_key(item[0]),
        ),
        reverse=True,
    )

    batches: list[ValidationMarkupBatch] = []
    assigned_cases = 0
    for group_index, (group_key, cases_for_group) in enumerate(group_rows, start=1):
        sorted_cases = sorted(
            cases_for_group,
            key=lambda item: (
                _normalize_text_key((item.get("cities") or [""])[0] if item.get("cities") else ""),
                _normalize_text_key((item.get("services") or [""])[0] if item.get("services") else ""),
                _normalize_text_key(str(item.get("name") or "")),
            ),
        )
        for chunk_index, start in enumerate(range(0, len(sorted_cases), batch_size), start=1):
            if max_batches and len(batches) >= max_batches:
                break
            chunk = sorted_cases[start : start + batch_size]
            batch_cities = sorted(
                {
                    str(city).strip()
                    for item in chunk
                    for city in _as_str_list(item.get("cities"))
                    if str(city).strip()
                },
                key=_normalize_text_key,
            )
            batch_services = sorted(
                {
                    str(service).strip()
                    for item in chunk
                    for service in _as_str_list(item.get("services"))
                    if str(service).strip()
                },
                key=_normalize_text_key,
            )
            batches.append(
                ValidationMarkupBatch(
                    batch_id=f"{normalized_group_by}-{group_index:02d}-{chunk_index:02d}",
                    group_by=normalized_group_by,
                    group_key=group_key,
                    priority=len(cases_for_group),
                    cases_total=len(chunk),
                    cities=batch_cities,
                    services=batch_services,
                    case_names=[str(item.get("name") or "") for item in chunk],
                    cases=chunk,
                )
            )
            assigned_cases += len(chunk)
        if max_batches and len(batches) >= max_batches:
            break

    summary = ValidationMarkupPlanSummary(
        coverage_path=str(coverage_path),
        group_by=normalized_group_by,
        batch_size=batch_size,
        pending_cases_total=len(pending_cases),
        pending_groups_total=len(group_rows),
        batches_total=len(batches),
        max_batches=max_batches,
        queued_cases_total=assigned_cases,
        remaining_cases_total=max(0, len(pending_cases) - assigned_cases),
    )
    return batches, summary


def validation_markup_plan_payload(
    *,
    coverage_path: str | Path,
    batches: list[ValidationMarkupBatch],
    summary: ValidationMarkupPlanSummary,
) -> dict[str, Any]:
    return {
        "coverage_path": str(coverage_path),
        "summary": asdict(summary),
        "batches": [asdict(item) for item in batches],
    }


def find_validation_case(cases: list[ValidationCase], case_name: str) -> ValidationCase:
    normalized_target = _normalize_text_key(case_name)
    for case in cases:
        if _normalize_text_key(case.name) == normalized_target:
            return case
    raise ValueError(f"Validation case not found: {case_name}")


def run_validation_cases(
    cases: list[ValidationCase],
    *,
    collector: Collector,
    config: RuntimeConfig,
) -> tuple[list[ValidationResult], ValidationSummary]:
    results: list[ValidationResult] = []
    totals = {
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "unlabeled": 0,
    }

    for case in cases:
        request = SearchRequest(
            cities=case.cities,
            services=[ServiceQuery(name=value) for value in case.services],
            period_days=case.period_days,
            platforms=case.platforms,
            top_n=case.top_n,
            report_mode=case.report_mode,
        )
        bundle = run_pipeline(request, collector=collector, config=config).bundle
        result = evaluate_validation_case(case, bundle)
        totals["tp"] += len(result.true_positives)
        totals["fp"] += len(result.false_positives)
        totals["fn"] += len(result.false_negatives)
        totals["unlabeled"] += len(result.unlabeled_hits)
        results.append(result)

    summary = ValidationSummary(
        cases_total=len(results),
        true_positives=totals["tp"],
        false_positives=totals["fp"],
        false_negatives=totals["fn"],
        unlabeled_hits=totals["unlabeled"],
        precision=_ratio(totals["tp"], totals["tp"] + totals["fp"]),
        recall=_ratio(totals["tp"], totals["tp"] + totals["fn"]),
        strict_precision=_ratio(totals["tp"], totals["tp"] + totals["fp"] + totals["unlabeled"]),
    )
    return results, summary


def evaluate_validation_case(case: ValidationCase, bundle: ReportBundle) -> ValidationResult:
    actual_urls = sorted({_normalize_url(item.candidate.account_url) for item in bundle.ranked_accounts})
    relevant_urls = {_normalize_url(value) for value in case.expected_relevant_urls}
    irrelevant_urls = {_normalize_url(value) for value in case.expected_irrelevant_urls}
    actual_set = set(actual_urls)

    true_positives = sorted(actual_set & relevant_urls)
    false_positives = sorted(actual_set & irrelevant_urls)
    false_negatives = sorted(relevant_urls - actual_set)
    unlabeled_hits = sorted(actual_set - relevant_urls - irrelevant_urls)

    precision = _ratio(len(true_positives), len(true_positives) + len(false_positives))
    recall = _ratio(len(true_positives), len(true_positives) + len(false_negatives))
    return ValidationResult(
        case_name=case.name,
        actual_urls=actual_urls,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        unlabeled_hits=unlabeled_hits,
        precision=precision,
        recall=recall,
    )


def strip_rule_config_alias_overrides(rule_config: RuleConfig) -> RuleConfig:
    return replace(
        rule_config,
        service_alias_overrides={},
        service_discovery_hint_overrides={},
        city_alias_overrides={},
    )


def compare_validation_case(
    case: ValidationCase,
    *,
    baseline_collector: Collector,
    baseline_config: RuntimeConfig,
    candidate_collector: Collector,
    candidate_config: RuntimeConfig,
    baseline_label: str = "baseline_without_alias_overrides",
    candidate_label: str = "candidate_rule_config",
) -> ValidationCaseComparison:
    baseline_results, _baseline_summary = run_validation_cases([case], collector=baseline_collector, config=baseline_config)
    candidate_results, _candidate_summary = run_validation_cases([case], collector=candidate_collector, config=candidate_config)
    baseline_result = baseline_results[0]
    candidate_result = candidate_results[0]
    urls_added = sorted(set(candidate_result.actual_urls) - set(baseline_result.actual_urls))
    urls_removed = sorted(set(baseline_result.actual_urls) - set(candidate_result.actual_urls))
    recall_delta = round(candidate_result.recall - baseline_result.recall, 4)
    precision_delta = round(candidate_result.precision - baseline_result.precision, 4)
    return ValidationCaseComparison(
        case_name=case.name,
        cities=list(case.cities),
        services=list(case.services),
        platforms=list(case.platforms),
        baseline_label=baseline_label,
        candidate_label=candidate_label,
        baseline_rule_config_path=str(baseline_config.rule_config_path or ""),
        candidate_rule_config_path=str(candidate_config.rule_config_path or ""),
        baseline_result=baseline_result,
        candidate_result=candidate_result,
        recall_delta=recall_delta,
        precision_delta=precision_delta,
        urls_added=urls_added,
        urls_removed=urls_removed,
        improved=recall_delta > 0 or (recall_delta == 0 and precision_delta > 0),
    )


def validation_case_comparison_payload(
    *,
    dataset_path: str | Path,
    case: ValidationCase,
    comparison: ValidationCaseComparison,
) -> dict[str, Any]:
    return {
        "dataset": str(dataset_path),
        "case": asdict(case),
        "baseline": {
            "label": comparison.baseline_label,
            "rule_config_path": comparison.baseline_rule_config_path,
            "result": asdict(comparison.baseline_result),
        },
        "candidate": {
            "label": comparison.candidate_label,
            "rule_config_path": comparison.candidate_rule_config_path,
            "result": asdict(comparison.candidate_result),
        },
        "summary": {
            "case_name": comparison.case_name,
            "improved": comparison.improved,
            "baseline_recall": comparison.baseline_result.recall,
            "candidate_recall": comparison.candidate_result.recall,
            "recall_delta": comparison.recall_delta,
            "baseline_precision": comparison.baseline_result.precision,
            "candidate_precision": comparison.candidate_result.precision,
            "precision_delta": comparison.precision_delta,
            "urls_added_total": len(comparison.urls_added),
            "urls_removed_total": len(comparison.urls_removed),
            "urls_added": list(comparison.urls_added),
            "urls_removed": list(comparison.urls_removed),
        },
    }


def compare_validation_cases(
    cases: list[ValidationCase],
    *,
    baseline_collector: Collector,
    baseline_config: RuntimeConfig,
    candidate_collector: Collector,
    candidate_config: RuntimeConfig,
    baseline_label: str = "baseline_without_alias_overrides",
    candidate_label: str = "candidate_rule_config",
) -> tuple[list[ValidationCaseComparison], ValidationComparisonSummary]:
    comparisons = [
        compare_validation_case(
            case,
            baseline_collector=baseline_collector,
            baseline_config=baseline_config,
            candidate_collector=candidate_collector,
            candidate_config=candidate_config,
            baseline_label=baseline_label,
            candidate_label=candidate_label,
        )
        for case in cases
    ]
    comparisons.sort(
        key=lambda item: (
            item.recall_delta,
            item.precision_delta,
            len(item.urls_added),
            -len(item.urls_removed),
        ),
        reverse=True,
    )
    improved_cases = sum(1 for item in comparisons if item.recall_delta > 0 or item.precision_delta > 0)
    regressed_cases = sum(1 for item in comparisons if item.recall_delta < 0 or item.precision_delta < 0)
    unchanged_cases = len(comparisons) - improved_cases - regressed_cases
    summary = ValidationComparisonSummary(
        cases_total=len(comparisons),
        improved_cases=improved_cases,
        unchanged_cases=unchanged_cases,
        regressed_cases=regressed_cases,
        recall_delta_total=round(sum(item.recall_delta for item in comparisons), 4),
        precision_delta_total=round(sum(item.precision_delta for item in comparisons), 4),
        urls_added_total=sum(len(item.urls_added) for item in comparisons),
        urls_removed_total=sum(len(item.urls_removed) for item in comparisons),
    )
    return comparisons, summary


def validation_comparison_report_payload(
    *,
    dataset_path: str | Path,
    comparisons: list[ValidationCaseComparison],
    summary: ValidationComparisonSummary,
) -> dict[str, Any]:
    return {
        "dataset": str(dataset_path),
        "comparisons": [
            {
                "case_name": item.case_name,
                "cities": list(item.cities),
                "services": list(item.services),
                "platforms": list(item.platforms),
                "baseline_label": item.baseline_label,
                "candidate_label": item.candidate_label,
                "baseline_rule_config_path": item.baseline_rule_config_path,
                "candidate_rule_config_path": item.candidate_rule_config_path,
                "baseline_result": asdict(item.baseline_result),
                "candidate_result": asdict(item.candidate_result),
                "recall_delta": item.recall_delta,
                "precision_delta": item.precision_delta,
                "urls_added": list(item.urls_added),
                "urls_removed": list(item.urls_removed),
                "improved": item.improved,
            }
            for item in comparisons
        ],
        "summary": asdict(summary),
    }


def load_validation_comparison_report(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Validation comparison report must be a JSON object.")
    comparisons = payload.get("comparisons")
    if not isinstance(comparisons, list):
        raise ValueError("Validation comparison report must include a comparisons list.")
    return payload


def build_validation_comparison_action_plan(
    report_payload: dict[str, Any],
    *,
    report_path: str | Path = "",
) -> tuple[list[ValidationComparisonActionItem], ValidationComparisonActionSummary]:
    raw_comparisons = report_payload.get("comparisons", [])
    actions: list[ValidationComparisonActionItem] = []
    counters = {
        "regression": 0,
        "followup-gap": 0,
        "accepted-improvement": 0,
    }
    for raw_item in raw_comparisons:
        if not isinstance(raw_item, dict):
            continue
        action = _comparison_action_for_case(raw_item)
        if action is None:
            continue
        actions.append(action)
        counters[action.action_type] += 1
    type_order = {
        "regression": 3,
        "followup-gap": 2,
        "accepted-improvement": 1,
    }
    actions.sort(
        key=lambda item: (
            type_order.get(item.action_type, 0),
            item.priority,
            abs(item.recall_delta),
            abs(item.precision_delta),
        ),
        reverse=True,
    )
    summary = ValidationComparisonActionSummary(
        report_path=str(report_path),
        actions_total=len(actions),
        regressions_total=counters["regression"],
        followup_gap_total=counters["followup-gap"],
        accepted_improvements_total=counters["accepted-improvement"],
    )
    return actions, summary


def validation_comparison_action_plan_payload(
    *,
    report_path: str | Path,
    actions: list[ValidationComparisonActionItem],
    summary: ValidationComparisonActionSummary,
) -> dict[str, Any]:
    return {
        "report_path": str(report_path),
        "actions": [asdict(item) for item in actions],
        "summary": asdict(summary),
    }


def load_validation_comparison_action_plan(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Validation comparison action plan must be a JSON object.")
    actions = payload.get("actions")
    if not isinstance(actions, list):
        raise ValueError("Validation comparison action plan must include an actions list.")
    return payload


def draft_validation_comparison_followups(
    plan_payload: dict[str, Any],
) -> tuple[list[VkProfileSeedEntry], list[ValidationDraftSuggestion], ValidationComparisonFollowupSummary]:
    raw_actions = plan_payload.get("actions", [])
    seed_entries: list[VkProfileSeedEntry] = []
    alias_drafts: dict[str, ValidationDraftSuggestion] = {}
    city_alias_drafts: dict[str, ValidationDraftSuggestion] = {}
    manual_review_drafts: dict[str, ValidationDraftSuggestion] = {}

    for raw_action in raw_actions:
        if not isinstance(raw_action, dict):
            continue
        action_type = str(raw_action.get("action_type") or "").strip()
        case_name = str(raw_action.get("case_name") or "unknown-case")
        cities = _as_str_list(raw_action.get("cities"))
        services = _as_str_list(raw_action.get("services"))
        platforms = {value.casefold() for value in _as_str_list(raw_action.get("platforms"))}
        false_negatives = _unique_urls(_as_str_list(raw_action.get("false_negatives")))
        false_positives = _unique_urls(_as_str_list(raw_action.get("false_positives")))
        unlabeled_hits = _unique_urls(_as_str_list(raw_action.get("unlabeled_hits")))
        urls_added = _unique_urls(_as_str_list(raw_action.get("urls_added")))
        urls_removed = _unique_urls(_as_str_list(raw_action.get("urls_removed")))

        if action_type == "followup-gap":
            seed_urls = [url for url in false_negatives if _is_vk_url(url)]
            if "vk" in platforms and len(cities) == 1 and len(services) == 1 and seed_urls:
                seed_entries.append(VkProfileSeedEntry(city=cities[0], service=services[0], urls=seed_urls))
                continue
            if services:
                key = _normalize_text_key(services[0])
                draft = alias_drafts.setdefault(
                    key,
                    ValidationDraftSuggestion(
                        suggestion_type="aliases",
                        key=services[0],
                        rationale="Кейс всё ещё имеет recall-gap после alias-overrides; нужно расширить service aliases / discovery hints.",
                    ),
                )
                _merge_draft_item(
                    draft,
                    case_name=case_name,
                    cities=cities,
                    services=services,
                    urls=false_negatives or unlabeled_hits,
                    rationale="Остались false negatives после compare-smoke.",
                )
                continue

        if action_type == "regression":
            key = _normalize_text_key(case_name)
            draft = manual_review_drafts.setdefault(
                key,
                ValidationDraftSuggestion(
                    suggestion_type="manual-review",
                    key=case_name,
                    rationale="После alias/city-alias overrides появился regression; нужен разбор removed URLs и candidate diagnostics.",
                ),
            )
            _merge_draft_item(
                draft,
                case_name=case_name,
                cities=cities,
                services=services,
                urls=urls_removed or false_negatives or false_positives or unlabeled_hits or urls_added,
                rationale="Нужно вручную проверить регрессию и решить, откатывать ли часть overrides или корректировать правила.",
            )
            continue

        if action_type == "accepted-improvement":
            continue

        if cities:
            key = _normalize_text_key(cities[0])
            draft = city_alias_drafts.setdefault(
                key,
                ValidationDraftSuggestion(
                    suggestion_type="city-alias",
                    key=cities[0],
                    rationale="Кейс требует отдельной проверки city aliases и геосигналов.",
                ),
            )
            _merge_draft_item(
                draft,
                case_name=case_name,
                cities=cities,
                services=services,
                urls=false_negatives or urls_removed or unlabeled_hits,
                rationale="После compare-smoke остались неоднозначные city-related сигналы.",
            )

    drafts = [
        *alias_drafts.values(),
        *city_alias_drafts.values(),
        *manual_review_drafts.values(),
    ]
    summary = ValidationComparisonFollowupSummary(
        action_plan_path=str(plan_payload.get("report_path") or ""),
        seed_entries_total=len(seed_entries),
        seed_urls_total=sum(len(entry.urls) for entry in seed_entries),
        alias_drafts_total=len(alias_drafts),
        city_alias_drafts_total=len(city_alias_drafts),
        manual_review_drafts_total=len(manual_review_drafts),
    )
    return seed_entries, drafts, summary


def validation_comparison_followup_payload(
    *,
    action_plan_path: str | Path,
    seed_entries: list[VkProfileSeedEntry],
    drafts: list[ValidationDraftSuggestion],
    summary: ValidationComparisonFollowupSummary,
) -> dict[str, Any]:
    return {
        "action_plan_path": str(action_plan_path),
        "seed_entries": [asdict(item) for item in seed_entries],
        "drafts": [asdict(item) for item in drafts],
        "summary": asdict(summary),
    }


def load_validation_comparison_followups(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Validation comparison followups must be a JSON object.")
    if not isinstance(payload.get("seed_entries"), list):
        raise ValueError("Validation comparison followups must include a seed_entries list.")
    if not isinstance(payload.get("drafts"), list):
        raise ValueError("Validation comparison followups must include a drafts list.")
    return payload


def apply_validation_comparison_followups(
    followup_payload: dict[str, Any],
) -> tuple[list[VkProfileSeedEntry], list[ValidationDraftSuggestion], ValidationComparisonFollowupApplySummary]:
    raw_seed_entries = followup_payload.get("seed_entries", [])
    raw_drafts = followup_payload.get("drafts", [])
    seed_entries: list[VkProfileSeedEntry] = []
    drafts: list[ValidationDraftSuggestion] = []
    alias_drafts_total = 0
    city_alias_drafts_total = 0
    manual_review_drafts_total = 0

    for raw_entry in raw_seed_entries:
        if not isinstance(raw_entry, dict):
            continue
        city = str(raw_entry.get("city") or "").strip()
        service = str(raw_entry.get("service") or "").strip()
        urls = _unique_urls(_as_str_list(raw_entry.get("urls")))
        if city and service and urls:
            seed_entries.append(VkProfileSeedEntry(city=city, service=service, urls=urls))

    for raw_draft in raw_drafts:
        if not isinstance(raw_draft, dict):
            continue
        draft = _draft_suggestion_from_payload(raw_draft)
        drafts.append(draft)
        if draft.suggestion_type == "aliases":
            alias_drafts_total += 1
        elif draft.suggestion_type == "city-alias":
            city_alias_drafts_total += 1
        elif draft.suggestion_type == "manual-review":
            manual_review_drafts_total += 1

    summary = ValidationComparisonFollowupApplySummary(
        followup_path=str(followup_payload.get("action_plan_path") or followup_payload.get("followup_path") or ""),
        seed_entries_applied=len(seed_entries),
        seed_urls_applied=sum(len(entry.urls) for entry in seed_entries),
        alias_drafts_total=alias_drafts_total,
        city_alias_drafts_total=city_alias_drafts_total,
        manual_review_drafts_total=manual_review_drafts_total,
    )
    return seed_entries, drafts, summary


def validation_comparison_followup_apply_payload(
    *,
    followup_path: str | Path,
    seed_file: str | Path,
    seed_entries: list[VkProfileSeedEntry],
    drafts: list[ValidationDraftSuggestion],
    summary: ValidationComparisonFollowupApplySummary,
) -> dict[str, Any]:
    return {
        "followup_path": str(followup_path),
        "seed_file": str(seed_file),
        "seed_entries": [asdict(item) for item in seed_entries],
        "drafts": [asdict(item) for item in drafts],
        "summary": asdict(summary),
    }


def validation_report_payload(
    cases: list[ValidationCase],
    results: list[ValidationResult],
    summary: ValidationSummary,
) -> dict[str, Any]:
    diagnostics, diagnostics_summary = build_validation_diagnostics(cases, results)
    return {
        "cases": [asdict(case) for case in cases],
        "results": [asdict(result) for result in results],
        "summary": asdict(summary),
        "diagnostics": {
            "cases": [asdict(item) for item in diagnostics],
            "summary": asdict(diagnostics_summary),
        },
    }


def build_validation_diagnostics(
    cases: list[ValidationCase],
    results: list[ValidationResult],
) -> tuple[list[ValidationCaseDiagnostic], ValidationDiagnosticsSummary]:
    diagnostics: list[ValidationCaseDiagnostic] = []
    ready_seed_cases = 0
    seed_candidate_urls_total = 0
    false_negative_cases = 0
    false_positive_cases = 0
    unlabeled_cases = 0

    for case, result in zip(cases, results, strict=False):
        seed_candidate_urls, seed_candidate_status = _seed_candidates_for_case(case, result)
        if result.false_negatives:
            false_negative_cases += 1
        if result.false_positives:
            false_positive_cases += 1
        if result.unlabeled_hits:
            unlabeled_cases += 1
        if seed_candidate_status == "ready":
            ready_seed_cases += 1
            seed_candidate_urls_total += len(seed_candidate_urls)

        diagnostics.append(
            ValidationCaseDiagnostic(
                case_name=case.name,
                cities=list(case.cities),
                services=list(case.services),
                platforms=list(case.platforms),
                precision=result.precision,
                recall=result.recall,
                true_positives=list(result.true_positives),
                false_positives=list(result.false_positives),
                false_negatives=list(result.false_negatives),
                unlabeled_hits=list(result.unlabeled_hits),
                actual_urls=list(result.actual_urls),
                candidate_urls=list(case.candidate_urls),
                raw_candidate_urls=list(case.raw_candidate_urls),
                seed_candidate_urls=seed_candidate_urls,
                seed_candidate_status=seed_candidate_status,
                notes=case.notes,
            )
        )

    diagnostics.sort(
        key=lambda item: (
            len(item.false_negatives),
            len(item.unlabeled_hits),
            len(item.false_positives),
            len(item.seed_candidate_urls),
        ),
        reverse=True,
    )
    summary = ValidationDiagnosticsSummary(
        cases_total=len(diagnostics),
        cases_with_false_negatives=false_negative_cases,
        cases_with_false_positives=false_positive_cases,
        cases_with_unlabeled_hits=unlabeled_cases,
        ready_seed_cases=ready_seed_cases,
        seed_candidate_urls_total=seed_candidate_urls_total,
    )
    return diagnostics, summary


def recommend_vk_seed_entries(
    cases: list[ValidationCase],
    *,
    mode: str = "missing_only",
) -> tuple[list[VkProfileSeedEntry], list[VkSeedRecommendationSkip], list[VkSeedRecommendation]]:
    if mode not in {"missing_only", "all_relevant"}:
        raise ValueError(f"Unsupported vk seed recommendation mode: {mode}")

    aggregated: dict[tuple[str, str], VkSeedRecommendation] = {}
    skipped: list[VkSeedRecommendationSkip] = []

    for case in cases:
        platforms = {item.casefold() for item in case.platforms}
        if "vk" not in platforms:
            skipped.append(VkSeedRecommendationSkip(case_name=case.name, reason="platform_without_vk"))
            continue
        if len(case.cities) != 1 or len(case.services) != 1:
            skipped.append(VkSeedRecommendationSkip(case_name=case.name, reason="ambiguous_city_or_service"))
            continue

        relevant_urls = [url for url in _unique_urls(case.expected_relevant_urls) if _is_vk_url(url)]
        if not relevant_urls:
            skipped.append(VkSeedRecommendationSkip(case_name=case.name, reason="no_vk_relevant_urls"))
            continue

        if mode == "missing_only":
            captured_urls = {_normalize_url(url) for url in case.candidate_urls}
            recommended_urls = [url for url in relevant_urls if _normalize_url(url) not in captured_urls]
        else:
            recommended_urls = relevant_urls

        if not recommended_urls:
            skipped.append(VkSeedRecommendationSkip(case_name=case.name, reason="no_missing_vk_urls"))
            continue

        city = case.cities[0]
        service = case.services[0]
        key = (_normalize_text_key(city), _normalize_text_key(service))
        recommendation = aggregated.get(key)
        if recommendation is None:
            recommendation = VkSeedRecommendation(city=city, service=service)
            aggregated[key] = recommendation
        for url in recommended_urls:
            if url not in recommendation.urls:
                recommendation.urls.append(url)
        if case.name not in recommendation.source_cases:
            recommendation.source_cases.append(case.name)

    recommendations = list(aggregated.values())
    entries = [
        VkProfileSeedEntry(city=item.city, service=item.service, urls=item.urls)
        for item in recommendations
    ]
    return entries, skipped, recommendations


def vk_seed_recommendations_payload(
    *,
    dataset_path: str | Path,
    mode: str,
    entries: list[VkProfileSeedEntry],
    recommendations: list[VkSeedRecommendation],
    skipped: list[VkSeedRecommendationSkip],
) -> dict[str, Any]:
    return {
        "dataset": str(dataset_path),
        "mode": mode,
        "recommendations": [asdict(item) for item in recommendations],
        "entries": [asdict(item) for item in entries],
        "skipped_cases": [asdict(item) for item in skipped],
        "stats": {
            "recommendations_total": len(recommendations),
            "seed_entries_total": len(entries),
            "seed_urls_total": sum(len(item.urls) for item in recommendations),
            "skipped_cases_total": len(skipped),
        },
    }


def load_validation_report(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Validation report must be a JSON object.")
    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        raise ValueError("Validation report must include diagnostics.")
    cases = diagnostics.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Validation report diagnostics must include a cases list.")
    return payload


def build_validation_action_plan(
    report_payload: dict[str, Any],
    *,
    report_path: str | Path = "",
) -> tuple[list[ValidationActionItem], ValidationActionSummary]:
    diagnostics = report_payload.get("diagnostics", {})
    raw_cases = diagnostics.get("cases", [])
    actions: list[ValidationActionItem] = []
    counters = {
        "seed": 0,
        "aliases": 0,
        "city-alias": 0,
        "manual-review": 0,
    }

    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            continue
        action = _action_for_validation_case(raw_case)
        if action is None:
            continue
        actions.append(action)
        counters[action.action_type] += 1

    actions.sort(key=lambda item: (item.priority, len(item.urls), len(item.false_negatives), len(item.unlabeled_hits)), reverse=True)
    summary = ValidationActionSummary(
        report_path=str(report_path),
        actions_total=len(actions),
        seed_actions=counters["seed"],
        aliases_actions=counters["aliases"],
        city_alias_actions=counters["city-alias"],
        manual_review_actions=counters["manual-review"],
    )
    return actions, summary


def validation_action_plan_payload(
    *,
    report_path: str | Path,
    actions: list[ValidationActionItem],
    summary: ValidationActionSummary,
) -> dict[str, Any]:
    return {
        "report_path": str(report_path),
        "actions": [asdict(item) for item in actions],
        "summary": asdict(summary),
    }


def load_validation_action_plan(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Validation action plan must be a JSON object.")
    actions = payload.get("actions")
    if not isinstance(actions, list):
        raise ValueError("Validation action plan must include an actions list.")
    return payload


def apply_validation_action_plan(
    plan_payload: dict[str, Any],
) -> tuple[list[VkProfileSeedEntry], list[ValidationDraftSuggestion], ValidationActionApplySummary]:
    raw_actions = plan_payload.get("actions", [])
    seed_entries: list[VkProfileSeedEntry] = []
    alias_drafts: dict[str, ValidationDraftSuggestion] = {}
    city_alias_drafts: dict[str, ValidationDraftSuggestion] = {}
    manual_review_drafts: dict[str, ValidationDraftSuggestion] = {}

    for raw_action in raw_actions:
        if not isinstance(raw_action, dict):
            continue
        action_type = str(raw_action.get("action_type") or "").strip()
        case_name = str(raw_action.get("case_name") or "unknown-case")
        cities = _as_str_list(raw_action.get("cities"))
        services = _as_str_list(raw_action.get("services"))
        urls = _unique_urls(_as_str_list(raw_action.get("urls")))
        rationale = str(raw_action.get("rationale") or "")

        if action_type == "seed":
            if len(cities) == 1 and len(services) == 1 and urls:
                seed_entries.append(VkProfileSeedEntry(city=cities[0], service=services[0], urls=urls))
            continue
        if action_type == "aliases":
            key = _normalize_text_key(services[0] if services else case_name)
            draft = alias_drafts.setdefault(
                key,
                ValidationDraftSuggestion(
                    suggestion_type="aliases",
                    key=services[0] if services else case_name,
                    rationale="Расширить service aliases / discovery hints по проблемному кейсу.",
                ),
            )
            _merge_draft_item(draft, case_name=case_name, cities=cities, services=services, urls=urls, rationale=rationale)
            continue
        if action_type == "city-alias":
            key = _normalize_text_key(cities[0] if cities else case_name)
            draft = city_alias_drafts.setdefault(
                key,
                ValidationDraftSuggestion(
                    suggestion_type="city-alias",
                    key=cities[0] if cities else case_name,
                    rationale="Проверить и расширить city aliases и геосигналы профиля.",
                ),
            )
            _merge_draft_item(draft, case_name=case_name, cities=cities, services=services, urls=urls, rationale=rationale)
            continue
        key = _normalize_text_key(case_name)
        draft = manual_review_drafts.setdefault(
            key,
            ValidationDraftSuggestion(
                suggestion_type="manual-review",
                key=case_name,
                rationale="Нужен ручной разбор кейса и уточнение правил.",
            ),
        )
        _merge_draft_item(draft, case_name=case_name, cities=cities, services=services, urls=urls, rationale=rationale)

    drafts = [
        *alias_drafts.values(),
        *city_alias_drafts.values(),
        *manual_review_drafts.values(),
    ]
    summary = ValidationActionApplySummary(
        action_plan_path=str(plan_payload.get("report_path") or plan_payload.get("action_plan_path") or ""),
        seed_entries_applied=len(seed_entries),
        seed_urls_applied=sum(len(entry.urls) for entry in seed_entries),
        alias_drafts_total=len(alias_drafts),
        city_alias_drafts_total=len(city_alias_drafts),
        manual_review_drafts_total=len(manual_review_drafts),
    )
    return seed_entries, drafts, summary


def validation_action_apply_payload(
    *,
    action_plan_path: str | Path,
    seed_file: str | Path,
    seed_entries: list[VkProfileSeedEntry],
    drafts: list[ValidationDraftSuggestion],
    summary: ValidationActionApplySummary,
) -> dict[str, Any]:
    return {
        "action_plan_path": str(action_plan_path),
        "seed_file": str(seed_file),
        "seed_entries": [asdict(item) for item in seed_entries],
        "drafts": [asdict(item) for item in drafts],
        "summary": asdict(summary),
    }


def load_validation_action_apply(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Validation action apply payload must be a JSON object.")
    drafts = payload.get("drafts")
    if not isinstance(drafts, list):
        raise ValueError("Validation action apply payload must include a drafts list.")
    return payload


def build_alias_patch_draft(
    apply_payload: dict[str, Any],
    *,
    action_apply_path: str | Path = "",
) -> tuple[list[ServiceAliasPatchDraft], list[CityAliasPatchDraft], list[ValidationDraftSuggestion], AliasPatchDraftSummary]:
    raw_drafts = apply_payload.get("drafts", [])
    service_patches: list[ServiceAliasPatchDraft] = []
    city_patches: list[CityAliasPatchDraft] = []
    manual_review: list[ValidationDraftSuggestion] = []

    for raw_draft in raw_drafts:
        if not isinstance(raw_draft, dict):
            continue
        suggestion_type = str(raw_draft.get("suggestion_type") or "").strip()
        if suggestion_type == "aliases":
            service_patches.extend(_service_alias_patches_from_draft(raw_draft))
            continue
        if suggestion_type == "city-alias":
            city_patches.extend(_city_alias_patches_from_draft(raw_draft))
            continue
        manual_review.append(_draft_suggestion_from_payload(raw_draft))

    summary = AliasPatchDraftSummary(
        action_apply_path=str(action_apply_path),
        service_alias_patches_total=len(service_patches),
        city_alias_patches_total=len(city_patches),
        manual_review_cases_total=len(manual_review),
    )
    return service_patches, city_patches, manual_review, summary


def validation_alias_patch_payload(
    *,
    action_apply_path: str | Path,
    service_patches: list[ServiceAliasPatchDraft],
    city_patches: list[CityAliasPatchDraft],
    manual_review: list[ValidationDraftSuggestion],
    summary: AliasPatchDraftSummary,
) -> dict[str, Any]:
    return {
        "action_apply_path": str(action_apply_path),
        "service_alias_patches": [asdict(item) for item in service_patches],
        "city_alias_patches": [asdict(item) for item in city_patches],
        "manual_review": [asdict(item) for item in manual_review],
        "summary": asdict(summary),
    }


def load_validation_alias_patch_draft(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Validation alias patch draft must be a JSON object.")
    if not isinstance(payload.get("service_alias_patches", []), list):
        raise ValueError("Validation alias patch draft must include service_alias_patches list.")
    if not isinstance(payload.get("city_alias_patches", []), list):
        raise ValueError("Validation alias patch draft must include city_alias_patches list.")
    return payload


def build_rule_config_alias_overrides(
    draft_payload: dict[str, Any],
    *,
    draft_path: str | Path = "",
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]], AliasPatchApplySummary]:
    service_alias_overrides: dict[str, list[str]] = {}
    service_hint_overrides: dict[str, list[str]] = {}
    city_alias_overrides: dict[str, list[str]] = {}

    for patch in draft_payload.get("service_alias_patches", []):
        if not isinstance(patch, dict):
            continue
        service = str(patch.get("service") or "").strip()
        if not service:
            continue
        suggested_aliases = _unique_values(_as_str_list(patch.get("suggested_aliases")))
        suggested_hints = _unique_values(_as_str_list(patch.get("suggested_discovery_hints")))
        if suggested_aliases:
            service_alias_overrides[service] = suggested_aliases
        if suggested_hints:
            service_hint_overrides[service] = suggested_hints

    for patch in draft_payload.get("city_alias_patches", []):
        if not isinstance(patch, dict):
            continue
        city = str(patch.get("city") or "").strip()
        if not city:
            continue
        suggested_aliases = _unique_values(_as_str_list(patch.get("suggested_aliases")))
        if suggested_aliases:
            city_alias_overrides[city] = suggested_aliases

    summary = AliasPatchApplySummary(
        draft_path=str(draft_path),
        service_alias_services_total=len(service_alias_overrides),
        service_alias_values_total=sum(len(values) for values in service_alias_overrides.values()),
        service_hint_services_total=len(service_hint_overrides),
        service_hint_values_total=sum(len(values) for values in service_hint_overrides.values()),
        city_alias_cities_total=len(city_alias_overrides),
        city_alias_values_total=sum(len(values) for values in city_alias_overrides.values()),
    )
    return service_alias_overrides, service_hint_overrides, city_alias_overrides, summary


def validation_alias_patch_apply_payload(
    *,
    draft_path: str | Path,
    rule_config_path: str | Path,
    service_alias_overrides: dict[str, list[str]],
    service_hint_overrides: dict[str, list[str]],
    city_alias_overrides: dict[str, list[str]],
    summary: AliasPatchApplySummary,
) -> dict[str, Any]:
    return {
        "draft_path": str(draft_path),
        "rule_config_path": str(rule_config_path),
        "service_alias_overrides": service_alias_overrides,
        "service_discovery_hint_overrides": service_hint_overrides,
        "city_alias_overrides": city_alias_overrides,
        "summary": asdict(summary),
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _normalize_url(value: str) -> str:
    return value.rstrip("/").casefold()


def _unique_urls(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = _normalize_url(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(value.rstrip("/"))
    return unique


def _is_vk_url(value: str) -> bool:
    normalized = _normalize_url(value)
    return normalized.startswith("https://vk.com/") or normalized.startswith("https://vk.ru/")


def _normalize_text_key(value: str) -> str:
    return " ".join(part for part in value.casefold().split() if part)


def _slugify_text(value: str) -> str:
    return "_".join(part for part in normalize_text(value).split() if part) or "case"


def _seed_candidates_for_case(case: ValidationCase, result: ValidationResult) -> tuple[list[str], str]:
    if "vk" not in {platform.casefold() for platform in case.platforms}:
        return [], "platform_without_vk"
    if len(case.cities) != 1 or len(case.services) != 1:
        return [], "ambiguous_city_or_service"
    vk_false_negatives = [url for url in result.false_negatives if _is_vk_url(url)]
    if not vk_false_negatives:
        return [], "no_vk_false_negatives"
    return vk_false_negatives, "ready"


def _action_for_validation_case(raw_case: dict[str, Any]) -> ValidationActionItem | None:
    false_negatives = _as_str_list(raw_case.get("false_negatives"))
    false_positives = _as_str_list(raw_case.get("false_positives"))
    unlabeled_hits = _as_str_list(raw_case.get("unlabeled_hits"))
    seed_candidate_urls = _as_str_list(raw_case.get("seed_candidate_urls"))
    raw_candidate_urls = _as_str_list(raw_case.get("raw_candidate_urls"))
    actual_urls = _as_str_list(raw_case.get("actual_urls"))
    cities = _as_str_list(raw_case.get("cities"))
    services = _as_str_list(raw_case.get("services"))
    platforms = _as_str_list(raw_case.get("platforms"))

    if not false_negatives and not false_positives and not unlabeled_hits:
        return None

    case_name = str(raw_case.get("case_name") or "unknown-case")
    if seed_candidate_urls:
        return ValidationActionItem(
            case_name=case_name,
            action_type="seed",
            priority=100 + len(seed_candidate_urls),
            cities=cities,
            services=services,
            platforms=platforms,
            rationale="Есть false_negatives для однозначного VK кейса; URL готовы для curated seed слоя.",
            urls=seed_candidate_urls,
            false_negatives=false_negatives,
            false_positives=false_positives,
            unlabeled_hits=unlabeled_hits,
        )
    if unlabeled_hits:
        return ValidationActionItem(
            case_name=case_name,
            action_type="manual-review",
            priority=90 + len(unlabeled_hits),
            cities=cities,
            services=services,
            platforms=platforms,
            rationale="Есть неразмеченные попадания; сначала нужно вручную разметить кейс и отделить шум от релевантных профилей.",
            urls=unlabeled_hits,
            false_negatives=false_negatives,
            false_positives=false_positives,
            unlabeled_hits=unlabeled_hits,
        )
    if false_positives:
        return ValidationActionItem(
            case_name=case_name,
            action_type="manual-review",
            priority=80 + len(false_positives),
            cities=cities,
            services=services,
            platforms=platforms,
            rationale="Есть ложные включения; нужно проверить rule-based фильтры и профильные исключающие признаки.",
            urls=false_positives,
            false_negatives=false_negatives,
            false_positives=false_positives,
            unlabeled_hits=unlabeled_hits,
        )
    if false_negatives and raw_candidate_urls and not actual_urls:
        return ValidationActionItem(
            case_name=case_name,
            action_type="city-alias",
            priority=70 + len(false_negatives),
            cities=cities,
            services=services,
            platforms=platforms,
            rationale="Кандидаты всплывали в сыром слое, но не дошли до выдачи; сначала проверить city alias и геофильтр.",
            urls=false_negatives,
            false_negatives=false_negatives,
            false_positives=false_positives,
            unlabeled_hits=unlabeled_hits,
        )
    if false_negatives and not raw_candidate_urls:
        return ValidationActionItem(
            case_name=case_name,
            action_type="aliases",
            priority=60 + len(false_negatives),
            cities=cities,
            services=services,
            platforms=platforms,
            rationale="Профильные кандидаты не поднялись даже в raw_candidates; нужно расширять service aliases и discovery hints.",
            urls=false_negatives,
            false_negatives=false_negatives,
            false_positives=false_positives,
            unlabeled_hits=unlabeled_hits,
        )
    return ValidationActionItem(
        case_name=case_name,
        action_type="manual-review",
        priority=50 + len(false_negatives),
        cities=cities,
        services=services,
        platforms=platforms,
        rationale="Кейс требует ручного разбора: discovery и фильтры расходятся с ожидаемой выдачей.",
        urls=false_negatives or false_positives or unlabeled_hits,
        false_negatives=false_negatives,
        false_positives=false_positives,
        unlabeled_hits=unlabeled_hits,
    )


def _comparison_action_for_case(raw_item: dict[str, Any]) -> ValidationComparisonActionItem | None:
    case_name = str(raw_item.get("case_name") or "unknown-case")
    cities = _as_str_list(raw_item.get("cities"))
    services = _as_str_list(raw_item.get("services"))
    platforms = _as_str_list(raw_item.get("platforms"))
    recall_delta = float(raw_item.get("recall_delta") or 0.0)
    precision_delta = float(raw_item.get("precision_delta") or 0.0)
    urls_added = _unique_urls(_as_str_list(raw_item.get("urls_added")))
    urls_removed = _unique_urls(_as_str_list(raw_item.get("urls_removed")))
    baseline_result = raw_item.get("baseline_result")
    candidate_result = raw_item.get("candidate_result")
    if not isinstance(baseline_result, dict) or not isinstance(candidate_result, dict):
        return None
    baseline_recall = float(baseline_result.get("recall") or 0.0)
    candidate_recall = float(candidate_result.get("recall") or 0.0)
    baseline_precision = float(baseline_result.get("precision") or 0.0)
    candidate_precision = float(candidate_result.get("precision") or 0.0)
    false_negatives = _unique_urls(_as_str_list(candidate_result.get("false_negatives")))
    false_positives = _unique_urls(_as_str_list(candidate_result.get("false_positives")))
    unlabeled_hits = _unique_urls(_as_str_list(candidate_result.get("unlabeled_hits")))

    if recall_delta < 0 or precision_delta < 0 or urls_removed:
        rationale = "После alias/city-alias overrides есть регрессия: нужно разобрать removed URLs и candidate false positives/false negatives."
        return ValidationComparisonActionItem(
            case_name=case_name,
            action_type="regression",
            priority=100 + int(abs(recall_delta) * 100) + int(abs(precision_delta) * 100) + len(urls_removed),
            rationale=rationale,
            cities=cities,
            services=services,
            platforms=platforms,
            baseline_recall=baseline_recall,
            candidate_recall=candidate_recall,
            baseline_precision=baseline_precision,
            candidate_precision=candidate_precision,
            recall_delta=recall_delta,
            precision_delta=precision_delta,
            urls_added=urls_added,
            urls_removed=urls_removed,
            false_negatives=false_negatives,
            false_positives=false_positives,
            unlabeled_hits=unlabeled_hits,
        )

    if false_negatives or false_positives or unlabeled_hits:
        rationale = "Регрессии нет, но кейс всё ещё не закрыт: остались false negatives/false positives или unlabeled hits."
        return ValidationComparisonActionItem(
            case_name=case_name,
            action_type="followup-gap",
            priority=70 + len(false_negatives) + len(false_positives) + len(unlabeled_hits),
            rationale=rationale,
            cities=cities,
            services=services,
            platforms=platforms,
            baseline_recall=baseline_recall,
            candidate_recall=candidate_recall,
            baseline_precision=baseline_precision,
            candidate_precision=candidate_precision,
            recall_delta=recall_delta,
            precision_delta=precision_delta,
            urls_added=urls_added,
            urls_removed=urls_removed,
            false_negatives=false_negatives,
            false_positives=false_positives,
            unlabeled_hits=unlabeled_hits,
        )

    if recall_delta > 0 or precision_delta > 0 or urls_added:
        rationale = "Кейс улучшился после alias/city-alias overrides и не содержит оставшихся диагностических проблем."
        return ValidationComparisonActionItem(
            case_name=case_name,
            action_type="accepted-improvement",
            priority=40 + int(recall_delta * 100) + int(precision_delta * 100) + len(urls_added),
            rationale=rationale,
            cities=cities,
            services=services,
            platforms=platforms,
            baseline_recall=baseline_recall,
            candidate_recall=candidate_recall,
            baseline_precision=baseline_precision,
            candidate_precision=candidate_precision,
            recall_delta=recall_delta,
            precision_delta=precision_delta,
            urls_added=urls_added,
            urls_removed=urls_removed,
            false_negatives=false_negatives,
            false_positives=false_positives,
            unlabeled_hits=unlabeled_hits,
        )

    return None


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _unique_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        token = str(value).strip()
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def _merge_draft_item(
    draft: ValidationDraftSuggestion,
    *,
    case_name: str,
    cities: list[str],
    services: list[str],
    urls: list[str],
    rationale: str,
) -> None:
    if case_name not in draft.cases:
        draft.cases.append(case_name)
    for city in cities:
        if city not in draft.cities:
            draft.cities.append(city)
    for service in services:
        if service not in draft.services:
            draft.services.append(service)
    for url in urls:
        if url not in draft.urls:
            draft.urls.append(url)
    if rationale and rationale not in draft.rationale:
        if draft.rationale:
            draft.rationale = f"{draft.rationale} {rationale}".strip()
        else:
            draft.rationale = rationale


def _service_alias_patches_from_draft(raw_draft: dict[str, Any]) -> list[ServiceAliasPatchDraft]:
    cases = _as_str_list(raw_draft.get("cases"))
    urls = _unique_urls(_as_str_list(raw_draft.get("urls")))
    services = _as_str_list(raw_draft.get("services"))
    cities = _as_str_list(raw_draft.get("cities"))
    patches: list[ServiceAliasPatchDraft] = []
    for service in services:
        existing_aliases = service_search_terms(service)[1:]
        existing_hints = service_discovery_hints(service)
        suggested_aliases = _suggest_service_aliases(service, cities, urls, existing_aliases)
        suggested_hints = _suggest_service_discovery_hints(service, existing_hints)
        patches.append(
            ServiceAliasPatchDraft(
                service=service,
                target_synonyms="SERVICE_SYNONYM_GROUPS",
                target_hints="SERVICE_DISCOVERY_HINT_GROUPS",
                existing_aliases=existing_aliases,
                existing_discovery_hints=existing_hints,
                suggested_aliases=suggested_aliases,
                suggested_discovery_hints=suggested_hints,
                cases=list(cases),
                urls=list(urls),
            )
        )
    return patches


def _city_alias_patches_from_draft(raw_draft: dict[str, Any]) -> list[CityAliasPatchDraft]:
    cases = _as_str_list(raw_draft.get("cases"))
    urls = _unique_urls(_as_str_list(raw_draft.get("urls")))
    cities = _as_str_list(raw_draft.get("cities"))
    patches: list[CityAliasPatchDraft] = []
    for city in cities:
        existing_aliases = list(CITY_ALIAS_MAP.get(city, [city]))
        suggested_aliases = _suggest_city_aliases(city, existing_aliases)
        patches.append(
            CityAliasPatchDraft(
                city=city,
                target="CITY_ALIAS_MAP",
                existing_aliases=existing_aliases,
                suggested_aliases=suggested_aliases,
                cases=list(cases),
                urls=list(urls),
            )
        )
    return patches


def _draft_suggestion_from_payload(raw_draft: dict[str, Any]) -> ValidationDraftSuggestion:
    return ValidationDraftSuggestion(
        suggestion_type=str(raw_draft.get("suggestion_type") or "manual-review"),
        key=str(raw_draft.get("key") or "manual-review"),
        cases=_as_str_list(raw_draft.get("cases")),
        cities=_as_str_list(raw_draft.get("cities")),
        services=_as_str_list(raw_draft.get("services")),
        urls=_as_str_list(raw_draft.get("urls")),
        rationale=str(raw_draft.get("rationale") or ""),
    )


def _suggest_service_aliases(service: str, cities: list[str], urls: list[str], existing_aliases: list[str]) -> list[str]:
    existing_terms = {normalize_text(term) for term in [service, *existing_aliases]}
    city_terms = {
        normalize_text(alias)
        for city in cities
        for alias in CITY_ALIAS_MAP.get(city, [city])
        if normalize_text(alias)
    }
    candidates: list[str] = []
    for url in urls:
        for token in _url_text_tokens(url):
            normalized = normalize_text(token)
            if len(normalized) < 4:
                continue
            if normalized in existing_terms or normalized in city_terms:
                continue
            if normalized in {"club", "vk", "page", "studio", "salon", "master"}:
                continue
            if token not in candidates:
                candidates.append(token)
    return candidates


def _suggest_service_discovery_hints(service: str, existing_hints: list[str]) -> list[str]:
    candidates = [
        f"мастер {service}",
        f"студия {service}",
        f"{service} студия",
    ]
    existing = {normalize_text(value) for value in existing_hints}
    return [value for value in candidates if normalize_text(value) not in existing]


def _suggest_city_aliases(city: str, existing_aliases: list[str]) -> list[str]:
    normalized_existing = {normalize_text(alias) for alias in existing_aliases}
    base = normalize_text(city)
    transliterated = _transliterate_city(city)
    candidates = [
        base,
        base.replace(" ", ""),
        f"#{base.replace(' ', '')}",
        transliterated,
        transliterated.replace(" ", ""),
    ]
    suggestions: list[str] = []
    for value in candidates:
        normalized = normalize_text(value)
        if normalized and normalized not in normalized_existing and value not in suggestions:
            suggestions.append(value)
    return suggestions


def _url_text_tokens(url: str) -> list[str]:
    path = url.rstrip("/").rsplit("/", 1)[-1]
    parts = [part for part in normalize_text(path).split() if part]
    return parts


def _transliterate_city(value: str) -> str:
    translit_map = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ы": "y",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "ь": "",
        "ъ": "",
        "-": "-",
        " ": " ",
    }
    lowered = value.casefold()
    return "".join(translit_map.get(char, char) for char in lowered)
