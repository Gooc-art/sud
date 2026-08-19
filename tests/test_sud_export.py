from __future__ import annotations

import tempfile
import threading
import time
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from godmod.sud_export import Row, collect, export_sud, parse_case, parse_schedule, read_url, row_matches_fns_yanao


class SudExportTests(unittest.TestCase):
    def test_parse_schedule_extracts_case_row(self) -> None:
        page = """
        <table><tr>
        <td>1</td><td><a href="/case.php?id=1">2-123/2026</a></td>
        <td>09:30</td><td>зал 1</td><td>Исковое заявление</td><td>Иванов И.И.</td><td>Назначено</td>
        </tr></table>
        """

        rows = parse_schedule(page, "https://salehardsky--ynao.sudrf.ru/modules.php", "Салехардский суд", date(2026, 7, 1))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].case_number, "2-123/2026")
        self.assertEqual(rows[0].time, "09:30")
        self.assertEqual(rows[0].url, "https://salehardsky--ynao.sudrf.ru/case.php?id=1")

    def test_parse_case_extracts_lawyers_from_parties_block(self) -> None:
        page = """
        <div id="cont3"><table>
        <tr><td>Истец</td><td>Петров</td></tr>
        <tr><td>Защитник (адвокат)</td><td>Сидоров</td></tr>
        </table></div>
        """

        parties, lawyers, check = parse_case(page)

        self.assertIn("Истец: Петров", parties)
        self.assertEqual(lawyers, "Защитник (адвокат): Сидоров")
        self.assertEqual(check, "ok")

    def test_export_sud_report_writes_artifacts_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            row = Row(
                court="Салехардский городской суд",
                hearing_date="2026-07-01",
                time="09:30",
                case_number="2-123/2026",
                info="Иск",
                judge="Иванов",
                lawyers="Представитель: Сидоров",
                check="ok",
            )

            with patch("godmod.sud_export.collect", return_value=([row], [])):
                paths = export_sud(date(2026, 7, 1), date(2026, 7, 1), outdir)

            self.assertEqual(paths["xlsx"], outdir / "report.xlsx")
            for name in ("report.xlsx", "report.pdf", "report.html", "report.csv", "run_log.csv"):
                self.assertTrue((outdir / name).exists(), name)

    def test_row_matches_fns_yanao_short_and_full_names(self) -> None:
        short = Row(
            court="Суд ЯНАО",
            hearing_date="2026-07-01",
            time="09:30",
            case_number="2-1/2026",
            info="Иск",
            judge="Иванов",
            parties="Истец: УФНС по ЯНАО; Ответчик: ООО Ромашка",
        )
        full = Row(
            court="Суд ЯНАО",
            hearing_date="2026-07-01",
            time="10:00",
            case_number="2-2/2026",
            info="Заявление Управления Федеральной налоговой службы по Ямало-Ненецкому автономному округу",
            judge="Петров",
        )
        other = Row(
            court="Суд ЯНАО",
            hearing_date="2026-07-01",
            time="11:00",
            case_number="2-3/2026",
            info="Иск ООО Ромашка",
            judge="Сидоров",
        )

        self.assertTrue(row_matches_fns_yanao(short))
        self.assertTrue(row_matches_fns_yanao(full))
        self.assertFalse(row_matches_fns_yanao(other))

    def test_row_matches_fns_yanao_inspection_name(self) -> None:
        row = Row(
            court="Суд ЯНАО",
            hearing_date="2026-07-01",
            time="09:30",
            case_number="2-1/2026",
            info="Иск Межрайонной ИФНС России №1 по ЯНАО",
            judge="Иванов",
        )

        self.assertTrue(row_matches_fns_yanao(row))

    def test_read_url_falls_back_to_previous_sud_cache_on_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sud_root = Path(tmp) / "sud"
            previous_cache = sud_root / "old-job" / "cache" / "schedules" / "court.example" / "2026-07-01.html"
            current_cache = sud_root / "new-job" / "cache" / "schedules" / "court.example" / "2026-07-01.html"
            previous_cache.parent.mkdir(parents=True)
            previous_cache.write_text("<html>cached schedule</html>", encoding="utf-8")

            with patch("godmod.sud_export._curl_url", side_effect=RuntimeError("timed out")):
                text = read_url("https://court.example/schedule", current_cache)

            self.assertEqual(text, "<html>cached schedule</html>")
            self.assertEqual(current_cache.read_text(encoding="utf-8"), "<html>cached schedule</html>")

    def test_collect_fetches_case_pages_with_workers(self) -> None:
        active = 0
        peak = 0
        lock = threading.Lock()

        def fake_read_url(url: str, *_args, **_kwargs) -> str:
            nonlocal active, peak
            if "H_date" in url:
                return """
                <table>
                <tr><td>1</td><td><a href="/case.php?id=1">2-1/2026</a></td><td>09:00</td><td></td><td>Иск</td><td>Иванов</td></tr>
                <tr><td>2</td><td><a href="/case.php?id=2">2-2/2026</a></td><td>10:00</td><td></td><td>Иск</td><td>Петров</td></tr>
                </table>
                """
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return '<div id="cont3"><table><tr><td>Истец</td><td>ООО</td></tr></table></div>'

        with tempfile.TemporaryDirectory() as tmp, patch("godmod.sud_export.read_url", side_effect=fake_read_url):
            rows, log = collect(
                date(2026, 7, 1),
                date(2026, 7, 1),
                Path(tmp),
                court="salehardsky--ynao.sudrf.ru",
                workers=2,
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(log, [])
        self.assertGreaterEqual(peak, 2)

    def test_export_sud_report_adds_fns_yanao_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            fns_row = Row(
                court="Салехардский городской суд",
                hearing_date="2026-07-01",
                time="09:30",
                case_number="2-123/2026",
                info="Иск УФНС по ЯНАО",
                judge="Иванов",
                parties="Истец: УФНС по ЯНАО",
                check="ok",
            )
            other_row = Row(
                court="Салехардский городской суд",
                hearing_date="2026-07-01",
                time="10:00",
                case_number="2-124/2026",
                info="Иск ООО Ромашка",
                judge="Петров",
                check="ok",
            )

            with patch("godmod.sud_export.collect", return_value=([fns_row, other_row], [])):
                export_sud(date(2026, 7, 1), date(2026, 7, 1), outdir)

            with zipfile.ZipFile(outdir / "report.xlsx") as z:
                workbook = z.read("xl/workbook.xml").decode("utf-8")
                fns_sheet = z.read("xl/worksheets/sheet2.xml").decode("utf-8")

            self.assertIn('name="ФНС ЯНАО"', workbook)
            self.assertIn("2-123/2026", fns_sheet)
            self.assertNotIn("2-124/2026", fns_sheet)


if __name__ == "__main__":
    unittest.main()
