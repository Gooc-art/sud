from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import re

from .markers import city_hits, extract_booking_links, normalize_text, official_signal_hits, official_signal_level
from .models import DuplicateReviewItem, FilterDebugItem, RankedAccount, ReportBundle


SUMMARY_COLUMNS = [
    ("city", "Город"),
    ("service", "Услуга"),
    ("platform", "Площадка"),
    ("accounts_total", "Найдено аккаунтов"),
    ("private_count", "Частных мастеров"),
    ("studio_count", "Студий/салонов"),
    ("company_count", "Компаний"),
    ("unknown_type_count", "Неопределённый тип"),
    ("strong_count", "Сильных действующих"),
    ("active_count", "Действующих"),
    ("moderate_count", "Умеренно активных"),
    ("weak_count", "Слабых"),
    ("abandoned_count", "Заброшенных"),
    ("avg_activity_score", "Средний балл"),
    ("fresh_posts_count", "Со свежими постами"),
    ("high_geo_confidence_count", "С высокой геопривязкой"),
    ("best_account", "Лучший аккаунт"),
    ("best_account_url", "Ссылка на лучший аккаунт"),
    ("best_score", "Лучший балл"),
    ("latest_post_date", "Самый свежий пост"),
]

ACCOUNT_COLUMNS = [
    ("export_id", "id"),
    ("account_title", "Название"),
    ("platform", "Площадка"),
    ("provider_type", "Тип"),
    ("account_url", "Ссылка"),
    ("location_label", "Город / локация"),
    ("api_city", "Город из API"),
    ("address", "Адрес (если есть)"),
    ("geo_coordinates", "Координаты"),
    ("business_categories", "Категории"),
    ("rating_details", "Рейтинг / отзывы"),
    ("working_hours", "Часы работы"),
    ("activity_description", "Описание деятельности"),
    ("service_keywords", "Ключевые слова услуг"),
    ("followers", "Подписчики"),
    ("posting_activity", "Активность (постинг)"),
    ("posts_last_30_days", "Постов за 30 дней"),
    ("avg_likes", "Средние лайки"),
    ("avg_comments", "Средние комментарии"),
    ("avg_reposts", "Средние репосты"),
    ("engagement_rate_percent", "ER, %"),
    ("commercial_markers_found", "Коммерческие маркеры"),
    ("team_size_label", "Сотрудники"),
    ("phone_contacts", "Телефон"),
    ("admin_contacts", "Контакты администратора"),
    ("booking_links", "Ссылка для записи"),
    ("price_details", "Цены / прайс"),
    ("official_requisites", "Официальные реквизиты"),
    ("service_fields", "Служебные поля 2GIS"),
    ("employee_count", "Сотрудников (2GIS)"),
    ("collected_at", "Дата сбора"),
    ("note", "Примечание"),
]

ACCOUNT_REVIEW_COLUMNS = [
    ("rank", "Место"),
    ("activity_class_human", "Состояние"),
    ("activity_score", "Оценка"),
    ("city", "Город"),
    ("service", "Услуга"),
    ("platform", "Площадка"),
    ("api_city", "Город из API"),
    ("geo_coordinates", "Координаты"),
    ("address", "Адрес"),
    ("business_categories", "Категории"),
    ("rating_details", "Рейтинг / отзывы"),
    ("working_hours", "Часы работы"),
    ("account_name", "Аккаунт"),
    ("account_url", "Ссылка"),
    ("provider_type", "Кто это"),
    ("work_format", "Как работает"),
    ("team_signal", "Команда"),
    ("description", "Описание профиля"),
    ("phone_contacts", "Телефон"),
    ("telegram_contacts", "Telegram"),
    ("contact_summary", "Контакты"),
    ("price_details", "Цены / прайс"),
    ("official_requisites", "Официальные реквизиты"),
    ("service_fields", "Служебные поля 2GIS"),
    ("employee_count", "Сотрудников (2GIS)"),
    ("official_signal_level", "Официальные признаки"),
    ("followers", "Подписчики"),
    ("posts_in_period", "Постов за период"),
    ("last_post_date", "Последний пост"),
    ("freshness_status", "Активность сейчас"),
    ("geo_confidence", "Привязка к городу"),
    ("service_signals", "Признаки услуги"),
    ("evidence_summary", "Что подтверждает работу"),
    ("account_summary", "Короткий вывод"),
    ("review_note", "Что проверить"),
    ("evidence_post_1", "Подтверждающий пост 1"),
    ("evidence_post_2", "Подтверждающий пост 2"),
    ("evidence_post_3", "Подтверждающий пост 3"),
]

TECHNICAL_COLUMNS = [
    ("rank", "Место"),
    ("account_name", "Аккаунт"),
    ("account_url", "Ссылка"),
    ("username_or_id", "Username / ID"),
    ("provider_type_confidence", "Уверенность по типу"),
    ("work_format_confidence", "Уверенность по формату"),
    ("team_signal_confidence", "Уверенность по команде"),
    ("days_since_last_post", "Дней с последнего поста"),
    ("avg_likes", "Ср. лайки"),
    ("avg_comments", "Ср. комментарии"),
    ("avg_reposts", "Ср. репосты"),
    ("avg_views", "Ср. просмотры"),
    ("engagement_index", "Индекс вовлечённости"),
    ("commercial_signal_count", "Коммерч. сигналов"),
    ("commercial_markers_found", "Коммерч. маркеры"),
    ("city_signal_count", "Геосигналов"),
    ("city_signals_found", "Геосигналы"),
    ("noise_signal_count", "Шумовых сигналов"),
    ("noise_markers_found", "Шумовые маркеры"),
    ("official_markers_found", "Официальные маркеры"),
    ("score_activity", "Балл: активность"),
    ("score_engagement", "Балл: вовлечённость"),
    ("score_commercial", "Балл: коммерция"),
    ("score_locality", "Балл: гео"),
    ("score_stability", "Балл: стабильность"),
    ("score_penalty", "Штраф"),
    ("search_queries_count", "Найден по запросам"),
    ("search_queries_used", "Поисковые запросы"),
    ("business_categories", "Категории"),
    ("rating_details", "Рейтинг / отзывы"),
    ("working_hours", "Часы работы"),
    ("price_details", "Ценовые сигналы"),
    ("official_requisites", "Реквизиты"),
    ("service_fields", "Служебные поля 2GIS"),
    ("employee_count", "Сотрудников (2GIS)"),
    ("geo_coordinates", "Координаты"),
    ("why_ranked_high", "Почему стоит высоко"),
]

SEARCH_LOG_COLUMNS = [
    ("city", "Город"),
    ("service", "Услуга"),
    ("platform", "Площадка"),
    ("source", "Источник discovery"),
    ("discovery_mode", "Режим discovery"),
    ("query", "Поисковый запрос"),
    ("details", "Диагностика"),
]

RAW_CANDIDATE_COLUMNS = [
    ("export_id", "id"),
    ("platform", "Площадка"),
    ("account_title", "Название"),
    ("account_url", "Ссылка"),
    ("city", "Город запроса"),
    ("api_city", "Город из API"),
    ("profile_city_signals", "Геосигналы профиля"),
    ("api_address", "Адрес из API"),
    ("geo_coordinates", "Координаты"),
    ("business_categories", "Категории"),
    ("rating_details", "Рейтинг / отзывы"),
    ("working_hours", "Часы работы"),
    ("activity_description", "Описание"),
    ("followers", "Подписчики"),
    ("posts_total", "Постов собрано"),
    ("search_queries", "Поисковые запросы"),
    ("discovery_sources", "Источники discovery"),
    ("discovery_modes", "Режимы discovery"),
    ("contacts", "Контакты"),
    ("booking_links", "Ссылка для записи"),
    ("price_details", "Цены / прайс"),
    ("official_requisites", "Официальные реквизиты"),
    ("service_fields", "Служебные поля 2GIS"),
    ("employee_count", "Сотрудников (2GIS)"),
]

DUPLICATE_COLUMNS = [
    ("left_account_url", "Ссылка 1"),
    ("right_account_url", "Ссылка 2"),
    ("confidence", "Уверенность"),
    ("reason", "Причина совпадения"),
]

FILTER_DEBUG_COLUMNS = [
    ("status", "Статус"),
    ("decision_stage", "Этап"),
    ("reason", "Причина"),
    ("city", "Город"),
    ("service", "Услуга"),
    ("platform", "Площадка"),
    ("account_name", "Аккаунт"),
    ("account_url", "Ссылка"),
    ("username_or_id", "Username / ID"),
    ("posts_total", "Постов собрано"),
    ("posts_in_period", "Постов в периоде"),
    ("score_total", "Балл"),
    ("activity_class", "Состояние"),
    ("city_signals", "Геосигналы"),
    ("service_profile_hits", "Сигналы услуги в профиле"),
    ("commercial_markers", "Коммерческие сигналы"),
    ("noise_markers", "Шумовые сигналы"),
    ("official_signals", "Официальные сигналы"),
    ("search_queries", "Поисковые запросы"),
    ("description", "Описание профиля"),
]


def build_report_rows(bundle: ReportBundle) -> dict[str, list[dict[str, object]]]:
    ranked = bundle.ranked_accounts
    raw_candidates = bundle.raw_candidates or [item.candidate for item in ranked]
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    account_rows = [
        _account_row(index, item, period_days=bundle.request.period_days, collected_at=collected_at)
        for index, item in enumerate(ranked, start=1)
    ]
    compact_account_rows = [_compact_all_accounts_row(row) for row in account_rows]
    return {
        "all_accounts": _localize_rows(compact_account_rows, ACCOUNT_COLUMNS),
        "summary": _localize_rows(_summary_rows(ranked), SUMMARY_COLUMNS),
        "account_review": _localize_rows(account_rows, ACCOUNT_REVIEW_COLUMNS),
        "technical_details": _localize_rows(account_rows, TECHNICAL_COLUMNS),
        "search_log": _localize_rows([_search_log_row(entry) for entry in bundle.search_log], SEARCH_LOG_COLUMNS),
        "raw_candidates": _localize_rows(
            [_raw_candidate_row(index, candidate) for index, candidate in enumerate(raw_candidates, start=1)],
            RAW_CANDIDATE_COLUMNS,
        ),
        "filter_debug": _localize_rows(
            [_filter_debug_row(item) for item in bundle.filter_debug],
            FILTER_DEBUG_COLUMNS,
        ),
        "duplicates_review": _localize_rows(
            [_duplicate_row(item) for item in bundle.duplicates_review],
            DUPLICATE_COLUMNS,
        ),
    }


def _account_row(rank: int, item: RankedAccount, *, period_days: int, collected_at: str) -> dict[str, object]:
    candidate = item.candidate
    metrics = item.metrics
    score = item.score
    matched_services = _matched_services(candidate)
    service_label = ", ".join(matched_services)
    evidence = item.evidence_posts + [None, None, None]
    days_since_last_post = _days_since_last_post(metrics.last_post_at)
    engagement_index = _engagement_index(item)
    provider_type, provider_type_confidence = _provider_profile(item)
    work_format, work_format_confidence = _work_format(item)
    team_signal, team_signal_confidence = _team_signal(item)
    normalized_activity_class = _normalized_activity_class(item.activity_class)
    report_activity_class = _report_activity_class(item)
    official_hits = official_signal_hits(
        [
            candidate.account_name,
            candidate.username_or_id,
            candidate.description,
            *[post.text for post in candidate.posts[:5]],
        ]
    )
    official_level = official_signal_level(official_hits)
    account_summary = _account_summary(
        item,
        normalized_activity_class=normalized_activity_class,
        provider_type=provider_type,
        work_format=work_format,
        team_signal=team_signal,
        official_signal_level=official_level,
        days_since_last_post=days_since_last_post,
    )
    review_note = _review_note(item, days_since_last_post, official_signal_level=official_level)
    if item.duplicate_reason:
        review_note = f"{review_note} Возможный дубль: {item.duplicate_reason}"
    address = candidate.api_address or _extract_address(
        [
            candidate.description,
            *[post.text for post in candidate.posts[:5]],
        ]
    )
    booking_links = ", ".join(extract_booking_links([candidate.description])) or "нет"
    possible_booking_phone_note = _possible_booking_phone_note(candidate, booking_links)
    if possible_booking_phone_note:
        review_note = f"{review_note} {possible_booking_phone_note}".strip()
    price_details = candidate.price_details or "нет"
    official_requisites = candidate.official_requisites or "нет"
    service_fields = candidate.service_fields or "нет"
    employee_count = candidate.employee_count if candidate.employee_count is not None else "нет"
    engagement_rate_percent = _engagement_rate_percent(item)
    return {
        "rank": rank,
        "export_id": _export_id(candidate, rank),
        "account_title": candidate.account_name,
        "service": service_label,
        "city": candidate.city,
        "platform": _platform_label(candidate.platform),
        "location_label": _location_label(metrics.city_signals, candidate.city),
        "api_city": candidate.api_city or "нет",
        "address": address,
        "geo_coordinates": candidate.geo_coordinates or "нет",
        "business_categories": candidate.business_categories or "нет",
        "rating_details": candidate.rating_details or "нет",
        "working_hours": candidate.working_hours or "нет",
        "activity_description": candidate.description or "нет описания",
        "service_keywords": _service_keywords(matched_services, metrics.commercial_markers),
        "activity_class_human": report_activity_class,
        "posting_activity": report_activity_class,
        "provider_type": provider_type,
        "provider_type_confidence": provider_type_confidence,
        "work_format": work_format,
        "work_format_confidence": work_format_confidence,
        "team_signal": team_signal,
        "team_size_label": _team_size_label(team_signal),
        "team_signal_confidence": team_signal_confidence,
        "account_name": candidate.account_name,
        "account_url": candidate.account_url,
        "username_or_id": candidate.username_or_id,
        "description": candidate.description or "нет описания",
        "phone_contacts": ", ".join(candidate.contacts.get("phone", [])) or "нет",
        "telegram_contacts": ", ".join(candidate.contacts.get("telegram", [])) or "нет",
        "contact_summary": _contact_summary(candidate.contacts),
        "admin_contacts": _contact_summary(candidate.contacts),
        "booking_links": booking_links,
        "price_details": price_details,
        "official_requisites": official_requisites,
        "service_fields": service_fields,
        "employee_count": employee_count,
        "official_signal_level": official_level,
        "followers": candidate.followers if candidate.followers is not None else "нет данных",
        "posts_in_period": metrics.posts_in_period,
        "posts_last_30_days": _posts_in_last_days(candidate.posts, 30),
        "last_post_date": _format_dt(metrics.last_post_at),
        "days_since_last_post": days_since_last_post if days_since_last_post is not None else "нет данных",
        "freshness_status": _freshness_status(days_since_last_post, period_days),
        "avg_likes": metrics.avg_likes if metrics.avg_likes is not None else "нет данных",
        "avg_comments": metrics.avg_comments if metrics.avg_comments is not None else "нет данных",
        "avg_reposts": metrics.avg_reposts if metrics.avg_reposts is not None else "нет данных",
        "avg_views": metrics.avg_views if metrics.avg_views is not None else "нет данных",
        "engagement_index": engagement_index if engagement_index is not None else "нет данных",
        "engagement_rate_percent": (
            engagement_rate_percent if engagement_rate_percent is not None else "нет данных"
        ),
        "commercial_signal_count": len(metrics.commercial_markers),
        "commercial_markers_found": ", ".join(metrics.commercial_markers) or "нет",
        "service_signals": _service_signals(metrics.commercial_markers),
        "city_signal_count": len(metrics.city_signals),
        "city_signals_found": ", ".join(metrics.city_signals) or "нет",
        "geo_confidence": _geo_confidence(metrics.city_signals, candidate.city),
        "noise_signal_count": len(metrics.noise_markers),
        "noise_markers_found": ", ".join(metrics.noise_markers) or "нет",
        "official_markers_found": ", ".join(official_hits) or "нет",
        "activity_score": score.total,
        "activity_class": report_activity_class,
        "score_activity": score.activity,
        "score_engagement": score.engagement,
        "score_commercial": score.commercial,
        "score_locality": score.locality,
        "score_stability": score.stability,
        "score_penalty": score.penalty,
        "search_queries_count": len(candidate.search_queries),
        "search_queries_used": ", ".join(_unique_preserve_order(candidate.search_queries)) or "нет",
        "evidence_summary": _evidence_summary(item),
        "account_summary": account_summary,
        "review_note": review_note,
        "collected_at": collected_at,
        "note": _user_note(account_summary, review_note),
        "evidence_post_1": evidence[0].url if evidence[0] else "",
        "evidence_post_2": evidence[1].url if evidence[1] else "",
        "evidence_post_3": evidence[2].url if evidence[2] else "",
        "why_ranked_high": _why_ranked_high(item),
    }


def _search_log_row(entry) -> dict[str, object]:
    return {
        "city": entry.city,
        "service": entry.service,
        "platform": _platform_label(entry.platform),
        "source": entry.source or "не указан",
        "discovery_mode": entry.discovery_mode or "не указан",
        "query": entry.query,
        "details": entry.details or "нет",
    }


def _raw_candidate_row(index: int, candidate) -> dict[str, object]:
    booking_links = ", ".join(extract_booking_links([candidate.description])) or "нет"
    contacts = _contact_summary(candidate.contacts)
    profile_city_signals = ", ".join(city_hits(
        [candidate.account_name, candidate.username_or_id, candidate.description],
        [candidate.city],
    )) or "нет"
    return {
        "export_id": _export_id(candidate, index),
        "platform": _platform_label(candidate.platform),
        "account_title": candidate.account_name,
        "account_url": candidate.account_url,
        "city": candidate.city,
        "api_city": candidate.api_city or "нет данных",
        "profile_city_signals": profile_city_signals,
        "api_address": candidate.api_address or "нет данных",
        "geo_coordinates": candidate.geo_coordinates or "нет",
        "business_categories": candidate.business_categories or "нет",
        "rating_details": candidate.rating_details or "нет",
        "working_hours": candidate.working_hours or "нет",
        "activity_description": candidate.description or "нет описания",
        "followers": candidate.followers if candidate.followers is not None else "нет данных",
        "posts_total": len(candidate.posts),
        "search_queries": ", ".join(_unique_preserve_order(candidate.search_queries)) or "нет",
        "discovery_sources": ", ".join(candidate.discovery_sources) or "нет",
        "discovery_modes": ", ".join(candidate.discovery_modes) or "нет",
        "contacts": contacts,
        "booking_links": booking_links,
        "price_details": candidate.price_details or "нет",
        "official_requisites": candidate.official_requisites or "нет",
        "service_fields": candidate.service_fields or "нет",
        "employee_count": candidate.employee_count if candidate.employee_count is not None else "нет",
    }


def _duplicate_row(item: DuplicateReviewItem) -> dict[str, object]:
    return {
        "left_account_url": item.left_account_url,
        "right_account_url": item.right_account_url,
        "confidence": _confidence_label(item.confidence),
        "reason": item.reason,
    }


def _filter_debug_row(item: FilterDebugItem) -> dict[str, object]:
    return {
        "status": _debug_status_label(item.status),
        "decision_stage": _debug_stage_label(item.decision_stage),
        "reason": item.reason,
        "city": item.city,
        "service": item.service,
        "platform": _platform_label(item.platform),
        "account_name": item.account_name,
        "account_url": item.account_url,
        "username_or_id": item.username_or_id,
        "posts_total": item.posts_total,
        "posts_in_period": item.posts_in_period if item.posts_in_period is not None else "нет данных",
        "score_total": item.score_total if item.score_total is not None else "нет данных",
        "activity_class": _debug_activity_class_label(item),
        "city_signals": ", ".join(item.city_signals) or "нет",
        "service_profile_hits": ", ".join(item.service_profile_hits) or "нет",
        "commercial_markers": ", ".join(item.commercial_markers) or "нет",
        "noise_markers": ", ".join(item.noise_markers) or "нет",
        "official_signals": ", ".join(item.official_signals) or "нет",
        "search_queries": ", ".join(_unique_preserve_order(item.search_queries)) or "нет",
        "description": item.description or "нет описания",
    }


def _summary_rows(ranked: list[RankedAccount]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[RankedAccount]] = defaultdict(list)
    for item in ranked:
        for service in _matched_services(item.candidate):
            key = (item.candidate.city, service, item.candidate.platform)
            grouped[key].append(item)

    rows: list[dict[str, object]] = []
    for (city, service, platform), items in sorted(grouped.items()):
        classes = [_report_activity_class(item) for item in items]
        best = items[0]
        provider_types = [_provider_profile(item)[0] for item in items]
        rows.append(
            {
                "city": city,
                "service": service,
                "platform": _platform_label(platform),
                "accounts_total": len(items),
                "private_count": provider_types.count("частный мастер"),
                "studio_count": provider_types.count("студия/салон"),
                "company_count": provider_types.count("компания"),
                "unknown_type_count": provider_types.count("неопределено"),
                "strong_count": classes.count("сильный действующий"),
                "active_count": classes.count("действующий"),
                "moderate_count": classes.count("умеренно активный"),
                "weak_count": classes.count("слабый"),
                "abandoned_count": classes.count("заброшенный"),
                "avg_activity_score": round(sum(item.score.total for item in items) / len(items), 2),
                "fresh_posts_count": sum(1 for item in items if _days_since_last_post(item.metrics.last_post_at) is not None and _days_since_last_post(item.metrics.last_post_at) <= 14),
                "high_geo_confidence_count": sum(
                    1
                    for item in items
                    if _geo_confidence(item.metrics.city_signals, item.candidate.city) == "высокая"
                ),
                "best_account": best.candidate.account_name,
                "best_account_url": best.candidate.account_url,
                "best_score": best.score.total,
                "latest_post_date": _format_dt(max((item.metrics.last_post_at for item in items if item.metrics.last_post_at), default=None)),
            }
        )
    return rows


def _why_ranked_high(item: RankedAccount) -> str:
    if _is_business_card_seed(item):
        source_label = _platform_label(item.candidate.platform)
        return f"карточка {source_label}; локальность подтверждена адресом или категорией; доступна бизнес-карточка"
    parts = [
        f"активность {item.score.activity}",
        f"вовлечённость {item.score.engagement}",
        f"коммерч. явность {item.score.commercial}",
        f"локальность {item.score.locality}",
    ]
    return "; ".join(parts)


def _format_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "нет данных"


def _export_id(candidate, rank: int) -> str:
    identifier = candidate.username_or_id.strip() if candidate.username_or_id else str(rank)
    return f"{candidate.platform}:{identifier}"


def _days_since_last_post(value: datetime | None) -> int | None:
    if value is None:
        return None
    return max((datetime.now(value.tzinfo) - value).days, 0)


def _freshness_status(days_since_last_post: int | None, period_days: int) -> str:
    if days_since_last_post is None:
        return "нет данных"
    if days_since_last_post <= 7:
        return "очень свежий"
    if days_since_last_post <= 21:
        return "свежий"
    if days_since_last_post <= max(period_days // 2, 30):
        return "заметно активен"
    if days_since_last_post <= period_days:
        return "стареет"
    return "давно не активен"


def _geo_confidence(city_signals: list[str], candidate_city: str) -> str:
    hits = set(city_signals)
    if candidate_city in hits:
        return "высокая"
    if "ЯНАО/Ямал" in hits or hits:
        return "средняя"
    return "низкая"


def _engagement_index(item: RankedAccount) -> float | None:
    reactions = (item.metrics.avg_likes or 0) + (item.metrics.avg_comments or 0) * 2 + (item.metrics.avg_reposts or 0) * 2
    if reactions <= 0 and not item.metrics.avg_views:
        return None
    if item.candidate.followers and item.candidate.followers > 0:
        value = ((reactions + (item.metrics.avg_views or 0) * 0.2) / item.candidate.followers) * 100
        return round(value, 2)
    return round(reactions + (item.metrics.avg_views or 0) * 0.05, 2)


def _engagement_rate_percent(item: RankedAccount) -> float | None:
    followers = item.candidate.followers
    if followers is None or followers <= 0:
        return None
    reactions = (item.metrics.avg_likes or 0) + (item.metrics.avg_comments or 0) + (item.metrics.avg_reposts or 0)
    return round((reactions / followers) * 100, 2)


def _location_label(city_signals: list[str], candidate_city: str) -> str:
    ordered_signals = [candidate_city]
    ordered_signals.extend(signal for signal in _unique_preserve_order(city_signals) if signal != candidate_city)
    return ", ".join(ordered_signals)


def _extract_address(texts: list[str]) -> str:
    corpus = " ".join(filter(None, texts))
    patterns = [
        re.compile(r"(?:адрес|по адресу)\s*[:\-]?\s*([^;\n]+)", re.IGNORECASE),
        re.compile(r"((?:ул\.?|улица|проспект|пр-кт|микрорайон|мкр\.?)\s*[^.;\n]{4,})", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.search(corpus)
        if match:
            value = re.sub(r"\s+", " ", match.group(1))
            value = re.split(
                r"(?:\s+(?:телефон|тел\.?|запись|звоните|пишите|писать|whatsapp|tg|telegram)\b|\s+@)",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            value = value.rstrip(" .,:;!-")
            if value:
                return value
    return "нет данных"


def _service_keywords(service: str | list[str], markers: list[str]) -> str:
    services = [service] if isinstance(service, str) else service
    keywords = [*_unique_preserve_order(services), *_unique_preserve_order(markers)[:4]]
    return ", ".join(keyword for keyword in keywords if keyword)


def _matched_services(candidate) -> list[str]:
    services = list(getattr(candidate, "matched_services", []))
    if candidate.service:
        services.insert(0, candidate.service)
    return _unique_preserve_order([service for service in services if service])


def _compact_all_accounts_row(row: dict[str, object]) -> dict[str, object]:
    compact = dict(row)
    compact["activity_description"] = _compact_cell_text(row.get("activity_description"), limit=150)
    compact["service_keywords"] = _compact_cell_text(row.get("service_keywords"), limit=80)
    compact["commercial_markers_found"] = _compact_cell_text(row.get("commercial_markers_found"), limit=90)
    compact["admin_contacts"] = _compact_cell_text(row.get("admin_contacts"), limit=90)
    compact["phone_contacts"] = _compact_cell_text(row.get("phone_contacts"), limit=70)
    compact["booking_links"] = _compact_cell_text(row.get("booking_links"), limit=100)
    compact["price_details"] = _compact_cell_text(row.get("price_details"), limit=90)
    compact["business_categories"] = _compact_cell_text(row.get("business_categories"), limit=80)
    compact["rating_details"] = _compact_cell_text(row.get("rating_details"), limit=70)
    compact["working_hours"] = _compact_cell_text(row.get("working_hours"), limit=80)
    compact["official_requisites"] = _compact_cell_text(row.get("official_requisites"), limit=90)
    compact["service_fields"] = _compact_cell_text(row.get("service_fields"), limit=90)
    compact["note"] = _compact_cell_text(row.get("note"), limit=170)
    return compact


def _compact_cell_text(value: object, *, limit: int) -> object:
    if not isinstance(value, str):
        return value
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    shortened = normalized[: limit - 1].rstrip()
    boundary = max(shortened.rfind(" "), shortened.rfind(","), shortened.rfind(";"))
    if boundary >= max(limit // 2, 24):
        shortened = shortened[:boundary].rstrip()
    return f"{shortened}…"


def _posts_in_last_days(posts, days: int) -> int:
    if not posts:
        return 0
    reference_time = datetime.now(posts[0].published_at.tzinfo) if posts[0].published_at.tzinfo else datetime.now()
    threshold = reference_time - timedelta(days=days)
    return sum(1 for post in posts if post.published_at >= threshold)


def _evidence_summary(item: RankedAccount) -> str:
    if not item.evidence_posts:
        return "Нет сильных доказательных постов в периоде"
    top_reasons = item.evidence_posts[0].reasons[:2]
    return "; ".join(top_reasons) or "Есть свежий пост в периоде"


def _review_note(
    item: RankedAccount,
    days_since_last_post: int | None,
    *,
    official_signal_level: str,
) -> str:
    if _is_business_card_seed(item):
        source_label = _platform_label(item.candidate.platform)
        return f"Карточка {source_label} добавлена как business seed: адрес и контакты нужно сверить вручную, постинг соцсетей не анализировался."
    if _normalized_activity_class(item.activity_class) == "заброшенный":
        return "Показывается в отчёте, но активность устарела или отсутствует."
    if len(item.metrics.noise_markers) >= 2 and len(item.metrics.commercial_markers) <= 1:
        return "Похоже на паблик-агрегатор или медиа: нужен ручной контроль."
    if len(item.metrics.commercial_markers) < 2:
        return "Нужна ручная проверка: коммерческих сигналов пока мало."
    if official_signal_level == "нет":
        return "Аккаунт выглядит рабочим, но явных официальных признаков в профиле не видно."
    if days_since_last_post is not None and days_since_last_post > 30:
        return "Есть признаки бизнеса, но свежесть публикаций уже снижается."
    if item.metrics.avg_views is None and item.candidate.followers is None:
        return "Ограниченные публичные данные по охвату и аудитории."
    return "Похож на действующий и регулярно обновляемый аккаунт."


def _provider_profile(item: RankedAccount) -> tuple[str, str]:
    candidate = item.candidate
    texts = [
        candidate.account_name,
        candidate.description,
        *[post.text for post in candidate.posts[:5]],
    ]
    corpus = normalize_text(" ".join(filter(None, texts)))

    studio_signals = _count_signals(
        corpus,
        [
            "студия",
            "салон",
            "beauty",
            "барбершоп",
            "barbershop",
            "кабинет",
            "nails studio",
            "studio",
        ],
    )
    company_signals = _count_signals(
        corpus,
        [
            "ооо",
            "ип ",
            "компания",
            "сервис",
            "центр",
            "агентство",
            "мастерская",
            "автосервис",
            "клиника",
            "филиал",
        ],
    )
    private_signals = _count_signals(
        corpus,
        [
            "частный мастер",
            "мастер",
            "принимаю",
            "работаю сама",
            "работаю сам",
            "мой кабинет",
            "на дому",
            "принимаю лично",
        ],
    )

    if studio_signals >= max(company_signals, private_signals) and studio_signals > 0:
        return "студия/салон", _confidence_from_hits(studio_signals)
    if company_signals > max(studio_signals, private_signals) and company_signals > 0:
        return "компания", _confidence_from_hits(company_signals)
    if private_signals > 0:
        return "частный мастер", _confidence_from_hits(private_signals)
    return "неопределено", "низкая"


def _work_format(item: RankedAccount) -> tuple[str, str]:
    candidate = item.candidate
    corpus = normalize_text(
        " ".join(
            filter(
                None,
                [
                    candidate.account_name,
                    candidate.description,
                    *[post.text for post in candidate.posts[:5]],
                ],
            )
        )
    )

    home_hits = _count_signals(corpus, ["на дому", "дома", "домашний кабинет", "принимаю дома", "у себя дома"])
    office_hits = _count_signals(corpus, ["кабинет", "офис", "в кабинете"])
    salon_hits = _count_signals(corpus, ["салон", "студия", "barbershop", "beauty", "клиника"])
    mobile_hits = _count_signals(corpus, ["выезд", "на выезд", "с выездом", "по адресу клиента", "выезжаю"])
    online_hits = _count_signals(corpus, ["онлайн", "дистанционно", "удаленно", "удалённо"])

    labelled_hits = [
        ("на дому", home_hits),
        ("кабинет", office_hits),
        ("салон", salon_hits),
        ("выезд", mobile_hits),
        ("онлайн", online_hits),
    ]
    active_labels = [label for label, hits in labelled_hits if hits > 0]
    if len(active_labels) > 1:
        max_hits = max(hits for _, hits in labelled_hits)
        if sum(1 for _, hits in labelled_hits if hits == max_hits and hits > 0) > 1:
            return "смешанный", _confidence_from_hits(max_hits)
        best_label, best_hits = max(labelled_hits, key=lambda item: item[1])
        return best_label, _confidence_from_hits(best_hits)
    if len(active_labels) == 1:
        label = active_labels[0]
        hits = next(hits for item_label, hits in labelled_hits if item_label == label)
        return label, _confidence_from_hits(hits)
    return "неопределено", "низкая"


def _team_signal(item: RankedAccount) -> tuple[str, str]:
    candidate = item.candidate
    corpus = normalize_text(
        " ".join(
            filter(
                None,
                [
                    candidate.account_name,
                    candidate.description,
                    *[post.text for post in candidate.posts[:5]],
                ],
            )
        )
    )

    branch_hits = _count_signals(corpus, ["филиал", "филиалы", "несколько адресов", "2 адреса", "две студии"])
    multi_master_hits = _count_signals(
        corpus,
        [
            "несколько мастеров",
            "2 мастера",
            "3 мастера",
            "4 мастера",
            "наши мастера",
            "ищем мастера",
            "ищем администратора",
        ],
    )
    team_hits = _count_signals(corpus, ["команда", "коллектив", "специалисты", "администратор", "мы работаем", "наша команда"])
    solo_hits = _count_signals(corpus, ["работаю сама", "работаю сам", "частный мастер", "принимаю лично", "один мастер", "я мастер"])

    if branch_hits > 0:
        return "сеть/филиалы", _confidence_from_hits(branch_hits)
    if multi_master_hits > 0:
        return "несколько мастеров", _confidence_from_hits(multi_master_hits)
    if team_hits > 0:
        return "команда", _confidence_from_hits(team_hits)
    if solo_hits > 0:
        return "1 человек", _confidence_from_hits(solo_hits)
    return "неопределено", "низкая"


def _contact_summary(contacts: dict[str, list[str]]) -> str:
    parts: list[str] = []
    phones = contacts.get("phone", [])
    telegram_contacts = contacts.get("telegram", [])
    emails = contacts.get("email", [])
    websites = contacts.get("website", [])
    if phones:
        parts.append(f"тел. {', '.join(phones)}")
    if telegram_contacts:
        parts.append(f"tg {', '.join(telegram_contacts)}")
    if emails:
        parts.append(f"email {', '.join(emails)}")
    if websites:
        parts.append(f"сайт {', '.join(websites)}")
    return " | ".join(parts) if parts else "нет"


def _service_signals(markers: list[str]) -> str:
    unique_markers = _unique_preserve_order(markers)
    if not unique_markers:
        return "прямые признаки не найдены"
    return ", ".join(unique_markers[:4])


def _team_size_label(team_signal: str) -> str:
    if team_signal == "неопределено":
        return "нет данных"
    return team_signal


def _account_summary(
    item: RankedAccount,
    *,
    normalized_activity_class: str,
    provider_type: str,
    work_format: str,
    team_signal: str,
    official_signal_level: str,
    days_since_last_post: int | None,
) -> str:
    who = provider_type if provider_type != "неопределено" else "исполнитель услуги"
    parts = [f"{who.capitalize()} в {item.candidate.city}"]

    if _is_business_card_seed(item):
        parts.append(f"карточка найдена в {_platform_label(item.candidate.platform)}")
        if work_format != "неопределено":
            parts.append(f"формат: {work_format}")
        if team_signal not in {"неопределено", "1 человек"}:
            parts.append(f"масштаб: {team_signal}")
        if official_signal_level != "нет":
            parts.append(f"официальные признаки: {official_signal_level}")
        if item.metrics.commercial_markers:
            parts.append(
                f"видны признаки услуги: {', '.join(_unique_preserve_order(item.metrics.commercial_markers)[:2])}"
            )
        parts.append("данных по постингу соцсетей нет")
        return "; ".join(parts)

    if normalized_activity_class == "сильный действующий":
        parts.append("аккаунт активно обновляется")
    elif normalized_activity_class == "действующий":
        parts.append("аккаунт регулярно обновляется")
    elif normalized_activity_class == "умеренно активный":
        parts.append("активность есть, но неравномерная")
    elif normalized_activity_class == "слабый":
        parts.append("активность слабая")
    else:
        parts.append("аккаунт давно не обновлялся")

    if work_format != "неопределено":
        parts.append(f"формат: {work_format}")
    if team_signal not in {"неопределено", "1 человек"}:
        parts.append(f"масштаб: {team_signal}")
    if official_signal_level != "нет":
        parts.append(f"официальные признаки: {official_signal_level}")
    if item.metrics.commercial_markers:
        parts.append(f"видны признаки услуги: {', '.join(_unique_preserve_order(item.metrics.commercial_markers)[:2])}")
    if days_since_last_post is not None and normalized_activity_class != "заброшенный":
        parts.append(f"последний пост {days_since_last_post} дн. назад")
    return "; ".join(parts)


def _user_note(account_summary: str, review_note: str) -> str:
    booking_phone_prefix = "Возможный телефон для записи:"
    if review_note and booking_phone_prefix in review_note:
        sentences = [part.strip() for part in review_note.split(".") if part.strip()]
        booking_sentences = [part for part in sentences if booking_phone_prefix in part]
        other_sentences = [part for part in sentences if booking_phone_prefix not in part]
        prioritized_review = ". ".join([*booking_sentences, *other_sentences]).strip()
        if prioritized_review:
            prioritized_review = f"{prioritized_review}."
        review_note = prioritized_review
        if account_summary:
            return f"{review_note} {account_summary}".strip()
    if not account_summary:
        return review_note
    if not review_note or review_note in account_summary:
        return account_summary
    return f"{account_summary}. {review_note}"


def _possible_booking_phone_note(candidate, booking_links: str) -> str:
    if booking_links != "нет":
        return ""
    phones = candidate.contacts.get("phone", [])
    if not phones:
        return ""
    if not _has_2gis_business_enrichment(candidate):
        return ""
    return f"Возможный телефон для записи: {phones[0]} (из 2GIS, без отдельной booking-ссылки)."


def _has_2gis_business_enrichment(candidate) -> bool:
    return candidate.platform == "2gis" or any(
        [
            bool(candidate.geo_coordinates),
            bool(candidate.official_requisites),
            bool(candidate.service_fields),
            candidate.employee_count is not None,
        ]
    )


def _platform_label(value: str) -> str:
    labels = {
        "vk": "VK",
        "telegram": "Telegram",
        "places": "Google Places",
        "2gis": "2GIS",
    }
    return labels.get(value, value)


def _report_activity_class(item: RankedAccount) -> str:
    if _is_business_card_seed(item):
        return "нет данных по постингу"
    return _normalized_activity_class(item.activity_class)


def _debug_activity_class_label(item: FilterDebugItem) -> str:
    if item.platform in {"places", "2gis"} and item.posts_total <= 0:
        return "нет данных по постингу"
    if item.activity_class:
        return _normalized_activity_class(item.activity_class)
    return "нет данных"


def _is_business_card_seed(item: RankedAccount) -> bool:
    return item.candidate.platform in {"places", "2gis"} and not item.candidate.posts


def _normalized_activity_class(value: str) -> str:
    normalized = normalize_text(value)
    if "сильный действующий" in normalized:
        return "сильный действующий"
    if "умеренно активный" in normalized:
        return "умеренно активный"
    if "заброш" in normalized:
        return "заброшенный"
    if "слаб" in normalized:
        return "слабый"
    if "действующ" in normalized:
        return "действующий"
    return value


def _localize_rows(rows: list[dict[str, object]], columns: list[tuple[str, str]]) -> list[dict[str, object]]:
    return [{label: row.get(key, "") for key, label in columns} for row in rows]


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _confidence_label(value: str) -> str:
    labels = {
        "high": "высокая",
        "medium": "средняя",
        "low": "низкая",
    }
    return labels.get(value, value)


def _debug_status_label(value: str) -> str:
    labels = {
        "included": "включён",
        "excluded": "отсечён",
    }
    return labels.get(value, value)


def _debug_stage_label(value: str) -> str:
    labels = {
        "city_filter": "фильтр города",
        "service_filter": "профильный фильтр",
        "official_filter": "режим official_only",
        "final": "итоговый отчёт",
    }
    return labels.get(value, value)


def _count_signals(corpus: str, signals: list[str]) -> int:
    return sum(1 for signal in signals if normalize_text(signal) in corpus)


def _confidence_from_hits(hits: int) -> str:
    if hits >= 3:
        return "высокая"
    if hits == 2:
        return "средняя"
    return "низкая"
