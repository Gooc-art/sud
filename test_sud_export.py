import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import sud_export as s


class SudExportCompatibilityTests(unittest.TestCase):
    def test_root_wrapper_exports_courts_and_functions(self):
        self.assertIn("salehardsky--ynao.sudrf.ru", s.COURTS)
        self.assertTrue(callable(s.export_sud))

    def test_parse_schedule_still_available(self):
        rows = s.parse_schedule(
            '<table><tr><td>1</td><td><a href="/case.php?id=1">2-1/2026</a></td><td>09:30</td><td></td><td>Иск</td><td>Судья</td></tr></table>',
            "https://court.example/modules.php",
            "Суд",
            date(2026, 7, 1),
        )

        self.assertEqual(rows[0].case_number, "2-1/2026")
        self.assertEqual(rows[0].url, "https://court.example/case.php?id=1")


if __name__ == "__main__":
    unittest.main()
