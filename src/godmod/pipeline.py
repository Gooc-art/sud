from __future__ import annotations

from dataclasses import dataclass, replace
from typing import NamedTuple

from .config import RuntimeConfig
from .collectors.base import Collector
from .markers import (
    city_hits,
    configure_marker_alias_overrides,
    extract_booking_links,
    hospitality_amenity_hits,
    is_food_service,
    marker_hits,
    official_signal_hits,
    official_signal_level,
    service_profile_hits,
    normalize_text,
)
from .models import AccountCandidate, FilterDebugItem, RankedAccount, ReportBundle, SearchRequest
from .scoring import _ranking_sort_key, detect_duplicates, score_candidates


@dataclass(slots=True)
class PipelineResult:
    bundle: ReportBundle


class _ServiceProviderDecision(NamedTuple):
    keep: bool
    reason: str
    service_profile_matches: list[str]
    header_noise: list[str]
    header_commercial: list[str]
    official_hits: list[str]


PROFILE_BUSINESS_STRUCTURAL_MARKERS = [
    "адрес",
    "режим работы",
    "время работы",
    "ежедневно",
    "улица",
    "ул.",
    "дом",
    "д.",
    "павильон",
]


def run_pipeline(
    request: SearchRequest,
    *,
    collector: Collector,
    config: RuntimeConfig,
) -> PipelineResult:
    configure_marker_alias_overrides(config.rule_config)
    candidates, search_log = collector.collect(request)
    raw_candidates = list(candidates)
    collector_cache_stats = getattr(collector, "cache_stats", {})
    collector_platform_failures = list(getattr(collector, "platform_failures", []))
    collector_cache_ttls = getattr(
        collector,
        "cache_ttls",
        {
            "vk_wall_cache_ttl_hours": getattr(collector, "wall_cache_ttl_hours", ""),
            "vk_owner_cache_ttl_hours": getattr(collector, "owner_cache_ttl_hours", ""),
            "vk_city_cache_ttl_hours": getattr(collector, "city_cache_ttl_hours", ""),
            "twogis_search_cache_ttl_hours": getattr(collector, "search_cache_ttl_hours", ""),
        },
    )
    collector_platform_metrics = list(getattr(collector, "platform_metrics", []))
    filter_debug: list[FilterDebugItem] = []
    candidates, city_excluded = _filter_candidates_to_selected_city(candidates)
    filter_debug.extend(city_excluded)
    markers_by_service = {service.name: service.markers for service in request.services}
    ranked_accounts, _ = score_candidates(
        candidates,
        period_days=request.period_days,
        cities=request.cities,
        extra_markers_by_service=markers_by_service,
        max_evidence_posts=config.max_evidence_posts,
        rule_config=config.rule_config,
    )
    ranked_accounts, service_excluded, service_kept = _filter_ranked_accounts_to_service_pages(
        ranked_accounts,
        markers_by_service,
        config=config,
    )
    filter_debug.extend(service_excluded)
    ranked_accounts, official_excluded = _filter_ranked_accounts_by_report_mode(ranked_accounts, request.report_mode)
    filter_debug.extend(official_excluded)
    ranked_accounts = _collapse_ranked_accounts(ranked_accounts)
    duplicates = detect_duplicates(ranked_accounts)
    filter_debug.extend(_included_debug_items(ranked_accounts, service_kept))
    bundle = ReportBundle(
        request=request,
        ranked_accounts=ranked_accounts,
        search_log=search_log,
        duplicates_review=duplicates,
        filter_debug=filter_debug,
        raw_candidates=raw_candidates,
        report_meta={
            "rule_config_path": str(config.rule_config_path) if config.rule_config_path else "",
            "cache_enabled": config.cache_enabled,
            "cache_dir": str(config.cache_dir),
            "platform_failures": collector_platform_failures,
            "platform_failures_total": len(collector_platform_failures),
            "platform_metrics": collector_platform_metrics,
            **collector_cache_ttls,
            **collector_cache_stats,
        },
    )
    return PipelineResult(bundle=bundle)


def _filter_candidates_to_selected_city(
    candidates: list[AccountCandidate],
) -> tuple[list[AccountCandidate], list[FilterDebugItem]]:
    filtered: list[AccountCandidate] = []
    debug_rows: list[FilterDebugItem] = []
    for candidate in candidates:
        profile_texts = [
            candidate.account_name,
            candidate.username_or_id,
            candidate.description,
        ]
        matched_cities = city_hits(profile_texts, [candidate.city])
        if candidate.city in matched_cities:
            filtered.append(candidate)
            continue
        debug_rows.append(
            _base_filter_debug_item(
                candidate,
                status="excluded",
                decision_stage="city_filter",
                reason=(
                    "В профиле нет явного сигнала выбранного города: "
                    "город должен быть в названии, username или описании."
                ),
            )
        )
    return filtered, debug_rows


def _filter_ranked_accounts_to_service_pages(
    ranked_accounts: list[RankedAccount],
    markers_by_service: dict[str, list[str]],
    *,
    config: RuntimeConfig,
) -> tuple[list[RankedAccount], list[FilterDebugItem], dict[str, list[_ServiceProviderDecision]]]:
    filtered: list[RankedAccount] = []
    debug_rows: list[FilterDebugItem] = []
    kept_decisions: dict[str, list[_ServiceProviderDecision]] = {}
    for item in ranked_accounts:
        extra_markers = markers_by_service.get(item.candidate.service, [])
        decision = _service_provider_decision(item, extra_markers=extra_markers, config=config)
        if decision.keep:
            filtered.append(item)
            kept_decisions.setdefault(item.candidate.account_url, []).append(decision)
            continue
        debug_rows.append(_service_filter_debug_item(item, decision))
    return filtered, debug_rows, kept_decisions


def _is_service_provider_page(item: RankedAccount, *, extra_markers: list[str], config: RuntimeConfig) -> bool:
    return _service_provider_decision(item, extra_markers=extra_markers, config=config).keep


def _service_provider_decision(
    item: RankedAccount,
    *,
    extra_markers: list[str],
    config: RuntimeConfig,
) -> _ServiceProviderDecision:
    candidate = item.candidate
    rule_config = config.rule_config
    profile_texts = [
        candidate.account_name,
        candidate.username_or_id,
        candidate.description,
    ]
    header_noise = marker_hits([candidate.account_name, candidate.description], rule_config.hard_noise_markers)
    header_commercial = marker_hits(
        [candidate.account_name, candidate.description],
        rule_config.commercial_markers + extra_markers,
    )
    appointment_hits = marker_hits(profile_texts, rule_config.provider_appointment_markers)
    retail_hits = marker_hits(profile_texts, rule_config.service_retail_markers)
    training_hits = marker_hits(profile_texts, rule_config.service_training_markers)
    pet_hits = marker_hits(profile_texts, rule_config.pet_grooming_markers)
    hospitality_hits = hospitality_amenity_hits(profile_texts)
    official_hits = official_signal_hits(profile_texts)
    exclusion_hits = marker_hits(profile_texts, rule_config.exclusion_markers)
    commercial_count = len(item.metrics.commercial_markers)
    noise_count = len(item.metrics.noise_markers)
    direct_service_hit = normalize_text(candidate.service) in normalize_text(" ".join(filter(None, profile_texts)))
    identity_service_matches = service_profile_hits(
        [candidate.account_name, candidate.username_or_id],
        candidate.service,
        extra_markers,
    )
    context_service_matches = _context_service_hits(item, extra_markers=extra_markers)
    profile_service_matches = service_profile_hits(profile_texts, candidate.service, extra_markers)
    inferred_service_profile = candidate.platform in {"vk", "telegram"} and _has_inferred_business_profile(
        candidate=candidate,
        context_service_matches=context_service_matches,
        header_commercial=header_commercial,
        appointment_hits=appointment_hits,
        official_hits=official_hits,
    )
    strong_profile = _has_strong_business_profile(
        candidate=candidate,
        direct_service_hit=direct_service_hit,
        identity_service_matches=identity_service_matches,
        header_commercial=header_commercial,
        appointment_hits=appointment_hits,
        official_hits=official_hits,
    )

    critical_noise = {
        "доска объявлений",
        "объявления",
        "барахолка",
        "подслушано",
        "чат",
        "каталог",
        "справочник",
        "агрегатор",
        "маркетплейс",
        "товары и услуги",
    }

    if not profile_service_matches:
        if inferred_service_profile and not any(marker in critical_noise for marker in header_noise):
            profile_service_matches = context_service_matches
        else:
            return _ServiceProviderDecision(
                False,
                "Услуга не заявлена в названии, username или описании профиля.",
                profile_service_matches,
                header_noise,
                header_commercial,
                official_hits,
            )

    if exclusion_hits:
        return _ServiceProviderDecision(
            False,
            f"Профиль содержит исключающие маркеры личной/некоммерческой страницы: {', '.join(exclusion_hits)}.",
            profile_service_matches,
            header_noise + exclusion_hits,
            header_commercial,
            official_hits,
        )

    if is_food_service(candidate.service) and hospitality_hits and not identity_service_matches:
        return _ServiceProviderDecision(
            False,
            f"Профиль похож на гостиницу/отель с дополнительной food-зоной, а не на отдельную точку услуги: {', '.join(hospitality_hits)}.",
            profile_service_matches,
            header_noise + hospitality_hits,
            header_commercial,
            official_hits,
        )

    if candidate.platform in {"places", "2gis"}:
        source_label = "Google Places" if candidate.platform == "places" else "2GIS"
        if any(marker in critical_noise for marker in header_noise):
            return _ServiceProviderDecision(
                False,
                f"Карточка {source_label} похожа на агрегатор или каталог: {', '.join(header_noise)}.",
                profile_service_matches,
                header_noise,
                header_commercial,
                official_hits,
            )
        if candidate.contacts or official_hits:
            return _ServiceProviderDecision(
                True,
                f"Карточка {source_label} прошла фильтр по запросу и бизнес-сигналам.",
                profile_service_matches,
                header_noise,
                header_commercial,
                official_hits,
            )
        return _ServiceProviderDecision(
            False,
            f"Карточка {source_label} найдена по запросу, но в ней мало контактных или официальных сигналов.",
            profile_service_matches,
            header_noise,
            header_commercial,
            official_hits,
        )

    if len(pet_hits) >= 2:
        return _ServiceProviderDecision(
            False,
            "Профиль относится к pet/grooming-услугам, а не к маникюру для клиентов.",
            profile_service_matches,
            header_noise + pet_hits,
            header_commercial,
            official_hits,
        )
    if len(retail_hits) >= 3 and len(appointment_hits) < 2:
        return _ServiceProviderDecision(
            False,
            "Профиль похож на магазин материалов или товаров для мастеров, а не на исполнителя услуги.",
            profile_service_matches,
            header_noise + retail_hits,
            header_commercial,
            official_hits,
        )
    if len(training_hits) >= 3 and len(appointment_hits) < 2:
        return _ServiceProviderDecision(
            False,
            "Профиль в первую очередь продвигает обучение или курсы, а не запись клиента на услугу.",
            profile_service_matches,
            header_noise + training_hits,
            header_commercial,
            official_hits,
        )
    if commercial_count < 2 and not strong_profile and not inferred_service_profile:
        return _ServiceProviderDecision(
            False,
            f"Слишком мало коммерческих сигналов в постах за период: найдено {commercial_count}.",
            profile_service_matches,
            header_noise,
            header_commercial,
            official_hits,
        )
    if any(marker in critical_noise for marker in header_noise):
        return _ServiceProviderDecision(
            False,
            f"Профиль похож на объявления, чат или агрегатор: {', '.join(header_noise)}.",
            profile_service_matches,
            header_noise,
            header_commercial,
            official_hits,
        )
    if len(header_noise) >= 2 and len(official_hits) < 2:
        return _ServiceProviderDecision(
            False,
            "В шапке профиля слишком много шумовых признаков и мало официальных сигналов.",
            profile_service_matches,
            header_noise,
            header_commercial,
            official_hits,
        )
    if (
        not direct_service_hit
        and len(profile_service_matches) < 2
        and len(header_commercial) < 2
        and not strong_profile
        and not inferred_service_profile
    ):
        return _ServiceProviderDecision(
            False,
            "Слабый профильный сигнал услуги: услуга плохо подтверждается в шапке профиля.",
            profile_service_matches,
            header_noise,
            header_commercial,
            official_hits,
        )
    if header_noise and len(header_commercial) < 2:
        return _ServiceProviderDecision(
            False,
            "В шапке профиля есть шумовые маркеры, но не хватает коммерческих признаков.",
            profile_service_matches,
            header_noise,
            header_commercial,
            official_hits,
        )
    if noise_count >= 2 and len(header_commercial) < 1 and len(official_hits) < 1:
        return _ServiceProviderDecision(
            False,
            "По аккаунту накопилось слишком много шумовых сигналов без коммерческих или официальных подтверждений.",
            profile_service_matches,
            header_noise,
            header_commercial,
            official_hits,
        )
    return _ServiceProviderDecision(
        True,
        "Прошёл профильный фильтр и антишумовую проверку.",
        profile_service_matches,
        header_noise,
        header_commercial,
        official_hits,
    )


def _has_strong_business_profile(
    *,
    candidate: AccountCandidate,
    direct_service_hit: bool,
    identity_service_matches: list[str],
    header_commercial: list[str],
    appointment_hits: list[str],
    official_hits: list[str],
) -> bool:
    if not (direct_service_hit or identity_service_matches):
        return False

    profile_description = candidate.description or ""
    structural_signals = 0
    if candidate.contacts:
        structural_signals += 1
    if extract_booking_links([profile_description]):
        structural_signals += 1
    if candidate.api_address:
        structural_signals += 1
    if candidate.working_hours:
        structural_signals += 1
    if marker_hits([profile_description], PROFILE_BUSINESS_STRUCTURAL_MARKERS):
        structural_signals += 1
    if header_commercial or appointment_hits or official_hits:
        structural_signals += 1
    return structural_signals >= _required_business_structure_signals(candidate)


def _has_inferred_business_profile(
    *,
    candidate: AccountCandidate,
    context_service_matches: list[str],
    header_commercial: list[str],
    appointment_hits: list[str],
    official_hits: list[str],
) -> bool:
    if not context_service_matches:
        return False

    profile_description = candidate.description or ""
    structural_signals = 0
    if candidate.contacts:
        structural_signals += 1
    if extract_booking_links([profile_description]):
        structural_signals += 1
    if candidate.api_address:
        structural_signals += 1
    if candidate.working_hours:
        structural_signals += 1
    if marker_hits([profile_description], PROFILE_BUSINESS_STRUCTURAL_MARKERS):
        structural_signals += 1
    if header_commercial or appointment_hits or official_hits:
        structural_signals += 1
    return structural_signals >= _required_business_structure_signals(candidate)


def _required_business_structure_signals(candidate: AccountCandidate) -> int:
    if candidate.platform == "telegram":
        return 1
    return 2


def _context_service_hits(item: RankedAccount, *, extra_markers: list[str]) -> list[str]:
    candidate = item.candidate
    context_texts = [
        *candidate.search_queries,
        candidate.business_categories or "",
        candidate.service_fields or "",
        *[post.text for post in candidate.posts[:5]],
    ]
    return service_profile_hits(context_texts, candidate.service, extra_markers)


def _filter_ranked_accounts_by_report_mode(
    ranked_accounts: list[RankedAccount],
    report_mode: str,
) -> tuple[list[RankedAccount], list[FilterDebugItem]]:
    if report_mode != "official_only":
        return ranked_accounts, []

    filtered: list[RankedAccount] = []
    debug_rows: list[FilterDebugItem] = []
    for item in ranked_accounts:
        official_hits = official_signal_hits(
            [
                item.candidate.account_name,
                item.candidate.username_or_id,
                item.candidate.description,
                *[post.text for post in item.candidate.posts[:5]],
            ]
        )
        level = official_signal_level(official_hits)
        if level in {"средние", "сильные"}:
            filtered.append(item)
            continue
        debug_rows.append(
            FilterDebugItem(
                city=item.candidate.city,
                service=item.candidate.service,
                platform=item.candidate.platform,
                account_name=item.candidate.account_name,
                account_url=item.candidate.account_url,
                username_or_id=item.candidate.username_or_id,
                description=item.candidate.description,
                status="excluded",
                decision_stage="official_filter",
                reason=f"Недостаточно официальных признаков для режима official_only: уровень {level}.",
                search_queries=list(item.candidate.search_queries),
                posts_total=len(item.candidate.posts),
                posts_in_period=item.metrics.posts_in_period,
                score_total=item.score.total,
                activity_class=item.activity_class,
                city_signals=list(item.metrics.city_signals),
                commercial_markers=list(item.metrics.commercial_markers),
                noise_markers=list(item.metrics.noise_markers),
                official_signals=official_hits,
            )
        )
    return filtered, debug_rows


def _base_filter_debug_item(
    candidate: AccountCandidate,
    *,
    status: str,
    decision_stage: str,
    reason: str,
) -> FilterDebugItem:
    return FilterDebugItem(
        city=candidate.city,
        service=candidate.service,
        platform=candidate.platform,
        account_name=candidate.account_name,
        account_url=candidate.account_url,
        username_or_id=candidate.username_or_id,
        description=candidate.description,
        status=status,
        decision_stage=decision_stage,
        reason=reason,
        search_queries=list(candidate.search_queries),
        posts_total=len(candidate.posts),
    )


def _service_filter_debug_item(item: RankedAccount, decision: _ServiceProviderDecision) -> FilterDebugItem:
    candidate = item.candidate
    return FilterDebugItem(
        city=candidate.city,
        service=candidate.service,
        platform=candidate.platform,
        account_name=candidate.account_name,
        account_url=candidate.account_url,
        username_or_id=candidate.username_or_id,
        description=candidate.description,
        status="excluded",
        decision_stage="service_filter",
        reason=decision.reason,
        search_queries=list(candidate.search_queries),
        posts_total=len(candidate.posts),
        posts_in_period=item.metrics.posts_in_period,
        score_total=item.score.total,
        activity_class=item.activity_class,
        city_signals=list(item.metrics.city_signals),
        service_profile_hits=list(decision.service_profile_matches),
        commercial_markers=list(item.metrics.commercial_markers),
        noise_markers=list(item.metrics.noise_markers),
        official_signals=list(decision.official_hits),
    )


def _included_debug_items(
    ranked_accounts: list[RankedAccount],
    service_kept: dict[str, list[_ServiceProviderDecision]],
) -> list[FilterDebugItem]:
    rows: list[FilterDebugItem] = []
    for item in ranked_accounts:
        candidate = item.candidate
        decisions = service_kept.get(candidate.account_url, [])
        rows.append(
            FilterDebugItem(
                city=candidate.city,
                service=candidate.service,
                platform=candidate.platform,
                account_name=candidate.account_name,
                account_url=candidate.account_url,
                username_or_id=candidate.username_or_id,
                description=candidate.description,
                status="included",
                decision_stage="final",
                reason=_included_reason(decisions),
                search_queries=list(candidate.search_queries),
                posts_total=len(candidate.posts),
                posts_in_period=item.metrics.posts_in_period,
                score_total=item.score.total,
                activity_class=item.activity_class,
                city_signals=list(item.metrics.city_signals),
                service_profile_hits=_included_service_hits(decisions),
                commercial_markers=list(item.metrics.commercial_markers),
                noise_markers=list(item.metrics.noise_markers),
                official_signals=_included_official_hits(decisions),
            )
        )
    return rows


def _collapse_ranked_accounts(ranked_accounts: list[RankedAccount]) -> list[RankedAccount]:
    grouped: dict[str, list[RankedAccount]] = {}
    order: list[str] = []
    for item in ranked_accounts:
        key = _account_identity_key(item.candidate)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(item)

    collapsed: list[RankedAccount] = []
    for key in order:
        items = grouped[key]
        if len(items) == 1:
            item = items[0]
            item.candidate.matched_services = _candidate_services(item.candidate)
            collapsed.append(item)
            continue
        collapsed.append(_merge_ranked_account_group(items))
    return sorted(collapsed, key=_ranking_sort_key, reverse=True)


def _merge_ranked_account_group(items: list[RankedAccount]) -> RankedAccount:
    best_item = max(items, key=_ranking_sort_key)
    merged_candidate = _merge_candidate_group([item.candidate for item in items], preferred=best_item.candidate)
    merged_metrics = replace(
        best_item.metrics,
        commercial_markers=_merge_lists(item.metrics.commercial_markers for item in items),
        city_signals=_merge_lists(item.metrics.city_signals for item in items),
        noise_markers=_merge_lists(item.metrics.noise_markers for item in items),
        posts_in_period=max(item.metrics.posts_in_period for item in items),
        last_post_at=max((item.metrics.last_post_at for item in items if item.metrics.last_post_at is not None), default=None),
        avg_likes=_max_present(item.metrics.avg_likes for item in items),
        avg_comments=_max_present(item.metrics.avg_comments for item in items),
        avg_reposts=_max_present(item.metrics.avg_reposts for item in items),
        avg_views=_max_present(item.metrics.avg_views for item in items),
        stability_ratio=max(item.metrics.stability_ratio for item in items),
    )
    merged_evidence = _merge_evidence_posts(items)
    return RankedAccount(
        candidate=merged_candidate,
        metrics=merged_metrics,
        score=best_item.score,
        evidence_posts=merged_evidence,
        activity_class=best_item.activity_class,
    )


def _merge_candidate_group(
    candidates: list[AccountCandidate],
    *,
    preferred: AccountCandidate,
) -> AccountCandidate:
    matched_services = _merge_lists(_candidate_services(candidate) for candidate in candidates)
    merged_contacts = _merge_contacts(candidates)
    merged_posts = _merge_posts(candidates)
    return replace(
        preferred,
        service=matched_services[0] if matched_services else preferred.service,
        matched_services=matched_services,
        account_name=_prefer_string([candidate.account_name for candidate in candidates], fallback=preferred.account_name),
        account_url=_prefer_string([candidate.account_url for candidate in candidates], fallback=preferred.account_url),
        username_or_id=_prefer_string([candidate.username_or_id for candidate in candidates], fallback=preferred.username_or_id),
        description=_prefer_string([candidate.description for candidate in candidates], fallback=preferred.description),
        followers=_max_present(candidate.followers for candidate in candidates),
        posts=merged_posts,
        search_queries=_merge_lists(candidate.search_queries for candidate in candidates),
        discovery_sources=_merge_lists(candidate.discovery_sources for candidate in candidates),
        discovery_modes=_merge_lists(candidate.discovery_modes for candidate in candidates),
        contacts=merged_contacts,
        api_city=_prefer_string([candidate.api_city for candidate in candidates], fallback=preferred.api_city),
        api_address=_prefer_string([candidate.api_address for candidate in candidates], fallback=preferred.api_address),
        geo_coordinates=_prefer_string([candidate.geo_coordinates for candidate in candidates], fallback=preferred.geo_coordinates),
        business_categories=_prefer_string([candidate.business_categories for candidate in candidates], fallback=preferred.business_categories),
        rating_details=_prefer_string([candidate.rating_details for candidate in candidates], fallback=preferred.rating_details),
        working_hours=_prefer_string([candidate.working_hours for candidate in candidates], fallback=preferred.working_hours),
        price_details=_prefer_string([candidate.price_details for candidate in candidates], fallback=preferred.price_details),
        official_requisites=_prefer_string([candidate.official_requisites for candidate in candidates], fallback=preferred.official_requisites),
        service_fields=_prefer_string([candidate.service_fields for candidate in candidates], fallback=preferred.service_fields),
        employee_count=_max_present(candidate.employee_count for candidate in candidates),
    )


def _merge_posts(candidates: list[AccountCandidate]):
    unique: dict[str, object] = {}
    ordered: list[object] = []
    for candidate in candidates:
        for post in candidate.posts:
            if post.url in unique:
                continue
            unique[post.url] = post
            ordered.append(post)
    return sorted(ordered, key=lambda post: post.published_at, reverse=True)


def _merge_contacts(candidates: list[AccountCandidate]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for candidate in candidates:
        for key, values in candidate.contacts.items():
            target = merged.setdefault(key, [])
            for value in values:
                if value and value not in target:
                    target.append(value)
    return merged


def _merge_evidence_posts(items: list[RankedAccount]):
    unique: dict[str, object] = {}
    ordered: list[object] = []
    for item in items:
        for evidence in item.evidence_posts:
            existing = unique.get(evidence.url)
            if existing is None or (evidence.score, evidence.published_at) > (existing.score, existing.published_at):
                unique[evidence.url] = evidence
    ordered.extend(unique.values())
    return sorted(ordered, key=lambda evidence: (evidence.score, evidence.published_at), reverse=True)


def _candidate_services(candidate: AccountCandidate) -> list[str]:
    values = list(candidate.matched_services)
    if candidate.service:
        values.insert(0, candidate.service)
    return _merge_lists([values])


def _account_identity_key(candidate: AccountCandidate) -> str:
    account_url = candidate.account_url.strip().rstrip("/").casefold()
    if account_url:
        return account_url
    return f"{candidate.platform}:{candidate.username_or_id.strip().casefold()}"


def _merge_lists(groups) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for value in group:
            normalized = str(value).strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
    return merged


def _prefer_string(values, *, fallback: str | None) -> str | None:
    best = fallback or ""
    for value in values:
        normalized = (value or "").strip()
        if len(normalized) > len(best):
            best = normalized
    return best or None


def _max_present(values):
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(present)


def _included_reason(decisions: list[_ServiceProviderDecision]) -> str:
    if not decisions:
        return "Прошёл все фильтры и попал в итоговый отчёт."
    reasons = _merge_lists([[decision.reason] for decision in decisions])
    return "; ".join(reasons)


def _included_service_hits(decisions: list[_ServiceProviderDecision]) -> list[str]:
    return _merge_lists(decision.service_profile_matches for decision in decisions)


def _included_official_hits(decisions: list[_ServiceProviderDecision]) -> list[str]:
    return _merge_lists(decision.official_hits for decision in decisions)
