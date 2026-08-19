from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


Platform = Literal["vk", "telegram", "places", "2gis"]


@dataclass(slots=True)
class ServiceQuery:
    name: str
    markers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SearchRequest:
    cities: list[str]
    services: list[ServiceQuery]
    period_days: int
    platforms: list[Platform]
    top_n: int
    report_mode: str = "all"


@dataclass(slots=True)
class SearchLogEntry:
    city: str
    service: str
    platform: Platform
    query: str
    source: str = ""
    discovery_mode: str = ""
    details: str = ""


@dataclass(slots=True)
class PostRecord:
    url: str
    text: str
    published_at: datetime
    likes: int | None = None
    comments: int | None = None
    reposts: int | None = None
    views: int | None = None


@dataclass(slots=True)
class AccountCandidate:
    service: str
    city: str
    platform: Platform
    account_name: str
    account_url: str
    username_or_id: str
    description: str
    followers: int | None = None
    posts: list[PostRecord] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    discovery_sources: list[str] = field(default_factory=list)
    discovery_modes: list[str] = field(default_factory=list)
    contacts: dict[str, list[str]] = field(default_factory=dict)
    api_city: str | None = None
    api_address: str | None = None
    geo_coordinates: str | None = None
    business_categories: str | None = None
    rating_details: str | None = None
    working_hours: str | None = None
    price_details: str | None = None
    official_requisites: str | None = None
    service_fields: str | None = None
    employee_count: int | None = None
    matched_services: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvidencePost:
    url: str
    published_at: datetime
    reasons: list[str]
    score: float


@dataclass(slots=True)
class AccountMetrics:
    posts_in_period: int
    last_post_at: datetime | None
    avg_likes: float | None
    avg_comments: float | None
    avg_reposts: float | None
    avg_views: float | None
    commercial_markers: list[str]
    city_signals: list[str]
    stability_ratio: float
    noise_markers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScoreBreakdown:
    activity: float
    engagement: float
    commercial: float
    locality: float
    stability: float
    penalty: float = 0.0

    @property
    def total(self) -> float:
        return round(
            self.activity
            + self.engagement
            + self.commercial
            + self.locality
            + self.stability
            + self.penalty,
            2,
        )


@dataclass(slots=True)
class RankedAccount:
    candidate: AccountCandidate
    metrics: AccountMetrics
    score: ScoreBreakdown
    evidence_posts: list[EvidencePost]
    activity_class: str
    duplicate_group: str | None = None
    duplicate_reason: str | None = None


@dataclass(slots=True)
class DuplicateReviewItem:
    left_account_url: str
    right_account_url: str
    confidence: str
    reason: str


@dataclass(slots=True)
class FilterDebugItem:
    city: str
    service: str
    platform: Platform
    account_name: str
    account_url: str
    username_or_id: str
    description: str
    status: str
    decision_stage: str
    reason: str
    search_queries: list[str] = field(default_factory=list)
    posts_total: int = 0
    posts_in_period: int | None = None
    score_total: float | None = None
    activity_class: str | None = None
    city_signals: list[str] = field(default_factory=list)
    service_profile_hits: list[str] = field(default_factory=list)
    commercial_markers: list[str] = field(default_factory=list)
    noise_markers: list[str] = field(default_factory=list)
    official_signals: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReportBundle:
    request: SearchRequest
    ranked_accounts: list[RankedAccount]
    search_log: list[SearchLogEntry]
    duplicates_review: list[DuplicateReviewItem]
    filter_debug: list[FilterDebugItem] = field(default_factory=list)
    raw_candidates: list[AccountCandidate] = field(default_factory=list)
    report_meta: dict[str, object] = field(default_factory=dict)
