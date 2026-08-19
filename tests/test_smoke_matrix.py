from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from godmod.cli import build_parser, run_review_smoke_matrix, run_service_keyword_audit, _vk_profile_search_failures
from godmod.collectors.mock import MockCollector
from godmod.config import RuntimeConfig
from godmod.models import SearchRequest
from godmod.rule_config import RuleConfig
from godmod.smoke_matrix import (
    build_service_keyword_audit_payload,
    build_smoke_matrix_action_plan_payload,
    build_smoke_matrix_payload,
    write_smoke_matrix_payload,
)
from godmod.telegram_profile_seeds import TelegramProfileSeedEntry, TelegramProfileSeedStore
from godmod.vk_profile_seeds import VkProfileSeedEntry, VkProfileSeedStore


class EmptyCollector:
    def collect(self, request: SearchRequest):
        return [], []


class FailingCollector:
    def collect(self, request: SearchRequest):  # pragma: no cover - should not be called
        raise AssertionError("checkpointed cases should not be collected again")


class CountingEmptyCollector:
    def __init__(self) -> None:
        self.requests: list[SearchRequest] = []

    def collect(self, request: SearchRequest):
        self.requests.append(request)
        return [], []


class SlowCollector:
    def collect(self, request: SearchRequest):
        time.sleep(2)
        return [], []


class SmokeMatrixTests(unittest.TestCase):
    def test_build_smoke_matrix_payload_records_city_service_results(self) -> None:
        payload = build_smoke_matrix_payload(
            cities=["Салехард"],
            services=["маникюр", "ремонт"],
            platforms=["vk"],
            period_days=30,
            top_n=10,
            report_mode="all",
            collector=MockCollector(),
            config=RuntimeConfig(),
        )

        self.assertEqual(payload["summary"]["cases_total"], 2)
        self.assertEqual(payload["summary"]["cases_with_result"], 2)
        self.assertEqual(payload["summary"]["cases_without_result"], 0)
        self.assertEqual(payload["summary"]["statuses"], {"ok": 2})
        self.assertEqual(payload["cases"][0]["city"], "Салехард")
        self.assertEqual(payload["cases"][0]["service"], "маникюр")
        self.assertGreater(payload["cases"][0]["counts"]["ranked_accounts"], 0)
        self.assertTrue(payload["cases"][0]["top_urls"][0].startswith("https://vk.com/"))
        self.assertTrue(payload["cases"][0]["raw_urls"][0].startswith("https://vk.com/"))
        self.assertTrue(payload["cases"][0]["filter_reasons"])
        self.assertEqual(payload["cases"][0]["search_sources"], {"mock": 1})
        self.assertEqual(payload["cases"][0]["discovery_modes"], {"mock_data": 1})
        self.assertEqual(
            payload["cases"][0]["vk_profile_search"],
            {
                "attempted": False,
                "groups_search_queries": 0,
                "users_search_queries": 0,
                "fallback_errors": [],
            },
        )

    def test_parser_accepts_vk_profile_smoke_flags(self) -> None:
        args = build_parser().parse_args(
            [
                "smoke-matrix",
                "--platforms",
                "vk",
                "--vk-full-recall",
                "--require-vk-profile-search",
            ]
        )

        self.assertTrue(args.vk_full_recall)
        self.assertTrue(args.require_vk_profile_search)

    def test_vk_profile_search_failures_detects_fallback_errors(self) -> None:
        payload = {
            "cases": [
                {
                    "city": "Надым",
                    "service": "барбершоп",
                    "platforms": ["vk"],
                    "vk_profile_search": {
                        "attempted": True,
                        "groups_search_queries": 1,
                        "users_search_queries": 0,
                        "fallback_errors": ["User authorization failed"],
                    },
                },
                {
                    "city": "Салехард",
                    "service": "маникюр",
                    "platforms": ["vk"],
                    "vk_profile_search": {
                        "attempted": True,
                        "groups_search_queries": 2,
                        "users_search_queries": 2,
                        "fallback_errors": [],
                    },
                },
            ]
        }

        failures = _vk_profile_search_failures(payload)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["city"], "Надым")
        self.assertIn("fallback", failures[0]["reason"])

    def test_vk_profile_search_failures_detects_missing_profile_attempts(self) -> None:
        payload = {
            "cases": [
                {
                    "city": "Надым",
                    "service": "барбершоп",
                    "platforms": ["vk"],
                    "vk_profile_search": {
                        "attempted": False,
                        "groups_search_queries": 0,
                        "users_search_queries": 0,
                        "fallback_errors": [],
                    },
                }
            ]
        }

        failures = _vk_profile_search_failures(payload)

        self.assertEqual(len(failures), 1)
        self.assertIn("no vk.groups.search/users.search", failures[0]["reason"])

    def test_build_smoke_matrix_payload_records_runtime_diagnostics(self) -> None:
        payload = build_smoke_matrix_payload(
            cities=["Салехард"],
            services=["маникюр"],
            platforms=["vk"],
            period_days=30,
            top_n=10,
            report_mode="all",
            collector=MockCollector(),
            config=RuntimeConfig(),
            runtime_diagnostics={"vk_api_token_configured": True, "vk_full_recall": True},
        )

        self.assertEqual(
            payload["request"]["runtime_diagnostics"],
            {"vk_api_token_configured": True, "vk_full_recall": True},
        )

    def test_build_smoke_matrix_payload_records_empty_cases(self) -> None:
        payload = build_smoke_matrix_payload(
            cities=["Салехард"],
            services=["маникюр"],
            platforms=["vk"],
            period_days=30,
            top_n=10,
            report_mode="all",
            collector=EmptyCollector(),
            config=RuntimeConfig(),
        )

        self.assertEqual(payload["summary"]["cases_with_result"], 0)
        self.assertEqual(payload["summary"]["cases_without_result"], 1)
        self.assertEqual(payload["summary"]["empty_cases"][0]["status"], "empty_with_warnings")
        self.assertEqual(payload["cases"][0]["silent_platforms"], ["vk"])

    def test_write_smoke_matrix_payload_saves_json(self) -> None:
        payload = {
            "summary": {"cases_total": 1},
            "cases": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "smoke.json"

            saved = write_smoke_matrix_payload(payload, path)

            self.assertEqual(saved, path)
            self.assertIn('"cases_total": 1', path.read_text(encoding="utf-8"))

    def test_build_smoke_matrix_payload_marks_case_timeout_as_failed(self) -> None:
        payload = build_smoke_matrix_payload(
            cities=["Салехард"],
            services=["кафе"],
            platforms=["vk"],
            period_days=30,
            top_n=2,
            report_mode="all",
            collector=SlowCollector(),
            config=RuntimeConfig(),
            case_timeout_seconds=1,
        )

        self.assertEqual(payload["summary"]["statuses"], {"failed": 1})
        self.assertIn("case timed out after 1 seconds", payload["cases"][0]["error"])
        self.assertEqual(payload["request"]["case_timeout_seconds"], 1)

    def test_build_smoke_matrix_payload_checkpoints_and_resumes_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "smoke_checkpoint.json"

            first_payload = build_smoke_matrix_payload(
                cities=["Салехард"],
                services=["маникюр", "ремонт"],
                platforms=["vk"],
                period_days=30,
                top_n=2,
                report_mode="all",
                collector=MockCollector(),
                config=RuntimeConfig(),
                checkpoint_path=checkpoint_path,
            )

            self.assertTrue(checkpoint_path.exists())
            checkpoint_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint_payload["checkpoint"]["completed_cases"], 2)
            self.assertTrue(checkpoint_payload["checkpoint"]["is_complete"])

            resumed_payload = build_smoke_matrix_payload(
                cities=["Салехард"],
                services=["маникюр", "ремонт"],
                platforms=["vk"],
                period_days=30,
                top_n=2,
                report_mode="all",
                collector=FailingCollector(),
                config=RuntimeConfig(),
                checkpoint_path=checkpoint_path,
            )

            self.assertEqual(first_payload["summary"]["cases_total"], 2)
            self.assertEqual(resumed_payload["summary"]["cases_total"], 2)
            self.assertEqual(resumed_payload["checkpoint"]["completed_cases"], 2)

    def test_build_smoke_matrix_payload_resumes_missing_cases_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "smoke_checkpoint.json"

            build_smoke_matrix_payload(
                cities=["Салехард"],
                services=["маникюр"],
                platforms=["vk"],
                period_days=30,
                top_n=2,
                report_mode="all",
                collector=MockCollector(),
                config=RuntimeConfig(),
                checkpoint_path=checkpoint_path,
            )

            collector = CountingEmptyCollector()
            resumed_payload = build_smoke_matrix_payload(
                cities=["Салехард"],
                services=["маникюр", "ремонт"],
                platforms=["vk"],
                period_days=30,
                top_n=2,
                report_mode="all",
                collector=collector,
                config=RuntimeConfig(),
                checkpoint_path=checkpoint_path,
            )

            self.assertEqual(len(collector.requests), 1)
            self.assertEqual(collector.requests[0].services[0].name, "ремонт")
            self.assertEqual(resumed_payload["checkpoint"]["completed_cases"], 2)

    def test_build_smoke_matrix_payload_ignores_incompatible_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "smoke_checkpoint.json"

            build_smoke_matrix_payload(
                cities=["Салехард"],
                services=["маникюр", "ремонт"],
                platforms=["vk"],
                period_days=30,
                top_n=2,
                report_mode="all",
                collector=MockCollector(),
                config=RuntimeConfig(),
                checkpoint_path=checkpoint_path,
            )

            collector = CountingEmptyCollector()
            resumed_payload = build_smoke_matrix_payload(
                cities=["Салехард"],
                services=["маникюр", "ремонт"],
                platforms=["vk"],
                period_days=30,
                top_n=3,
                report_mode="all",
                collector=collector,
                config=RuntimeConfig(),
                checkpoint_path=checkpoint_path,
            )

            self.assertEqual(len(collector.requests), 2)
            self.assertEqual(resumed_payload["request"]["top_n"], 3)
            self.assertEqual(resumed_payload["checkpoint"]["completed_cases"], 2)

    def test_build_smoke_matrix_action_plan_classifies_empty_raw_case(self) -> None:
        payload = {
            "request": {"platforms": ["vk"]},
            "cases": [
                {
                    "city": "Салехард",
                    "service": "барбершоп",
                    "status": "empty",
                    "counts": {"ranked_accounts": 0, "raw_candidates": 0},
                    "platform_failures": [],
                    "silent_platforms": [],
                    "filter_reasons": [],
                    "raw_urls": [],
                    "top_urls": [],
                    "search_queries": ["барбершоп Салехард"],
                }
            ],
        }

        plan = build_smoke_matrix_action_plan_payload(payload)

        self.assertEqual(plan["summary"]["actions_total"], 1)
        self.assertEqual(plan["actions"][0]["action_type"], "seed-or-discovery-needed")
        self.assertEqual(plan["actions"][0]["priority"], "high")

    def test_build_smoke_matrix_action_plan_classifies_service_filter_case(self) -> None:
        payload = {
            "cases": [
                {
                    "city": "Салехард",
                    "service": "ресницы",
                    "status": "empty",
                    "counts": {"ranked_accounts": 0, "raw_candidates": 2},
                    "platform_failures": [],
                    "silent_platforms": [],
                    "filter_reasons": [
                        {
                            "decision_stage": "service_filter",
                            "reason": "Услуга не заявлена в названии, username или описании профиля.",
                            "count": 2,
                        }
                    ],
                    "raw_urls": ["https://vk.com/example"],
                    "top_urls": [],
                    "search_queries": ["ресницы Салехард"],
                }
            ],
        }

        plan = build_smoke_matrix_action_plan_payload(payload)

        self.assertEqual(plan["actions"][0]["action_type"], "service-alias-needed")

    def test_build_service_keyword_audit_payload_reports_terms_and_seed_coverage(self) -> None:
        config = RuntimeConfig(
            popular_services=["маникюр", "барбершоп"],
            rule_config=RuleConfig(
                service_alias_overrides={"барбершоп": ["barber"]},
                service_discovery_hint_overrides={"барбершоп": ["мужская стрижка"]},
            ),
        )
        seed_store = VkProfileSeedStore(
            [
                VkProfileSeedEntry(
                    city="Салехард",
                    service="барбершоп",
                    urls=["https://vk.com/oldboy.salekhard"],
                )
            ]
        )
        telegram_seed_store = TelegramProfileSeedStore(
            [
                TelegramProfileSeedEntry(
                    city="Салехард",
                    service="барбершоп",
                    urls=["https://t.me/oldboy_salekhard"],
                ),
                TelegramProfileSeedEntry(
                    city="Салехард",
                    service="Забегаев",
                    urls=["https://t.me/example_unknown"],
                ),
            ]
        )

        payload = build_service_keyword_audit_payload(
            services=["барбершоп"],
            cities=["Салехард", "Ноябрьск"],
            config=config,
            vk_seed_store=seed_store,
            telegram_seed_store=telegram_seed_store,
        )

        row = payload["services"][0]
        self.assertEqual(payload["summary"]["services_total"], 1)
        self.assertIn("barber", row["profile_terms"])
        self.assertIn("мужская стрижка", row["discovery_hints"])
        self.assertEqual(row["vk_seed_counts_by_city"]["Салехард"], 1)
        self.assertEqual(row["vk_seed_missing_cities"], ["Ноябрьск"])
        self.assertEqual(row["telegram_seed_counts_by_city"]["Салехард"], 1)
        self.assertEqual(row["telegram_seed_missing_cities"], ["Ноябрьск"])
        self.assertEqual(payload["summary"]["unknown_telegram_seed_entries_total"], 1)
        self.assertEqual(payload["unknown_seed_entries"][0]["service"], "Забегаев")

    def test_review_smoke_matrix_cli_writes_action_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            smoke_path = Path(temp_dir) / "smoke.json"
            output_path = Path(temp_dir) / "plan.json"
            smoke_path.write_text(
                '{"cases":[{"city":"Салехард","service":"барбершоп","counts":{"ranked_accounts":0,"raw_candidates":0},"platform_failures":[],"silent_platforms":[]}]}',
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "review-smoke-matrix",
                    "--input",
                    str(smoke_path),
                    "--output",
                    str(output_path),
                ]
            )

            run_review_smoke_matrix(args)

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["actions"][0]["action_type"], "seed-or-discovery-needed")

    def test_service_keyword_audit_cli_writes_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            rule_config = temp_path / "marker_rules.json"
            seed_file = temp_path / "vk_profile_seeds.json"
            telegram_seed_file = temp_path / "telegram_profile_seeds.json"
            dotenv = temp_path / ".env"
            output_path = temp_path / "audit.json"
            rule_config.write_text(
                '{"service_alias_overrides":{"барбершоп":["barber"]},"service_discovery_hint_overrides":{},"city_alias_overrides":{}}',
                encoding="utf-8",
            )
            seed_file.write_text('{"entries":[]}', encoding="utf-8")
            telegram_seed_file.write_text(
                '{"entries":[{"city":"Салехард","service":"Забегаев","urls":["https://t.me/example_unknown"]}]}',
                encoding="utf-8",
            )
            dotenv.write_text(
                "\n".join(
                    [
                        f"GODMOD_RULE_CONFIG_PATH={rule_config}",
                        f"GODMOD_VK_PROFILE_SEEDS_PATH={seed_file}",
                        f"GODMOD_TELEGRAM_PROFILE_SEEDS_PATH={telegram_seed_file}",
                        f"GODMOD_OUTPUT_DIR={temp_path}",
                    ]
                ),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(
                [
                    "service-keyword-audit",
                    "--dotenv",
                    str(dotenv),
                    "--services",
                    "барбершоп",
                    "--cities",
                    "Салехард",
                    "--output",
                    str(output_path),
                ]
            )

            run_service_keyword_audit(args)

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["services_total"], 1)
            self.assertIn("barber", payload["services"][0]["profile_terms"])
            self.assertEqual(payload["summary"]["unknown_seed_entries_total"], 1)


if __name__ == "__main__":
    unittest.main()
