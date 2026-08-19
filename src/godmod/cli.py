from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from .collectors.factory import ConfiguredCollector
from .config import RuntimeConfig
from .collectors.mock import MockCollector
from .export.reports import write_report_artifacts_with_timing
from .markers import normalize_slug
from .models import SearchRequest, ServiceQuery
from .pipeline import run_pipeline
from .request_options import expand_service_names, format_period_label, service_selection_section_by_token
from .rule_config import DEFAULT_RULE_CONFIG_PATH, load_rule_config, merge_rule_config_alias_overrides
from .settings import AppSettings
from .smoke_matrix import (
    build_service_keyword_audit_payload,
    build_smoke_matrix_action_plan_payload,
    build_smoke_matrix_payload,
    load_smoke_matrix_payload,
    write_smoke_matrix_payload,
)
from .validation import (
    apply_validation_action_plan,
    ValidationCase,
    append_validation_case,
    bootstrap_validation_cases,
    build_rule_config_alias_overrides,
    apply_validation_comparison_followups,
    build_alias_patch_draft,
    build_validation_comparison_action_plan,
    draft_validation_comparison_followups,
    compare_validation_cases,
    build_validation_action_plan,
    compare_validation_case,
    find_validation_case,
    load_validation_cases,
    load_validation_action_apply,
    load_validation_action_plan,
    load_validation_alias_patch_draft,
    load_validation_dataset_coverage,
    load_validation_comparison_report,
    load_validation_comparison_action_plan,
    load_validation_comparison_followups,
    load_validation_report,
    recommend_vk_seed_entries,
    run_validation_cases,
    strip_rule_config_alias_overrides,
    build_validation_markup_plan,
    validation_dataset_coverage_payload,
    validation_action_apply_payload,
    validation_action_plan_payload,
    validation_alias_patch_apply_payload,
    validation_alias_patch_payload,
    validation_comparison_action_plan_payload,
    validation_comparison_followup_apply_payload,
    validation_comparison_followup_payload,
    validation_markup_plan_payload,
    validation_case_comparison_payload,
    validation_comparison_report_payload,
    vk_seed_recommendations_payload,
    validation_report_payload,
)
from .telegram_profile_seeds import load_telegram_profile_seed_store
from .vk_profile_seeds import load_vk_profile_seed_store, merge_vk_profile_seed_entries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Godmod MVP CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample = subparsers.add_parser("sample", help="Generate sample YANAO report")
    sample.add_argument("--cities", required=True, help="Comma-separated cities")
    sample.add_argument("--services", required=True, help="Comma-separated services")
    sample.add_argument("--period-days", type=int, default=60, help="0 means all available history")
    sample.add_argument("--top-n", type=int, default=20)
    sample.add_argument(
        "--report-mode",
        default="all",
        choices=["all", "official_only"],
        help="Report mode: all or official_only",
    )
    sample.add_argument(
        "--platforms",
        default="vk",
        help="Comma-separated platforms: vk,telegram,places,2gis",
    )
    sample.add_argument(
        "--output",
        default="output/yanao_report.xlsx",
        help="Path to resulting xlsx file; sibling pdf will be created automatically",
    )

    smoke_matrix = subparsers.add_parser(
        "smoke-matrix",
        help="Run city-service smoke matrix and save JSON diagnostics",
    )
    smoke_matrix.add_argument("--cities", default="", help="Comma-separated cities; empty means all runtime YANAO cities")
    smoke_matrix.add_argument("--services", default="", help="Comma-separated services or category names; empty means all popular services")
    smoke_matrix.add_argument("--category", default="", help="One service category to expand, for example: Красота и уход")
    smoke_matrix.add_argument("--period-days", type=int, default=30, help="0 means all available history")
    smoke_matrix.add_argument("--top-n", type=int, default=20)
    smoke_matrix.add_argument(
        "--report-mode",
        default="all",
        choices=["all", "official_only"],
        help="Report mode: all or official_only",
    )
    smoke_matrix.add_argument(
        "--platforms",
        default="",
        help="Comma-separated platforms; empty means configured platforms",
    )
    smoke_matrix.add_argument("--dotenv", default=".env", help="Path to .env file for real collectors")
    smoke_matrix.add_argument("--mock", action="store_true", help="Use MockCollector instead of configured real collectors")
    smoke_matrix.add_argument(
        "--vk-full-recall",
        action="store_true",
        help="Force VK full recall for this smoke run: do not stop after the first enough profile hits.",
    )
    smoke_matrix.add_argument(
        "--require-vk-profile-search",
        action="store_true",
        help="Fail before a VK smoke run if VK_API_TOKEN is not configured for groups.search/users.search.",
    )
    smoke_matrix.add_argument("--write-reports", action="store_true", help="Also write xlsx/pdf/manifest for every matrix case")
    smoke_matrix.add_argument("--reports-dir", default="", help="Directory for per-case reports when --write-reports is set")
    smoke_matrix.add_argument(
        "--case-timeout-seconds",
        type=int,
        default=0,
        help="Maximum seconds for one city-service case; 0 disables per-case timeout",
    )
    smoke_matrix.add_argument(
        "--checkpoint",
        action="store_true",
        help="Write output JSON after every case and resume existing city-service cases from --output",
    )
    smoke_matrix.add_argument("--output", default="", help="Path to smoke JSON; empty writes timestamped file in output/")

    review_smoke_matrix = subparsers.add_parser(
        "review-smoke-matrix",
        help="Build action plan from smoke-matrix JSON",
    )
    review_smoke_matrix.add_argument("--input", required=True, help="Path to smoke-matrix JSON")
    review_smoke_matrix.add_argument("--output", default="", help="Path to action plan JSON; empty writes next to input")

    service_keyword_audit = subparsers.add_parser(
        "service-keyword-audit",
        help="Audit service keywords, discovery hints and VK seed coverage",
    )
    service_keyword_audit.add_argument("--services", default="", help="Comma-separated services or category names; empty means all popular services")
    service_keyword_audit.add_argument("--category", default="", help="One service category to audit, for example: Красота и уход")
    service_keyword_audit.add_argument("--cities", default="", help="Comma-separated cities; empty means all runtime YANAO cities")
    service_keyword_audit.add_argument("--dotenv", default=".env", help="Path to .env file")
    service_keyword_audit.add_argument("--seed-file", default="", help="VK seed file; empty means configured GODMOD_VK_PROFILE_SEEDS_PATH")
    service_keyword_audit.add_argument(
        "--telegram-seed-file",
        default="",
        help="Telegram seed file; empty means configured GODMOD_TELEGRAM_PROFILE_SEEDS_PATH",
    )
    service_keyword_audit.add_argument("--output", default="", help="Path to audit JSON; empty writes timestamped file in output/")

    validate_dataset = subparsers.add_parser("validate-dataset", help="Run validation dataset and calculate precision/recall")
    validate_dataset.add_argument(
        "--dataset",
        default="data/validation_dataset.sample.json",
        help="Path to validation dataset JSON",
    )
    validate_dataset.add_argument(
        "--output",
        default="output/validation_report.json",
        help="Path to validation result JSON",
    )
    validate_dataset.add_argument(
        "--dotenv",
        default=".env",
        help="Path to .env file for real collectors",
    )
    validate_dataset.add_argument(
        "--mock",
        action="store_true",
        help="Use MockCollector instead of configured real collectors",
    )
    validate_dataset.add_argument(
        "--strict-unlabeled",
        action="store_true",
        help="Fail process when unlabeled hits are present and print strict precision",
    )

    add_validation_case = subparsers.add_parser("add-validation-case", help="Append one validation case to dataset JSON")
    add_validation_case.add_argument("--dataset", default="data/validation_dataset.sample.json", help="Path to validation dataset JSON")
    add_validation_case.add_argument("--name", required=True, help="Case name")
    add_validation_case.add_argument("--cities", required=True, help="Comma-separated cities")
    add_validation_case.add_argument("--services", required=True, help="Comma-separated services")
    add_validation_case.add_argument("--period-days", type=int, default=60)
    add_validation_case.add_argument("--platforms", default="vk", help="Comma-separated platforms")
    add_validation_case.add_argument("--top-n", type=int, default=20)
    add_validation_case.add_argument(
        "--report-mode",
        default="all",
        choices=["all", "official_only"],
        help="Report mode: all or official_only",
    )
    add_validation_case.add_argument("--relevant-urls", default="", help="Comma-separated relevant profile URLs")
    add_validation_case.add_argument("--irrelevant-urls", default="", help="Comma-separated irrelevant profile URLs")
    add_validation_case.add_argument("--notes", default="", help="Optional case notes")

    bootstrap_validation_dataset = subparsers.add_parser(
        "bootstrap-validation-dataset",
        help="Build validation dataset skeleton from VK seeds and/or city-service matrix",
    )
    bootstrap_validation_dataset.add_argument("--output", default="data/validation_dataset.yanao_template.json", help="Path to output validation dataset JSON")
    bootstrap_validation_dataset.add_argument("--seed-file", default="data/vk_profile_seeds.json", help="Path to VK seed JSON file")
    bootstrap_validation_dataset.add_argument("--cities", default="", help="Comma-separated cities; empty means runtime YANAO cities")
    bootstrap_validation_dataset.add_argument("--services", default="", help="Comma-separated services; empty means runtime popular services")
    bootstrap_validation_dataset.add_argument("--period-days", type=int, default=60)
    bootstrap_validation_dataset.add_argument("--top-n", type=int, default=20)
    bootstrap_validation_dataset.add_argument(
        "--report-mode",
        default="all",
        choices=["all", "official_only"],
        help="Report mode: all or official_only",
    )
    bootstrap_validation_dataset.add_argument("--platforms", default="vk", help="Comma-separated platforms")
    bootstrap_validation_dataset.add_argument("--from-seeds-only", action="store_true", help="Only create cases for explicit seed entries")
    bootstrap_validation_dataset.add_argument("--include-empty-cases", action="store_true", help="Include matrix cases even when no seed URLs are known")

    review_validation_dataset = subparsers.add_parser(
        "review-validation-dataset",
        help="Build coverage summary for validation dataset and highlight pending markup cases",
    )
    review_validation_dataset.add_argument("--dataset", default="data/validation_dataset.yanao_template.json", help="Path to validation dataset JSON")
    review_validation_dataset.add_argument("--output", default="output/validation_dataset_coverage.json", help="Path to coverage summary JSON")

    plan_validation_markup = subparsers.add_parser(
        "plan-validation-markup",
        help="Build prioritized markup batches from validation dataset coverage JSON",
    )
    plan_validation_markup.add_argument("--coverage", default="output/validation_dataset_coverage.json", help="Path to validation dataset coverage JSON")
    plan_validation_markup.add_argument("--output", default="output/validation_markup_plan.json", help="Path to markup plan JSON")
    plan_validation_markup.add_argument(
        "--group-by",
        default="city",
        choices=["city", "service", "none"],
        help="Batch pending cases by city, service or as one shared queue",
    )
    plan_validation_markup.add_argument("--batch-size", type=int, default=10, help="Maximum cases per markup batch")
    plan_validation_markup.add_argument("--max-batches", type=int, default=0, help="Optional cap for created batches; 0 means all")

    capture_validation_case = subparsers.add_parser("capture-validation-case", help="Capture discovered URLs into a validation case template")
    capture_validation_case.add_argument("--dataset", default="data/validation_dataset.yanao_template.json", help="Path to validation dataset JSON")
    capture_validation_case.add_argument("--name", required=True, help="Case name")
    capture_validation_case.add_argument("--cities", required=True, help="Comma-separated cities")
    capture_validation_case.add_argument("--services", required=True, help="Comma-separated services")
    capture_validation_case.add_argument("--period-days", type=int, default=60, help="0 means all available history")
    capture_validation_case.add_argument("--top-n", type=int, default=20)
    capture_validation_case.add_argument(
        "--report-mode",
        default="all",
        choices=["all", "official_only"],
        help="Report mode: all or official_only",
    )
    capture_validation_case.add_argument(
        "--platforms",
        default="vk",
        help="Comma-separated platforms: vk,telegram,places,2gis",
    )
    capture_validation_case.add_argument("--notes", default="", help="Optional case notes")
    capture_validation_case.add_argument("--dotenv", default=".env", help="Path to .env file for real collectors")
    capture_validation_case.add_argument("--mock", action="store_true", help="Use MockCollector instead of configured real collectors")

    recommend_vk_seeds = subparsers.add_parser(
        "recommend-vk-seeds",
        help="Build VK seed recommendations from validation dataset",
    )
    recommend_vk_seeds.add_argument("--dataset", default="data/validation_dataset.yanao_template.json", help="Path to validation dataset JSON")
    recommend_vk_seeds.add_argument("--output", default="output/vk_seed_recommendations.json", help="Path to recommendations JSON")
    recommend_vk_seeds.add_argument(
        "--mode",
        default="missing_only",
        choices=["missing_only", "all_relevant"],
        help="Recommend only missed relevant URLs or all labeled relevant VK URLs",
    )

    apply_vk_seeds = subparsers.add_parser(
        "apply-vk-seeds",
        help="Merge VK seed recommendations from validation dataset into seed file",
    )
    apply_vk_seeds.add_argument("--dataset", default="data/validation_dataset.yanao_template.json", help="Path to validation dataset JSON")
    apply_vk_seeds.add_argument("--seed-file", default="data/vk_profile_seeds.json", help="Path to VK seed JSON file")
    apply_vk_seeds.add_argument(
        "--mode",
        default="missing_only",
        choices=["missing_only", "all_relevant"],
        help="Apply only missed relevant URLs or all labeled relevant VK URLs",
    )

    review_validation_report = subparsers.add_parser(
        "review-validation-report",
        help="Build prioritized action list from validation report diagnostics",
    )
    review_validation_report.add_argument("--report", default="output/validation_report.json", help="Path to validation report JSON")
    review_validation_report.add_argument("--output", default="output/validation_action_plan.json", help="Path to action plan JSON")

    apply_validation_plan = subparsers.add_parser(
        "apply-validation-action-plan",
        help="Apply seed actions from validation action plan and save draft suggestions for the rest",
    )
    apply_validation_plan.add_argument("--plan", default="output/validation_action_plan.json", help="Path to validation action plan JSON")
    apply_validation_plan.add_argument("--seed-file", default="data/vk_profile_seeds.json", help="Path to VK seed JSON file")
    apply_validation_plan.add_argument("--output", default="output/validation_action_apply.json", help="Path to action apply result JSON")

    draft_alias_patches = subparsers.add_parser(
        "draft-validation-alias-patches",
        help="Build patch-like drafts for service aliases and city aliases from action-apply JSON",
    )
    draft_alias_patches.add_argument("--apply", default="output/validation_action_apply.json", help="Path to validation action apply JSON")
    draft_alias_patches.add_argument("--output", default="output/validation_alias_patch_draft.json", help="Path to alias patch draft JSON")

    apply_alias_patches = subparsers.add_parser(
        "apply-validation-alias-patches",
        help="Merge approved alias patch draft into external rule config JSON",
    )
    apply_alias_patches.add_argument("--draft", default="output/validation_alias_patch_draft.json", help="Path to validation alias patch draft JSON")
    apply_alias_patches.add_argument("--rule-config", default=str(DEFAULT_RULE_CONFIG_PATH), help="Path to marker rule config JSON")
    apply_alias_patches.add_argument("--output", default="output/validation_alias_patch_apply.json", help="Path to alias patch apply JSON")

    compare_validation_case = subparsers.add_parser(
        "compare-validation-case",
        help="Compare one validation case before and after alias-overrides in rule config",
    )
    compare_validation_case.add_argument("--dataset", default="data/validation_dataset.sample.json", help="Path to validation dataset JSON")
    compare_validation_case.add_argument("--case-name", required=True, help="Validation case name to compare")
    compare_validation_case.add_argument("--output", default="output/validation_case_compare.json", help="Path to case comparison JSON")
    compare_validation_case.add_argument(
        "--rule-config",
        default="",
        help="Optional candidate rule config JSON; defaults to active runtime config",
    )
    compare_validation_case.add_argument(
        "--baseline-rule-config",
        default="",
        help="Optional baseline rule config JSON; defaults to current config with alias overrides stripped",
    )
    compare_validation_case.add_argument("--dotenv", default=".env", help="Path to .env file for real collectors")
    compare_validation_case.add_argument("--mock", action="store_true", help="Use MockCollector instead of configured real collectors")

    compare_validation_dataset = subparsers.add_parser(
        "compare-validation-dataset",
        help="Compare validation dataset cases before and after alias-overrides in rule config",
    )
    compare_validation_dataset.add_argument("--dataset", default="data/validation_dataset.sample.json", help="Path to validation dataset JSON")
    compare_validation_dataset.add_argument("--output", default="output/validation_compare_report.json", help="Path to dataset comparison JSON")
    compare_validation_dataset.add_argument(
        "--case-names",
        default="",
        help="Optional comma-separated case names; if empty, compare all dataset cases",
    )
    compare_validation_dataset.add_argument(
        "--rule-config",
        default="",
        help="Optional candidate rule config JSON; defaults to active runtime config",
    )
    compare_validation_dataset.add_argument(
        "--baseline-rule-config",
        default="",
        help="Optional baseline rule config JSON; defaults to current config with alias overrides stripped",
    )
    compare_validation_dataset.add_argument("--dotenv", default=".env", help="Path to .env file for real collectors")
    compare_validation_dataset.add_argument("--mock", action="store_true", help="Use MockCollector instead of configured real collectors")

    review_validation_comparison = subparsers.add_parser(
        "review-validation-comparison",
        help="Build prioritized action list from validation compare report",
    )
    review_validation_comparison.add_argument("--report", default="output/validation_compare_report.json", help="Path to validation compare report JSON")
    review_validation_comparison.add_argument("--output", default="output/validation_compare_action_plan.json", help="Path to comparison action plan JSON")

    draft_validation_comparison_followups = subparsers.add_parser(
        "draft-validation-comparison-followups",
        help="Build seed and draft followups from validation comparison action plan",
    )
    draft_validation_comparison_followups.add_argument("--plan", default="output/validation_compare_action_plan.json", help="Path to validation comparison action plan JSON")
    draft_validation_comparison_followups.add_argument("--output", default="output/validation_compare_followups.json", help="Path to comparison followups JSON")

    apply_validation_comparison_followups = subparsers.add_parser(
        "apply-validation-comparison-followups",
        help="Apply seed followups from validation comparison followups and keep drafts for manual review",
    )
    apply_validation_comparison_followups.add_argument("--followups", default="output/validation_compare_followups.json", help="Path to validation comparison followups JSON")
    apply_validation_comparison_followups.add_argument("--seed-file", default="data/vk_profile_seeds.json", help="Path to VK seed JSON file")
    apply_validation_comparison_followups.add_argument("--output", default="output/validation_compare_followups_apply.json", help="Path to comparison followups apply JSON")

    run_validation_improvement_cycle = subparsers.add_parser(
        "run-validation-improvement-cycle",
        help="Run compare-review-followups-apply cycle and save all intermediate JSON artifacts",
    )
    run_validation_improvement_cycle.add_argument("--dataset", default="data/validation_dataset.sample.json", help="Path to validation dataset JSON")
    run_validation_improvement_cycle.add_argument("--output-prefix", default="output/validation_cycle", help="Output path prefix for cycle artifacts")
    run_validation_improvement_cycle.add_argument("--case-names", default="", help="Optional comma-separated case names; if empty, use all dataset cases")
    run_validation_improvement_cycle.add_argument("--rule-config", default="", help="Optional candidate rule config JSON; defaults to active runtime config")
    run_validation_improvement_cycle.add_argument("--baseline-rule-config", default="", help="Optional baseline rule config JSON; defaults to current config with alias overrides stripped")
    run_validation_improvement_cycle.add_argument("--seed-file", default="data/vk_profile_seeds.json", help="Path to VK seed JSON file")
    run_validation_improvement_cycle.add_argument("--summary-output", default="", help="Optional cycle summary JSON path; defaults to <output-prefix>_summary.json")
    run_validation_improvement_cycle.add_argument("--dotenv", default=".env", help="Path to .env file for real collectors")
    run_validation_improvement_cycle.add_argument("--mock", action="store_true", help="Use MockCollector instead of configured real collectors")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "sample":
        run_sample(args)
    elif args.command == "smoke-matrix":
        run_smoke_matrix(args)
    elif args.command == "review-smoke-matrix":
        run_review_smoke_matrix(args)
    elif args.command == "service-keyword-audit":
        run_service_keyword_audit(args)
    elif args.command == "validate-dataset":
        run_validate_dataset(args)
    elif args.command == "add-validation-case":
        run_add_validation_case(args)
    elif args.command == "bootstrap-validation-dataset":
        run_bootstrap_validation_dataset(args)
    elif args.command == "review-validation-dataset":
        run_review_validation_dataset(args)
    elif args.command == "plan-validation-markup":
        run_plan_validation_markup(args)
    elif args.command == "capture-validation-case":
        run_capture_validation_case(args)
    elif args.command == "recommend-vk-seeds":
        run_recommend_vk_seeds(args)
    elif args.command == "apply-vk-seeds":
        run_apply_vk_seeds(args)
    elif args.command == "review-validation-report":
        run_review_validation_report(args)
    elif args.command == "apply-validation-action-plan":
        run_apply_validation_action_plan(args)
    elif args.command == "draft-validation-alias-patches":
        run_draft_validation_alias_patches(args)
    elif args.command == "apply-validation-alias-patches":
        run_apply_validation_alias_patches(args)
    elif args.command == "compare-validation-case":
        run_compare_validation_case(args)
    elif args.command == "compare-validation-dataset":
        run_compare_validation_dataset(args)
    elif args.command == "review-validation-comparison":
        run_review_validation_comparison(args)
    elif args.command == "draft-validation-comparison-followups":
        run_draft_validation_comparison_followups(args)
    elif args.command == "apply-validation-comparison-followups":
        run_apply_validation_comparison_followups(args)
    elif args.command == "run-validation-improvement-cycle":
        run_validation_improvement_cycle(args)


def run_sample(args: argparse.Namespace) -> None:
    config = RuntimeConfig()
    started_at = datetime.now(UTC)
    services = expand_service_names(_split_csv(args.services), config.popular_services)
    request = SearchRequest(
        cities=_split_csv(args.cities),
        services=[ServiceQuery(name=item, markers=[]) for item in services],
        period_days=args.period_days,
        platforms=_split_csv(args.platforms),
        top_n=args.top_n,
        report_mode=args.report_mode,
    )
    result = run_pipeline(request, collector=MockCollector(), config=config)
    collected_at = datetime.now(UTC)
    artifacts = write_report_artifacts_with_timing(
        result.bundle,
        Path(args.output),
        started_at=started_at,
        collected_at=collected_at,
        report_origin="cli_sample",
    )
    print(f"Saved XLSX report: {artifacts.workbook}")
    if artifacts.pdf is not None:
        print(f"Saved PDF report: {artifacts.pdf}")
    else:
        print(f"PDF report was skipped: {artifacts.pdf_error}")
    print(f"Accounts analysed: {len(result.bundle.ranked_accounts)}")
    print(f"Period: {format_period_label(request.period_days)}")
    print(f"Report mode: {request.report_mode}")
    print("Main sheet all_accounts is simplified for manual review; expanded fields are in account_review, raw metrics in technical_details, rejection reasons in filter_debug.")


def run_smoke_matrix(args: argparse.Namespace) -> None:
    if args.mock:
        config = RuntimeConfig()
        collector = MockCollector()
        platforms = _split_csv(args.platforms) or ["vk"]
        runtime_diagnostics = {
            "mock": True,
            "vk_api_token_configured": False,
            "vk_full_recall": False,
            "vk_profile_search_required": bool(args.require_vk_profile_search),
        }
    else:
        settings = AppSettings.from_env(args.dotenv)
        if args.vk_full_recall:
            settings = replace(settings, vk_full_recall=True)
        explicit_platforms = _split_csv(args.platforms)
        platforms = explicit_platforms or _configured_platforms_from_settings(settings)
        if args.require_vk_profile_search and "vk" in platforms and not settings.vk_api_token:
            raise SystemExit("VK profile search was required, but VK_API_TOKEN is not configured.")
        config = settings.runtime
        collector = ConfiguredCollector(settings)
        runtime_diagnostics = {
            "mock": False,
            "vk_api_token_configured": bool(settings.vk_api_token),
            "vk_service_token_configured": bool(settings.vk_service_token),
            "vk_full_recall": bool(settings.vk_full_recall),
            "vk_profile_search_required": bool(args.require_vk_profile_search),
        }

    cities = _split_csv(args.cities) or list(config.cities)
    services = _smoke_matrix_services(args, config)
    if not cities:
        raise SystemExit("Smoke matrix needs at least one city.")
    if not services:
        raise SystemExit("Smoke matrix needs at least one service.")
    if not platforms:
        raise SystemExit("Smoke matrix needs at least one configured or explicit platform.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else config.output_dir / f"{timestamp}_smoke_matrix.json"
    reports_dir = Path(args.reports_dir) if args.reports_dir else None
    payload = build_smoke_matrix_payload(
        cities=cities,
        services=services,
        platforms=platforms,
        period_days=args.period_days,
        top_n=args.top_n,
        report_mode=args.report_mode,
        collector=collector,
        config=config,
        write_reports=args.write_reports,
        reports_dir=reports_dir,
        checkpoint_path=output_path if args.checkpoint else None,
        case_timeout_seconds=max(args.case_timeout_seconds, 0),
        runtime_diagnostics=runtime_diagnostics,
    )
    write_smoke_matrix_payload(payload, output_path)
    summary = payload["summary"]

    print(f"Saved smoke matrix: {output_path}")
    print(f"Cases: {summary['cases_total']}")
    print(f"Cases with result: {summary['cases_with_result']}")
    print(f"Cases without result: {summary['cases_without_result']}")
    print(f"Platform failures: {summary['platform_failures_total']}")
    print(f"Silent platforms: {summary['silent_platforms_total']}")
    if args.write_reports:
        print(f"Per-case reports: {payload['request']['reports_dir']}")
    if args.require_vk_profile_search and "vk" in platforms and not args.mock:
        profile_failures = _vk_profile_search_failures(payload)
        if profile_failures:
            print(f"VK profile search failures: {len(profile_failures)}")
            for failure in profile_failures[:5]:
                print(f"- {failure['city']} / {failure['service']}: {failure['reason']}")
            raise SystemExit(2)


def run_review_smoke_matrix(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_action_plan.json")
    payload = load_smoke_matrix_payload(input_path)
    action_plan = build_smoke_matrix_action_plan_payload(payload, source_path=input_path)
    write_smoke_matrix_payload(action_plan, output_path)
    summary = action_plan["summary"]

    print(f"Saved smoke action plan: {output_path}")
    print(f"Actions: {summary['actions_total']}")
    print(f"By type: {summary['by_type']}")
    print(f"By priority: {summary['by_priority']}")


def run_service_keyword_audit(args: argparse.Namespace) -> None:
    settings = AppSettings.from_env(args.dotenv)
    config = settings.runtime
    cities = _split_csv(args.cities) or list(config.cities)
    services = _smoke_matrix_services(args, config)
    seed_path = Path(args.seed_file) if args.seed_file else settings.vk_profile_seeds_path
    seed_store = load_vk_profile_seed_store(seed_path)
    telegram_seed_path = (
        Path(args.telegram_seed_file)
        if args.telegram_seed_file
        else settings.telegram_profile_seeds_path
    )
    telegram_seed_store = load_telegram_profile_seed_store(telegram_seed_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else config.output_dir / f"{timestamp}_service_keyword_audit.json"
    payload = build_service_keyword_audit_payload(
        services=services,
        cities=cities,
        config=config,
        vk_seed_store=seed_store,
        telegram_seed_store=telegram_seed_store,
    )
    write_smoke_matrix_payload(payload, output_path)
    summary = payload["summary"]

    print(f"Saved service keyword audit: {output_path}")
    print(f"Services: {summary['services_total']}")
    print(f"Services with VK seeds: {summary['services_with_vk_seeds']}")
    print(f"Services without VK seeds: {summary['services_without_vk_seeds']}")
    print(f"VK seed URLs: {summary['vk_seed_urls_total']}")
    print(f"Services with Telegram seeds: {summary['services_with_telegram_seeds']}")
    print(f"Services without Telegram seeds: {summary['services_without_telegram_seeds']}")
    print(f"Telegram seed URLs: {summary['telegram_seed_urls_total']}")
    print(f"Unknown seed entries: {summary['unknown_seed_entries_total']}")
    print(f"Services with alias overrides: {summary['services_with_alias_overrides']}")
    print(f"Services with discovery overrides: {summary['services_with_discovery_overrides']}")


def run_validate_dataset(args: argparse.Namespace) -> None:
    dataset_path = Path(args.dataset)
    output_path = Path(args.output)
    cases = load_validation_cases(dataset_path)
    if args.mock:
        config = RuntimeConfig()
        collector = MockCollector()
    else:
        settings = AppSettings.from_env(args.dotenv)
        config = settings.runtime
        collector = ConfiguredCollector(settings)

    results, summary = run_validation_cases(cases, collector=collector, config=config)
    payload = validation_report_payload(cases, results, summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    diagnostics_summary = payload["diagnostics"]["summary"]

    print(f"Saved validation report: {output_path}")
    print(f"Cases: {summary.cases_total}")
    print(f"Precision: {summary.precision:.2%}")
    print(f"Strict precision: {summary.strict_precision:.2%}")
    print(f"Recall: {summary.recall:.2%}")
    print(f"True positives: {summary.true_positives}")
    print(f"False positives: {summary.false_positives}")
    print(f"False negatives: {summary.false_negatives}")
    print(f"Unlabeled hits: {summary.unlabeled_hits}")
    print(f"Cases with recall gaps: {diagnostics_summary['cases_with_false_negatives']}")
    print(f"Ready VK seed cases: {diagnostics_summary['ready_seed_cases']}")
    print(f"Ready VK seed URLs: {diagnostics_summary['seed_candidate_urls_total']}")
    if args.strict_unlabeled and summary.unlabeled_hits > 0:
        raise SystemExit("Validation failed: unlabeled hits are present. Label them or rerun without --strict-unlabeled.")


def run_add_validation_case(args: argparse.Namespace) -> None:
    case = ValidationCase(
        name=args.name,
        cities=_split_csv(args.cities),
        services=_split_csv(args.services),
        period_days=args.period_days,
        platforms=_split_csv(args.platforms),
        top_n=args.top_n,
        report_mode=args.report_mode,
        expected_relevant_urls=_split_csv(args.relevant_urls),
        expected_irrelevant_urls=_split_csv(args.irrelevant_urls),
        notes=args.notes,
    )
    cases = append_validation_case(args.dataset, case)
    print(f"Saved validation dataset: {args.dataset}")
    print(f"Cases total: {len(cases)}")
    print(f"Last case: {case.name}")


def run_bootstrap_validation_dataset(args: argparse.Namespace) -> None:
    config = RuntimeConfig()
    output_path = Path(args.output)
    seed_store = load_vk_profile_seed_store(args.seed_file)
    cities = _split_csv(args.cities) or list(config.cities)
    services = expand_service_names(_split_csv(args.services), config.popular_services) if args.services else list(config.popular_services)
    cases, summary = bootstrap_validation_cases(
        output_path=output_path,
        cities=cities,
        services=services,
        seed_store=seed_store,
        platforms=_split_csv(args.platforms),
        period_days=args.period_days,
        top_n=args.top_n,
        report_mode=args.report_mode,
        from_seeds_only=args.from_seeds_only,
        include_empty_cases=args.include_empty_cases,
    )

    print(f"Saved bootstrap validation dataset: {output_path}")
    print(f"Cases total: {summary.cases_total}")
    print(f"Cities total: {summary.cities_total}")
    print(f"Services total: {summary.services_total}")
    print(f"Cases with seed URLs: {summary.cases_with_seed_urls}")
    print(f"Seed URLs total: {summary.seed_urls_total}")
    if cases:
        print(f"First case: {cases[0].name}")


def run_review_validation_dataset(args: argparse.Namespace) -> None:
    dataset_path = Path(args.dataset)
    output_path = Path(args.output)
    cases = load_validation_cases(dataset_path)
    payload = validation_dataset_coverage_payload(cases, dataset_path=dataset_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = payload["summary"]

    print(f"Saved validation dataset coverage: {output_path}")
    print(f"Cases total: {summary['cases_total']}")
    print(f"Cities total: {summary['cities_total']}")
    print(f"Services total: {summary['services_total']}")
    print(f"Cases with relevant URLs: {summary['cases_with_relevant_urls']}")
    print(f"Cases with irrelevant URLs: {summary['cases_with_irrelevant_urls']}")
    print(f"Cases with candidate URLs: {summary['cases_with_candidate_urls']}")
    print(f"Pending markup cases: {summary['pending_markup_cases']}")


def run_plan_validation_markup(args: argparse.Namespace) -> None:
    coverage_path = Path(args.coverage)
    output_path = Path(args.output)
    coverage_payload = load_validation_dataset_coverage(coverage_path)
    batches, summary = build_validation_markup_plan(
        coverage_payload,
        coverage_path=coverage_path,
        group_by=args.group_by,
        batch_size=args.batch_size,
        max_batches=args.max_batches,
    )
    payload = validation_markup_plan_payload(
        coverage_path=coverage_path,
        batches=batches,
        summary=summary,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved validation markup plan: {output_path}")
    print(f"Group by: {summary.group_by}")
    print(f"Batch size: {summary.batch_size}")
    print(f"Pending cases total: {summary.pending_cases_total}")
    print(f"Pending groups total: {summary.pending_groups_total}")
    print(f"Batches total: {summary.batches_total}")
    print(f"Queued cases total: {summary.queued_cases_total}")
    print(f"Remaining cases total: {summary.remaining_cases_total}")


def run_capture_validation_case(args: argparse.Namespace) -> None:
    if args.mock:
        config = RuntimeConfig()
        collector = MockCollector()
    else:
        settings = AppSettings.from_env(args.dotenv)
        config = settings.runtime
        collector = ConfiguredCollector(settings)

    services = expand_service_names(_split_csv(args.services), config.popular_services)
    request = SearchRequest(
        cities=_split_csv(args.cities),
        services=[ServiceQuery(name=item, markers=[]) for item in services],
        period_days=args.period_days,
        platforms=_split_csv(args.platforms),
        top_n=args.top_n,
        report_mode=args.report_mode,
    )
    bundle = run_pipeline(request, collector=collector, config=config).bundle
    candidate_urls = [
        item.candidate.account_url
        for item in bundle.ranked_accounts
    ]
    raw_candidate_urls = [
        candidate.account_url
        for candidate in bundle.raw_candidates
    ]
    case = ValidationCase(
        name=args.name,
        cities=request.cities,
        services=[service.name for service in request.services],
        period_days=request.period_days,
        platforms=request.platforms,
        top_n=request.top_n,
        report_mode=request.report_mode,
        candidate_urls=_unique_preserve_order(candidate_urls),
        raw_candidate_urls=_unique_preserve_order(raw_candidate_urls),
        notes=args.notes or "captured from pipeline",
    )
    cases = append_validation_case(args.dataset, case)
    print(f"Saved validation dataset: {args.dataset}")
    print(f"Cases total: {len(cases)}")
    print(f"Captured ranked URLs: {len(case.candidate_urls)}")
    print(f"Captured raw candidate URLs: {len(case.raw_candidate_urls)}")
    print(f"Last case: {case.name}")


def run_recommend_vk_seeds(args: argparse.Namespace) -> None:
    dataset_path = Path(args.dataset)
    output_path = Path(args.output)
    cases = load_validation_cases(dataset_path)
    entries, skipped, recommendations = recommend_vk_seed_entries(cases, mode=args.mode)
    payload = vk_seed_recommendations_payload(
        dataset_path=dataset_path,
        mode=args.mode,
        entries=entries,
        recommendations=recommendations,
        skipped=skipped,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved VK seed recommendations: {output_path}")
    print(f"Recommendations: {len(recommendations)}")
    print(f"Seed URLs: {sum(len(item.urls) for item in recommendations)}")
    print(f"Skipped cases: {len(skipped)}")


def run_apply_vk_seeds(args: argparse.Namespace) -> None:
    dataset_path = Path(args.dataset)
    seed_path = Path(args.seed_file)
    cases = load_validation_cases(dataset_path)
    entries, skipped, recommendations = recommend_vk_seed_entries(cases, mode=args.mode)
    before_store = load_vk_profile_seed_store(seed_path)
    before_entries = len(before_store.entries)
    before_urls = sum(len(entry.urls) for entry in before_store.entries)
    after_store = merge_vk_profile_seed_entries(seed_path, entries)
    after_entries = len(after_store.entries)
    after_urls = sum(len(entry.urls) for entry in after_store.entries)

    print(f"Updated VK seed file: {seed_path}")
    print(f"Applied recommendations: {len(recommendations)}")
    print(f"Skipped cases: {len(skipped)}")
    print(f"Seed entries total: {after_entries} (was {before_entries})")
    print(f"Seed URLs total: {after_urls} (was {before_urls})")


def run_review_validation_report(args: argparse.Namespace) -> None:
    report_path = Path(args.report)
    output_path = Path(args.output)
    report_payload = load_validation_report(report_path)
    actions, summary = build_validation_action_plan(report_payload, report_path=report_path)
    payload = validation_action_plan_payload(report_path=report_path, actions=actions, summary=summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved validation action plan: {output_path}")
    print(f"Actions total: {summary.actions_total}")
    print(f"Seed actions: {summary.seed_actions}")
    print(f"Aliases actions: {summary.aliases_actions}")
    print(f"City-alias actions: {summary.city_alias_actions}")
    print(f"Manual-review actions: {summary.manual_review_actions}")


def run_apply_validation_action_plan(args: argparse.Namespace) -> None:
    plan_path = Path(args.plan)
    seed_path = Path(args.seed_file)
    output_path = Path(args.output)
    plan_payload = load_validation_action_plan(plan_path)
    seed_entries, drafts, summary = apply_validation_action_plan(plan_payload)
    before_store = load_vk_profile_seed_store(seed_path)
    before_entries = len(before_store.entries)
    before_urls = sum(len(entry.urls) for entry in before_store.entries)
    after_store = merge_vk_profile_seed_entries(seed_path, seed_entries)
    after_entries = len(after_store.entries)
    after_urls = sum(len(entry.urls) for entry in after_store.entries)
    payload = validation_action_apply_payload(
        action_plan_path=plan_path,
        seed_file=seed_path,
        seed_entries=seed_entries,
        drafts=drafts,
        summary=summary,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved validation action apply result: {output_path}")
    print(f"Applied seed entries: {summary.seed_entries_applied}")
    print(f"Applied seed URLs: {summary.seed_urls_applied}")
    print(f"Alias drafts: {summary.alias_drafts_total}")
    print(f"City-alias drafts: {summary.city_alias_drafts_total}")
    print(f"Manual-review drafts: {summary.manual_review_drafts_total}")
    print(f"Seed entries total: {after_entries} (was {before_entries})")
    print(f"Seed URLs total: {after_urls} (was {before_urls})")


def run_draft_validation_alias_patches(args: argparse.Namespace) -> None:
    apply_path = Path(args.apply)
    output_path = Path(args.output)
    apply_payload = load_validation_action_apply(apply_path)
    service_patches, city_patches, manual_review, summary = build_alias_patch_draft(
        apply_payload,
        action_apply_path=apply_path,
    )
    payload = validation_alias_patch_payload(
        action_apply_path=apply_path,
        service_patches=service_patches,
        city_patches=city_patches,
        manual_review=manual_review,
        summary=summary,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved validation alias patch draft: {output_path}")
    print(f"Service alias patches: {summary.service_alias_patches_total}")
    print(f"City alias patches: {summary.city_alias_patches_total}")
    print(f"Manual-review carryover: {summary.manual_review_cases_total}")


def run_apply_validation_alias_patches(args: argparse.Namespace) -> None:
    draft_path = Path(args.draft)
    rule_config_path = Path(args.rule_config)
    output_path = Path(args.output)
    draft_payload = load_validation_alias_patch_draft(draft_path)
    service_alias_overrides, service_hint_overrides, city_alias_overrides, summary = build_rule_config_alias_overrides(
        draft_payload,
        draft_path=draft_path,
    )
    merged_config = merge_rule_config_alias_overrides(
        rule_config_path,
        service_alias_overrides=service_alias_overrides,
        service_discovery_hint_overrides=service_hint_overrides,
        city_alias_overrides=city_alias_overrides,
    )
    payload = validation_alias_patch_apply_payload(
        draft_path=draft_path,
        rule_config_path=rule_config_path,
        service_alias_overrides=service_alias_overrides,
        service_hint_overrides=service_hint_overrides,
        city_alias_overrides=city_alias_overrides,
        summary=summary,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Updated rule config: {rule_config_path}")
    print(f"Saved alias patch apply result: {output_path}")
    print(f"Service alias services: {summary.service_alias_services_total}")
    print(f"Service alias values: {summary.service_alias_values_total}")
    print(f"Service hint services: {summary.service_hint_services_total}")
    print(f"Service hint values: {summary.service_hint_values_total}")
    print(f"City alias cities: {summary.city_alias_cities_total}")
    print(f"City alias values: {summary.city_alias_values_total}")
    print(f"Rule config alias override services: {len(merged_config.service_alias_overrides)}")
    print(f"Rule config city override cities: {len(merged_config.city_alias_overrides)}")


def run_compare_validation_case(args: argparse.Namespace) -> None:
    dataset_path = Path(args.dataset)
    output_path = Path(args.output)
    cases = load_validation_cases(dataset_path)
    case = find_validation_case(cases, args.case_name)
    candidate_rule_config_path = Path(args.rule_config) if args.rule_config else None
    baseline_rule_config_path = Path(args.baseline_rule_config) if args.baseline_rule_config else None

    if args.mock:
        candidate_rule_config = load_rule_config(candidate_rule_config_path or DEFAULT_RULE_CONFIG_PATH)
        candidate_config = RuntimeConfig(
            rule_config_path=candidate_rule_config_path or DEFAULT_RULE_CONFIG_PATH,
            rule_config=candidate_rule_config,
        )
        if baseline_rule_config_path is not None:
            baseline_config = RuntimeConfig(
                rule_config_path=baseline_rule_config_path,
                rule_config=load_rule_config(baseline_rule_config_path),
            )
            baseline_label = "baseline_rule_config"
        else:
            baseline_config = replace(
                candidate_config,
                rule_config=strip_rule_config_alias_overrides(candidate_rule_config),
            )
            baseline_label = "baseline_without_alias_overrides"
        candidate_collector = MockCollector()
        baseline_collector = MockCollector()
    else:
        settings = AppSettings.from_env(args.dotenv)
        candidate_runtime = settings.runtime
        if candidate_rule_config_path is not None:
            candidate_runtime = replace(
                settings.runtime,
                rule_config_path=candidate_rule_config_path,
                rule_config=load_rule_config(candidate_rule_config_path),
            )
        if baseline_rule_config_path is not None:
            baseline_runtime = replace(
                settings.runtime,
                rule_config_path=baseline_rule_config_path,
                rule_config=load_rule_config(baseline_rule_config_path),
            )
            baseline_label = "baseline_rule_config"
        else:
            baseline_runtime = replace(
                candidate_runtime,
                rule_config=strip_rule_config_alias_overrides(candidate_runtime.rule_config),
            )
            baseline_label = "baseline_without_alias_overrides"
        candidate_collector = ConfiguredCollector(replace(settings, runtime=candidate_runtime))
        baseline_collector = ConfiguredCollector(replace(settings, runtime=baseline_runtime))
        candidate_config = candidate_runtime
        baseline_config = baseline_runtime

    comparison = compare_validation_case(
        case,
        baseline_collector=baseline_collector,
        baseline_config=baseline_config,
        candidate_collector=candidate_collector,
        candidate_config=candidate_config,
        baseline_label=baseline_label,
        candidate_label="candidate_rule_config",
    )
    payload = validation_case_comparison_payload(
        dataset_path=dataset_path,
        case=case,
        comparison=comparison,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved validation case comparison: {output_path}")
    print(f"Case: {comparison.case_name}")
    print(f"Baseline recall: {comparison.baseline_result.recall:.2%}")
    print(f"Candidate recall: {comparison.candidate_result.recall:.2%}")
    print(f"Recall delta: {comparison.recall_delta:+.2%}")
    print(f"Baseline precision: {comparison.baseline_result.precision:.2%}")
    print(f"Candidate precision: {comparison.candidate_result.precision:.2%}")
    print(f"Precision delta: {comparison.precision_delta:+.2%}")
    print(f"URLs added: {len(comparison.urls_added)}")
    print(f"URLs removed: {len(comparison.urls_removed)}")
    print(f"Improved: {'yes' if comparison.improved else 'no'}")


def run_compare_validation_dataset(args: argparse.Namespace) -> None:
    dataset_path = Path(args.dataset)
    output_path = Path(args.output)
    cases = load_validation_cases(dataset_path)
    selected_case_names = _split_csv(args.case_names)
    if selected_case_names:
        selected_cases = [find_validation_case(cases, case_name) for case_name in selected_case_names]
    else:
        selected_cases = cases
    candidate_rule_config_path = Path(args.rule_config) if args.rule_config else None
    baseline_rule_config_path = Path(args.baseline_rule_config) if args.baseline_rule_config else None

    if args.mock:
        candidate_rule_config = load_rule_config(candidate_rule_config_path or DEFAULT_RULE_CONFIG_PATH)
        candidate_config = RuntimeConfig(
            rule_config_path=candidate_rule_config_path or DEFAULT_RULE_CONFIG_PATH,
            rule_config=candidate_rule_config,
        )
        if baseline_rule_config_path is not None:
            baseline_config = RuntimeConfig(
                rule_config_path=baseline_rule_config_path,
                rule_config=load_rule_config(baseline_rule_config_path),
            )
            baseline_label = "baseline_rule_config"
        else:
            baseline_config = replace(
                candidate_config,
                rule_config=strip_rule_config_alias_overrides(candidate_rule_config),
            )
            baseline_label = "baseline_without_alias_overrides"
        candidate_collector = MockCollector()
        baseline_collector = MockCollector()
    else:
        settings = AppSettings.from_env(args.dotenv)
        candidate_runtime = settings.runtime
        if candidate_rule_config_path is not None:
            candidate_runtime = replace(
                settings.runtime,
                rule_config_path=candidate_rule_config_path,
                rule_config=load_rule_config(candidate_rule_config_path),
            )
        if baseline_rule_config_path is not None:
            baseline_runtime = replace(
                settings.runtime,
                rule_config_path=baseline_rule_config_path,
                rule_config=load_rule_config(baseline_rule_config_path),
            )
            baseline_label = "baseline_rule_config"
        else:
            baseline_runtime = replace(
                candidate_runtime,
                rule_config=strip_rule_config_alias_overrides(candidate_runtime.rule_config),
            )
            baseline_label = "baseline_without_alias_overrides"
        candidate_collector = ConfiguredCollector(replace(settings, runtime=candidate_runtime))
        baseline_collector = ConfiguredCollector(replace(settings, runtime=baseline_runtime))
        candidate_config = candidate_runtime
        baseline_config = baseline_runtime

    comparisons, summary = compare_validation_cases(
        selected_cases,
        baseline_collector=baseline_collector,
        baseline_config=baseline_config,
        candidate_collector=candidate_collector,
        candidate_config=candidate_config,
        baseline_label=baseline_label,
        candidate_label="candidate_rule_config",
    )
    payload = validation_comparison_report_payload(
        dataset_path=dataset_path,
        comparisons=comparisons,
        summary=summary,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved validation dataset comparison: {output_path}")
    print(f"Cases compared: {summary.cases_total}")
    print(f"Improved cases: {summary.improved_cases}")
    print(f"Unchanged cases: {summary.unchanged_cases}")
    print(f"Regressed cases: {summary.regressed_cases}")
    print(f"Recall delta total: {summary.recall_delta_total:+.2f}")
    print(f"Precision delta total: {summary.precision_delta_total:+.2f}")
    print(f"URLs added total: {summary.urls_added_total}")
    print(f"URLs removed total: {summary.urls_removed_total}")


def run_review_validation_comparison(args: argparse.Namespace) -> None:
    report_path = Path(args.report)
    output_path = Path(args.output)
    report_payload = load_validation_comparison_report(report_path)
    actions, summary = build_validation_comparison_action_plan(report_payload, report_path=report_path)
    payload = validation_comparison_action_plan_payload(
        report_path=report_path,
        actions=actions,
        summary=summary,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved validation comparison action plan: {output_path}")
    print(f"Actions total: {summary.actions_total}")
    print(f"Regressions: {summary.regressions_total}")
    print(f"Followup gaps: {summary.followup_gap_total}")
    print(f"Accepted improvements: {summary.accepted_improvements_total}")


def run_draft_validation_comparison_followups(args: argparse.Namespace) -> None:
    plan_path = Path(args.plan)
    output_path = Path(args.output)
    plan_payload = load_validation_comparison_action_plan(plan_path)
    seed_entries, drafts, summary = draft_validation_comparison_followups(plan_payload)
    payload = validation_comparison_followup_payload(
        action_plan_path=plan_path,
        seed_entries=seed_entries,
        drafts=drafts,
        summary=summary,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved validation comparison followups: {output_path}")
    print(f"Seed entries: {summary.seed_entries_total}")
    print(f"Seed URLs: {summary.seed_urls_total}")
    print(f"Alias drafts: {summary.alias_drafts_total}")
    print(f"City-alias drafts: {summary.city_alias_drafts_total}")
    print(f"Manual-review drafts: {summary.manual_review_drafts_total}")


def run_apply_validation_comparison_followups(args: argparse.Namespace) -> None:
    followup_path = Path(args.followups)
    seed_path = Path(args.seed_file)
    output_path = Path(args.output)
    followup_payload = load_validation_comparison_followups(followup_path)
    seed_entries, drafts, summary = apply_validation_comparison_followups(followup_payload)
    before_store = load_vk_profile_seed_store(seed_path)
    before_entries = len(before_store.entries)
    before_urls = sum(len(entry.urls) for entry in before_store.entries)
    after_store = merge_vk_profile_seed_entries(seed_path, seed_entries)
    after_entries = len(after_store.entries)
    after_urls = sum(len(entry.urls) for entry in after_store.entries)
    payload = validation_comparison_followup_apply_payload(
        followup_path=followup_path,
        seed_file=seed_path,
        seed_entries=seed_entries,
        drafts=drafts,
        summary=summary,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved validation comparison followups apply result: {output_path}")
    print(f"Applied seed entries: {summary.seed_entries_applied}")
    print(f"Applied seed URLs: {summary.seed_urls_applied}")
    print(f"Alias drafts: {summary.alias_drafts_total}")
    print(f"City-alias drafts: {summary.city_alias_drafts_total}")
    print(f"Manual-review drafts: {summary.manual_review_drafts_total}")
    print(f"Seed entries total: {after_entries} (was {before_entries})")
    print(f"Seed URLs total: {after_urls} (was {before_urls})")


def run_validation_improvement_cycle(args: argparse.Namespace) -> None:
    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    summary_path = Path(args.summary_output) if args.summary_output else output_prefix.with_name(f"{output_prefix.name}_summary.json")

    compare_args = argparse.Namespace(
        dataset=args.dataset,
        output=str(output_prefix.with_name(f"{output_prefix.name}_compare_report.json")),
        case_names=args.case_names,
        rule_config=args.rule_config,
        baseline_rule_config=args.baseline_rule_config,
        dotenv=args.dotenv,
        mock=args.mock,
    )
    run_compare_validation_dataset(compare_args)

    review_args = argparse.Namespace(
        report=compare_args.output,
        output=str(output_prefix.with_name(f"{output_prefix.name}_compare_action_plan.json")),
    )
    run_review_validation_comparison(review_args)

    draft_args = argparse.Namespace(
        plan=review_args.output,
        output=str(output_prefix.with_name(f"{output_prefix.name}_compare_followups.json")),
    )
    run_draft_validation_comparison_followups(draft_args)

    apply_args = argparse.Namespace(
        followups=draft_args.output,
        seed_file=args.seed_file,
        output=str(output_prefix.with_name(f"{output_prefix.name}_compare_followups_apply.json")),
    )
    run_apply_validation_comparison_followups(apply_args)

    compare_payload = load_validation_comparison_report(compare_args.output)
    action_payload = load_validation_comparison_action_plan(review_args.output)
    followup_apply_payload = load_validation_comparison_followups(apply_args.output)
    compare_summary = compare_payload.get("summary", {})
    action_summary = action_payload.get("summary", {})
    apply_summary = followup_apply_payload.get("summary", {})
    summary_payload = {
        "dataset": args.dataset,
        "output_prefix": str(output_prefix),
        "summary_output": str(summary_path),
        "artifacts": {
            "compare_report": compare_args.output,
            "compare_action_plan": review_args.output,
            "compare_followups": draft_args.output,
            "compare_followups_apply": apply_args.output,
        },
        "compare_summary": compare_summary,
        "action_summary": action_summary,
        "apply_summary": apply_summary,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Completed validation improvement cycle: {output_prefix}")
    print(f"Compare cases: {compare_summary.get('cases_total', 0)}")
    print(f"Improved cases: {compare_summary.get('improved_cases', 0)}")
    print(f"Regressions: {action_summary.get('regressions_total', 0)}")
    print(f"Followup gaps: {action_summary.get('followup_gap_total', 0)}")
    print(f"Applied seed entries: {apply_summary.get('seed_entries_applied', 0)}")
    print(f"Manual-review drafts: {apply_summary.get('manual_review_drafts_total', 0)}")
    print(f"Saved cycle summary: {summary_path}")


def _smoke_matrix_services(args: argparse.Namespace, config: RuntimeConfig) -> list[str]:
    if args.category and args.services:
        raise SystemExit("Use either --category or --services for smoke-matrix, not both.")
    if args.category:
        section = service_selection_section_by_token(config.popular_services, normalize_slug(args.category))
        if section is None:
            raise SystemExit(f"Unknown service category: {args.category}")
        return list(section[1])
    if args.services:
        return expand_service_names(_split_csv(args.services), config.popular_services)
    return list(config.popular_services)


def _vk_profile_search_failures(payload: dict[str, object]) -> list[dict[str, str]]:
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        return []
    failures: list[dict[str, str]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        platforms = case.get("platforms", [])
        if isinstance(platforms, list) and "vk" not in platforms:
            continue
        summary = case.get("vk_profile_search", {})
        if not isinstance(summary, dict):
            reason = "missing vk_profile_search diagnostics"
        else:
            fallback_errors = summary.get("fallback_errors", [])
            groups = int(summary.get("groups_search_queries", 0) or 0)
            users = int(summary.get("users_search_queries", 0) or 0)
            attempted = bool(summary.get("attempted"))
            if fallback_errors:
                reason = f"profile search fallback: {fallback_errors[0]}"
            elif not attempted or (groups + users) == 0:
                reason = "no vk.groups.search/users.search attempts recorded"
            else:
                continue
        failures.append(
            {
                "city": str(case.get("city", "")),
                "service": str(case.get("service", "")),
                "reason": reason,
            }
        )
    return failures


def _configured_platforms_from_settings(settings: AppSettings) -> list[str]:
    platforms: list[str] = []
    if settings.vk_api_token or settings.vk_service_token or settings.use_mock_data:
        platforms.append("vk")
    if settings.telegram_mtproto_ready:
        platforms.append("telegram")
    if settings.google_places_ready:
        platforms.append("places")
    if settings.twogis_ready:
        platforms.append("2gis")
    return platforms


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


if __name__ == "__main__":
    main()
