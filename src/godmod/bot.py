from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Timer

from .access_control import authorize_user, is_authorized_user, is_access_protected, verify_access_code
from .bot_callbacks import WizardAction, parse_wizard_callback
from .bot_commands import HELP_TEXT, START_TEXT, ParsedCommand, parse_command
from .bot_flow import apply_action, apply_manual_services_input, can_confirm
from .bot_render import render_wizard, report_mode_label
from .bot_state import ChatId, MessageId, UserId, WIZARD_STATES, WizardState, ensure_wizard_state, get_wizard_state, reset_wizard_state
from .bot_ui import build_force_reply, build_main_menu_keyboard
from .collectors.factory import ConfiguredCollector
from .export.reports import ReportArtifacts, write_report_artifacts_with_timing
from .markers import hospitality_amenity_hits, is_food_service, normalize_slug, service_profile_hits
from .models import SearchRequest, ServiceQuery
from .operator_reports import (
    build_daily_report_payload,
    build_health_payload,
    find_latest_report_snapshot,
    format_daily_report_summary,
    format_health_summary,
    format_last_report_caption,
)
from .pipeline import run_pipeline
from .report_lock import ActiveReportRun, format_report_busy_message, release_report_run, try_acquire_report_run
from .request_options import expand_service_names, format_period_label, summarize_services
from .settings import AppSettings
from .telegram_api import TelegramApiError, TelegramBotClient
from .telegram_profile_seeds import (
    TelegramProfileSeedEntry,
    merge_telegram_profile_seed_entries,
    telegram_seed_url,
)
from .validation import (
    build_validation_markup_plan,
    load_validation_cases,
    validation_dataset_coverage_payload,
    validation_markup_plan_payload,
)
from .vk_profile_seeds import VkProfileSeedEntry, merge_vk_profile_seed_entries


BOT_STARTED_AT = datetime.now(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Godmod Telegram bot")
    parser.add_argument("--dotenv", default=".env", help="Path to .env file")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = AppSettings.from_env(args.dotenv)
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Put it into .env or environment.")

    client = TelegramBotClient(settings.telegram_bot_token)
    initialize_bot_menu(client)
    log_runtime_source_warnings(settings)
    print("Godmod bot is running...")
    poll_updates(client, settings)


def initialize_bot_menu(client: TelegramBotClient) -> None:
    try:
        client.set_my_commands([])
        client.delete_my_commands()
        client.set_chat_menu_button({"type": "default"})
    except TelegramApiError as exc:
        print(f"Telegram bot menu init failed: {exc}")


def log_runtime_source_warnings(settings: AppSettings) -> None:
    if settings.yandex_maps_requested:
        print(
            "Yandex Maps API key is set, but Yandex organization export remains disabled. "
            "Official docs state that only the basic license is available and saving/modifying received data is prohibited.",
        )


def poll_updates(client: TelegramBotClient, settings: AppSettings) -> None:
    offset: int | None = None
    while True:
        try:
            updates = client.get_updates(offset=offset, timeout=25)
            for update in updates:
                offset = update["update_id"] + 1
                handle_update(client, settings, update)
        except TelegramApiError as exc:
            print(f"Telegram API error: {exc}")
            time.sleep(3)
        except KeyboardInterrupt:
            print("Bot stopped.")
            return


def handle_update(client: TelegramBotClient, settings: AppSettings, update: dict) -> None:
    callback_query = update.get("callback_query")
    if callback_query:
        handle_callback_query(client, settings, callback_query)
        return

    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat = message.get("chat", {})
    sender = message.get("from", {})
    chat_id = chat.get("id")
    user_id = sender.get("id")
    text = message.get("text", "")
    if not _is_identifier(chat_id) or not _is_identifier(user_id) or not text:
        return

    if isinstance(chat_id, int) and settings.telegram_allowed_chat_ids and chat_id not in settings.telegram_allowed_chat_ids:
        client.send_message(chat_id, "Этот чат не разрешён для запуска отчётов.")
        return
    if is_access_protected(settings) and not is_authorized_user(settings, user_id):
        try:
            command = parse_command(text)
        except ValueError as exc:
            client.send_message(chat_id, f"Ошибка параметров: {exc}")
            return
        if command is not None and command.name == "access":
            handle_command(client, settings, chat_id, user_id, command)
            return
        client.send_message(chat_id, _access_required_text())
        return

    state = get_wizard_state(chat_id, user_id)
    if state is not None:
        _purge_transient_messages(client, state)

    try:
        command = parse_command(text)
        if command is None:
            if handle_wizard_text(client, settings, chat_id, user_id, text):
                return
            return
        handle_command(client, settings, chat_id, user_id, command)
    except ValueError as exc:
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        _send_transient_message(
            client,
            settings,
            state,
            f"Ошибка параметров: {exc}",
            reply_markup=_main_menu_markup_for_client(client),
        )
    except TelegramApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        _send_transient_message(
            client,
            settings,
            state,
            f"Не удалось обработать запрос: {exc}",
            reply_markup=_main_menu_markup_for_client(client),
        )


def handle_command(
    client: TelegramBotClient,
    settings: AppSettings,
    chat_id: ChatId,
    user_id: UserId,
    command: ParsedCommand,
) -> None:
    if command.name == "start":
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        reset_wizard_state(state)
        if _is_max_client(client):
            open_commerce_wizard(client, settings, chat_id, user_id)
            return
        _send_transient_message(client, settings, state, START_TEXT, reply_markup=_main_menu_markup_for_client(client))
        _upsert_wizard_message(client, settings, state)
        return

    if command.name == "help":
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        _send_transient_message(client, settings, state, HELP_TEXT, reply_markup=_main_menu_markup_for_client(client))
        if not _is_max_client(client):
            _upsert_wizard_message(client, settings, state)
        return

    if command.name == "cities":
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        reset_wizard_state(state)
        _upsert_wizard_message(client, settings, state, prefer_new_on_not_modified=True)
        return

    if command.name == "cancel":
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        reset_wizard_state(state)
        if _is_max_client(client):
            _upsert_wizard_message(client, settings, state)
            return
        _send_transient_message(client, settings, state, "Текущий выбор сброшен.", reply_markup=_main_menu_markup_for_client(client))
        _upsert_wizard_message(client, settings, state)
        return

    if command.name == "unknown":
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        _send_transient_message(
            client,
            settings,
            state,
            "Неизвестная команда.\n\n" + HELP_TEXT,
            reply_markup=_main_menu_markup_for_client(client),
        )
        if not _is_max_client(client):
            _upsert_wizard_message(client, settings, state)
        return
    if command.name == "access":
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        if not is_access_protected(settings):
            _send_transient_message(
                client,
                settings,
                state,
                "Команда доступа отключена: GODMOD_BOT_ACCESS_CODE не задан.",
                reply_markup=_main_menu_markup_for_client(client),
            )
            return
        if not verify_access_code(settings, str(command.args["code"])):
            _send_transient_message(client, settings, state, "Неверный код доступа.")
            return
        authorize_user(settings, user_id=user_id, chat_id=chat_id)
        reset_wizard_state(state)
        if _is_max_client(client):
            _upsert_wizard_message(client, settings, state)
            return
        _send_transient_message(
            client,
            settings,
            state,
            "Доступ подтверждён. Можно запускать сбор.",
            reply_markup=_main_menu_markup_for_client(client),
        )
        _upsert_wizard_message(client, settings, state)
        return

    if command.name == "markupplan":
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        _send_transient_message(client, settings, state, "Собираю coverage и JSON-план разметки validation-dataset.")
        plan_path, coverage_path, plan_summary = generate_validation_markup_plan(
            settings,
            group_by=str(command.args["group_by"]),
            batch_size=int(command.args["batch_size"]),
            max_batches=int(command.args["max_batches"]),
        )
        client.send_document(
            chat_id,
            plan_path,
            caption=(
                "План разметки готов.\n"
                f"Группировка: {plan_summary['group_by']}\n"
                f"Батчи: {plan_summary['batches_total']}\n"
                f"Pending cases: {plan_summary['pending_cases_total']}\n"
                f"Осталось вне очереди: {plan_summary['remaining_cases_total']}"
            ),
        )
        client.send_document(chat_id, coverage_path, caption="Coverage live validation-dataset.")
        return
    if command.name == "health":
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        _send_transient_message(client, settings, state, "Собираю health-снимок бота и последних артефактов.")
        health_path, payload = generate_operator_health_report(settings)
        client.send_document(chat_id, health_path, caption=format_health_summary(payload))
        return
    if command.name == "dailyreport":
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        _send_transient_message(client, settings, state, "Собираю ежедневную сводку по выгрузкам.")
        report_path, payload = generate_operator_daily_report(settings)
        client.send_document(chat_id, report_path, caption=format_daily_report_summary(payload))
        return
    if command.name == "lastreport":
        state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
        snapshot = find_latest_report_snapshot(settings.runtime.output_dir)
        if snapshot is None:
            _send_transient_message(
                client,
                settings,
                state,
                "Последняя выгрузка ещё не найдена в output.",
                reply_markup=_main_menu_markup_for_client(client),
            )
            return
        caption = format_last_report_caption(snapshot)
        client.send_document(chat_id, snapshot.workbook, caption=caption)
        if snapshot.pdf is not None:
            client.send_document(chat_id, snapshot.pdf, caption="PDF-версия последней выгрузки.")
        if snapshot.manifest is not None and snapshot.manifest.exists():
            client.send_document(chat_id, snapshot.manifest, caption="JSON-manifest последней выгрузки.")
        return

    if command.name == "sample":
        request = SearchRequest(
            cities=settings.runtime.cities[:3],
            services=[ServiceQuery(name=value) for value in settings.runtime.popular_services[:2]],
            period_days=settings.runtime.default_period_days,
            platforms=configured_platforms(settings),
            top_n=settings.runtime.default_top_n,
            report_mode="all",
        )
    else:
        services = expand_service_names(command.args["services"], settings.runtime.popular_services)
        request = SearchRequest(
            cities=command.args["cities"],
            services=[ServiceQuery(name=value) for value in services],
            period_days=command.args["period_days"],
            platforms=configured_platforms(settings),
            top_n=command.args["top_n"],
            report_mode=command.args["report_mode"],
        )

    state = ensure_wizard_state(chat_id, user_id, default_top_n=settings.runtime.default_top_n)
    lock, busy_run = try_acquire_report_run(
        settings.runtime.output_dir,
        chat_id=chat_id,
        user_id=user_id,
        request=request,
    )
    if lock is None:
        _send_transient_message(
            client,
            settings,
            state,
            _report_busy_text(busy_run, user_id),
            reply_markup=_main_menu_markup_for_client(client),
        )
        return
    _send_transient_message(client, settings, state, "Собираю отчёт. Это может занять некоторое время.")
    try:
        artifacts = generate_report(request, settings)
    finally:
        release_report_run(settings.runtime.output_dir, lock.lock_id)
    _purge_transient_messages(client, state)
    _send_report_artifacts(client, chat_id, artifacts, caption=_report_caption(request, settings, artifacts=artifacts), settings=settings, state=state)
    reset_wizard_state(state)
    state.step = "done"
    state.city = request.cities[0] if request.cities else None
    state.services = [service.name for service in request.services]
    state.period_days = request.period_days
    state.report_mode = request.report_mode
    _upsert_wizard_message(client, settings, state)


def handle_callback_query(client: TelegramBotClient, settings: AppSettings, callback_query: dict) -> None:
    callback_id = callback_query.get("id")
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    sender = callback_query.get("from", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    user_id = sender.get("id")
    message_id = message.get("message_id")

    if not isinstance(callback_id, str) or not _is_identifier(chat_id) or not _is_identifier(user_id):
        return

    if isinstance(chat_id, int) and settings.telegram_allowed_chat_ids and chat_id not in settings.telegram_allowed_chat_ids:
        client.answer_callback_query(callback_id, text="Этот чат не разрешён.", show_alert=True)
        return
    if is_access_protected(settings) and not is_authorized_user(settings, user_id):
        client.answer_callback_query(callback_id, text="Доступ закрыт.", show_alert=True)
        client.send_message(chat_id, _access_required_text())
        return

    action = parse_wizard_callback(data)
    if action is None:
        client.answer_callback_query(callback_id, text="Неизвестная кнопка.")
        return

    state = ensure_wizard_state(
        chat_id,
        user_id,
        default_top_n=settings.runtime.default_top_n,
        wizard_message_id=message_id if _is_identifier(message_id) else None,
    )
    if _is_identifier(message_id) and state.wizard_message_id is not None and message_id != state.wizard_message_id:
        client.answer_callback_query(callback_id, text="Этот экран уже устарел. Используйте последний.", show_alert=True)
        return

    _purge_transient_messages(client, state)
    try:
        if action.kind == "nav" and action.value == "confirm":
            _run_confirmed_report(client, settings, callback_id, state)
            return
        apply_action(state, action, settings)
        client.answer_callback_query(callback_id, text=_callback_notice(action, state, settings))
        _upsert_wizard_message(client, settings, state, replace_existing=not _is_max_client(client))
        if action.kind == "nav" and action.value == "manual":
            _send_transient_message(
                client,
                settings,
                state,
                f"Введите услуги для города {state.city} через запятую.",
                reply_markup=build_force_reply(),
            )
    except ValueError as exc:
        client.answer_callback_query(callback_id, text=str(exc), show_alert=True)
    except TelegramApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        client.answer_callback_query(callback_id, text=f"Ошибка: {exc}", show_alert=True)


def handle_wizard_text(
    client: TelegramBotClient,
    settings: AppSettings,
    chat_id: ChatId,
    user_id: UserId,
    text: str,
) -> bool:
    state = get_wizard_state(chat_id, user_id)
    if state is None or state.step != "manual_service_input":
        return False

    _purge_transient_messages(client, state)
    try:
        apply_manual_services_input(state, text, settings)
    except ValueError as exc:
        _send_transient_message(client, settings, state, str(exc), reply_markup=build_force_reply())
        return True

    _upsert_wizard_message(client, settings, state)
    return True


def generate_report(request: SearchRequest, settings: AppSettings) -> ReportArtifacts:
    started_at = datetime.now(UTC)
    collector = ConfiguredCollector(settings)
    result = run_pipeline(request, collector=collector, config=settings.runtime)
    collected_at = datetime.now(UTC)
    learn_vk_profile_seeds_from_report(settings, request, result.bundle)
    learn_telegram_profile_seeds_from_report(settings, request, result.bundle)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    city_part = normalize_slug(request.cities[0]) if request.cities else "report"
    file_name = f"{timestamp}_{city_part}.xlsx"
    target = settings.runtime.output_dir / file_name

    return write_report_artifacts_with_timing(
        result.bundle,
        target,
        started_at=started_at,
        collected_at=collected_at,
        report_origin="bot",
    )


def generate_validation_markup_plan(
    settings: AppSettings,
    *,
    group_by: str,
    batch_size: int,
    max_batches: int,
) -> tuple[Path, Path, dict[str, object]]:
    dataset_path = Path("data/validation_dataset.yanao_template.json")
    cases = load_validation_cases(dataset_path)
    coverage_payload = validation_dataset_coverage_payload(cases, dataset_path=dataset_path)
    batches, summary = build_validation_markup_plan(
        coverage_payload,
        coverage_path=settings.runtime.output_dir / "validation_dataset_coverage.json",
        group_by=group_by,
        batch_size=batch_size,
        max_batches=max_batches,
    )
    markup_payload = validation_markup_plan_payload(
        coverage_path=settings.runtime.output_dir / "validation_dataset_coverage.json",
        batches=batches,
        summary=summary,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    settings.runtime.output_dir.mkdir(parents=True, exist_ok=True)
    coverage_path = settings.runtime.output_dir / f"{timestamp}_validation_dataset_coverage.json"
    plan_path = settings.runtime.output_dir / f"{timestamp}_validation_markup_plan.json"
    coverage_path.write_text(json.dumps(coverage_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    plan_path.write_text(json.dumps(markup_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan_path, coverage_path, markup_payload["summary"]


def generate_operator_health_report(settings: AppSettings) -> tuple[Path, dict[str, object]]:
    payload = build_health_payload(
        output_dir=settings.runtime.output_dir,
        cache_dir=settings.runtime.cache_dir,
        startup_at=BOT_STARTED_AT,
        platforms=configured_platforms(settings),
        use_mock_data=settings.use_mock_data,
        allowed_chat_ids=settings.telegram_allowed_chat_ids,
        rule_config_path=settings.runtime.rule_config_path,
        yandex_maps_requested=settings.yandex_maps_requested,
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    settings.runtime.output_dir.mkdir(parents=True, exist_ok=True)
    path = settings.runtime.output_dir / f"{timestamp}_bot_health.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, payload


def generate_operator_daily_report(settings: AppSettings) -> tuple[Path, dict[str, object]]:
    payload = build_daily_report_payload(
        output_dir=settings.runtime.output_dir,
        timezone_name=settings.mac_daily_report_timezone,
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = settings.runtime.output_dir / f"{timestamp}_daily_report.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, payload


def learn_vk_profile_seeds_from_report(
    settings: AppSettings,
    request: SearchRequest,
    bundle,
) -> None:
    if settings.use_mock_data or settings.vk_profile_seeds_path is None:
        return
    if len(request.cities) != 1 or len(request.services) != 1:
        return

    ranked_vk_urls: list[str] = []
    for item in bundle.ranked_accounts:
        candidate = item.candidate
        if candidate.platform != "vk":
            continue
        if _should_skip_seed_learning_for_candidate(candidate):
            continue
        if candidate.account_url and candidate.account_url not in ranked_vk_urls:
            ranked_vk_urls.append(candidate.account_url)
    if not ranked_vk_urls:
        return

    merge_vk_profile_seed_entries(
        settings.vk_profile_seeds_path,
        [
            VkProfileSeedEntry(
                city=request.cities[0],
                service=request.services[0].name,
                urls=ranked_vk_urls,
            )
        ],
    )


def learn_telegram_profile_seeds_from_report(
    settings: AppSettings,
    request: SearchRequest,
    bundle,
) -> None:
    if settings.use_mock_data or settings.telegram_profile_seeds_path is None:
        return
    if len(request.cities) != 1 or len(request.services) != 1:
        return

    ranked_telegram_urls: list[str] = []
    for item in bundle.ranked_accounts:
        candidate = item.candidate
        if _should_skip_seed_learning_for_candidate(candidate):
            continue
        for url in _seedable_telegram_urls(candidate):
            if url not in ranked_telegram_urls:
                ranked_telegram_urls.append(url)
    if not ranked_telegram_urls:
        return

    merge_telegram_profile_seed_entries(
        settings.telegram_profile_seeds_path,
        [
            TelegramProfileSeedEntry(
                city=request.cities[0],
                service=request.services[0].name,
                urls=ranked_telegram_urls,
            )
        ],
    )


def _should_skip_seed_learning_for_candidate(candidate: AccountCandidate) -> bool:
    profile_texts = [candidate.account_name, candidate.username_or_id, candidate.description]
    if is_food_service(candidate.service):
        identity_service_matches = service_profile_hits(
            [candidate.account_name, candidate.username_or_id],
            candidate.service,
            (),
        )
        if hospitality_amenity_hits(profile_texts) and not identity_service_matches:
            return True
    return False


def _seedable_telegram_urls(candidate: AccountCandidate) -> list[str]:
    urls: list[str] = []
    if candidate.platform == "telegram":
        normalized_account_url = telegram_seed_url(candidate.account_url)
        if normalized_account_url is not None:
            urls.append(normalized_account_url)
    for raw_value in candidate.contacts.get("telegram", []):
        normalized_contact = telegram_seed_url(raw_value)
        if normalized_contact is not None and normalized_contact not in urls:
            urls.append(normalized_contact)
    return urls


def _send_report_artifacts(
    client: TelegramBotClient,
    chat_id: ChatId,
    artifacts: ReportArtifacts,
    *,
    caption: str,
    settings: AppSettings | None = None,
    state: WizardState | None = None,
) -> None:
    client.send_document(chat_id, artifacts.workbook, caption=caption)
    if artifacts.pdf is not None:
        client.send_document(chat_id, artifacts.pdf, caption="PDF-версия с той же таблицей all_accounts.")
    elif artifacts.pdf_error:
        if settings is not None and state is not None:
            _send_transient_message(
                client,
                settings,
                state,
                f"PDF-версию не удалось собрать, поэтому отправлен только XLSX: {artifacts.pdf_error}",
            )
        else:
            client.send_message(chat_id, f"PDF-версию не удалось собрать, поэтому отправлен только XLSX: {artifacts.pdf_error}")
    if _artifact_count(artifacts, "ranked_accounts") == 0:
        empty_caption = _empty_report_manifest_caption(artifacts)
        if artifacts.manifest is not None:
            client.send_document(chat_id, artifacts.manifest, caption=empty_caption)
        elif settings is not None and state is not None:
            _send_transient_message(client, settings, state, empty_caption)
        else:
            client.send_message(chat_id, empty_caption)


def configured_platforms(settings: AppSettings) -> list[str]:
    platforms = ["vk"]
    if settings.telegram_mtproto_ready:
        platforms.append("telegram")
    if settings.google_places_ready:
        platforms.append("places")
    if settings.twogis_ready:
        platforms.append("2gis")
    return platforms


def _artifact_count(artifacts: ReportArtifacts | None, key: str) -> int | None:
    if artifacts is None or not isinstance(artifacts.manifest_payload, dict):
        return None
    counts = artifacts.manifest_payload.get("counts", {})
    if not isinstance(counts, dict):
        return None
    value = counts.get(key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _empty_report_manifest_caption(artifacts: ReportArtifacts) -> str:
    raw_candidates = _artifact_count(artifacts, "raw_candidates") or 0
    filter_debug = _artifact_count(artifacts, "filter_debug") or 0
    failures = _artifact_platform_failures(artifacts)
    failures_label = ", ".join(failures) if failures else "нет"
    return (
        "JSON-manifest пустой выгрузки.\n"
        "Строк в all_accounts: 0\n"
        f"Сырых кандидатов: {raw_candidates}\n"
        f"Записей в filter_debug: {filter_debug}\n"
        f"Платформенные сбои: {failures_label}"
    )


def _artifact_platform_failures(artifacts: ReportArtifacts) -> list[str]:
    if not isinstance(artifacts.manifest_payload, dict):
        return []
    meta = artifacts.manifest_payload.get("meta", {})
    if not isinstance(meta, dict):
        return []
    payload = meta.get("platform_failures", [])
    if not isinstance(payload, list):
        return []
    results: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform", "")).strip()
        error = str(item.get("error", "")).strip()
        if platform and error:
            results.append(f"{platform}: {error}")
        elif platform:
            results.append(platform)
    return results


def _upsert_wizard_message(
    client: TelegramBotClient,
    settings: AppSettings,
    state: WizardState,
    *,
    prefer_new_on_not_modified: bool = False,
    replace_existing: bool = False,
) -> None:
    text, reply_markup = render_wizard(state, settings)
    if _is_max_client(client):
        reply_markup = _with_max_back_to_home(reply_markup)
    if replace_existing and state.wizard_message_id is not None:
        _delete_message_safely(client, state.chat_id, state.wizard_message_id)
        state.wizard_message_id = None
    if state.wizard_message_id is not None:
        try:
            client.edit_message_text(
                state.chat_id,
                state.wizard_message_id,
                text,
                reply_markup=reply_markup,
            )
            return
        except TelegramApiError as exc:
            if "message is not modified" in str(exc):
                if not prefer_new_on_not_modified:
                    return
                _delete_message_safely(client, state.chat_id, state.wizard_message_id)
                state.wizard_message_id = None

    sent = client.send_message(state.chat_id, text, reply_markup=reply_markup)
    message_id = _extract_message_id(sent)
    if message_id is not None:
        state.wizard_message_id = message_id
        state.touch()


def open_commerce_wizard(
    client: TelegramBotClient,
    settings: AppSettings,
    chat_id: ChatId,
    user_id: UserId,
    *,
    wizard_message_id: MessageId | None = None,
) -> None:
    state = ensure_wizard_state(
        chat_id,
        user_id,
        default_top_n=settings.runtime.default_top_n,
        wizard_message_id=wizard_message_id,
    )
    if wizard_message_id is not None:
        state.wizard_message_id = wizard_message_id
    reset_wizard_state(state)
    _upsert_wizard_message(client, settings, state)


def _extract_message_id(result: object) -> MessageId | None:
    if not isinstance(result, dict):
        return None
    message_id = result.get("message_id")
    return message_id if _is_identifier(message_id) else None


def _is_max_client(client: object) -> bool:
    return client.__class__.__name__ == "MaxBotClient"


def _main_menu_markup_for_client(client: object) -> dict:
    if not _is_max_client(client):
        return build_main_menu_keyboard()
    return {"inline_keyboard": _max_main_menu_rows()}


def _max_main_menu_rows() -> list[list[dict[str, str]]]:
    return [
        [{"text": "🏢 Выгрузка по коммерции", "callback_data": "max:commerce"}],
        [{"text": "⚖️ Выгрузка по судам", "callback_data": "sud:main"}],
        [{"text": "ℹ️ Помощь", "callback_data": "max:help"}],
    ]


def _with_max_back_to_home(reply_markup: dict | None) -> dict | None:
    if not reply_markup:
        return {"inline_keyboard": [[{"text": "⬅️ Назад в главное меню", "callback_data": "max:main"}]]}
    if not isinstance(reply_markup.get("inline_keyboard"), list):
        return reply_markup
    return {
        "inline_keyboard": [
            *reply_markup["inline_keyboard"],
            [{"text": "⬅️ Назад в главное меню", "callback_data": "max:main"}],
        ]
    }


def _send_transient_message(
    client: TelegramBotClient,
    settings: AppSettings,
    state: WizardState,
    text: str,
    *,
    reply_markup: dict | None = None,
) -> dict:
    _purge_transient_messages(client, state)
    if _is_max_client(client):
        reply_markup = None
    sent = client.send_message(state.chat_id, text, reply_markup=reply_markup)
    message_id = _extract_message_id(sent)
    if message_id is None:
        return sent
    state.transient_message_ids.append(message_id)
    state.touch()
    ttl_seconds = settings.telegram_ephemeral_message_ttl_seconds
    if ttl_seconds > 0:
        timer = Timer(ttl_seconds, _delete_tracked_message, args=(client, state, message_id))
        timer.daemon = True
        timer.start()
    return sent


def _purge_transient_messages(client: TelegramBotClient, state: WizardState) -> None:
    if not state.transient_message_ids:
        return
    message_ids = list(dict.fromkeys(state.transient_message_ids))
    state.transient_message_ids.clear()
    for message_id in message_ids:
        _delete_message_safely(client, state.chat_id, message_id)


def _delete_tracked_message(client: TelegramBotClient, state: WizardState, message_id: MessageId) -> None:
    try:
        _delete_message_safely(client, state.chat_id, message_id)
    finally:
        state.transient_message_ids = [value for value in state.transient_message_ids if value != message_id]


def _delete_message_safely(client: TelegramBotClient, chat_id: ChatId, message_id: MessageId) -> None:
    try:
        client.delete_message(chat_id, message_id)
    except TelegramApiError:
        return


def _run_confirmed_report(
    client: TelegramBotClient,
    settings: AppSettings,
    callback_id: str,
    state: WizardState,
) -> None:
    if not can_confirm(state):
        client.answer_callback_query(callback_id, text="Сначала заполните все параметры отчёта.", show_alert=True)
        return

    request = SearchRequest(
        cities=[state.city] if state.city else [],
        services=[ServiceQuery(name=value) for value in state.services],
        period_days=state.period_days if state.period_days is not None else settings.runtime.default_period_days,
        platforms=configured_platforms(settings),
        top_n=state.top_n,
        report_mode=state.report_mode or "all",
    )

    state.step = "running"
    state.touch()
    _upsert_wizard_message(client, settings, state, replace_existing=not _is_max_client(client))
    lock, busy_run = try_acquire_report_run(
        settings.runtime.output_dir,
        chat_id=state.chat_id,
        user_id=state.user_id,
        request=request,
    )
    if lock is None:
        client.answer_callback_query(callback_id, text="Сбор уже идёт.", show_alert=True)
        state.step = "confirm"
        state.touch()
        _upsert_wizard_message(client, settings, state, replace_existing=not _is_max_client(client))
        _send_transient_message(client, settings, state, _report_busy_text(busy_run, state.user_id))
        return
    client.answer_callback_query(callback_id, text="Запускаю сборку отчёта.")
    try:
        artifacts = generate_report(request, settings)
    except Exception as exc:  # noqa: BLE001
        state.step = "confirm"
        state.touch()
        _upsert_wizard_message(client, settings, state, replace_existing=not _is_max_client(client))
        _send_transient_message(client, settings, state, f"Не удалось собрать отчёт: {exc}")
        release_report_run(settings.runtime.output_dir, lock.lock_id)
        return
    release_report_run(settings.runtime.output_dir, lock.lock_id)

    _purge_transient_messages(client, state)
    _send_report_artifacts(
        client,
        state.chat_id,
        artifacts,
        caption=_report_caption(request, settings, artifacts=artifacts),
        settings=settings,
        state=state,
    )
    state.step = "done"
    state.touch()
    _upsert_wizard_message(client, settings, state, replace_existing=not _is_max_client(client))


def _report_caption(request: SearchRequest, settings: AppSettings, *, artifacts: ReportArtifacts | None = None) -> str:
    services_label = summarize_services([service.name for service in request.services], settings.runtime.popular_services)
    ranked_accounts = _artifact_count(artifacts, "ranked_accounts")
    intro = "Отчёт готов."
    rows_label = "нет данных"
    if ranked_accounts is not None:
        rows_label = str(ranked_accounts)
        if ranked_accounts == 0:
            intro = "Отчёт собран, но итоговая выгрузка пустая."
    return (
        f"{intro}\n"
        f"Города: {', '.join(request.cities)}\n"
        f"Услуги: {services_label}\n"
        f"Период: {format_period_label(request.period_days)}\n"
        f"Режим: {report_mode_label(request.report_mode)}\n"
        f"Строк в all_accounts: {rows_label}\n"
        "Лист all_accounts упрощён: самые активные аккаунты наверху, расширенные поля в account_review, raw-детали в technical_details, причины отсечения в filter_debug. Отдельно приложен PDF с той же пользовательской таблицей."
    )


def _callback_notice(action: WizardAction, state: WizardState, settings: AppSettings) -> str:
    if action.kind == "city":
        return f"Город: {state.city}"
    if action.kind == "category":
        if action.value.startswith("services:") and state.services:
            return f"Услуги: {summarize_services(state.services, settings.runtime.popular_services)}"
        return f"Раздел: {state.service_category or 'все разделы'}"
    if action.kind == "service":
        return f"Услуги: {summarize_services(state.services, settings.runtime.popular_services)}"
    if action.kind == "period" and state.period_days is not None:
        return f"Период: {format_period_label(state.period_days)}"
    if action.kind == "mode":
        return f"Режим: {report_mode_label(state.report_mode)}"
    if action.kind == "nav":
        notices = {
            "back": "Возвращаю на предыдущий шаг.",
            "reset": "Выбор сброшен.",
            "manual": "Переходим к ручному вводу.",
            "repeat": "Проверяем параметры заново.",
        }
        return notices.get(action.value, "Готово.")
    if action.kind == "edit":
        notices = {
            "city": "Можно выбрать другой город.",
            "service": "Можно выбрать другие услуги.",
            "period": "Можно выбрать другой период.",
            "mode": "Можно выбрать другой режим.",
        }
        return notices.get(action.value, "Готово.")
    return "Готово."


def _is_identifier(value: object) -> bool:
    return isinstance(value, int) or (isinstance(value, str) and bool(value))


def _access_required_text() -> str:
    return "Доступ к боту закрыт. Отправьте `/access <код>` и затем повторите команду."


def _report_busy_text(run: ActiveReportRun | None, user_id: UserId) -> str:
    if run is None:
        return "Сбор уже запущен."
    return format_report_busy_message(run, same_user=run.user_id == f"user:{user_id}")


if __name__ == "__main__":
    main()
