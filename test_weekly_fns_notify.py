import datetime as dt
import csv
import tempfile
import unittest

import weekly_fns_notify as w


class WeeklyFnsNotifyTest(unittest.TestCase):
    def test_next_week(self):
        self.assertEqual(w.next_week(dt.date(2026, 8, 10)), (dt.date(2026, 8, 17), dt.date(2026, 8, 23)))
        self.assertEqual(w.next_week(dt.date(2026, 8, 16)), (dt.date(2026, 8, 17), dt.date(2026, 8, 23)))

    def test_tax_rows_reads_export_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = w.Path(tmp) / "report.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Группа", "Кол-во", "Суд", "Дата", "Время", "Номер", "Категория", "Судья", "Стороны", "Представители", "Результат", "Ссылка", "Статус"])
                writer.writerow(["", "", "Суд", "2026-08-17", "10:00", "1", "", "", "Истец: Иванов", "", "", "", ""])
                writer.writerow(["", "", "Суд", "2026-08-17", "11:00", "2", "", "", "Ответчик: УФНС России по ЯНАО", "", "", "", ""])

            self.assertEqual(len(w.tax_rows(path)), 1)

    def test_weekly_chat_id_uses_file_when_env_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_file = w.CHAT_ID_FILE
            w.CHAT_ID_FILE = w.Path(tmp) / "weekly-chat-id"
            w.CHAT_ID_FILE.write_text("777\n", encoding="utf-8")
            try:
                self.assertEqual(w.weekly_chat_id(), "777")
            finally:
                w.CHAT_ID_FILE = old_file

    def test_weekly_chat_ids_includes_env_and_saved_chat_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_file = w.CHAT_ID_FILE
            old_env = w.os.environ.get("SUD_WEEKLY_CHAT_ID")
            w.CHAT_ID_FILE = w.Path(tmp) / "weekly-chat-id"
            w.CHAT_ID_FILE.write_text("777\n", encoding="utf-8")
            w.os.environ["SUD_WEEKLY_CHAT_ID"] = "555"
            try:
                self.assertEqual(w.weekly_chat_ids(), ["555", "777"])
                w.os.environ["SUD_WEEKLY_CHAT_ID"] = "777"
                self.assertEqual(w.weekly_chat_ids(), ["777"])
            finally:
                w.CHAT_ID_FILE = old_file
                if old_env is None:
                    w.os.environ.pop("SUD_WEEKLY_CHAT_ID", None)
                else:
                    w.os.environ["SUD_WEEKLY_CHAT_ID"] = old_env


if __name__ == "__main__":
    unittest.main()
