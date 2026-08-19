from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from godmod.operator_reports import build_daily_report_payload, build_health_payload, find_latest_report_snapshot, format_daily_report_summary


class OperatorReportsTests(unittest.TestCase):
    def test_find_latest_report_snapshot_uses_run_history_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            workbook = output_dir / "20260326_113827_salehard.xlsx"
            workbook.write_text("xlsx", encoding="utf-8")
            pdf = output_dir / "20260326_113827_salehard.pdf"
            pdf.write_text("pdf", encoding="utf-8")
            manifest = output_dir / "20260326_113827_salehard.json"
            manifest.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-26T11:38:27+00:00",
                        "workbook": str(workbook),
                        "pdf": {"path": str(pdf), "status": "created", "error": ""},
                        "request": {"cities": ["Салехард"], "services": ["маникюр"]},
                        "counts": {"ranked_accounts": 8},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            history = output_dir / "run_history.jsonl"
            history.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-26T11:38:27+00:00",
                        "workbook": str(workbook),
                        "pdf": {"path": str(pdf), "status": "created", "error": ""},
                        "request": {"cities": ["Салехард"], "services": ["маникюр"]},
                        "counts": {"ranked_accounts": 8},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            snapshot = find_latest_report_snapshot(output_dir)

        assert snapshot is not None
        self.assertEqual(snapshot.workbook, workbook)
        self.assertEqual(snapshot.pdf, pdf)
        self.assertEqual(snapshot.manifest, manifest)
        self.assertEqual(snapshot.manifest_payload["request"]["cities"], ["Салехард"])

    def test_build_health_payload_includes_latest_report_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            cache_dir = output_dir / "cache"
            cache_dir.mkdir()
            workbook = output_dir / "20260326_113827_salehard.xlsx"
            workbook.write_text("xlsx", encoding="utf-8")
            manifest = output_dir / "20260326_113827_salehard.json"
            manifest.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-26T11:38:27+00:00",
                        "workbook": str(workbook),
                        "pdf": {"path": "", "status": "failed", "error": "no pdf"},
                        "request": {"cities": ["Салехард"], "services": ["маникюр"]},
                        "counts": {"ranked_accounts": 3},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (output_dir / "run_history.jsonl").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-26T11:38:27+00:00",
                        "workbook": str(workbook),
                        "pdf": {"path": "", "status": "failed", "error": "no pdf"},
                        "request": {"cities": ["Салехард"], "services": ["маникюр"]},
                        "counts": {"ranked_accounts": 3},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_health_payload(
                output_dir=output_dir,
                cache_dir=cache_dir,
                startup_at=datetime(2026, 3, 26, 11, 0, tzinfo=UTC),
                platforms=["vk", "telegram"],
                use_mock_data=False,
                allowed_chat_ids=[1, 2],
                rule_config_path=Path("data/marker_rules.json"),
                yandex_maps_requested=True,
            )

        latest_report = payload["latest_report"]
        self.assertEqual(latest_report["available"], True)
        self.assertEqual(latest_report["cities"], ["Салехард"])
        self.assertEqual(latest_report["services"], ["маникюр"])
        self.assertEqual(latest_report["ranked_accounts"], 3)
        self.assertEqual(payload["runtime"]["platforms"], ["vk", "telegram"])
        self.assertEqual(payload["runtime"]["yandex_maps_requested"], True)
        self.assertEqual(payload["runtime"]["yandex_maps_export_enabled"], False)
        self.assertIn("saving/modifying", payload["runtime"]["yandex_maps_block_reason"])

    def test_build_daily_report_payload_aggregates_run_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            workbook = output_dir / "20260419_080000_salehard.xlsx"
            workbook.write_text("xlsx", encoding="utf-8")
            manifest = output_dir / "20260419_080000_salehard.json"
            manifest.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-04-19T08:05:30+03:00",
                        "workbook": str(workbook),
                        "pdf": {"path": "", "status": "failed", "error": "no pdf"},
                        "request": {"cities": ["Салехард"], "services": ["маникюр"]},
                        "counts": {"ranked_accounts": 7, "raw_candidates": 40},
                        "meta": {
                            "report_origin": "bot",
                            "started_at": "2026-04-19T08:00:00+03:00",
                            "collected_at": "2026-04-19T08:04:00+03:00",
                            "collection_duration_seconds": 240,
                            "export_started_at": "2026-04-19T08:04:00+03:00",
                            "finished_at": "2026-04-19T08:05:30+03:00",
                            "export_duration_seconds": 90,
                            "duration_seconds": 330,
                            "platform_failures": [{"platform": "telegram", "error": "session expired"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            history = output_dir / "run_history.jsonl"
            history.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "generated_at": "2026-04-19T08:05:30+03:00",
                                "workbook": str(workbook),
                                "pdf": {"path": "", "status": "failed", "error": "no pdf"},
                                "request": {"cities": ["Салехард"], "services": ["маникюр"]},
                                "counts": {"ranked_accounts": 7, "raw_candidates": 40},
                                "meta": {
                                    "report_origin": "bot",
                                    "started_at": "2026-04-19T08:00:00+03:00",
                                    "collected_at": "2026-04-19T08:04:00+03:00",
                                    "collection_duration_seconds": 240,
                                    "export_started_at": "2026-04-19T08:04:00+03:00",
                                    "finished_at": "2026-04-19T08:05:30+03:00",
                                    "export_duration_seconds": 90,
                                    "duration_seconds": 330,
                                    "platform_failures": [{"platform": "telegram", "error": "session expired"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "generated_at": "2026-04-19T18:24:00+03:00",
                                "workbook": str(output_dir / "20260419_182400_no.xlsx"),
                                "pdf": {"path": "", "status": "failed", "error": "no pdf"},
                                "request": {"cities": ["Новый Уренгой"], "services": ["кофейня"]},
                                "counts": {"ranked_accounts": 0, "raw_candidates": 12},
                                "meta": {
                                    "report_origin": "bot",
                                    "started_at": "2026-04-19T18:20:00+03:00",
                                    "collected_at": "2026-04-19T18:23:00+03:00",
                                    "collection_duration_seconds": 180,
                                    "export_started_at": "2026-04-19T18:23:00+03:00",
                                    "finished_at": "2026-04-19T18:24:00+03:00",
                                    "export_duration_seconds": 60,
                                    "duration_seconds": 240,
                                    "platform_failures": [],
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_daily_report_payload(
                output_dir=output_dir,
                now=datetime.fromisoformat("2026-04-20T08:00:00+03:00"),
                timezone_name="Asia/Yekaterinburg",
            )

        self.assertEqual(payload["report_date"], "2026-04-19")
        self.assertEqual(payload["timezone"], "Asia/Yekaterinburg")
        self.assertEqual(payload["runs"]["total"], 2)
        self.assertEqual(payload["runs"]["non_empty"], 1)
        self.assertEqual(payload["runs"]["empty"], 1)
        self.assertEqual(payload["runs"]["with_platform_failures"], 1)
        self.assertEqual(payload["runs"]["total_ranked_accounts"], 7)
        self.assertEqual(payload["runs"]["total_raw_candidates"], 52)
        self.assertEqual(payload["runs"]["total_collection_duration_seconds"], 420)
        self.assertEqual(payload["runs"]["total_export_duration_seconds"], 150)
        self.assertEqual(payload["runs"]["total_duration_seconds"], 570)
        self.assertEqual(payload["top_cities"][0], {"name": "Салехард", "count": 1})
        self.assertEqual(payload["top_services"][0], {"name": "маникюр", "count": 1})
        self.assertEqual(payload["platform_failures"][0], {"platform": "telegram", "count": 1})
        self.assertEqual(payload["report_origins"][0], {"name": "bot", "count": 2})
        self.assertEqual(payload["latest_run"]["generated_at"], "2026-04-19T18:24:00+03:00")

    def test_build_daily_report_payload_uses_configured_timezone_for_report_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "run_history.jsonl").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-04-19T23:30:00+00:00",
                        "workbook": str(output_dir / "20260419_233000.xlsx"),
                        "pdf": {"path": "", "status": "failed", "error": "no pdf"},
                        "request": {"cities": ["Салехард"], "services": ["маникюр"]},
                        "counts": {"ranked_accounts": 1, "raw_candidates": 2},
                        "meta": {"report_origin": "bot"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_daily_report_payload(
                output_dir=output_dir,
                now=datetime.fromisoformat("2026-04-20T05:30:00+00:00"),
                day_offset=0,
                timezone_name="Asia/Yekaterinburg",
            )

        self.assertEqual(payload["report_date"], "2026-04-20")
        self.assertEqual(payload["runs"]["total"], 1)

    def test_format_daily_report_summary_includes_extra_ops_fields(self) -> None:
        summary = format_daily_report_summary(
            {
                "report_date_label": "19.04.2026",
                "runs": {
                    "total": 4,
                    "non_empty": 3,
                    "empty": 1,
                    "with_platform_failures": 2,
                    "total_collection_duration_seconds": 480,
                    "avg_collection_duration_seconds": 120,
                    "total_export_duration_seconds": 64,
                    "avg_export_duration_seconds": 16,
                    "total_duration_seconds": 544,
                    "max_duration_seconds": 190,
                    "total_ranked_accounts": 54,
                    "total_raw_candidates": 182,
                    "first_run_at": "2026-04-19T08:02:00+03:00",
                    "last_run_at": "2026-04-19T18:24:00+03:00",
                },
                "top_cities": [{"name": "Салехард", "count": 2}],
                "top_services": [{"name": "маникюр", "count": 3}],
                "report_origins": [{"name": "bot", "count": 4}],
                "platform_failures": [{"platform": "telegram", "count": 2}],
                "latest_run": {"available": True, "generated_at": "2026-04-19T18:24:00+03:00", "ranked_accounts": 0},
            }
        )

        self.assertIn("Со сбоями платформ: 2", summary)
        self.assertIn("Окно активности:", summary)
        self.assertIn("Источники запусков: bot (4)", summary)
        self.assertIn("Сбои платформ: telegram (2)", summary)


if __name__ == "__main__":
    unittest.main()
