import hashlib
import hmac
import datetime as dt
import tempfile
import unittest
from unittest import mock

import max_bot as b


class MaxBotTest(unittest.TestCase):
    def setUp(self):
        b.commerce_password_pending.clear()
        b.verified_admin_phones.clear()
        b.verified_admin_phones["42"] = "79320588150"

    def signed_contact_update(self, user_id=1, phone="+7 932 058-81-50"):
        vcf_info = f"BEGIN:VCARD\r\nVERSION:3.0\r\nTEL;TYPE=cell:{phone}\r\nFN:Admin\r\nEND:VCARD\r\n"
        contact_hash = hmac.new(b.TOKEN.encode(), vcf_info.encode(), hashlib.sha256).hexdigest()
        return {
            "message": {
                "user_id": user_id,
                "body": {
                    "attachments": [
                        {
                            "type": "contact",
                            "payload": {"vcf_info": vcf_info, "hash": contact_hash},
                        }
                    ]
                },
            }
        }

    def test_last_full_week(self):
        self.assertEqual(b.last_full_week(dt.date(2026, 7, 29)), (dt.date(2026, 7, 20), dt.date(2026, 7, 26)))

    def test_last_full_month(self):
        self.assertEqual(b.last_full_month(dt.date(2026, 7, 29)), (dt.date(2026, 6, 1), dt.date(2026, 6, 30)))

    def test_current_week(self):
        self.assertEqual(b.current_week(dt.date(2026, 7, 29)), (dt.date(2026, 7, 27), dt.date(2026, 8, 2)))

    def test_parse_ru_date(self):
        self.assertEqual(b.parse_ru_date("29.07.2026"), dt.date(2026, 7, 29))
        self.assertEqual(b.parse_ru_date("2026-07-29"), dt.date(2026, 7, 29))
        self.assertIsNone(b.parse_ru_date("29/07/2026"))

    def test_message_id_shapes(self):
        self.assertEqual(b.message_id({"message": {"body": {"mid": "m1"}}}), "m1")
        self.assertEqual(b.message_id({"body": {"mid": "m2"}}), "m2")

    def test_show_menu_falls_back_when_edit_is_rejected(self):
        b.sessions.clear()
        b.sessions["42"] = b.Session(menu_message_id="old")
        calls = []

        def fake_request(method, path, params=None, body=None):
            calls.append((method, path, params))
            if method == "PUT":
                return {"success": False, "message": "error.edit.wrong.author"}
            return {"message": {"body": {"mid": "new"}}}

        with mock.patch.object(b, "request", side_effect=fake_request):
            with mock.patch.object(b.time, "sleep"):
                b.show_menu({"user_id": 42}, "Меню", b.main_buttons())

        self.assertEqual(calls[0], ("PUT", "/messages", {"message_id": "old"}))
        self.assertEqual(calls[1][0:2], ("POST", "/messages"))
        self.assertEqual(b.sessions["42"].menu_message_id, "new")

    def test_full_menu_flow_reuses_menu_message(self):
        b.sessions.clear()
        target = {"user_id": 42}
        calls = []

        def fake_request(method, path, params=None, body=None):
            calls.append((method, path, params))
            if method == "POST":
                return {"message": {"body": {"mid": "menu-1"}}}
            return {"success": True}

        def fake_start_job(_target, start, end, court):
            return b.Job("j1", _target, start, end, court, b.Path("out"))

        with mock.patch.object(b, "request", side_effect=fake_request):
            with mock.patch.object(b, "ack_callback"):
                with mock.patch.object(b.time, "sleep"):
                    with mock.patch.object(b, "start_job", side_effect=fake_start_job):
                        for payload in ("start", "period", "period_current", "court:all", "run_confirm"):
                            b.handle(target, "", payload, "cb1")

        self.assertEqual([call[0] for call in calls], ["POST", "PUT", "PUT", "PUT", "PUT"])
        self.assertEqual({call[2]["message_id"] for call in calls[1:]}, {"menu-1"})
        self.assertEqual(b.sessions["42"].step, "running")

    def test_extract_callback_target_from_recipient(self):
        target, text, payload, callback_id, source_message_id, contact_phone = b.extract_event(
            {
                "update_type": "message_callback",
                "callback": {"callback_id": "cb1", "payload": "week", "user": {"user_id": 42}},
                "message": {"recipient": {"chat_id": 7}, "body": {"text": "old", "mid": "msg1"}},
            }
        )

        self.assertEqual(target, {"chat_id": 7, "user_id": 42})
        self.assertEqual(text, "old")
        self.assertEqual(payload, "week")
        self.assertEqual(callback_id, "cb1")
        self.assertEqual(source_message_id, "msg1")
        self.assertEqual(contact_phone, "")

    def test_extract_nested_message_callback(self):
        target, text, payload, callback_id, source_message_id, contact_phone = b.extract_event(
            {
                "update_type": "message_callback",
                "message_callback": {
                    "callback": {"callback_id": "cb1", "payload": "week", "user": {"user_id": 42}},
                    "message": {"recipient": {"chat_id": 7}, "body": {"text": "old", "mid": "msg1"}},
                },
            }
        )

        self.assertEqual(target, {"chat_id": 7, "user_id": 42})
        self.assertEqual(text, "old")
        self.assertEqual(payload, "week")
        self.assertEqual(callback_id, "cb1")
        self.assertEqual(source_message_id, "msg1")
        self.assertEqual(contact_phone, "")

    def test_extract_callback_prefers_clicking_user_over_bot_sender(self):
        target, text, payload, callback_id, source_message_id, contact_phone = b.extract_event(
            {
                "update_type": "message_callback",
                "callback": {"callback_id": "cb1", "payload": "week", "user": {"user_id": 42}},
                "message": {
                    "sender": {"user_id": 1, "is_bot": True},
                    "recipient": {"user_id": 42},
                    "body": {"text": "old"},
                },
            }
        )

        self.assertEqual(target, {"user_id": 42})
        self.assertEqual(text, "old")
        self.assertEqual(payload, "week")
        self.assertEqual(callback_id, "cb1")
        self.assertEqual(source_message_id, "")
        self.assertEqual(contact_phone, "")

    def test_extract_bot_started_as_start(self):
        target, text, payload, callback_id, source_message_id, contact_phone = b.extract_event(
            {"update_type": "bot_started", "chat_id": 7, "user": {"user_id": 42}}
        )

        self.assertEqual(target, {"chat_id": 7, "user_id": 42})
        self.assertEqual(text, "/start")
        self.assertEqual(payload, "")
        self.assertEqual(callback_id, "")
        self.assertEqual(source_message_id, "")
        self.assertEqual(contact_phone, "")

    def test_callback_deletes_source_menu_and_posts_new_screen(self):
        b.sessions.clear()
        b.sessions["42"] = b.Session(menu_message_id="old", date_from=dt.date(2026, 7, 20), date_to=dt.date(2026, 7, 26))
        calls = []

        def fake_request(method, path, params=None, body=None):
            calls.append((method, path, params))
            if method == "POST" and path == "/messages":
                return {"message": {"body": {"mid": "new"}}}
            return {"success": True}

        with mock.patch.object(b, "request", side_effect=fake_request):
            with mock.patch.object(b, "ack_callback"):
                with mock.patch.object(b.time, "sleep"):
                    b.handle({"user_id": 42}, "", "court:all", "cb1", "old")

        self.assertEqual(calls[0], ("DELETE", "/messages", {"message_id": "old"}))
        self.assertEqual(calls[1][0:2], ("POST", "/messages"))
        self.assertEqual(b.sessions["42"].menu_message_id, "new")

    def test_start_reuses_existing_menu_after_reopening_bot(self):
        b.sessions.clear()
        b.sessions["42"] = b.Session(menu_message_id="old")
        calls = []

        def fake_request(method, path, params=None, body=None):
            calls.append((method, path, params))
            return {"message": {"body": {"mid": "new"}}}

        with mock.patch.object(b, "request", side_effect=fake_request):
            with mock.patch.object(b.time, "sleep"):
                b.handle({"user_id": 42}, "/start")

        self.assertEqual(calls[0], ("PUT", "/messages", {"message_id": "old"}))
        self.assertEqual(b.sessions["42"].menu_message_id, "old")

    def test_callback_action_survives_answer_failure(self):
        b.sessions.clear()
        shown = []
        with mock.patch.object(b, "ack_callback", side_effect=RuntimeError("answer failed")):
            with mock.patch.object(b, "show_menu", side_effect=lambda target, text, buttons: shown.append(text)):
                b.handle({"user_id": 42}, "", "month", "cb1")

        self.assertEqual(b.sessions["42"].step, "month_court")
        self.assertIn("Выберите суд", shown[-1])

    def test_callback_ack_happens_after_action(self):
        b.sessions.clear()
        calls = []
        with mock.patch.object(b, "show_menu", side_effect=lambda *args: calls.append("show")):
            with mock.patch.object(b, "ack_callback", side_effect=lambda callback_id: calls.append("ack")):
                b.handle({"user_id": 42}, "", "month", "cb1")

        self.assertEqual(calls, ["show", "ack"])

    def test_new_period_clears_previous_court(self):
        b.sessions.clear()
        b.sessions["42"] = b.Session(court="salehardsky--ynao.sudrf.ru")

        with mock.patch.object(b, "show_menu"):
            with mock.patch.object(b, "ack_callback"):
                b.handle({"user_id": 42}, "", "month", "cb1")

        self.assertIsNone(b.sessions["42"].court)

    def test_answer_callback_uses_notification(self):
        with mock.patch.object(b, "request") as req:
            b.answer_callback("cb1", "OK")

        req.assert_called_once_with("POST", "/answers", {"callback_id": "cb1"}, {"notification": "OK"})

    def test_all_button_payloads_route_to_non_fallback(self):
        b.sessions.clear()
        target = {"user_id": 42}
        b.sessions["42"] = b.Session(date_from=dt.date(2026, 7, 20), date_to=dt.date(2026, 7, 26))
        payloads = {
            payload
            for keyboard_rows in (b.main_buttons(), b.period_buttons(), b.court_buttons("court"), b.confirm_buttons())
            for row in keyboard_rows
            for _, payload in row
        }
        shown = []

        def show_menu(_target, text, _buttons):
            shown.append(text)

        with mock.patch.object(b, "show_menu", side_effect=show_menu):
            with mock.patch.object(b, "ack_callback"):
                with mock.patch.object(b, "start_job", side_effect=lambda *args: b.Job("j1", target, args[1], args[2], args[3], b.Path("out"))):
                    for payload in sorted(payloads):
                        shown.clear()
                        b.handle(target, "", payload, "cb1")
                        self.assertTrue(shown, payload)
                        self.assertNotEqual(shown[-1], "Выберите действие.", payload)

    def test_poll_subscribes_to_start_and_buttons(self):
        calls = []

        def fake_request(_method, _path, params):
            calls.append(params)
            raise KeyboardInterrupt

        with mock.patch.object(b, "request", side_effect=fake_request):
            with self.assertRaises(KeyboardInterrupt):
                b.poll()

        self.assertEqual(calls[0]["types"], "bot_started,message_created,message_callback")

    def test_poll_keeps_running_after_update_fetch_error(self):
        calls = []

        def fake_request(_method, _path, params):
            calls.append(params)
            if len(calls) == 1:
                raise OSError("network")
            raise KeyboardInterrupt

        with mock.patch.object(b, "request", side_effect=fake_request):
            with mock.patch.object(b.time, "sleep") as sleep:
                with self.assertRaises(KeyboardInterrupt):
                    b.poll()

        sleep.assert_called_once_with(5)
        self.assertEqual(len(calls), 2)

    def test_stale_court_button_without_period_asks_for_period(self):
        b.sessions.clear()
        shown = []
        with mock.patch.object(b, "show_menu", side_effect=lambda _target, text, _buttons, *_args: shown.append(text)):
            with mock.patch.object(b, "ack_callback") as ack:
                b.handle({"user_id": 42}, "", "court:all", "cb1")

        ack.assert_called_once_with("cb1")
        self.assertEqual(b.sessions["42"].step, "period")
        self.assertEqual(shown[-1], "Сначала выберите период выгрузки.")

    def test_stale_confirm_button_without_period_does_not_start_job(self):
        b.sessions.clear()
        shown = []
        with mock.patch.object(b, "show_menu", side_effect=lambda _target, text, _buttons, *_args: shown.append(text)):
            with mock.patch.object(b, "ack_callback") as ack:
                with mock.patch.object(b, "start_job") as start_job:
                    b.handle({"user_id": 42}, "", "run_confirm", "cb1")

        ack.assert_called_once_with("cb1")
        start_job.assert_not_called()
        self.assertEqual(b.sessions["42"].step, "period")
        self.assertEqual(shown[-1], "Сначала выберите период выгрузки.")

    def test_start_job_allows_45_days(self):
        b.sessions.clear()
        target = {"user_id": 42}
        start = dt.date(2026, 1, 1)
        old_max_days = b.MAX_DAYS
        b.MAX_DAYS = 45
        try:
            job = b.start_job(target, start, start + dt.timedelta(days=44), None)
            with self.assertRaises(ValueError):
                b.start_job(target, start, start + dt.timedelta(days=45), None)
        finally:
            b.MAX_DAYS = old_max_days
            b.jobs.pop(job.id, None)

        self.assertEqual(job.date_to, dt.date(2026, 2, 14))

    def test_done_message_mentions_future_empty_period(self):
        job = b.Job("j1", {"user_id": 42}, dt.date.today(), dt.date.today() + dt.timedelta(days=1), None, b.Path("out"))

        self.assertIn("расписание могло быть еще не опубликовано", b.done_message(job))

    def test_worker_uses_configured_export_timeout(self):
        class Queue:
            def __init__(self, job):
                self.job = job

            def get(self):
                if self.job:
                    job, self.job = self.job, None
                    return job
                raise KeyboardInterrupt

            def task_done(self):
                pass

        job = b.Job("j1", {"user_id": 42}, dt.date(2026, 1, 1), dt.date(2026, 1, 31), None, b.Path("out"))
        old_timeout = b.EXPORT_TIMEOUT_SECONDS
        b.EXPORT_TIMEOUT_SECONDS = 123
        try:
            with mock.patch.object(b, "job_queue", Queue(job)):
                with mock.patch.object(b, "show_menu"):
                    with mock.patch.object(b, "upload_and_send_file"):
                        with mock.patch.object(b.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="rows=0\n", stderr="")) as run:
                            with self.assertRaises(KeyboardInterrupt):
                                b.worker()
        finally:
            b.EXPORT_TIMEOUT_SECONDS = old_timeout

        self.assertEqual(run.call_args.kwargs["timeout"], 123)

    def test_worker_marks_export_with_only_log_errors_as_error(self):
        class Queue:
            def __init__(self, job):
                self.job = job

            def get(self):
                if self.job:
                    job, self.job = self.job, None
                    return job
                raise KeyboardInterrupt

            def task_done(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            outdir = b.Path(tmp)
            for name in ("report.xlsx", "report.pdf", "report.html", "report.csv"):
                (outdir / name).write_text("report", encoding="utf-8")
            (outdir / "run_log.csv").write_text("Суд,Дата,URL,Ошибка,Детали\n" + "x" * 80, encoding="utf-8")
            job = b.Job("j1", {"user_id": 42}, dt.date(2026, 8, 14), dt.date(2026, 8, 21), None, outdir)
            uploads = []

            with mock.patch.object(b, "job_queue", Queue(job)):
                with mock.patch.object(b, "show_menu"):
                    with mock.patch.object(b, "upload_and_send_file", side_effect=lambda _target, path, caption: uploads.append((path.name, caption))):
                        with mock.patch.object(b.subprocess, "run", return_value=mock.Mock(returncode=2, stdout="rows=0\n", stderr="")):
                            with self.assertRaises(KeyboardInterrupt):
                                b.worker()

        self.assertEqual(job.status, "error")
        self.assertIn("rows=0", job.error)
        self.assertNotIn(("report.xlsx", "Excel-отчет"), uploads)
        self.assertIn(("run_log.csv", "Лог выполнения"), uploads)

    def test_worker_posts_final_menu_after_completion(self):
        class Queue:
            def __init__(self, job):
                self.job = job

            def get(self):
                if self.job:
                    job, self.job = self.job, None
                    return job
                raise KeyboardInterrupt

            def task_done(self):
                pass

        b.sessions.clear()
        b.sessions["42"] = b.Session(menu_message_id="old")
        job = b.Job("j1", {"user_id": 42}, dt.date(2026, 1, 1), dt.date(2026, 1, 1), None, b.Path("/tmp/no-files"))
        calls = []

        def fake_request(method, path, params=None, body=None):
            calls.append((method, path, params))
            return {"success": True, "message": {"body": {"mid": "new"}}}

        with mock.patch.object(b, "job_queue", Queue(job)):
            with mock.patch.object(b, "request", side_effect=fake_request):
                with mock.patch.object(b.time, "sleep"):
                    with mock.patch.object(b.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="rows=0\n", stderr="")):
                        with self.assertRaises(KeyboardInterrupt):
                            b.worker()

        self.assertEqual(calls[0][0], "PUT")
        self.assertEqual(calls[-1][0:2], ("POST", "/messages"))

    def test_worker_posts_error_menu_after_log(self):
        class Queue:
            def __init__(self, job):
                self.job = job

            def get(self):
                if self.job:
                    job, self.job = self.job, None
                    return job
                raise KeyboardInterrupt

            def task_done(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            outdir = b.Path(tmp)
            (outdir / "run_log.csv").write_text("log", encoding="utf-8")
            b.sessions.clear()
            b.sessions["42"] = b.Session(menu_message_id="old")
            job = b.Job("j1", {"user_id": 42}, dt.date(2026, 1, 1), dt.date(2026, 1, 1), None, outdir)
            calls = []

            def fake_request(method, path, params=None, body=None):
                calls.append((method, path, params))
                if path == "/uploads":
                    return {"url": "https://upload.test"}
                return {"message": {"body": {"mid": "new"}}}

            with mock.patch.object(b, "job_queue", Queue(job)):
                with mock.patch.object(b, "request", side_effect=fake_request):
                    with mock.patch.object(b.time, "sleep"):
                        with mock.patch.object(b, "multipart_upload", return_value={"token": "file"}):
                            with mock.patch.object(b.subprocess, "run", return_value=mock.Mock(returncode=1, stdout="", stderr="boom")):
                                with self.assertRaises(KeyboardInterrupt):
                                    b.worker()

        self.assertEqual(calls[-1][0:2], ("POST", "/messages"))

    def test_worker_uses_configured_http_timeout(self):
        class Queue:
            def __init__(self, job):
                self.job = job

            def get(self):
                if self.job:
                    job, self.job = self.job, None
                    return job
                raise KeyboardInterrupt

            def task_done(self):
                pass

        job = b.Job("j1", {"user_id": 42}, dt.date(2026, 1, 1), dt.date(2026, 1, 31), None, b.Path("out"))
        old_http_timeout = b.HTTP_TIMEOUT_SECONDS
        b.HTTP_TIMEOUT_SECONDS = 25
        try:
            with mock.patch.object(b, "job_queue", Queue(job)):
                with mock.patch.object(b, "show_menu"):
                    with mock.patch.object(b, "upload_and_send_file"):
                        with mock.patch.object(b.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="rows=0\n", stderr="")) as run:
                            with self.assertRaises(KeyboardInterrupt):
                                b.worker()
        finally:
            b.HTTP_TIMEOUT_SECONDS = old_http_timeout

        self.assertIn("25", run.call_args.args[0])

    def test_save_weekly_chat_writes_chat_id(self):
        with mock.patch.object(b, "WEEKLY_CHAT_ID_FILE", b.Path("/tmp/sud-weekly-chat-test")):
            try:
                self.assertTrue(b.save_weekly_chat({"chat_id": 777, "user_id": 42}))
                self.assertEqual(b.Path("/tmp/sud-weekly-chat-test").read_text(encoding="utf-8"), "777")
                self.assertFalse(b.save_weekly_chat({"user_id": 42}))
            finally:
                b.Path("/tmp/sud-weekly-chat-test").unlink(missing_ok=True)

    def test_non_admin_gets_auth_request(self):
        with mock.patch.object(b, "ADMIN_USER_IDS", {6393482}):
            with mock.patch.object(b, "send_auth_request") as send_auth_request:
                with mock.patch.object(b, "show_menu") as show_menu:
                    with mock.patch.object(b, "ack_callback") as ack:
                        b.handle({"user_id": 1}, "/start", callback_id="cb1")

        send_auth_request.assert_called_once_with({"user_id": 1})
        show_menu.assert_not_called()
        ack.assert_called_once_with("cb1")

    def test_auth_request_stores_and_reuses_screen(self):
        b.sessions.clear()
        calls = []

        def fake_request(method, path, params=None, body=None):
            calls.append((method, path, params, body))
            return {"message": {"body": {"mid": "auth-1"}}}

        with mock.patch.object(b, "request", side_effect=fake_request):
            with mock.patch.object(b.time, "sleep"):
                b.send_auth_request({"user_id": 1})
                b.send_auth_request({"user_id": 1})

        self.assertEqual(calls[0][0:3], ("POST", "/messages", {"user_id": 1}))
        self.assertEqual(calls[1][0:3], ("PUT", "/messages", {"message_id": "auth-1"}))
        self.assertEqual(calls[0][3]["attachments"][0]["payload"]["buttons"][0][0]["type"], "request_contact")
        self.assertEqual(b.sessions["1"].menu_message_id, "auth-1")

    def test_screen_state_survives_restart(self):
        b.sessions.clear()
        b.verified_admin_phones.clear()
        with tempfile.TemporaryDirectory() as tmp:
            state_file = b.Path(tmp) / "state.json"
            with mock.patch.object(b, "STATE_FILE", state_file):
                b.sessions["1"] = b.Session(menu_message_id="screen-1", screen_type="auth")
                b.verified_admin_phones["1"] = "79320588150"
                b.save_state()
                b.sessions.clear()
                b.verified_admin_phones.clear()
                b.load_state()

        self.assertEqual(b.sessions["1"].menu_message_id, "screen-1")
        self.assertEqual(b.sessions["1"].screen_type, "auth")
        self.assertIn("1", b.verified_admin_phones)

    def test_legacy_verified_key_does_not_make_user_admin(self):
        b.sessions.clear()
        b.verified_admin_phones.clear()
        with tempfile.TemporaryDirectory() as tmp:
            state_file = b.Path(tmp) / "state.json"
            state_file.write_text(
                b.json.dumps({"verified_admin_keys": ["23325864"], "verified_admin_phones": {"1": "79320588150"}}),
                encoding="utf-8",
            )
            with mock.patch.object(b, "STATE_FILE", state_file):
                with mock.patch.object(b, "ADMIN_USER_IDS", {6393482}):
                    with mock.patch.object(b, "ADMIN_PHONES", {"79320588150"}):
                        b.load_state()
                        self.assertFalse(b.is_admin({"user_id": 23325864}))
                        self.assertTrue(b.is_admin({"user_id": 1}))

    def test_contact_success_replaces_auth_screen_with_menu(self):
        b.sessions.clear()
        calls = []

        def fake_request(method, path, params=None, body=None):
            calls.append((method, path, params, body))
            if method == "POST" and params == {"user_id": 1}:
                return {"message": {"body": {"mid": "auth-1"}}}
            return {"success": True}

        with mock.patch.object(b, "ADMIN_USER_IDS", {6393482}):
            with mock.patch.object(b, "ADMIN_PHONES", {"79320588150"}):
                with mock.patch.object(b, "request", side_effect=fake_request):
                    with mock.patch.object(b, "ack_callback"):
                        with mock.patch.object(b.time, "sleep"):
                            b.handle({"user_id": 1}, "/start")
                            b.handle(*b.extract_event(self.signed_contact_update()))

        self.assertEqual(calls[0][0:3], ("POST", "/messages", {"user_id": 1}))
        self.assertEqual(calls[-2][0:3], ("DELETE", "/messages", {"message_id": "auth-1"}))
        self.assertEqual(calls[-1][0:3], ("POST", "/messages", {"user_id": 1}))
        self.assertIn("Доступ подтвержден", calls[-1][3]["text"])

    def test_screen_type_change_deletes_previous_screen(self):
        b.sessions.clear()
        b.sessions["1"] = b.Session(menu_message_id="auth-1", screen_type="auth")
        calls = []

        def fake_request(method, path, params=None, body=None):
            calls.append((method, path, params, body))
            if method == "POST":
                return {"message": {"body": {"mid": "menu-1"}}}
            return {"success": True}

        with mock.patch.object(b, "request", side_effect=fake_request):
            with mock.patch.object(b.time, "sleep"):
                b.show_menu({"user_id": 1}, "Доступ подтвержден.", b.main_buttons())

        self.assertEqual(calls[0][0:3], ("DELETE", "/messages", {"message_id": "auth-1"}))
        self.assertEqual(calls[1][0:3], ("POST", "/messages", {"user_id": 1}))
        self.assertEqual(b.sessions["1"].menu_message_id, "menu-1")
        self.assertEqual(b.sessions["1"].screen_type, "menu")

    def test_auth_request_without_user_id_has_no_contact_button(self):
        b.sessions.clear()
        bodies = []

        def fake_request(method, path, params=None, body=None):
            bodies.append(body)
            return {"message": {"body": {"mid": "auth-1"}}}

        with mock.patch.object(b, "request", side_effect=fake_request):
            with mock.patch.object(b.time, "sleep"):
                b.send_auth_request({"chat_id": 7})

        self.assertNotIn("attachments", bodies[0])
        self.assertIn("Откройте бота в личке", bodies[0]["text"])

    def test_contact_phone_authorizes_admin_and_notifies(self):
        with mock.patch.object(b, "ADMIN_USER_IDS", {6393482}):
            with mock.patch.object(b, "ADMIN_PHONES", {"79320588150"}):
                target, text, payload, callback_id, source_message_id, contact_phone = b.extract_event(
                    self.signed_contact_update()
                )
                with mock.patch.object(b, "show_menu") as show_menu:
                    with mock.patch.object(b, "send_text") as send_text:
                        with mock.patch.object(b, "ack_callback"):
                            b.handle(target, text, payload, callback_id, source_message_id, contact_phone)

        self.assertEqual(contact_phone, "79320588150")
        self.assertIn("1", b.verified_admin_phones)
        show_menu.assert_called_once()
        send_text.assert_called_once()
        self.assertEqual(send_text.call_args.args[0], {"user_id": 6393482})

    def test_contact_login_does_not_verify_chat_id(self):
        with mock.patch.object(b, "ADMIN_USER_IDS", {6393482}):
            with mock.patch.object(b, "ADMIN_PHONES", {"79320588150"}):
                with mock.patch.object(b, "notify_admins_about_contact"):
                    with mock.patch.object(b, "show_menu"):
                        with mock.patch.object(b, "ack_callback"):
                            b.handle({"user_id": 1, "chat_id": 7}, "", contact_phone="79320588150")

            self.assertTrue(b.is_admin({"user_id": 1}))
            self.assertFalse(b.is_admin({"chat_id": 7}))

    def test_non_admin_user_and_phone_do_not_open_menu(self):
        target, text, payload, callback_id, source_message_id, contact_phone = b.extract_event(
            self.signed_contact_update(user_id=23325864, phone="+7 912 911-11-19")
        )
        with mock.patch.object(b, "ADMIN_USER_IDS", {6393482}):
            with mock.patch.object(b, "ADMIN_PHONES", {"79320588150"}):
                with mock.patch.object(b, "show_menu") as show_menu:
                    with mock.patch.object(b, "send_auth_request") as send_auth_request:
                        with mock.patch.object(b, "notify_admins_about_contact") as notify:
                            with mock.patch.object(b, "ack_callback"):
                                b.handle(target, text, payload, callback_id, source_message_id, contact_phone)
                self.assertFalse(b.is_admin({"user_id": 23325864}))

        self.assertEqual(contact_phone, "79129111119")
        show_menu.assert_not_called()
        send_auth_request.assert_called_once_with({"user_id": 23325864})
        notify.assert_called_once_with({"user_id": 23325864}, "79129111119", False)

    def test_empty_admin_ids_do_not_make_user_admin(self):
        b.verified_admin_phones.clear()
        with mock.patch.object(b, "ADMIN_USER_IDS", set()):
            with mock.patch.object(b, "ADMIN_PHONES", {"79320588150"}):
                self.assertFalse(b.is_admin({"user_id": 23325864}))

    def test_stale_verified_phone_not_in_admin_phones_does_not_open_menu(self):
        b.verified_admin_phones.clear()
        b.verified_admin_phones["23325864"] = "79129111119"
        with mock.patch.object(b, "ADMIN_USER_IDS", {6393482}):
            with mock.patch.object(b, "ADMIN_PHONES", {"79320588150"}):
                self.assertFalse(b.is_admin({"user_id": 23325864}))

    def test_startup_prunes_saved_menu_for_non_admin(self):
        b.sessions.clear()
        b.sessions["23325864"] = b.Session(menu_message_id="menu-1", screen_type="menu")
        calls = []

        with mock.patch.object(b, "ADMIN_USER_IDS", {6393482}):
            with mock.patch.object(b, "ADMIN_PHONES", {"79320588150"}):
                with mock.patch.object(b, "delete_message", side_effect=lambda message_id: calls.append(message_id)):
                    b.prune_non_admin_screens()

        self.assertEqual(calls, ["menu-1"])
        self.assertIsNone(b.sessions["23325864"].menu_message_id)
        self.assertEqual(b.sessions["23325864"].screen_type, "")

    def test_verified_contact_can_open_menu_next_time(self):
        with mock.patch.object(b, "ADMIN_USER_IDS", {6393482}):
            with mock.patch.object(b, "ADMIN_PHONES", {"79320588150"}):
                with mock.patch.object(b, "notify_admins_about_contact"):
                    with mock.patch.object(b, "show_menu"):
                        with mock.patch.object(b, "ack_callback"):
                            b.handle({"user_id": 1}, "", contact_phone="79320588150")
            with mock.patch.object(b, "show_menu") as show_menu:
                with mock.patch.object(b, "send_auth_request") as send_auth_request:
                    with mock.patch.object(b, "ack_callback"):
                        b.handle({"user_id": 1}, "/start")

        show_menu.assert_called_once()
        send_auth_request.assert_not_called()

    def test_admin_can_open_menu(self):
        with mock.patch.object(b, "ADMIN_USER_IDS", {6393482}):
            with mock.patch.object(b, "show_menu") as show_menu:
                with mock.patch.object(b, "ack_callback"):
                    b.handle({"user_id": 6393482}, "/start")

        show_menu.assert_called_once()

    def test_commerce_password_opens_period_menu(self):
        b.sessions.clear()
        shown = []
        with mock.patch.object(b, "COMMERCE_PASSWORD", "secret"):
            with mock.patch.object(b, "show_menu", side_effect=lambda _target, text, _buttons, *_args: shown.append(text)):
                with mock.patch.object(b, "ack_callback"):
                    b.handle({"user_id": 42}, "", "commerce", "cb1")
                    b.handle({"user_id": 42}, "secret")

        self.assertEqual(b.sessions["42"].step, "period")
        self.assertEqual(shown[-1], "Выберите период выгрузки по коммерции.")

    def test_commerce_prompt_replaces_main_menu(self):
        b.sessions.clear()
        b.sessions["42"] = b.Session(menu_message_id="menu-1")
        calls = []

        def fake_request(method, path, params=None, body=None):
            calls.append((method, path, params, body))
            return {"success": True}

        with mock.patch.object(b, "COMMERCE_PASSWORD", "secret"):
            with mock.patch.object(b, "request", side_effect=fake_request):
                with mock.patch.object(b, "ack_callback"):
                    with mock.patch.object(b.time, "sleep"):
                        b.handle({"user_id": 42}, "", "commerce", "cb1")

        self.assertEqual(calls[0][0:3], ("PUT", "/messages", {"message_id": "menu-1"}))
        self.assertEqual(calls[0][3]["text"], "Введите пароль для выгрузки по коммерции.")
        self.assertEqual(b.sessions["42"].menu_message_id, "menu-1")

    def test_bad_commerce_password_stays_on_password_step(self):
        b.sessions.clear()
        shown = []
        with mock.patch.object(b, "COMMERCE_PASSWORD", "secret"):
            with mock.patch.object(b, "show_menu", side_effect=lambda _target, text, _buttons, *_args: shown.append(text)):
                with mock.patch.object(b, "ack_callback"):
                    b.handle({"user_id": 42}, "", "commerce", "cb1")
                    b.handle({"user_id": 42}, "wrong")

        self.assertEqual(b.sessions["42"].step, "commerce_password")
        self.assertEqual(shown[-1], "Неверный пароль. Введите пароль еще раз.")

    def test_bad_commerce_password_reuses_password_screen(self):
        b.sessions.clear()
        b.sessions["42"] = b.Session(step="commerce_password", menu_message_id="commerce-1")
        b.commerce_password_pending.add("42")
        calls = []

        def fake_request(method, path, params=None, body=None):
            calls.append((method, path, params, body))
            return {"success": True}

        with mock.patch.object(b, "COMMERCE_PASSWORD", "secret"):
            with mock.patch.object(b, "request", side_effect=fake_request):
                with mock.patch.object(b, "ack_callback"):
                    with mock.patch.object(b.time, "sleep"):
                        b.handle({"user_id": 42}, "wrong")

        self.assertEqual(calls[0][0:3], ("PUT", "/messages", {"message_id": "commerce-1"}))
        self.assertEqual(calls[0][3]["text"], "Неверный пароль. Введите пароль еще раз.")

    def test_commerce_password_blocks_stale_period_buttons(self):
        b.sessions.clear()
        b.commerce_password_pending.clear()
        shown = []
        with mock.patch.object(b, "COMMERCE_PASSWORD", "secret"):
            with mock.patch.object(b, "show_menu", side_effect=lambda _target, text, _buttons, *_args: shown.append(text)):
                with mock.patch.object(b, "ack_callback"):
                    b.handle({"user_id": 42}, "", "commerce", "cb1")
                    b.handle({"user_id": 42}, "", "period_current", "cb2")

        self.assertEqual(b.sessions["42"].step, "commerce_password")
        self.assertEqual(shown[-1], "Введите пароль для выгрузки по коммерции.")

    def test_commerce_password_blocks_text_period_commands(self):
        b.sessions.clear()
        b.commerce_password_pending.clear()
        shown = []
        with mock.patch.object(b, "COMMERCE_PASSWORD", "secret"):
            with mock.patch.object(b, "show_menu", side_effect=lambda _target, text, _buttons, *_args: shown.append(text)):
                with mock.patch.object(b, "ack_callback"):
                    b.handle({"user_id": 42}, "", "commerce", "cb1")
                    for command in ("/period", "/month", "/week"):
                        b.handle({"user_id": 42}, command)

        self.assertEqual(b.sessions["42"].step, "commerce_password")
        self.assertEqual(shown[-3:], ["Введите пароль для выгрузки по коммерции."] * 3)

    def test_commerce_password_survives_callback_target_shape_drift(self):
        b.sessions.clear()
        b.commerce_password_pending.clear()
        shown = []
        with mock.patch.object(b, "COMMERCE_PASSWORD", "secret"):
            with mock.patch.object(b, "show_menu", side_effect=lambda _target, text, _buttons, *_args: shown.append(text)):
                with mock.patch.object(b, "ack_callback"):
                    b.handle({"chat_id": 7, "user_id": 42}, "", "commerce", "cb1")
                    b.handle({"user_id": 42}, "", "week", "cb2")

        self.assertEqual(b.sessions["42"].step, "commerce_password")
        self.assertEqual(shown[-1], "Введите пароль для выгрузки по коммерции.")

    def test_commerce_password_does_not_survive_to_chat_only_target(self):
        b.sessions.clear()
        b.commerce_password_pending.clear()
        shown = []
        with mock.patch.object(b, "COMMERCE_PASSWORD", "secret"):
            with mock.patch.object(b, "show_menu", side_effect=lambda _target, text, _buttons=None, *_args: shown.append(text)):
                with mock.patch.object(b, "send_auth_request", side_effect=lambda _target: shown.append("auth")):
                    with mock.patch.object(b, "ack_callback"):
                        b.handle({"user_id": 42, "chat_id": 7}, "", "commerce", "cb1")
                        b.handle({"chat_id": 7}, "", "week", "cb2")

        self.assertEqual(b.sessions["42"].step, "commerce_password")
        self.assertEqual(shown[-1], "auth")

    def test_commerce_password_text_wins_over_reserved_actions(self):
        b.sessions.clear()
        shown = []
        with mock.patch.object(b, "COMMERCE_PASSWORD", "week"):
            with mock.patch.object(b, "show_menu", side_effect=lambda _target, text, _buttons, *_args: shown.append(text)):
                with mock.patch.object(b, "ack_callback"):
                    b.handle({"user_id": 42}, "", "commerce", "cb1")
                    b.handle({"user_id": 42}, "week")

        self.assertEqual(b.sessions["42"].step, "period")
        self.assertEqual(shown[-1], "Выберите период выгрузки по коммерции.")


if __name__ == "__main__":
    unittest.main()
