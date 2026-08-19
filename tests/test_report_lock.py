from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from godmod.models import SearchRequest, ServiceQuery
from godmod.report_lock import format_report_busy_message, read_active_report_run, release_report_run, try_acquire_report_run


class ReportLockTests(unittest.TestCase):
    def test_try_acquire_blocks_second_run_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            request = SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="маникюр")],
                period_days=60,
                platforms=["vk"],
                top_n=20,
                report_mode="all",
            )

            lock, busy = try_acquire_report_run(output_dir, chat_id=1, user_id=10, request=request)
            self.assertIsNotNone(lock)
            self.assertIsNone(busy)

            second_lock, second_busy = try_acquire_report_run(output_dir, chat_id=2, user_id=20, request=request)
            self.assertIsNone(second_lock)
            self.assertIsNotNone(second_busy)
            self.assertEqual(second_busy.user_id, "user:10")
            self.assertIn("Салехард", format_report_busy_message(second_busy))

            release_report_run(output_dir, lock.lock_id)
            self.assertIsNone(read_active_report_run(output_dir))


if __name__ == "__main__":
    unittest.main()
