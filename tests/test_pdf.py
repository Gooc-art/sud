from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import tempfile
import unittest
from pathlib import Path
import re

from godmod.export.pdf import _PdfFont, _build_pages, write_pdf_report
from godmod.export.reports import write_report_artifacts
from godmod.models import (
    AccountCandidate,
    AccountMetrics,
    PostRecord,
    RankedAccount,
    ReportBundle,
    ScoreBreakdown,
    SearchRequest,
    ServiceQuery,
)
from godmod.report_rows import build_report_rows


def _build_bundle() -> ReportBundle:
    now = datetime.now(UTC).replace(microsecond=0)
    return ReportBundle(
        request=SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=60,
            platforms=["vk"],
            top_n=20,
        ),
        ranked_accounts=[
            RankedAccount(
                candidate=AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Studio One",
                    account_url="https://vk.com/studio1",
                    username_or_id="studio1",
                    description="Маникюр в Салехарде. Адрес: ул. Ленина, 10. Телефон +7 900 000-00-00",
                    followers=1200,
                    posts=[
                        PostRecord(
                            url="https://vk.com/studio1?w=wall-1_1",
                            text="Маникюр Салехард, запись открыта",
                            published_at=now,
                        ),
                        PostRecord(
                            url="https://vk.com/studio1?w=wall-1_2",
                            text="Отзывы клиентов, Салехард",
                            published_at=now - timedelta(days=5),
                        ),
                    ],
                    contacts={"phone": ["+7 900 000-00-00"], "telegram": ["@studio1"]},
                ),
                metrics=AccountMetrics(
                    posts_in_period=10,
                    last_post_at=now,
                    avg_likes=30,
                    avg_comments=4,
                    avg_reposts=1,
                    avg_views=250,
                    commercial_markers=["цены", "запись"],
                    city_signals=["Салехард"],
                    stability_ratio=0.8,
                ),
                score=ScoreBreakdown(3.0, 1.5, 2.0, 1.5, 1.0),
                evidence_posts=[],
                activity_class="сильный действующий аккаунт",
            )
        ],
        search_log=[],
        duplicates_review=[],
    )


class PdfWriterTests(unittest.TestCase):
    def test_write_pdf_report_creates_valid_pdf(self) -> None:
        bundle = _build_bundle()
        rows = build_report_rows(bundle)

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "report.pdf"
            write_pdf_report(target, bundle, rows)
            data = target.read_bytes()

        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertIn(b"/Type /Catalog", data)
        self.assertIn(b"/Subtype /Type0", data)

    def test_write_report_artifacts_creates_xlsx_and_pdf(self) -> None:
        bundle = _build_bundle()

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "report.xlsx"
            artifacts = write_report_artifacts(bundle, target)

            self.assertTrue(artifacts.workbook.exists())
            self.assertTrue(artifacts.pdf.exists() if artifacts.pdf else False)
            self.assertTrue(artifacts.manifest.exists() if artifacts.manifest else False)
            self.assertTrue(artifacts.history.exists() if artifacts.history else False)
            self.assertIsNone(artifacts.pdf_error)

    def test_write_report_artifacts_creates_manifest_with_request_and_counts(self) -> None:
        bundle = _build_bundle()
        bundle.report_meta = {
            "cache_enabled": True,
            "cache_dir": "output/cache",
            "wall_hits": 0,
            "platform_failures_total": 1,
            "platform_failures": [{"platform": "2gis", "error": "blocked key"}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "report.xlsx"
            artifacts = write_report_artifacts(bundle, target)
            assert artifacts.manifest is not None
            manifest = json.loads(artifacts.manifest.read_text(encoding="utf-8"))

        self.assertEqual(manifest["request"]["cities"], ["Салехард"])
        self.assertEqual(manifest["request"]["services"], ["маникюр"])
        self.assertEqual(manifest["counts"]["ranked_accounts"], 1)
        self.assertEqual(manifest["counts"]["raw_candidates"], 0)
        self.assertEqual(manifest["pdf"]["status"], "created")
        self.assertEqual(manifest["meta"]["cache_dir"], "output/cache")
        self.assertIn("wall_hits", manifest["meta"])
        self.assertEqual(manifest["meta"]["platform_failures_total"], 1)
        self.assertEqual(manifest["meta"]["platform_failures"][0]["platform"], "2gis")
        self.assertIn("all_accounts", manifest["sheets"])
        self.assertEqual(artifacts.manifest_payload["counts"]["ranked_accounts"], 1)
        self.assertEqual(artifacts.manifest_payload["meta"]["platform_failures_total"], 1)

    def test_write_report_artifacts_appends_run_history(self) -> None:
        bundle = _build_bundle()

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "report.xlsx"
            first = write_report_artifacts(bundle, target)
            second = write_report_artifacts(bundle, Path(temp_dir) / "report_second.xlsx")
            assert first.history is not None
            assert second.history is not None
            lines = [line for line in first.history.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual(first.history, second.history)
        self.assertEqual(len(lines), 2)

    def test_pdf_layout_uses_all_accounts_table_headers(self) -> None:
        bundle = _build_bundle()
        rows = build_report_rows(bundle)
        font = _PdfFont.load()

        pages = _build_pages(bundle, rows, font)
        normalized_page_text = re.sub(r"\s+", "", "".join(line.text for line in pages[0].lines))

        for header in rows["all_accounts"][0]:
            self.assertIn(re.sub(r"\s+", "", header), normalized_page_text)

        self.assertIn(re.sub(r"\s+", "", "Studio One"), normalized_page_text)


if __name__ == "__main__":
    unittest.main()
