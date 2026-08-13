import datetime as dt
import tempfile
import unittest
import zipfile

import sud_export as s


class SudExportTest(unittest.TestCase):
    def test_ynao_courts_include_requested_districts(self):
        self.assertEqual(s.COURTS["gubkinskiy--ynao.sudrf.ru"], "Губкинский районный суд")
        self.assertEqual(s.COURTS["purovsky--ynao.sudrf.ru"], "Пуровский районный суд")
        self.assertEqual(s.COURTS["krasnoselkupsky--ynao.sudrf.ru"], "Красноселькупский районный суд")
        self.assertEqual(s.COURTS["shuryshkarsky--ynao.sudrf.ru"], "Шурышкарский районный суд")

    def test_parse_schedule_and_case(self):
        schedule = """
        <table><tr><td>1</td><td><a href="/modules.php?name=sud_delo&name_op=case&case_id=1">2-1/2026</a></td>
        <td>09:30</td><td>1</td><td>КАТЕГОРИЯ: спор<br>ИСТЕЦ: Иванов</td><td>Петров П.П.</td><td>Отложено</td></tr></table>
        """
        rows = s.parse_schedule(schedule, "https://court.sudrf.ru/modules.php?name=sud_delo", "Суд", dt.date(2026, 7, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].case_number, "2-1/2026")
        self.assertEqual(rows[0].url, "https://court.sudrf.ru/modules.php?name=sud_delo&name_op=case&case_id=1")
        parties, lawyers, check = s.parse_case("СТОРОНЫ ПО ДЕЛУ Истец Иванов Защитник (адвокат): Сидоров С.С. СУДЕБНЫЕ АКТЫ")
        self.assertIn("Истец Иванов", parties)
        self.assertIn("Сидоров", lawyers)
        self.assertEqual(check, "ok")

    def test_sort_by_lawyer_groups_by_count(self):
        rows = [
            s.Row("Суд", "2026-07-02", "10:00", "3", "", "", "", "ПРЕДСТАВИТЕЛЬ: Петров П.П.", "", "", "ok"),
            s.Row("Суд", "2026-07-01", "10:00", "1", "", "", "", "ПРЕДСТАВИТЕЛЬ: Иванов И.И.", "", "", "ok"),
            s.Row("Суд", "2026-07-03", "10:00", "4", "", "", "", "", "", "", "no_lawyer"),
            s.Row("Суд", "2026-07-02", "09:00", "2", "", "", "", "ПРЕДСТАВИТЕЛЬ: Иванов И.И.", "", "", "ok"),
        ]
        table = s.sort_by_lawyer(rows)
        self.assertEqual([r[0] for r in table], ["Иванов И.И.", "Иванов И.И.", "Петров П.П.", "Без представителя"])
        self.assertEqual([r[1] for r in table], ["2", "2", "1", "1"])

    def test_is_tax_party_matches_any_role(self):
        defendant = s.Row("Суд", "2026-07-01", "", "1", "", "", "Ответчик: УФНС России по ЯНАО", "", "", "", "")
        long_name = s.Row("Суд", "2026-07-01", "", "2", "", "", "Административный ответчик: Управление Федеральной налоговой службы по ЯНАО", "", "", "", "")
        claimant = s.Row("Суд", "2026-07-01", "", "3", "", "", "Истец: ИФНС России по г. Муравленко; Ответчик: Иванов", "", "", "", "")
        unrelated = s.Row("Суд", "2026-07-01", "", "4", "", "", "Истец: Иванов; Ответчик: Петров", "", "", "", "")

        self.assertTrue(s.is_tax_party(defendant))
        self.assertTrue(s.is_tax_party(long_name))
        self.assertTrue(s.is_tax_party(claimant))
        self.assertFalse(s.is_tax_party(unrelated))

    def test_write_xlsx_adds_ufns_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = s.Path(tmp) / "report.xlsx"
            s.write_xlsx(path, [s.HEADERS], [("ФНС участвует", [s.HEADERS])])

            with zipfile.ZipFile(path) as z:
                self.assertIn("xl/worksheets/sheet2.xml", z.namelist())
                workbook = z.read("xl/workbook.xml").decode()

        self.assertIn("ФНС участвует", workbook)

    def test_read_url_rejects_cached_bad_gateway(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = s.Path(tmp) / "bad.html"
            path.write_text("<html><title>502 Bad Gateway</title></html>", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "bad gateway"):
                s.read_url("https://court.test", path)


if __name__ == "__main__":
    unittest.main()
