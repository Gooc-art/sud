from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from godmod.cli import (
    build_parser,
    run_add_validation_case,
    run_bootstrap_validation_dataset,
    run_plan_validation_markup,
    run_review_validation_dataset,
    run_apply_validation_alias_patches,
    run_apply_validation_comparison_followups,
    run_apply_vk_seeds,
    run_apply_validation_action_plan,
    run_compare_validation_case,
    run_compare_validation_dataset,
    run_draft_validation_comparison_followups,
    run_review_validation_comparison,
    run_validation_improvement_cycle,
    run_capture_validation_case,
    run_draft_validation_alias_patches,
    run_recommend_vk_seeds,
    run_review_validation_report,
    run_validate_dataset,
)
from godmod.collectors.mock import MockCollector
from godmod.config import RuntimeConfig
from godmod.models import AccountCandidate, PostRecord, SearchLogEntry, SearchRequest
from godmod.rule_config import RuleConfig
from godmod.vk_profile_seeds import VkProfileSeedEntry, VkProfileSeedStore
from godmod.validation import (
    apply_validation_action_plan,
    apply_validation_comparison_followups,
    append_validation_case,
    bootstrap_validation_cases,
    build_rule_config_alias_overrides,
    build_alias_patch_draft,
    build_validation_comparison_action_plan,
    draft_validation_comparison_followups,
    compare_validation_cases,
    build_validation_action_plan,
    build_validation_markup_plan,
    build_validation_diagnostics,
    compare_validation_case,
    find_validation_case,
    ValidationCase,
    load_validation_action_apply,
    load_validation_action_plan,
    load_validation_alias_patch_draft,
    load_validation_comparison_report,
    load_validation_comparison_action_plan,
    load_validation_comparison_followups,
    load_validation_cases,
    load_validation_report,
    recommend_vk_seed_entries,
    run_validation_cases,
    strip_rule_config_alias_overrides,
    validation_dataset_coverage_payload,
    validation_markup_plan_payload,
)


class AliasSensitiveCollector:
    platform_name = "vk"

    def collect(self, request: SearchRequest) -> tuple[list[AccountCandidate], list[SearchLogEntry]]:
        now = datetime.now(UTC)
        candidates: list[AccountCandidate] = []
        search_log: list[SearchLogEntry] = []
        for service in request.services:
            for city in request.cities:
                search_log.append(
                    SearchLogEntry(
                        city=city,
                        service=service.name,
                        platform="vk",
                        query=f"{service.name} {city}",
                        source="alias-sensitive",
                        discovery_mode="test",
                    )
                )
                candidates.append(
                    AccountCandidate(
                        service=service.name,
                        city=city,
                        platform="vk",
                        account_name="Nail Room SHD",
                        account_url="https://vk.com/nail_room_shd",
                        username_or_id="nail_room_shd",
                        description="Nail room SHD. Прайс, цена, запись в сообщения.",
                        followers=120,
                        posts=[
                            PostRecord(
                                url="https://vk.com/nail_room_shd?w=wall-1_1",
                                text="Свободные окна, цена 2000 руб, запись в лс.",
                                published_at=now - timedelta(days=3),
                                likes=8,
                                comments=1,
                                reposts=0,
                            ),
                            PostRecord(
                                url="https://vk.com/nail_room_shd?w=wall-1_2",
                                text="Прайс на услуги и запись в сообщения.",
                                published_at=now - timedelta(days=11),
                                likes=6,
                                comments=0,
                                reposts=0,
                            ),
                        ],
                        search_queries=[f"{service.name} {city}"],
                        discovery_sources=["alias-sensitive"],
                        discovery_modes=["test"],
                    )
                )
        return candidates, search_log


class ValidationTests(unittest.TestCase):
    def test_load_validation_cases_reads_json_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "dataset.json"
            dataset.write_text(
                json.dumps(
                    [
                        {
                            "name": "case-1",
                            "cities": ["Салехард"],
                            "services": ["маникюр"],
                            "period_days": 60,
                            "platforms": ["vk"],
                            "expected_relevant_urls": ["https://vk.com/test"],
                            "expected_irrelevant_urls": ["https://vk.com/noise"],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            cases = load_validation_cases(dataset)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].name, "case-1")
        self.assertEqual(cases[0].cities, ["Салехард"])

    def test_run_validation_cases_calculates_precision_and_recall(self) -> None:
        cases = load_validation_cases("data/validation_dataset.sample.json")

        results, summary = run_validation_cases(cases, collector=MockCollector(), config=RuntimeConfig())

        self.assertEqual(len(results), 2)
        self.assertEqual(summary.cases_total, 2)
        self.assertEqual(summary.false_positives, 0)
        self.assertEqual(summary.false_negatives, 0)
        self.assertGreaterEqual(summary.precision, 1.0)
        self.assertGreaterEqual(summary.recall, 1.0)

    def test_validate_dataset_cli_supports_mock_mode(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "validate-dataset",
                "--dataset",
                "data/validation_dataset.sample.json",
                "--output",
                "output/test_validation_report.json",
                "--mock",
            ]
        )

        run_validate_dataset(args)

        payload = json.loads(Path("output/test_validation_report.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["cases_total"], 2)
        self.assertIn("precision", payload["summary"])
        self.assertIn("strict_precision", payload["summary"])
        self.assertIn("diagnostics", payload)
        self.assertEqual(payload["diagnostics"]["summary"]["cases_total"], 2)

    def test_append_validation_case_persists_new_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "dataset.json"
            append_validation_case(
                dataset,
                load_validation_cases("data/validation_dataset.sample.json")[0],
            )
            cases = load_validation_cases(dataset)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].name, "mock_vk_manicure_salehard")

    def test_add_validation_case_cli_appends_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "manual_dataset.json"
            parser = build_parser()
            args = parser.parse_args(
                [
                    "add-validation-case",
                    "--dataset",
                    str(dataset),
                    "--name",
                    "manual-case",
                    "--cities",
                    "Салехард",
                    "--services",
                    "маникюр",
                    "--platforms",
                    "vk",
                    "--relevant-urls",
                    "https://vk.com/studio1",
                    "--irrelevant-urls",
                    "https://vk.com/noise1",
                    "--notes",
                    "ручная разметка",
                ]
            )

            run_add_validation_case(args)
            payload = json.loads(dataset.read_text(encoding="utf-8"))

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["name"], "manual-case")
        self.assertEqual(payload[0]["expected_relevant_urls"], ["https://vk.com/studio1"])
        self.assertEqual(payload[0]["expected_irrelevant_urls"], ["https://vk.com/noise1"])

    def test_bootstrap_validation_cases_builds_cases_from_seed_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "bootstrap_dataset.json"
            seed_store = VkProfileSeedStore(
                [
                    VkProfileSeedEntry(
                        city="Салехард",
                        service="маникюр",
                        urls=["https://vk.com/loft_shd"],
                    )
                ]
            )

            cases, summary = bootstrap_validation_cases(
                output_path=output,
                cities=["Салехард", "Новый Уренгой"],
                services=["маникюр", "массаж"],
                seed_store=seed_store,
                from_seeds_only=False,
                include_empty_cases=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(summary.cases_total, 4)
        self.assertEqual(summary.cases_with_seed_urls, 1)
        self.assertEqual(summary.seed_urls_total, 1)
        self.assertEqual(cases[0].name, "bootstrap_салехард_маникюр")
        self.assertEqual(payload[0]["expected_relevant_urls"], ["https://vk.com/loft_shd"])

    def test_bootstrap_validation_dataset_cli_supports_seed_only_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "bootstrap_dataset.json"
            seed_file = Path(temp_dir) / "vk_profile_seeds.json"
            seed_file.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "city": "Салехард",
                                "service": "маникюр",
                                "urls": ["https://vk.com/loft_shd"],
                            },
                            {
                                "city": "Новый Уренгой",
                                "service": "маникюр",
                                "urls": ["https://vk.com/salon_tvoy"],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "bootstrap-validation-dataset",
                    "--output",
                    str(output),
                    "--seed-file",
                    str(seed_file),
                    "--from-seeds-only",
                ]
            )

            run_bootstrap_validation_dataset(args)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["expected_relevant_urls"], ["https://vk.com/loft_shd"])
        self.assertEqual(payload[1]["expected_relevant_urls"], ["https://vk.com/salon_tvoy"])

    def test_validation_dataset_coverage_payload_counts_pending_cases(self) -> None:
        cases = [
            ValidationCase(
                name="covered-case",
                cities=["Салехард"],
                services=["маникюр"],
                period_days=60,
                platforms=["vk"],
                expected_relevant_urls=["https://vk.com/loft_shd"],
            ),
            ValidationCase(
                name="pending-case",
                cities=["Новый Уренгой"],
                services=["ремонт"],
                period_days=60,
                platforms=["vk"],
            ),
        ]

        payload = validation_dataset_coverage_payload(cases, dataset_path="data/validation_dataset.yanao_template.json")

        self.assertEqual(payload["summary"]["cases_total"], 2)
        self.assertEqual(payload["summary"]["cases_with_relevant_urls"], 1)
        self.assertEqual(payload["summary"]["pending_markup_cases"], 1)
        self.assertEqual(payload["by_city"][0]["city"], "Новый Уренгой")
        self.assertEqual(payload["pending_cases"][0]["name"], "pending-case")

    def test_review_validation_dataset_cli_writes_coverage_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "dataset.json"
            output = Path(temp_dir) / "coverage.json"
            dataset.write_text(
                json.dumps(
                    [
                        {
                            "name": "covered-case",
                            "cities": ["Салехард"],
                            "services": ["маникюр"],
                            "period_days": 60,
                            "platforms": ["vk"],
                            "expected_relevant_urls": ["https://vk.com/loft_shd"],
                        },
                        {
                            "name": "pending-case",
                            "cities": ["Новый Уренгой"],
                            "services": ["ремонт"],
                            "period_days": 60,
                            "platforms": ["vk"],
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "review-validation-dataset",
                    "--dataset",
                    str(dataset),
                    "--output",
                    str(output),
                ]
            )

            run_review_validation_dataset(args)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["summary"]["cases_total"], 2)
        self.assertEqual(payload["summary"]["pending_markup_cases"], 1)
        self.assertEqual(payload["pending_cases"][0]["name"], "pending-case")

    def test_build_validation_markup_plan_groups_pending_cases_by_city(self) -> None:
        coverage_payload = {
            "pending_cases": [
                {
                    "name": "pending-nur-1",
                    "cities": ["Новый Уренгой"],
                    "services": ["маникюр"],
                    "platforms": ["vk"],
                    "notes": "",
                },
                {
                    "name": "pending-nur-2",
                    "cities": ["Новый Уренгой"],
                    "services": ["массаж"],
                    "platforms": ["vk"],
                    "notes": "",
                },
                {
                    "name": "pending-salehard-1",
                    "cities": ["Салехард"],
                    "services": ["маникюр"],
                    "platforms": ["vk"],
                    "notes": "",
                },
            ]
        }

        batches, summary = build_validation_markup_plan(
            coverage_payload,
            coverage_path="output/validation_dataset_coverage.json",
            group_by="city",
            batch_size=1,
        )
        payload = validation_markup_plan_payload(
            coverage_path="output/validation_dataset_coverage.json",
            batches=batches,
            summary=summary,
        )

        self.assertEqual(summary.pending_cases_total, 3)
        self.assertEqual(summary.pending_groups_total, 2)
        self.assertEqual(summary.batches_total, 3)
        self.assertEqual(payload["batches"][0]["group_key"], "Новый Уренгой")
        self.assertEqual(payload["batches"][0]["cases_total"], 1)
        self.assertEqual(payload["batches"][0]["priority"], 2)

    def test_plan_validation_markup_cli_writes_markup_plan_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            coverage = Path(temp_dir) / "coverage.json"
            output = Path(temp_dir) / "markup_plan.json"
            coverage.write_text(
                json.dumps(
                    {
                        "pending_cases": [
                            {
                                "name": "pending-case-1",
                                "cities": ["Ноябрьск"],
                                "services": ["ремонт"],
                                "platforms": ["vk"],
                                "notes": "",
                            },
                            {
                                "name": "pending-case-2",
                                "cities": ["Ноябрьск"],
                                "services": ["фотограф"],
                                "platforms": ["vk"],
                                "notes": "",
                            },
                            {
                                "name": "pending-case-3",
                                "cities": ["Надым"],
                                "services": ["ремонт"],
                                "platforms": ["vk"],
                                "notes": "",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "plan-validation-markup",
                    "--coverage",
                    str(coverage),
                    "--output",
                    str(output),
                    "--group-by",
                    "city",
                    "--batch-size",
                    "2",
                    "--max-batches",
                    "1",
                ]
            )

            run_plan_validation_markup(args)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["summary"]["group_by"], "city")
        self.assertEqual(payload["summary"]["batch_size"], 2)
        self.assertEqual(payload["summary"]["pending_cases_total"], 3)
        self.assertEqual(payload["summary"]["batches_total"], 1)
        self.assertEqual(payload["summary"]["queued_cases_total"], 2)
        self.assertEqual(payload["summary"]["remaining_cases_total"], 1)
        self.assertEqual(payload["batches"][0]["group_key"], "Ноябрьск")

    def test_capture_validation_case_cli_collects_ranked_and_raw_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "captured_dataset.json"
            parser = build_parser()
            args = parser.parse_args(
                [
                    "capture-validation-case",
                    "--dataset",
                    str(dataset),
                    "--name",
                    "captured-case",
                    "--cities",
                    "Салехард",
                    "--services",
                    "маникюр",
                    "--platforms",
                    "vk",
                    "--mock",
                ]
            )

            run_capture_validation_case(args)
            payload = json.loads(dataset.read_text(encoding="utf-8"))

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["name"], "captured-case")
        self.assertTrue(payload[0]["candidate_urls"])
        self.assertTrue(payload[0]["raw_candidate_urls"])

    def test_recommend_vk_seed_entries_returns_only_missing_relevant_urls(self) -> None:
        cases = [
            load_validation_cases("data/validation_dataset.sample.json")[0],
            load_validation_cases("data/validation_dataset.sample.json")[1],
        ]
        cases[0].candidate_urls = ["https://vk.com/mock_salekhard_nails"]
        cases[0].expected_relevant_urls = [
            "https://vk.com/mock_salekhard_nails",
            "https://vk.com/missed_salekhard_nails",
        ]

        entries, skipped, recommendations = recommend_vk_seed_entries(cases, mode="missing_only")

        self.assertEqual(len(entries), 2)
        manicure_entry = next(entry for entry in entries if entry.service == "маникюр")
        self.assertEqual(manicure_entry.urls, ["https://vk.com/missed_salekhard_nails"])
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(recommendations), 2)

    def test_build_validation_diagnostics_marks_seed_candidates_for_false_negatives(self) -> None:
        case = load_validation_cases("data/validation_dataset.sample.json")[0]
        case.candidate_urls = ["https://vk.com/маникюр-салехард"]
        case.expected_relevant_urls = [
            "https://vk.com/маникюр-салехард",
            "https://vk.com/missed_salekhard_nails",
        ]
        results, _summary = run_validation_cases([case], collector=MockCollector(), config=RuntimeConfig())

        diagnostics, diagnostics_summary = build_validation_diagnostics([case], results)

        self.assertEqual(diagnostics_summary.cases_with_false_negatives, 1)
        self.assertEqual(diagnostics_summary.ready_seed_cases, 1)
        self.assertEqual(diagnostics_summary.seed_candidate_urls_total, 1)
        self.assertEqual(diagnostics[0].seed_candidate_status, "ready")
        self.assertEqual(diagnostics[0].seed_candidate_urls, ["https://vk.com/missed_salekhard_nails"])

    def test_recommend_vk_seeds_cli_writes_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "dataset.json"
            output = Path(temp_dir) / "recommendations.json"
            dataset.write_text(
                json.dumps(
                    [
                        {
                            "name": "seed-case",
                            "cities": ["Салехард"],
                            "services": ["маникюр"],
                            "period_days": 60,
                            "platforms": ["vk"],
                            "expected_relevant_urls": ["https://vk.com/loft_shd"],
                            "candidate_urls": [],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "recommend-vk-seeds",
                    "--dataset",
                    str(dataset),
                    "--output",
                    str(output),
                ]
            )

            run_recommend_vk_seeds(args)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["stats"]["recommendations_total"], 1)
        self.assertEqual(payload["recommendations"][0]["urls"], ["https://vk.com/loft_shd"])

    def test_apply_vk_seeds_cli_merges_recommendations_into_seed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "dataset.json"
            seed_file = Path(temp_dir) / "vk_profile_seeds.json"
            dataset.write_text(
                json.dumps(
                    [
                        {
                            "name": "seed-case",
                            "cities": ["Новый Уренгой"],
                            "services": ["маникюр"],
                            "period_days": 90,
                            "platforms": ["vk"],
                            "expected_relevant_urls": ["https://vk.com/salon_tvoy"],
                            "candidate_urls": [],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            seed_file.write_text(json.dumps({"entries": []}, ensure_ascii=False), encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(
                [
                    "apply-vk-seeds",
                    "--dataset",
                    str(dataset),
                    "--seed-file",
                    str(seed_file),
                ]
            )

            run_apply_vk_seeds(args)
            payload = json.loads(seed_file.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(payload["entries"][0]["city"], "Новый Уренгой")
        self.assertEqual(payload["entries"][0]["service"], "маникюр")
        self.assertEqual(payload["entries"][0]["urls"], ["https://vk.com/salon_tvoy"])

    def test_build_validation_action_plan_classifies_cases(self) -> None:
        report_payload = {
            "diagnostics": {
                "cases": [
                    {
                        "case_name": "seed-case",
                        "cities": ["Салехард"],
                        "services": ["маникюр"],
                        "platforms": ["vk"],
                        "false_negatives": ["https://vk.com/missed-seed"],
                        "false_positives": [],
                        "unlabeled_hits": [],
                        "seed_candidate_urls": ["https://vk.com/missed-seed"],
                        "raw_candidate_urls": [],
                        "actual_urls": [],
                    },
                    {
                        "case_name": "aliases-case",
                        "cities": ["Салехард"],
                        "services": ["массаж"],
                        "platforms": ["vk"],
                        "false_negatives": ["https://vk.com/missed-alias"],
                        "false_positives": [],
                        "unlabeled_hits": [],
                        "seed_candidate_urls": [],
                        "raw_candidate_urls": [],
                        "actual_urls": [],
                    },
                    {
                        "case_name": "city-case",
                        "cities": ["Новый Уренгой"],
                        "services": ["маникюр"],
                        "platforms": ["vk"],
                        "false_negatives": ["https://vk.com/missed-city"],
                        "false_positives": [],
                        "unlabeled_hits": [],
                        "seed_candidate_urls": [],
                        "raw_candidate_urls": ["https://vk.com/raw-city"],
                        "actual_urls": [],
                    },
                    {
                        "case_name": "manual-case",
                        "cities": ["Салехард"],
                        "services": ["маникюр"],
                        "platforms": ["vk"],
                        "false_negatives": [],
                        "false_positives": [],
                        "unlabeled_hits": ["https://vk.com/unlabeled"],
                        "seed_candidate_urls": [],
                        "raw_candidate_urls": [],
                        "actual_urls": ["https://vk.com/unlabeled"],
                    },
                ]
            }
        }

        actions, summary = build_validation_action_plan(report_payload, report_path="output/validation_report.json")

        self.assertEqual(summary.actions_total, 4)
        self.assertEqual(summary.seed_actions, 1)
        self.assertEqual(summary.aliases_actions, 1)
        self.assertEqual(summary.city_alias_actions, 1)
        self.assertEqual(summary.manual_review_actions, 1)
        self.assertEqual(actions[0].action_type, "seed")
        self.assertEqual({item.case_name: item.action_type for item in actions}, {
            "seed-case": "seed",
            "aliases-case": "aliases",
            "city-case": "city-alias",
            "manual-case": "manual-review",
        })

    def test_review_validation_report_cli_writes_action_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "validation_report.json"
            output = Path(temp_dir) / "validation_action_plan.json"
            report.write_text(
                json.dumps(
                    {
                        "diagnostics": {
                            "cases": [
                                {
                                    "case_name": "seed-case",
                                    "cities": ["Салехард"],
                                    "services": ["маникюр"],
                                    "platforms": ["vk"],
                                    "false_negatives": ["https://vk.com/missed-seed"],
                                    "false_positives": [],
                                    "unlabeled_hits": [],
                                    "seed_candidate_urls": ["https://vk.com/missed-seed"],
                                    "raw_candidate_urls": [],
                                    "actual_urls": [],
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "review-validation-report",
                    "--report",
                    str(report),
                    "--output",
                    str(output),
                ]
            )

            run_review_validation_report(args)
            payload = json.loads(output.read_text(encoding="utf-8"))
            loaded_report = load_validation_report(report)

        self.assertEqual(payload["summary"]["actions_total"], 1)
        self.assertEqual(payload["actions"][0]["action_type"], "seed")
        self.assertIn("diagnostics", loaded_report)

    def test_apply_validation_action_plan_splits_seed_entries_and_drafts(self) -> None:
        plan_payload = {
            "report_path": "output/validation_report.json",
            "actions": [
                {
                    "case_name": "seed-case",
                    "action_type": "seed",
                    "cities": ["Салехард"],
                    "services": ["маникюр"],
                    "platforms": ["vk"],
                    "urls": ["https://vk.com/missed-seed"],
                    "rationale": "seed rationale",
                },
                {
                    "case_name": "aliases-case",
                    "action_type": "aliases",
                    "cities": ["Салехард"],
                    "services": ["массаж"],
                    "platforms": ["vk"],
                    "urls": ["https://vk.com/missed-alias"],
                    "rationale": "aliases rationale",
                },
                {
                    "case_name": "city-case",
                    "action_type": "city-alias",
                    "cities": ["Новый Уренгой"],
                    "services": ["маникюр"],
                    "platforms": ["vk"],
                    "urls": ["https://vk.com/missed-city"],
                    "rationale": "city rationale",
                },
            ],
        }

        seed_entries, drafts, summary = apply_validation_action_plan(plan_payload)

        self.assertEqual(summary.seed_entries_applied, 1)
        self.assertEqual(summary.seed_urls_applied, 1)
        self.assertEqual(summary.alias_drafts_total, 1)
        self.assertEqual(summary.city_alias_drafts_total, 1)
        self.assertEqual(len(seed_entries), 1)
        self.assertEqual(seed_entries[0].city, "Салехард")
        self.assertEqual(seed_entries[0].service, "маникюр")
        self.assertEqual(len(drafts), 2)
        self.assertEqual({draft.suggestion_type for draft in drafts}, {"aliases", "city-alias"})

    def test_apply_validation_action_plan_cli_updates_seed_file_and_writes_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = Path(temp_dir) / "validation_action_plan.json"
            seed_file = Path(temp_dir) / "vk_profile_seeds.json"
            output = Path(temp_dir) / "validation_action_apply.json"
            plan.write_text(
                json.dumps(
                    {
                        "report_path": "output/validation_report.json",
                        "actions": [
                            {
                                "case_name": "seed-case",
                                "action_type": "seed",
                                "cities": ["Салехард"],
                                "services": ["маникюр"],
                                "platforms": ["vk"],
                                "urls": ["https://vk.com/missed-seed"],
                                "rationale": "seed rationale",
                            },
                            {
                                "case_name": "aliases-case",
                                "action_type": "aliases",
                                "cities": ["Салехард"],
                                "services": ["массаж"],
                                "platforms": ["vk"],
                                "urls": ["https://vk.com/missed-alias"],
                                "rationale": "aliases rationale",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            seed_file.write_text(json.dumps({"entries": []}, ensure_ascii=False), encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(
                [
                    "apply-validation-action-plan",
                    "--plan",
                    str(plan),
                    "--seed-file",
                    str(seed_file),
                    "--output",
                    str(output),
                ]
            )

            run_apply_validation_action_plan(args)
            payload = json.loads(output.read_text(encoding="utf-8"))
            stored_seeds = json.loads(seed_file.read_text(encoding="utf-8"))
            loaded_plan = load_validation_action_plan(plan)

        self.assertEqual(payload["summary"]["seed_entries_applied"], 1)
        self.assertEqual(len(payload["drafts"]), 1)
        self.assertEqual(payload["drafts"][0]["suggestion_type"], "aliases")
        self.assertEqual(stored_seeds["entries"][0]["urls"], ["https://vk.com/missed-seed"])
        self.assertIn("actions", loaded_plan)

    def test_build_alias_patch_draft_returns_service_and_city_suggestions(self) -> None:
        apply_payload = {
            "drafts": [
                {
                    "suggestion_type": "aliases",
                    "key": "массаж",
                    "cases": ["aliases-case"],
                    "cities": ["Салехард"],
                    "services": ["массаж"],
                    "urls": ["https://vk.com/massage_salehard_pro"],
                    "rationale": "aliases rationale",
                },
                {
                    "suggestion_type": "city-alias",
                    "key": "Новый Уренгой",
                    "cases": ["city-case"],
                    "cities": ["Новый Уренгой"],
                    "services": ["маникюр"],
                    "urls": ["https://vk.com/city_case"],
                    "rationale": "city rationale",
                },
            ]
        }

        service_patches, city_patches, manual_review, summary = build_alias_patch_draft(
            apply_payload,
            action_apply_path="output/validation_action_apply.json",
        )

        self.assertEqual(summary.service_alias_patches_total, 1)
        self.assertEqual(summary.city_alias_patches_total, 1)
        self.assertEqual(summary.manual_review_cases_total, 0)
        self.assertEqual(service_patches[0].service, "массаж")
        self.assertIn("мастер массаж", service_patches[0].suggested_discovery_hints)
        self.assertEqual(city_patches[0].city, "Новый Уренгой")
        self.assertTrue(city_patches[0].suggested_aliases)
        self.assertEqual(manual_review, [])

    def test_draft_validation_alias_patches_cli_writes_patch_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            apply_path = Path(temp_dir) / "validation_action_apply.json"
            output = Path(temp_dir) / "validation_alias_patch_draft.json"
            apply_path.write_text(
                json.dumps(
                    {
                        "drafts": [
                            {
                                "suggestion_type": "aliases",
                                "key": "массаж",
                                "cases": ["aliases-case"],
                                "cities": ["Салехард"],
                                "services": ["массаж"],
                                "urls": ["https://vk.com/massage_salehard_pro"],
                                "rationale": "aliases rationale",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "draft-validation-alias-patches",
                    "--apply",
                    str(apply_path),
                    "--output",
                    str(output),
                ]
            )

            run_draft_validation_alias_patches(args)
            payload = json.loads(output.read_text(encoding="utf-8"))
            loaded_apply = load_validation_action_apply(apply_path)

        self.assertEqual(payload["summary"]["service_alias_patches_total"], 1)
        self.assertEqual(payload["service_alias_patches"][0]["service"], "массаж")
        self.assertIn("drafts", loaded_apply)

    def test_build_rule_config_alias_overrides_extracts_values_from_draft(self) -> None:
        draft_payload = {
            "service_alias_patches": [
                {
                    "service": "массаж",
                    "suggested_aliases": ["massage_salehard_pro"],
                    "suggested_discovery_hints": ["мастер массаж"],
                }
            ],
            "city_alias_patches": [
                {
                    "city": "Салехард",
                    "suggested_aliases": ["shd"],
                }
            ],
        }

        service_aliases, service_hints, city_aliases, summary = build_rule_config_alias_overrides(
            draft_payload,
            draft_path="output/validation_alias_patch_draft.json",
        )

        self.assertEqual(service_aliases, {"массаж": ["massage_salehard_pro"]})
        self.assertEqual(service_hints, {"массаж": ["мастер массаж"]})
        self.assertEqual(city_aliases, {"Салехард": ["shd"]})
        self.assertEqual(summary.service_alias_services_total, 1)
        self.assertEqual(summary.city_alias_cities_total, 1)

    def test_apply_validation_alias_patches_cli_updates_rule_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            draft = Path(temp_dir) / "validation_alias_patch_draft.json"
            rule_config = Path(temp_dir) / "marker_rules.json"
            output = Path(temp_dir) / "validation_alias_patch_apply.json"
            draft.write_text(
                json.dumps(
                    {
                        "service_alias_patches": [
                            {
                                "service": "массаж",
                                "suggested_aliases": ["massage_salehard_pro"],
                                "suggested_discovery_hints": ["мастер массаж"],
                            }
                        ],
                        "city_alias_patches": [
                            {
                                "city": "Салехард",
                                "suggested_aliases": ["shd"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            rule_config.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(
                [
                    "apply-validation-alias-patches",
                    "--draft",
                    str(draft),
                    "--rule-config",
                    str(rule_config),
                    "--output",
                    str(output),
                ]
            )

            run_apply_validation_alias_patches(args)
            payload = json.loads(output.read_text(encoding="utf-8"))
            updated_rules = json.loads(rule_config.read_text(encoding="utf-8"))
            loaded_draft = load_validation_alias_patch_draft(draft)

        self.assertEqual(payload["summary"]["service_alias_services_total"], 1)
        self.assertEqual(updated_rules["service_alias_overrides"]["массаж"], ["massage_salehard_pro"])
        self.assertEqual(updated_rules["service_discovery_hint_overrides"]["массаж"], ["мастер массаж"])
        self.assertEqual(updated_rules["city_alias_overrides"]["Салехард"], ["shd"])
        self.assertIn("service_alias_patches", loaded_draft)

    def test_compare_validation_case_detects_recall_gain_from_alias_overrides(self) -> None:
        case = find_validation_case(load_validation_cases("data/validation_dataset.sample.json"), "mock_vk_manicure_salehard")
        case.expected_relevant_urls = ["https://vk.com/nail_room_shd"]
        baseline_config = RuntimeConfig(rule_config=RuleConfig())
        candidate_rule_config = RuleConfig(
            service_alias_overrides={"маникюр": ["nail room"]},
            city_alias_overrides={"Салехард": ["shd"]},
        )
        candidate_config = RuntimeConfig(rule_config_path=Path("data/marker_rules.json"), rule_config=candidate_rule_config)

        comparison = compare_validation_case(
            case,
            baseline_collector=AliasSensitiveCollector(),
            baseline_config=baseline_config,
            candidate_collector=AliasSensitiveCollector(),
            candidate_config=candidate_config,
        )

        self.assertEqual(comparison.baseline_result.recall, 0.0)
        self.assertEqual(comparison.candidate_result.recall, 1.0)
        self.assertTrue(comparison.improved)
        self.assertEqual(comparison.urls_added, ["https://vk.com/nail_room_shd"])
        stripped = strip_rule_config_alias_overrides(candidate_rule_config)
        self.assertEqual(stripped.service_alias_overrides, {})
        self.assertEqual(stripped.city_alias_overrides, {})

    def test_compare_validation_case_cli_writes_case_delta_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "dataset.json"
            output = Path(temp_dir) / "validation_case_compare.json"
            rule_config = Path(temp_dir) / "marker_rules.json"
            dataset.write_text(
                json.dumps(
                    [
                        {
                            "name": "alias-case",
                            "cities": ["Салехард"],
                            "services": ["маникюр"],
                            "period_days": 60,
                            "platforms": ["vk"],
                            "expected_relevant_urls": ["https://vk.com/nail_room_shd"],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            rule_config.write_text(
                json.dumps(
                    {
                        "service_alias_overrides": {"маникюр": ["nail room"]},
                        "city_alias_overrides": {"Салехард": ["shd"]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "compare-validation-case",
                    "--dataset",
                    str(dataset),
                    "--case-name",
                    "alias-case",
                    "--rule-config",
                    str(rule_config),
                    "--output",
                    str(output),
                    "--mock",
                ]
            )

            with patch("godmod.cli.MockCollector", AliasSensitiveCollector):
                run_compare_validation_case(args)

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["summary"]["case_name"], "alias-case")
        self.assertTrue(payload["summary"]["improved"])
        self.assertEqual(payload["summary"]["recall_delta"], 1.0)
        self.assertEqual(payload["summary"]["urls_added"], ["https://vk.com/nail_room_shd"])

    def test_compare_validation_cases_builds_summary(self) -> None:
        cases = [
            find_validation_case(load_validation_cases("data/validation_dataset.sample.json"), "mock_vk_manicure_salehard"),
            find_validation_case(load_validation_cases("data/validation_dataset.sample.json"), "mock_vk_repair_salehard"),
        ]
        cases[0].expected_relevant_urls = ["https://vk.com/nail_room_shd"]
        cases[1].expected_relevant_urls = ["https://vk.com/remont-salehard"]
        baseline_config = RuntimeConfig(rule_config=RuleConfig())
        candidate_config = RuntimeConfig(
            rule_config=RuleConfig(
                service_alias_overrides={"маникюр": ["nail room"]},
                city_alias_overrides={"Салехард": ["shd"]},
            )
        )

        comparisons, summary = compare_validation_cases(
            cases,
            baseline_collector=AliasSensitiveCollector(),
            baseline_config=baseline_config,
            candidate_collector=AliasSensitiveCollector(),
            candidate_config=candidate_config,
        )

        self.assertEqual(summary.cases_total, 2)
        self.assertEqual(summary.improved_cases, 1)
        self.assertEqual(summary.unchanged_cases, 1)
        self.assertEqual(summary.regressed_cases, 0)
        self.assertEqual(summary.urls_added_total, 1)
        self.assertEqual(comparisons[0].case_name, "mock_vk_manicure_salehard")
        self.assertEqual(comparisons[0].recall_delta, 1.0)

    def test_compare_validation_dataset_cli_writes_summary_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "dataset.json"
            output = Path(temp_dir) / "validation_compare_report.json"
            rule_config = Path(temp_dir) / "marker_rules.json"
            dataset.write_text(
                json.dumps(
                    [
                        {
                            "name": "alias-case",
                            "cities": ["Салехард"],
                            "services": ["маникюр"],
                            "period_days": 60,
                            "platforms": ["vk"],
                            "expected_relevant_urls": ["https://vk.com/nail_room_shd"],
                        },
                        {
                            "name": "control-case",
                            "cities": ["Салехард"],
                            "services": ["ремонт"],
                            "period_days": 60,
                            "platforms": ["vk"],
                            "expected_relevant_urls": ["https://vk.com/remont-salehard"],
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            rule_config.write_text(
                json.dumps(
                    {
                        "service_alias_overrides": {"маникюр": ["nail room"]},
                        "city_alias_overrides": {"Салехард": ["shd"]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "compare-validation-dataset",
                    "--dataset",
                    str(dataset),
                    "--rule-config",
                    str(rule_config),
                    "--output",
                    str(output),
                    "--mock",
                ]
            )

            with patch("godmod.cli.MockCollector", AliasSensitiveCollector):
                run_compare_validation_dataset(args)

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["summary"]["cases_total"], 2)
        self.assertEqual(payload["summary"]["improved_cases"], 1)
        self.assertEqual(payload["summary"]["unchanged_cases"], 1)
        self.assertEqual(payload["summary"]["urls_added_total"], 1)
        self.assertEqual(payload["comparisons"][0]["case_name"], "alias-case")
        self.assertEqual(payload["comparisons"][0]["recall_delta"], 1.0)

    def test_build_validation_comparison_action_plan_classifies_compare_cases(self) -> None:
        report_payload = {
            "comparisons": [
                {
                    "case_name": "regression-case",
                    "recall_delta": -1.0,
                    "precision_delta": 0.0,
                    "urls_added": [],
                    "urls_removed": ["https://vk.com/lost"],
                    "baseline_result": {"recall": 1.0, "precision": 1.0},
                    "candidate_result": {
                        "recall": 0.0,
                        "precision": 1.0,
                        "false_negatives": ["https://vk.com/lost"],
                        "false_positives": [],
                        "unlabeled_hits": [],
                    },
                },
                {
                    "case_name": "gap-case",
                    "recall_delta": 0.0,
                    "precision_delta": 0.0,
                    "urls_added": [],
                    "urls_removed": [],
                    "baseline_result": {"recall": 0.0, "precision": 1.0},
                    "candidate_result": {
                        "recall": 0.0,
                        "precision": 1.0,
                        "false_negatives": ["https://vk.com/missed"],
                        "false_positives": [],
                        "unlabeled_hits": [],
                    },
                },
                {
                    "case_name": "improved-case",
                    "recall_delta": 1.0,
                    "precision_delta": 1.0,
                    "urls_added": ["https://vk.com/found"],
                    "urls_removed": [],
                    "baseline_result": {"recall": 0.0, "precision": 0.0},
                    "candidate_result": {
                        "recall": 1.0,
                        "precision": 1.0,
                        "false_negatives": [],
                        "false_positives": [],
                        "unlabeled_hits": [],
                    },
                },
            ]
        }

        actions, summary = build_validation_comparison_action_plan(
            report_payload,
            report_path="output/validation_compare_report.json",
        )

        self.assertEqual(summary.actions_total, 3)
        self.assertEqual(summary.regressions_total, 1)
        self.assertEqual(summary.followup_gap_total, 1)
        self.assertEqual(summary.accepted_improvements_total, 1)
        self.assertEqual(actions[0].action_type, "regression")
        self.assertEqual({item.case_name: item.action_type for item in actions}, {
            "regression-case": "regression",
            "gap-case": "followup-gap",
            "improved-case": "accepted-improvement",
        })

    def test_review_validation_comparison_cli_writes_action_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "validation_compare_report.json"
            output = Path(temp_dir) / "validation_compare_action_plan.json"
            report.write_text(
                json.dumps(
                    {
                        "comparisons": [
                            {
                                "case_name": "regression-case",
                                "recall_delta": -1.0,
                                "precision_delta": 0.0,
                                "urls_added": [],
                                "urls_removed": ["https://vk.com/lost"],
                                "baseline_result": {"recall": 1.0, "precision": 1.0},
                                "candidate_result": {
                                    "recall": 0.0,
                                    "precision": 1.0,
                                    "false_negatives": ["https://vk.com/lost"],
                                    "false_positives": [],
                                    "unlabeled_hits": [],
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "review-validation-comparison",
                    "--report",
                    str(report),
                    "--output",
                    str(output),
                ]
            )

            run_review_validation_comparison(args)
            payload = json.loads(output.read_text(encoding="utf-8"))
            loaded_report = load_validation_comparison_report(report)

        self.assertEqual(payload["summary"]["actions_total"], 1)
        self.assertEqual(payload["summary"]["regressions_total"], 1)
        self.assertEqual(payload["actions"][0]["action_type"], "regression")
        self.assertIn("comparisons", loaded_report)

    def test_draft_validation_comparison_followups_builds_seeds_and_manual_review(self) -> None:
        plan_payload = {
            "report_path": "output/validation_compare_report.json",
            "actions": [
                {
                    "case_name": "gap-case",
                    "action_type": "followup-gap",
                    "cities": ["Салехард"],
                    "services": ["маникюр"],
                    "platforms": ["vk"],
                    "false_negatives": ["https://vk.com/missed-gap"],
                    "false_positives": [],
                    "unlabeled_hits": [],
                    "urls_added": [],
                    "urls_removed": [],
                },
                {
                    "case_name": "regression-case",
                    "action_type": "regression",
                    "cities": ["Новый Уренгой"],
                    "services": ["маникюр"],
                    "platforms": ["vk"],
                    "false_negatives": ["https://vk.com/lost"],
                    "false_positives": [],
                    "unlabeled_hits": [],
                    "urls_added": [],
                    "urls_removed": ["https://vk.com/lost"],
                },
            ],
        }

        seed_entries, drafts, summary = draft_validation_comparison_followups(plan_payload)

        self.assertEqual(summary.seed_entries_total, 1)
        self.assertEqual(summary.seed_urls_total, 1)
        self.assertEqual(summary.manual_review_drafts_total, 1)
        self.assertEqual(seed_entries[0].city, "Салехард")
        self.assertEqual(seed_entries[0].service, "маникюр")
        self.assertEqual(seed_entries[0].urls, ["https://vk.com/missed-gap"])
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].suggestion_type, "manual-review")
        self.assertEqual(drafts[0].key, "regression-case")

    def test_draft_validation_comparison_followups_cli_writes_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = Path(temp_dir) / "validation_compare_action_plan.json"
            output = Path(temp_dir) / "validation_compare_followups.json"
            plan.write_text(
                json.dumps(
                    {
                        "report_path": "output/validation_compare_report.json",
                        "actions": [
                            {
                                "case_name": "gap-case",
                                "action_type": "followup-gap",
                                "cities": ["Салехард"],
                                "services": ["маникюр"],
                                "platforms": ["vk"],
                                "false_negatives": ["https://vk.com/missed-gap"],
                                "false_positives": [],
                                "unlabeled_hits": [],
                                "urls_added": [],
                                "urls_removed": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "draft-validation-comparison-followups",
                    "--plan",
                    str(plan),
                    "--output",
                    str(output),
                ]
            )

            run_draft_validation_comparison_followups(args)
            payload = json.loads(output.read_text(encoding="utf-8"))
            loaded_plan = load_validation_comparison_action_plan(plan)

        self.assertEqual(payload["summary"]["seed_entries_total"], 1)
        self.assertEqual(payload["seed_entries"][0]["urls"], ["https://vk.com/missed-gap"])
        self.assertEqual(payload["summary"]["manual_review_drafts_total"], 0)
        self.assertIn("actions", loaded_plan)

    def test_apply_validation_comparison_followups_returns_seed_entries_and_drafts(self) -> None:
        followup_payload = {
            "action_plan_path": "output/validation_compare_action_plan.json",
            "seed_entries": [
                {
                    "city": "Салехард",
                    "service": "маникюр",
                    "urls": ["https://vk.com/missed-gap"],
                }
            ],
            "drafts": [
                {
                    "suggestion_type": "manual-review",
                    "key": "regression-case",
                    "cases": ["regression-case"],
                    "cities": ["Новый Уренгой"],
                    "services": ["маникюр"],
                    "urls": ["https://vk.com/lost"],
                    "rationale": "regression rationale",
                }
            ],
        }

        seed_entries, drafts, summary = apply_validation_comparison_followups(followup_payload)

        self.assertEqual(summary.seed_entries_applied, 1)
        self.assertEqual(summary.seed_urls_applied, 1)
        self.assertEqual(summary.manual_review_drafts_total, 1)
        self.assertEqual(seed_entries[0].urls, ["https://vk.com/missed-gap"])
        self.assertEqual(drafts[0].suggestion_type, "manual-review")
        self.assertEqual(drafts[0].key, "regression-case")

    def test_apply_validation_comparison_followups_cli_updates_seed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            followups = Path(temp_dir) / "validation_compare_followups.json"
            seed_file = Path(temp_dir) / "vk_profile_seeds.json"
            output = Path(temp_dir) / "validation_compare_followups_apply.json"
            followups.write_text(
                json.dumps(
                    {
                        "action_plan_path": "output/validation_compare_action_plan.json",
                        "seed_entries": [
                            {
                                "city": "Салехард",
                                "service": "маникюр",
                                "urls": ["https://vk.com/missed-gap"],
                            }
                        ],
                        "drafts": [
                            {
                                "suggestion_type": "manual-review",
                                "key": "regression-case",
                                "cases": ["regression-case"],
                                "cities": ["Новый Уренгой"],
                                "services": ["маникюр"],
                                "urls": ["https://vk.com/lost"],
                                "rationale": "regression rationale",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            seed_file.write_text(json.dumps({"entries": []}, ensure_ascii=False), encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(
                [
                    "apply-validation-comparison-followups",
                    "--followups",
                    str(followups),
                    "--seed-file",
                    str(seed_file),
                    "--output",
                    str(output),
                ]
            )

            run_apply_validation_comparison_followups(args)
            payload = json.loads(output.read_text(encoding="utf-8"))
            stored_seeds = json.loads(seed_file.read_text(encoding="utf-8"))
            loaded_followups = load_validation_comparison_followups(followups)

        self.assertEqual(payload["summary"]["seed_entries_applied"], 1)
        self.assertEqual(payload["summary"]["manual_review_drafts_total"], 1)
        self.assertEqual(payload["drafts"][0]["suggestion_type"], "manual-review")
        self.assertEqual(stored_seeds["entries"][0]["urls"], ["https://vk.com/missed-gap"])
        self.assertIn("seed_entries", loaded_followups)

    def test_run_validation_improvement_cycle_cli_writes_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "dataset.json"
            seed_file = Path(temp_dir) / "vk_profile_seeds.json"
            output_prefix = Path(temp_dir) / "cycle"
            summary_output = Path(temp_dir) / "cycle_summary.json"
            dataset.write_text(
                json.dumps(
                    [
                        {
                            "name": "cycle-case",
                            "cities": ["Салехард"],
                            "services": ["маникюр"],
                            "period_days": 60,
                            "platforms": ["vk"],
                            "expected_relevant_urls": ["https://vk.com/nail_room_shd"],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            seed_file.write_text(json.dumps({"entries": []}, ensure_ascii=False), encoding="utf-8")
            rule_config = Path(temp_dir) / "marker_rules.json"
            rule_config.write_text(
                json.dumps(
                    {
                        "service_alias_overrides": {"маникюр": ["nail room"]},
                        "city_alias_overrides": {"Салехард": ["shd"]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "run-validation-improvement-cycle",
                    "--dataset",
                    str(dataset),
                    "--output-prefix",
                    str(output_prefix),
                    "--summary-output",
                    str(summary_output),
                    "--seed-file",
                    str(seed_file),
                    "--rule-config",
                    str(rule_config),
                    "--mock",
                ]
            )

            with patch("godmod.cli.MockCollector", AliasSensitiveCollector):
                run_validation_improvement_cycle(args)

            compare_report = output_prefix.with_name(f"{output_prefix.name}_compare_report.json")
            action_plan = output_prefix.with_name(f"{output_prefix.name}_compare_action_plan.json")
            followups = output_prefix.with_name(f"{output_prefix.name}_compare_followups.json")
            apply_result = output_prefix.with_name(f"{output_prefix.name}_compare_followups_apply.json")
            cycle_summary = json.loads(summary_output.read_text(encoding="utf-8"))

            compare_payload = json.loads(compare_report.read_text(encoding="utf-8"))
            action_payload = json.loads(action_plan.read_text(encoding="utf-8"))
            followup_payload = json.loads(followups.read_text(encoding="utf-8"))
            apply_payload = json.loads(apply_result.read_text(encoding="utf-8"))

        self.assertEqual(compare_payload["summary"]["cases_total"], 1)
        self.assertEqual(compare_payload["summary"]["improved_cases"], 1)
        self.assertEqual(action_payload["summary"]["accepted_improvements_total"], 1)
        self.assertEqual(followup_payload["summary"]["seed_entries_total"], 0)
        self.assertEqual(apply_payload["summary"]["seed_entries_applied"], 0)
        self.assertEqual(cycle_summary["artifacts"]["compare_report"], str(compare_report))
        self.assertEqual(cycle_summary["compare_summary"]["improved_cases"], 1)
        self.assertEqual(cycle_summary["action_summary"]["accepted_improvements_total"], 1)


if __name__ == "__main__":
    unittest.main()
