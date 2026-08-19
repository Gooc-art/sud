from __future__ import annotations

import unittest
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from godmod.bot import handle_callback_query, handle_command, handle_update, initialize_bot_menu
from godmod.bot_commands import ParsedCommand, START_TEXT
from godmod.bot_callbacks import build_nav_callback, build_period_callback
from godmod.bot_state import WIZARD_STATES, ensure_wizard_state, get_wizard_state
from godmod.config import RuntimeConfig
from godmod.export.reports import ReportArtifacts
from godmod.models import AccountCandidate, AccountMetrics, ReportBundle, ScoreBreakdown, SearchRequest, ServiceQuery, RankedAccount
from godmod.operator_reports import LatestReportSnapshot
from godmod.settings import AppSettings
from godmod.telegram_api import TelegramApiError


class BotFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        WIZARD_STATES.clear()

    def tearDown(self) -> None:
        WIZARD_STATES.clear()

    def test_handle_callback_query_accepts_all_time_period_in_confirm_step(self) -> None:
        chat_id = 101
        user_id = 501
        state = ensure_wizard_state(chat_id, user_id, default_top_n=20, wizard_message_id=55)
        state.city = "Салехард"
        state.services = ["маникюр"]
        state.period_days = 0
        state.report_mode = "all"
        state.step = "confirm"
        settings = _settings()
        client = Mock()

        with patch(
            "godmod.bot.generate_report",
            return_value=ReportArtifacts(workbook=Path("output/test.xlsx"), pdf=None, manifest=Path("output/test.json")),
        ) as generate_report:
            handle_callback_query(
                client,
                settings,
                {
                    "id": "cb-1",
                    "data": build_nav_callback("confirm"),
                    "from": {"id": user_id},
                    "message": {
                        "chat": {"id": chat_id},
                        "message_id": 55,
                    },
                },
            )

        generate_report.assert_called_once()
        request = generate_report.call_args.args[0]
        self.assertEqual(request.cities, ["Салехард"])
        self.assertEqual([service.name for service in request.services], ["маникюр"])
        self.assertEqual(request.period_days, 0)
        self.assertEqual(request.report_mode, "all")
        self.assertEqual(get_wizard_state(chat_id, user_id).step, "done")
        client.send_document.assert_called_once_with(
            chat_id,
            Path("output/test.xlsx"),
            caption=unittest.mock.ANY,
        )

    def test_handle_callback_query_sends_manifest_diagnostics_for_empty_report(self) -> None:
        chat_id = 102
        user_id = 502
        state = ensure_wizard_state(chat_id, user_id, default_top_n=20, wizard_message_id=56)
        state.city = "Салехард"
        state.services = ["маникюр"]
        state.period_days = 30
        state.report_mode = "all"
        state.step = "confirm"
        settings = _settings()
        client = Mock()

        artifacts = ReportArtifacts(
            workbook=Path("output/empty.xlsx"),
            pdf=None,
            manifest=Path("output/empty.json"),
            manifest_payload={
                "counts": {
                    "ranked_accounts": 0,
                    "raw_candidates": 8,
                    "filter_debug": 8,
                },
                "meta": {
                    "platform_failures": [
                        {"platform": "telegram", "error": "session is not authorized"},
                    ]
                },
            },
        )

        with patch("godmod.bot.generate_report", return_value=artifacts):
            handle_callback_query(
                client,
                settings,
                {
                    "id": "cb-empty",
                    "data": build_nav_callback("confirm"),
                    "from": {"id": user_id},
                    "message": {
                        "chat": {"id": chat_id},
                        "message_id": 56,
                    },
                },
            )

        self.assertEqual(get_wizard_state(chat_id, user_id).step, "done")
        first_call = client.send_document.call_args_list[0]
        self.assertEqual(first_call.args[0], chat_id)
        self.assertEqual(first_call.args[1], Path("output/empty.xlsx"))
        self.assertIn("итоговая выгрузка пустая", first_call.kwargs["caption"])
        self.assertIn("Строк в all_accounts: 0", first_call.kwargs["caption"])
        client.send_document.assert_any_call(
            chat_id,
            Path("output/empty.json"),
            caption=unittest.mock.ANY,
        )
        manifest_call = client.send_document.call_args_list[-1]
        self.assertEqual(manifest_call.args[1], Path("output/empty.json"))
        self.assertIn("JSON-manifest пустой выгрузки.", manifest_call.kwargs["caption"])
        self.assertIn("Сырых кандидатов: 8", manifest_call.kwargs["caption"])

    def test_initialize_bot_menu_clears_commands_and_resets_default_button(self) -> None:
        client = Mock()

        initialize_bot_menu(client)

        client.set_my_commands.assert_called_once_with([])
        client.delete_my_commands.assert_called_once_with()
        client.set_chat_menu_button.assert_called_once_with({"type": "default"})

    def test_handle_start_command_sends_compact_start_text(self) -> None:
        chat_id = 120
        user_id = 220
        settings = _settings()
        client = Mock()

        handle_command(
            client,
            settings,
            chat_id,
            user_id,
            ParsedCommand(name="start", args={}),
        )

        client.send_message.assert_any_call(chat_id, START_TEXT, reply_markup=unittest.mock.ANY)
        state = get_wizard_state(chat_id, user_id)
        assert state is not None
        self.assertEqual(state.step, "select_city")

    def test_handle_start_command_deletes_previous_transient_messages(self) -> None:
        chat_id = 121
        user_id = 221
        settings = _settings()
        client = Mock()
        client.send_message.return_value = {"message_id": 99}
        state = ensure_wizard_state(chat_id, user_id, default_top_n=20, wizard_message_id=77)
        state.transient_message_ids = [88]

        with patch("godmod.bot.Timer") as timer_cls:
            handle_command(
                client,
                settings,
                chat_id,
                user_id,
                ParsedCommand(name="start", args={}),
            )

        client.delete_message.assert_called_once_with(chat_id, 88)
        self.assertEqual(get_wizard_state(chat_id, user_id).transient_message_ids, [99])
        timer_cls.assert_called_once()

    def test_handle_cities_command_resets_state_and_sends_new_wizard_when_text_is_unchanged(self) -> None:
        chat_id = 122
        user_id = 222
        settings = _settings()
        client = Mock()
        client.edit_message_text.side_effect = TelegramApiError("Bad Request: message is not modified")
        client.send_message.return_value = {"message_id": 101}

        state = ensure_wizard_state(chat_id, user_id, default_top_n=20, wizard_message_id=77)
        state.step = "select_city"
        state.city = "Салехард"
        state.services = ["маникюр"]
        state.period_days = 60
        state.report_mode = "all"

        handle_command(
            client,
            settings,
            chat_id,
            user_id,
            ParsedCommand(name="cities", args={}),
        )

        state = get_wizard_state(chat_id, user_id)
        assert state is not None
        self.assertEqual(state.step, "select_city")
        self.assertIsNone(state.city)
        self.assertEqual(state.services, [])
        self.assertIsNone(state.period_days)
        self.assertIsNone(state.report_mode)
        self.assertEqual(state.wizard_message_id, 101)
        client.delete_message.assert_called_once_with(chat_id, 77)
        client.send_message.assert_called_once_with(chat_id, unittest.mock.ANY, reply_markup=unittest.mock.ANY)

    def test_handle_callback_query_replaces_previous_wizard_message(self) -> None:
        chat_id = 202
        user_id = 602
        state = ensure_wizard_state(chat_id, user_id, default_top_n=20, wizard_message_id=77)
        state.city = "Салехард"
        state.services = ["маникюр"]
        state.step = "select_period"
        settings = _settings()
        client = Mock()
        client.send_message.return_value = {"message_id": 88}

        handle_callback_query(
            client,
            settings,
            {
                "id": "cb-2",
                "data": build_period_callback(0),
                "from": {"id": user_id},
                "message": {
                    "chat": {"id": chat_id},
                    "message_id": 77,
                },
            },
        )

        self.assertEqual(get_wizard_state(chat_id, user_id).period_days, 0)
        self.assertEqual(get_wizard_state(chat_id, user_id).step, "select_mode")
        self.assertEqual(get_wizard_state(chat_id, user_id).wizard_message_id, 88)
        client.answer_callback_query.assert_called_once_with("cb-2", text="Период: За всё время")
        client.delete_message.assert_called_once_with(chat_id, 77)
        client.send_message.assert_called_once_with(chat_id, unittest.mock.ANY, reply_markup=unittest.mock.ANY)

    def test_handle_command_markupplan_sends_plan_and_coverage_json(self) -> None:
        chat_id = 303
        user_id = 703
        settings = _settings()
        client = Mock()

        with patch(
            "godmod.bot.generate_validation_markup_plan",
            return_value=(
                Path("output/markup_plan.json"),
                Path("output/coverage.json"),
                {
                    "group_by": "city",
                    "batches_total": 14,
                    "pending_cases_total": 109,
                    "remaining_cases_total": 0,
                },
            ),
        ) as generate_markup:
            handle_command(
                client,
                settings,
                chat_id,
                user_id,
                ParsedCommand(
                    name="markupplan",
                    args={"group_by": "city", "batch_size": 10, "max_batches": 0},
                ),
            )

        generate_markup.assert_called_once_with(settings, group_by="city", batch_size=10, max_batches=0)
        client.send_document.assert_any_call(
            chat_id,
            Path("output/markup_plan.json"),
            caption=unittest.mock.ANY,
        )
        client.send_document.assert_any_call(
            chat_id,
            Path("output/coverage.json"),
            caption="Coverage live validation-dataset.",
        )

    def test_handle_update_requires_access_code_before_report_command(self) -> None:
        settings = _settings()
        settings.bot_access_code = "secret-pass"
        client = Mock()

        handle_update(
            client,
            settings,
            {
                "message": {
                    "chat": {"id": 700},
                    "from": {"id": 900},
                    "text": "/report Салехард | маникюр | 60 | 20",
                }
            },
        )

        client.send_message.assert_called_once_with(700, "Доступ к боту закрыт. Отправьте `/access <код>` и затем повторите команду.")

    def test_handle_command_access_authorizes_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = _settings(output_dir=Path(temp_dir) / "output")
            settings.bot_access_code = "secret-pass"
            client = Mock()

            handle_command(
                client,
                settings,
                701,
                901,
                ParsedCommand(name="access", args={"code": "secret-pass"}),
            )

            self.assertIn(
                unittest.mock.call(701, "Доступ подтверждён. Можно запускать сбор.", reply_markup=unittest.mock.ANY),
                client.send_message.call_args_list,
            )

    def test_handle_command_report_notifies_when_another_run_is_active(self) -> None:
        settings = _settings()
        client = Mock()
        state = ensure_wizard_state(702, 902, default_top_n=20)

        with patch(
            "godmod.bot.try_acquire_report_run",
            return_value=(None, unittest.mock.Mock(user_id="user:777", chat_id="chat:ops", started_at=datetime(2026, 4, 21, 8, 0, tzinfo=UTC), cities=["Салехард"], services=["маникюр"], period_days=60)),
        ):
            handle_command(
                client,
                settings,
                702,
                902,
                ParsedCommand(
                    name="report",
                    args={
                        "cities": ["Салехард"],
                        "services": ["маникюр"],
                        "period_days": 60,
                        "top_n": 20,
                        "report_mode": "all",
                    },
                ),
            )

        sent_texts = [call.args[1] for call in client.send_message.call_args_list]
        self.assertTrue(any("Сбор уже запущен." in text for text in sent_texts))

    def test_handle_command_health_sends_snapshot_json(self) -> None:
        chat_id = 304
        user_id = 704
        settings = _settings()
        client = Mock()

        with patch(
            "godmod.bot.generate_operator_health_report",
            return_value=(
                Path("output/bot_health.json"),
                {
                    "uptime_seconds": 42,
                    "runtime": {"platforms": ["vk"], "use_mock_data": False},
                    "latest_report": {"available": False},
                },
            ),
        ) as generate_health:
            handle_command(
                client,
                settings,
                chat_id,
                user_id,
                ParsedCommand(name="health", args={}),
            )

        generate_health.assert_called_once_with(settings)
        client.send_document.assert_called_once_with(
            chat_id,
            Path("output/bot_health.json"),
            caption=unittest.mock.ANY,
        )

    def test_handle_command_dailyreport_sends_snapshot_json(self) -> None:
        chat_id = 307
        user_id = 707
        settings = _settings()
        client = Mock()

        with patch(
            "godmod.bot.generate_operator_daily_report",
            return_value=(
                Path("output/daily_report.json"),
                {
                    "report_date_label": "19.04.2026",
                    "runs": {
                        "total": 4,
                        "non_empty": 3,
                        "empty": 1,
                        "with_platform_failures": 1,
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
                },
            ),
        ) as generate_daily:
            handle_command(
                client,
                settings,
                chat_id,
                user_id,
                ParsedCommand(name="dailyreport", args={}),
            )

        generate_daily.assert_called_once_with(settings)
        client.send_document.assert_called_once_with(
            chat_id,
            Path("output/daily_report.json"),
            caption=unittest.mock.ANY,
        )

    def test_handle_command_lastreport_sends_workbook_pdf_and_manifest(self) -> None:
        chat_id = 305
        user_id = 705
        settings = _settings()
        client = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "latest.json"
            manifest.write_text("{}", encoding="utf-8")
            snapshot = LatestReportSnapshot(
                workbook=Path("output/latest.xlsx"),
                pdf=Path("output/latest.pdf"),
                manifest=manifest,
                manifest_payload={
                    "generated_at": "2026-03-26T11:38:27+00:00",
                    "request": {"cities": ["Салехард"], "services": ["маникюр"]},
                    "counts": {"ranked_accounts": 8},
                    "pdf": {"status": "created"},
                },
            )

            with patch("godmod.bot.find_latest_report_snapshot", return_value=snapshot) as find_snapshot:
                handle_command(
                    client,
                    settings,
                    chat_id,
                    user_id,
                    ParsedCommand(name="lastreport", args={}),
                )

        find_snapshot.assert_called_once_with(settings.runtime.output_dir)
        client.send_document.assert_any_call(
            chat_id,
            Path("output/latest.xlsx"),
            caption=unittest.mock.ANY,
        )
        client.send_document.assert_any_call(
            chat_id,
            Path("output/latest.pdf"),
            caption="PDF-версия последней выгрузки.",
        )
        client.send_document.assert_any_call(
            chat_id,
            manifest,
            caption="JSON-manifest последней выгрузки.",
        )

    def test_handle_command_lastreport_reports_missing_snapshot(self) -> None:
        chat_id = 306
        user_id = 706
        settings = _settings()
        client = Mock()

        with patch("godmod.bot.find_latest_report_snapshot", return_value=None):
            handle_command(
                client,
                settings,
                chat_id,
                user_id,
                ParsedCommand(name="lastreport", args={}),
            )

        client.send_message.assert_called_once_with(
            chat_id,
            "Последняя выгрузка ещё не найдена в output.",
            reply_markup=unittest.mock.ANY,
        )

    def test_learn_vk_profile_seeds_from_report_merges_ranked_vk_urls(self) -> None:
        from godmod.bot import learn_vk_profile_seeds_from_report

        with unittest.mock.patch("godmod.bot.merge_vk_profile_seed_entries") as merge_entries:
            settings = _settings(vk_profile_seeds_path=Path("data/vk_profile_seeds.json"))
            request = SearchRequest(
                cities=["Новый Уренгой"],
                services=[ServiceQuery(name="маникюр")],
                period_days=0,
                platforms=["vk"],
                top_n=20,
            )
            bundle = ReportBundle(
                request=request,
                ranked_accounts=[
                    RankedAccount(
                        candidate=AccountCandidate(
                            service="маникюр",
                            city="Новый Уренгой",
                            platform="vk",
                            account_name="Salon Tvoy",
                            account_url="https://vk.com/salon_tvoy",
                            username_or_id="salon_tvoy",
                            description="Маникюр Новый Уренгой",
                        ),
                        metrics=AccountMetrics(
                            posts_in_period=1,
                            last_post_at=None,
                            avg_likes=None,
                            avg_comments=None,
                            avg_reposts=None,
                            avg_views=None,
                            commercial_markers=[],
                            city_signals=[],
                            stability_ratio=1.0,
                        ),
                        score=ScoreBreakdown(activity=1.0, engagement=1.0, commercial=1.0, locality=1.0, stability=1.0),
                        evidence_posts=[],
                        activity_class="активно",
                    ),
                    RankedAccount(
                        candidate=AccountCandidate(
                            service="маникюр",
                            city="Новый Уренгой",
                            platform="vk",
                            account_name="White Kot",
                            account_url="https://vk.com/white_kot_nur",
                            username_or_id="white_kot_nur",
                            description="Маникюр Новый Уренгой",
                        ),
                        metrics=AccountMetrics(
                            posts_in_period=1,
                            last_post_at=None,
                            avg_likes=None,
                            avg_comments=None,
                            avg_reposts=None,
                            avg_views=None,
                            commercial_markers=[],
                            city_signals=[],
                            stability_ratio=1.0,
                        ),
                        score=ScoreBreakdown(activity=1.0, engagement=1.0, commercial=1.0, locality=1.0, stability=1.0),
                        evidence_posts=[],
                        activity_class="активно",
                    ),
                ],
                search_log=[],
                duplicates_review=[],
            )

            learn_vk_profile_seeds_from_report(settings, request, bundle)

        merge_entries.assert_called_once()
        seed_path = merge_entries.call_args.args[0]
        entries = merge_entries.call_args.args[1]
        self.assertEqual(seed_path, Path("data/vk_profile_seeds.json"))
        self.assertEqual(entries[0].city, "Новый Уренгой")
        self.assertEqual(entries[0].service, "маникюр")
        self.assertEqual(entries[0].urls, ["https://vk.com/salon_tvoy", "https://vk.com/white_kot_nur"])

    def test_learn_vk_profile_seeds_from_report_skips_hotel_like_food_amenity_pages(self) -> None:
        from godmod.bot import learn_vk_profile_seeds_from_report

        with unittest.mock.patch("godmod.bot.merge_vk_profile_seed_entries") as merge_entries:
            settings = _settings(vk_profile_seeds_path=Path("data/vk_profile_seeds.json"))
            request = SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="кофейня")],
                period_days=0,
                platforms=["vk"],
                top_n=20,
            )
            bundle = ReportBundle(
                request=request,
                ranked_accounts=[
                    RankedAccount(
                        candidate=AccountCandidate(
                            service="кофейня",
                            city="Салехард",
                            platform="vk",
                            account_name="Гостиница Арктика Салехард",
                            account_url="https://vk.com/arktika_89",
                            username_or_id="arktika_89",
                            description="Гостиница, номера, проживание, ресторан и кофейня на территории.",
                        ),
                        metrics=AccountMetrics(
                            posts_in_period=1,
                            last_post_at=None,
                            avg_likes=None,
                            avg_comments=None,
                            avg_reposts=None,
                            avg_views=None,
                            commercial_markers=[],
                            city_signals=[],
                            stability_ratio=1.0,
                        ),
                        score=ScoreBreakdown(activity=1.0, engagement=1.0, commercial=1.0, locality=1.0, stability=1.0),
                        evidence_posts=[],
                        activity_class="активно",
                    ),
                ],
                search_log=[],
                duplicates_review=[],
            )

            learn_vk_profile_seeds_from_report(settings, request, bundle)

        merge_entries.assert_not_called()

    def test_learn_telegram_profile_seeds_from_report_merges_ranked_telegram_urls(self) -> None:
        from godmod.bot import learn_telegram_profile_seeds_from_report

        with unittest.mock.patch("godmod.bot.merge_telegram_profile_seed_entries") as merge_entries:
            settings = _settings()
            settings.telegram_profile_seeds_path = Path("data/telegram_profile_seeds.json")
            request = SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="кофейня")],
                period_days=0,
                platforms=["telegram"],
                top_n=20,
            )
            bundle = ReportBundle(
                request=request,
                ranked_accounts=[
                    RankedAccount(
                        candidate=AccountCandidate(
                            service="кофейня",
                            city="Салехард",
                            platform="telegram",
                            account_name="DO.BRO Coffee",
                            account_url="https://t.me/dobro_salehard",
                            username_or_id="dobro_salehard",
                            description="Кофейня Салехард",
                        ),
                        metrics=AccountMetrics(
                            posts_in_period=1,
                            last_post_at=None,
                            avg_likes=None,
                            avg_comments=None,
                            avg_reposts=None,
                            avg_views=None,
                            commercial_markers=[],
                            city_signals=[],
                            stability_ratio=1.0,
                        ),
                        score=ScoreBreakdown(activity=1.0, engagement=1.0, commercial=1.0, locality=1.0, stability=1.0),
                        evidence_posts=[],
                        activity_class="активно",
                    ),
                ],
                search_log=[],
                duplicates_review=[],
            )

            learn_telegram_profile_seeds_from_report(settings, request, bundle)

        merge_entries.assert_called_once()
        seed_path = merge_entries.call_args.args[0]
        entries = merge_entries.call_args.args[1]
        self.assertEqual(seed_path, Path("data/telegram_profile_seeds.json"))
        self.assertEqual(entries[0].city, "Салехард")
        self.assertEqual(entries[0].service, "кофейня")
        self.assertEqual(entries[0].urls, ["https://t.me/dobro_salehard"])

    def test_learn_telegram_profile_seeds_from_report_merges_telegram_contacts_from_vk(self) -> None:
        from godmod.bot import learn_telegram_profile_seeds_from_report

        with unittest.mock.patch("godmod.bot.merge_telegram_profile_seed_entries") as merge_entries:
            settings = _settings()
            settings.telegram_profile_seeds_path = Path("data/telegram_profile_seeds.json")
            request = SearchRequest(
                cities=["Салехард"],
                services=[ServiceQuery(name="кофейня")],
                period_days=0,
                platforms=["vk", "telegram"],
                top_n=20,
            )
            bundle = ReportBundle(
                request=request,
                ranked_accounts=[
                    RankedAccount(
                        candidate=AccountCandidate(
                            service="кофейня",
                            city="Салехард",
                            platform="vk",
                            account_name="DO.BRO Coffee",
                            account_url="https://vk.com/dobro_salehard",
                            username_or_id="dobro_salehard",
                            description="Кофейня Салехард",
                            contacts={"telegram": ["@dobro_salehard", "https://t.me/dobro_salehard"]},
                        ),
                        metrics=AccountMetrics(
                            posts_in_period=1,
                            last_post_at=None,
                            avg_likes=None,
                            avg_comments=None,
                            avg_reposts=None,
                            avg_views=None,
                            commercial_markers=[],
                            city_signals=[],
                            stability_ratio=1.0,
                        ),
                        score=ScoreBreakdown(activity=1.0, engagement=1.0, commercial=1.0, locality=1.0, stability=1.0),
                        evidence_posts=[],
                        activity_class="активно",
                    ),
                ],
                search_log=[],
                duplicates_review=[],
            )

            learn_telegram_profile_seeds_from_report(settings, request, bundle)

        merge_entries.assert_called_once()
        entries = merge_entries.call_args.args[1]
        self.assertEqual(entries[0].urls, ["https://t.me/dobro_salehard"])


def _settings(*, vk_profile_seeds_path: Path | None = None, output_dir: Path | None = None) -> AppSettings:
    return AppSettings(
        telegram_bot_token="bot-token",
        telegram_allowed_chat_ids=[],
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_user_session=None,
        vk_api_token=None,
        vk_service_token="vk-service",
        vk_community_token=None,
        vk_profile_seeds_path=vk_profile_seeds_path,
        google_places_api_key=None,
        runtime=RuntimeConfig(
            output_dir=output_dir or Path("output"),
            cities=["Салехард"],
            popular_services=["маникюр"],
            period_options=[30, 60, 90, 0],
        ),
        use_mock_data=False,
        telegram_ephemeral_message_ttl_seconds=20,
    )


if __name__ == "__main__":
    unittest.main()
