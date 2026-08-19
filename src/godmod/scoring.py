from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from .markers import (
    extract_websites,
    extract_booking_links,
    city_hits,
    extract_contacts,
    marker_hits,
)
from .models import (
    AccountCandidate,
    AccountMetrics,
    DuplicateReviewItem,
    EvidencePost,
    RankedAccount,
    ScoreBreakdown,
)
from .request_options import is_all_time_period
from .rule_config import RuleConfig, default_rule_config


BUSINESS_CARD_PLATFORMS = {"places", "2gis"}
IGNORED_WEBSITE_DUPLICATE_DOMAINS = {
    "vk.com",
    "vk.ru",
    "t.me",
    "telegram.me",
    "telegram.dog",
}


def score_candidates(
    candidates: list[AccountCandidate],
    *,
    period_days: int,
    cities: list[str],
    extra_markers_by_service: dict[str, list[str]],
    max_evidence_posts: int = 3,
    now: datetime | None = None,
    rule_config: RuleConfig | None = None,
) -> tuple[list[RankedAccount], list[DuplicateReviewItem]]:
    active_rule_config = rule_config or default_rule_config()
    ranked = [
        score_candidate(
            candidate,
            period_days=period_days,
            cities=cities,
            extra_markers=extra_markers_by_service.get(candidate.service, []),
            max_evidence_posts=max_evidence_posts,
            now=now,
            rule_config=active_rule_config,
        )
        for candidate in candidates
    ]
    _enrich_ranked_accounts_from_business_cards(ranked)
    duplicates = detect_duplicates(ranked)
    return sorted(ranked, key=_ranking_sort_key, reverse=True), duplicates


def score_candidate(
    candidate: AccountCandidate,
    *,
    period_days: int,
    cities: list[str],
    extra_markers: list[str],
    max_evidence_posts: int = 3,
    now: datetime | None = None,
    rule_config: RuleConfig | None = None,
) -> RankedAccount:
    active_rule_config = rule_config or default_rule_config()
    current_time = now or datetime.now(UTC)
    analysis_window_days = _analysis_window_days(candidate.posts, period_days, current_time)
    if is_all_time_period(period_days):
        period_posts = list(candidate.posts)
    else:
        start_at = current_time - timedelta(days=period_days)
        period_posts = [post for post in candidate.posts if post.published_at >= start_at]
    analysis_texts = [candidate.description] + [post.text for post in candidate.posts]

    texts = [candidate.description] + [post.text for post in period_posts]
    markers = active_rule_config.commercial_markers + extra_markers
    commercial_markers = marker_hits(texts, markers)
    city_signals = sorted(set([candidate.city] + city_hits(texts, cities)))
    noise_markers = marker_hits(analysis_texts, active_rule_config.noise_markers)

    metrics = AccountMetrics(
        posts_in_period=len(period_posts),
        last_post_at=max((post.published_at for post in period_posts), default=None),
        avg_likes=_average([post.likes for post in period_posts]),
        avg_comments=_average([post.comments for post in period_posts]),
        avg_reposts=_average([post.reposts for post in period_posts]),
        avg_views=_average([post.views for post in period_posts]),
        commercial_markers=commercial_markers,
        city_signals=city_signals,
        stability_ratio=_stability_ratio(period_posts, analysis_window_days),
        noise_markers=noise_markers,
    )

    if not candidate.contacts:
        candidate.contacts = extract_contacts(texts)

    score = ScoreBreakdown(
        activity=_activity_score(metrics.posts_in_period, metrics.last_post_at, analysis_window_days, current_time),
        engagement=_engagement_score(
            metrics.avg_likes,
            metrics.avg_comments,
            metrics.avg_reposts,
            metrics.avg_views,
            candidate.followers,
        ),
        commercial=_commercial_score(metrics.commercial_markers),
        locality=_locality_score(metrics.city_signals, candidate.city),
        stability=round(metrics.stability_ratio, 2),
        penalty=_noise_penalty(metrics.noise_markers, metrics.commercial_markers, metrics.posts_in_period),
    )

    evidence_posts = _select_evidence_posts(
        period_posts,
        markers=markers,
        candidate_city=candidate.city,
        known_cities=cities,
        max_items=max_evidence_posts,
        followers=candidate.followers,
    )

    return RankedAccount(
        candidate=candidate,
        metrics=metrics,
        score=score,
        evidence_posts=evidence_posts,
        activity_class=_activity_class(metrics, score.total, analysis_window_days, current_time),
    )


def detect_duplicates(ranked_accounts: list[RankedAccount]) -> list[DuplicateReviewItem]:
    for item in ranked_accounts:
        item.duplicate_group = None
        item.duplicate_reason = None
    groups_by_key: dict[str, list[RankedAccount]] = defaultdict(list)
    for item in ranked_accounts:
        candidate = item.candidate
        for key in _duplicate_group_keys(candidate, include_identity=True):
            groups_by_key[key].append(item)

    duplicates: list[DuplicateReviewItem] = []
    seen_pairs: set[tuple[str, str]] = set()
    duplicate_group_index = 0
    for reason, items in groups_by_key.items():
        unique_items = _unique_accounts(items)
        if len(unique_items) < 2:
            continue
        duplicate_group_index += 1
        duplicate_group = f"dup-{duplicate_group_index}"
        for item in unique_items:
            if item.duplicate_group is None:
                item.duplicate_group = duplicate_group
            if item.duplicate_reason is None:
                item.duplicate_reason = _duplicate_reason(reason)
        for left_index in range(len(unique_items) - 1):
            for right_index in range(left_index + 1, len(unique_items)):
                left = unique_items[left_index]
                right = unique_items[right_index]
                pair = tuple(sorted((left.candidate.account_url, right.candidate.account_url)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                confidence = _duplicate_confidence(reason)
                duplicates.append(
                    DuplicateReviewItem(
                        left_account_url=left.candidate.account_url,
                        right_account_url=right.candidate.account_url,
                        confidence=confidence,
                        reason=_duplicate_reason(reason),
                    )
                )
    return duplicates


def _enrich_ranked_accounts_from_business_cards(ranked_accounts: list[RankedAccount]) -> None:
    groups_by_key: dict[str, list[RankedAccount]] = defaultdict(list)
    for item in ranked_accounts:
        for key in _duplicate_group_keys(item.candidate, include_identity=False):
            groups_by_key[key].append(item)

    seen_pairs: set[tuple[str, str]] = set()
    for items in groups_by_key.values():
        unique_items = _unique_accounts(items)
        if len(unique_items) < 2:
            continue
        sources = [item for item in unique_items if item.candidate.platform in BUSINESS_CARD_PLATFORMS]
        targets = [item for item in unique_items if item.candidate.platform not in BUSINESS_CARD_PLATFORMS]
        if not sources or not targets:
            continue
        for source in sources:
            for target in targets:
                pair = (source.candidate.account_url, target.candidate.account_url)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                _merge_business_card_candidate(target.candidate, source.candidate)


def _duplicate_group_keys(candidate: AccountCandidate, *, include_identity: bool) -> list[str]:
    keys: list[str] = []
    if include_identity:
        keys.append(candidate.account_url)
        keys.append(candidate.username_or_id)
    for phone in candidate.contacts.get("phone", []):
        normalized_phone = _normalize_phone(phone)
        if normalized_phone:
            keys.append(f"phone:{normalized_phone}")
    for telegram_handle in candidate.contacts.get("telegram", []):
        normalized_handle = telegram_handle.strip().casefold()
        if normalized_handle:
            keys.append(f"telegram:{normalized_handle}")
    for email in candidate.contacts.get("email", []):
        normalized_email = email.strip().casefold()
        if normalized_email:
            keys.append(f"email:{normalized_email}")
    for booking_link in extract_booking_links([candidate.description]):
        keys.append(f"booking:{_normalize_link(booking_link)}")
    for website in _candidate_websites(candidate):
        keys.append(f"website:{website}")
    return keys


def _merge_business_card_candidate(target: AccountCandidate, source: AccountCandidate) -> None:
    for key, values in source.contacts.items():
        if not values:
            continue
        target_values = target.contacts.setdefault(key, [])
        for value in values:
            if value not in target_values:
                target_values.append(value)
    if source.api_address and not target.api_address:
        target.api_address = source.api_address
    if source.api_city and not target.api_city:
        target.api_city = source.api_city
    if source.geo_coordinates and not target.geo_coordinates:
        target.geo_coordinates = source.geo_coordinates
    if source.business_categories and (
        not target.business_categories or len(source.business_categories) > len(target.business_categories)
    ):
        target.business_categories = source.business_categories
    if source.rating_details and (
        not target.rating_details or len(source.rating_details) > len(target.rating_details)
    ):
        target.rating_details = source.rating_details
    if source.working_hours and (
        not target.working_hours or len(source.working_hours) > len(target.working_hours)
    ):
        target.working_hours = source.working_hours
    if source.price_details and (not target.price_details or len(source.price_details) > len(target.price_details)):
        target.price_details = source.price_details
    if source.official_requisites and (
        not target.official_requisites or len(source.official_requisites) > len(target.official_requisites)
    ):
        target.official_requisites = source.official_requisites
    if source.service_fields and (not target.service_fields or len(source.service_fields) > len(target.service_fields)):
        target.service_fields = source.service_fields
    if source.employee_count is not None and target.employee_count is None:
        target.employee_count = source.employee_count


def _normalize_phone(value: str) -> str:
    digits = "".join(char for char in value if char.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        return f"7{digits[1:]}"
    return digits if len(digits) == 11 else ""


def _normalize_link(value: str) -> str:
    return value.rstrip("/").casefold()


def _duplicate_reason(reason_key: str) -> str:
    if reason_key.startswith("phone:"):
        return f"Совпадает телефон: {reason_key.removeprefix('phone:')}"
    if reason_key.startswith("telegram:"):
        return f"Совпадает Telegram-контакт: {reason_key.removeprefix('telegram:')}"
    if reason_key.startswith("email:"):
        return f"Совпадает email: {reason_key.removeprefix('email:')}"
    if reason_key.startswith("booking:"):
        return f"Совпадает ссылка для записи: {reason_key.removeprefix('booking:')}"
    if reason_key.startswith("website:"):
        return f"Совпадает сайт: {reason_key.removeprefix('website:')}"
    return f"Общий контакт или идентификатор: {reason_key}"


def _duplicate_confidence(reason_key: str) -> str:
    if reason_key.startswith(("phone:", "booking:", "email:", "website:", "telegram:")):
        return "high"
    return "medium"


def _candidate_websites(candidate: AccountCandidate) -> list[str]:
    raw_websites = list(candidate.contacts.get("website", [])) + extract_websites([candidate.description])
    normalized: list[str] = []
    for website in raw_websites:
        domain = _root_domain(website)
        if domain and domain not in IGNORED_WEBSITE_DUPLICATE_DOMAINS and domain not in normalized:
            normalized.append(domain)
    return normalized


def _root_domain(value: str) -> str:
    normalized = _normalize_link(value)
    if normalized.startswith("https://"):
        normalized = normalized.removeprefix("https://")
    elif normalized.startswith("http://"):
        normalized = normalized.removeprefix("http://")
    normalized = normalized.removeprefix("www.")
    return normalized.split("/", 1)[0]


def _unique_accounts(items: list[RankedAccount]) -> list[RankedAccount]:
    unique: dict[str, RankedAccount] = {}
    for item in items:
        unique[item.candidate.account_url] = item
    return list(unique.values())


def _average(values: list[int | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 2)


def _analysis_window_days(posts, period_days: int, current_time: datetime) -> int:
    if not is_all_time_period(period_days):
        return max(period_days, 1)
    if not posts:
        return 365
    oldest_post_at = min(post.published_at for post in posts)
    span_days = max((current_time - oldest_post_at).days + 1, 30)
    # "За всё время" использует всё собранное API-историческое окно,
    # но не размывает активность бесконечным архивом, который API всё равно не отдаёт полностью.
    return min(span_days, 365)


def _stability_ratio(posts, period_days: int) -> float:
    if not posts:
        return 0.0
    weeks = max(math.ceil(period_days / 7), 1)
    active_weeks = {post.published_at.isocalendar().week for post in posts}
    return round(min(len(active_weeks) / weeks, 1.0), 2)


def _activity_score(
    posts_in_period: int,
    last_post_at: datetime | None,
    period_days: int,
    current_time: datetime,
) -> float:
    if posts_in_period <= 0:
        return 0.0
    target_posts = max(math.ceil(period_days / 7), 1)
    frequency = min(posts_in_period / target_posts, 1.0) * 2
    if not last_post_at:
        return round(frequency, 2)
    days_since_last_post = max((current_time - last_post_at).days, 0)
    recency = max(0.0, 1 - min(days_since_last_post / max(period_days, 1), 1))
    return round(frequency + recency, 2)


def _engagement_score(
    avg_likes: float | None,
    avg_comments: float | None,
    avg_reposts: float | None,
    avg_views: float | None,
    followers: int | None,
) -> float:
    reactions = (avg_likes or 0) + (avg_comments or 0) * 2 + (avg_reposts or 0) * 2
    if followers and followers > 0:
        ratio = reactions / followers
        views_ratio = (avg_views or 0) / followers if avg_views else 0
        return round(min(ratio * 10, 1.4) + min(views_ratio, 0.6), 2)
    if reactions <= 0 and not avg_views:
        return 0.0
    return round(min(reactions / 25, 1.3) + (0.5 if avg_views else 0), 2)


def _commercial_score(commercial_markers: list[str]) -> float:
    if not commercial_markers:
        return 0.0
    if len(commercial_markers) == 1:
        return 0.7
    return round(min(len(commercial_markers) / 4, 1.0) * 2, 2)


def _locality_score(city_signals: list[str], candidate_city: str) -> float:
    hits = set(city_signals)
    if candidate_city in hits and len(hits) > 1:
        return 2.0
    if candidate_city in hits:
        return 1.5
    if "ЯНАО/Ямал" in hits:
        return 0.8
    if hits:
        return 1.0
    return 0.0


def _noise_penalty(noise_markers: list[str], commercial_markers: list[str], posts_in_period: int) -> float:
    if not noise_markers:
        return 0.0
    penalty = 0.0
    if len(noise_markers) >= 2:
        penalty -= 0.8
    if len(noise_markers) >= 4:
        penalty -= 0.6
    if not commercial_markers:
        penalty -= 0.8
    if posts_in_period <= 1 and len(noise_markers) >= 2:
        penalty -= 0.4
    return round(max(penalty, -2.4), 2)


def _activity_class(
    metrics: AccountMetrics,
    total_score: float,
    period_days: int,
    current_time: datetime,
) -> str:
    days_since_last_post = _days_since_last_post(metrics.last_post_at, current_time)
    stale_limit = max(min(period_days, 45), 21)
    active_limit = max(min(period_days // 2, 21), 10)

    if metrics.posts_in_period <= 0 or days_since_last_post is None:
        return "заброшенный"
    if days_since_last_post > stale_limit:
        return "заброшенный"
    if total_score >= 8 and metrics.posts_in_period >= 4 and days_since_last_post <= 14:
        return "сильный действующий"
    if total_score >= 6 and days_since_last_post <= active_limit:
        return "действующий"
    if total_score >= 4:
        return "умеренно активный"
    return "слабый"


def _ranking_sort_key(item: RankedAccount) -> tuple[float, float, float, int, int, int]:
    return (
        float(_activity_priority(item.activity_class)),
        item.score.total,
        float(_freshness_score(item.metrics.last_post_at)),
        item.metrics.posts_in_period,
        len(item.metrics.commercial_markers),
        item.candidate.followers or 0,
    )


def _activity_priority(activity_class: str) -> int:
    priorities = {
        "сильный действующий": 4,
        "действующий": 3,
        "умеренно активный": 2,
        "слабый": 1,
        "заброшенный": 0,
    }
    return priorities.get(activity_class, 0)


def _freshness_score(last_post_at: datetime | None) -> float:
    if last_post_at is None:
        return -1.0
    return last_post_at.timestamp()


def _days_since_last_post(last_post_at: datetime | None, current_time: datetime) -> int | None:
    if last_post_at is None:
        return None
    return max((current_time - last_post_at).days, 0)


def _select_evidence_posts(
    posts,
    *,
    markers: list[str],
    candidate_city: str,
    known_cities: list[str],
    max_items: int,
    followers: int | None,
) -> list[EvidencePost]:
    evidence: list[EvidencePost] = []
    for post in posts:
        reasons: list[str] = []
        marker_matches = marker_hits([post.text], markers)
        city_matches = city_hits([post.text], known_cities)
        if marker_matches:
            reasons.append(f"Коммерческие маркеры: {', '.join(marker_matches[:3])}")
        if candidate_city in city_matches:
            reasons.append(f"Привязка к городу: {candidate_city}")

        interactions = (post.likes or 0) + (post.comments or 0) * 2 + (post.reposts or 0) * 2
        if interactions > 0:
            reasons.append(f"Реакции: {interactions}")
        if post.views:
            reasons.append(f"Просмотры: {post.views}")

        score = len(marker_matches) * 2 + len(city_matches) + interactions / 20
        if followers and followers > 0 and post.views:
            score += min(post.views / followers, 1.0)

        evidence.append(
            EvidencePost(
                url=post.url,
                published_at=post.published_at,
                reasons=reasons or ["Свежий пост в анализируемом периоде"],
                score=round(score, 2),
            )
        )
    return sorted(evidence, key=lambda item: item.score, reverse=True)[:max_items]
