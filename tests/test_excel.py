from __future__ import annotations

from datetime import UTC, datetime
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from godmod.export.excel import SheetSpec, write_workbook
from godmod.export.reports import write_report_artifacts
from godmod.models import (
    AccountCandidate,
    AccountMetrics,
    RankedAccount,
    ReportBundle,
    ScoreBreakdown,
    SearchRequest,
    ServiceQuery,
)


class ExcelWriterTests(unittest.TestCase):
    def test_write_workbook_creates_valid_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "report.xlsx"
            write_workbook(
                target,
                [
                    SheetSpec(
                        name="all_accounts",
                        rows=[{"name": "Test", "score": 8.5}],
                    )
                ],
            )
            self.assertTrue(target.exists())
            with ZipFile(target) as archive:
                names = set(archive.namelist())
                self.assertIn("[Content_Types].xml", names)
                self.assertIn("xl/workbook.xml", names)
                self.assertIn("xl/worksheets/sheet1.xml", names)

    def test_write_workbook_supports_freeze_filter_and_widths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "report.xlsx"
            write_workbook(
                target,
                [
                    SheetSpec(
                        name="all_accounts",
                        rows=[{"Название": "Test", "Ссылка": "https://example.com"}],
                        freeze_header=True,
                        auto_filter=True,
                        column_widths={"Название": 24.0, "Ссылка": 28.0},
                    )
                ],
            )

            with ZipFile(target) as archive:
                sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

        self.assertIn('state="frozen"', sheet_xml)
        self.assertIn('<autoFilter ref="A1:B2"/>', sheet_xml)
        self.assertIn('<col min="1" max="1" width="24.0" customWidth="1"/>', sheet_xml)
        self.assertIn('<col min="2" max="2" width="28.0" customWidth="1"/>', sheet_xml)

    def test_report_artifacts_configure_first_sheet_for_all_accounts(self) -> None:
        bundle = ReportBundle(
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
                        description="Маникюр в Салехарде",
                        followers=1200,
                        contacts={"phone": ["+7 900 000-00-00"]},
                    ),
                    metrics=AccountMetrics(
                        posts_in_period=6,
                        last_post_at=datetime(2026, 3, 24, 12, 0, tzinfo=UTC),
                        avg_likes=20,
                        avg_comments=2,
                        avg_reposts=1,
                        avg_views=140,
                        commercial_markers=["цены", "запись"],
                        city_signals=["Салехард"],
                        stability_ratio=0.8,
                    ),
                    score=ScoreBreakdown(2.5, 1.2, 1.6, 1.5, 0.8),
                    evidence_posts=[],
                    activity_class="действующий",
                )
            ],
            search_log=[],
            duplicates_review=[],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "report.xlsx"
            artifacts = write_report_artifacts(bundle, target)
            with ZipFile(artifacts.workbook) as archive:
                sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

        self.assertIn('state="frozen"', sheet_xml)
        self.assertIn("<autoFilter", sheet_xml)
        self.assertIn('topLeftCell="A2"', sheet_xml)


if __name__ == "__main__":
    unittest.main()
