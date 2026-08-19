from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
import sys
from typing import Any

from godmod.markers import (
    CITY_ALIAS_MAP,
    city_hits,
    configure_marker_alias_overrides,
    extract_contacts,
    hospitality_amenity_hits,
    is_food_service,
    marker_hits,
    normalize_text,
    official_signal_hits,
    service_profile_hits,
    service_search_query_plan,
)
from godmod.models import AccountCandidate, SearchLogEntry, SearchRequest
from godmod.models import PostRecord
from godmod.request_options import is_all_time_period
from godmod.rule_config import RuleConfig, default_rule_config
from godmod.vk_api import VkApiClient, VkApiError
from godmod.vk_cache import VkDiskCache
from godmod.vk_profile_seeds import VkProfileSeedStore


SEARCH_FIELDS = [
    "about",
    "city",
    "contacts",
    "description",
    "domain",
    "followers_count",
    "members_count",
    "occupation",
    "screen_name",
    "site",
    "status",
]

SEED_GROUP_FIELDS = [
    "city",
    "contacts",
    "description",
    "members_count",
    "screen_name",
    "site",
    "status",
]

SEED_USER_FIELDS = [
    "about",
    "city",
    "followers_count",
    "occupation",
    "screen_name",
    "site",
    "status",
]

PROFILE_USER_SEARCH_FIELDS = [
    "about",
    "city",
    "followers_count",
    "occupation",
    "screen_name",
    "site",
    "status",
]

VK_PROFILE_URL_PATTERN = re.compile(r"(?:https?://)?(?:m\.)?vk\.(?:com|ru)/([^/?#]+)", re.IGNORECASE)
CRITICAL_PROFILE_NOISE = {
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


@dataclass(slots=True)
class OwnerMeta:
    owner_id: int
    kind: str
    name: str
    screen_name: str | None
    description: str
    followers: int | None
    contacts: dict[str, list[str]]
    api_city: str | None = None
    api_address: str | None = None


class VkCollector:
    platform_name = "vk"

    def __init__(
        self,
        *,
        user_token: str | None = None,
        service_token: str | None = None,
        community_token: str | None = None,
        api_client: VkApiClient | None = None,
        profile_api_client: VkApiClient | None = None,
        rule_config: RuleConfig | None = None,
        search_page_size: int = 100,
        max_search_pages: int = 2,
        max_accounts_per_query: int = 35,
        profile_search_page_size: int = 200,
        profile_search_max_pages: int = 3,
        wall_post_limit: int = 30,
        query_expansion_candidate_target: int = 8,
        profile_seed_store: VkProfileSeedStore | None = None,
        cache_enabled: bool = True,
        cache_dir: str | Path | None = None,
        disk_cache: VkDiskCache | None = None,
        wall_cache_ttl_hours: int = 24,
        owner_cache_ttl_hours: int = 72,
        city_cache_ttl_hours: int = 720,
        full_recall: bool = False,
    ) -> None:
        token = service_token or community_token or user_token
        if not token and api_client is None:
            raise ValueError("VK collector requires at least one VK token.")

        self.user_token = user_token
        self.service_token = service_token
        self.community_token = community_token
        self.api_client = api_client or VkApiClient(token)
        self.profile_api_client = profile_api_client or api_client or (VkApiClient(user_token) if user_token else None)
        self.rule_config = rule_config or default_rule_config()
        configure_marker_alias_overrides(self.rule_config)
        self.search_page_size = search_page_size
        self.max_search_pages = max_search_pages
        self.max_accounts_per_query = max_accounts_per_query
        self.profile_search_page_size = profile_search_page_size
        self.profile_search_max_pages = profile_search_max_pages
        self.wall_post_limit = wall_post_limit
        self.query_expansion_candidate_target = query_expansion_candidate_target
        self.profile_seed_store = profile_seed_store or VkProfileSeedStore()
        self._wall_cache: dict[str, list[PostRecord]] = {}
        self._owner_meta_cache: dict[int, OwnerMeta] = {}
        self._city_id_cache: dict[str, int | None] = {}
        self.wall_cache_ttl_hours = wall_cache_ttl_hours
        self.owner_cache_ttl_hours = owner_cache_ttl_hours
        self.city_cache_ttl_hours = city_cache_ttl_hours
        self.cache_stats: dict[str, int] = {
            "wall_hits": 0,
            "wall_misses": 0,
            "owner_hits": 0,
            "owner_misses": 0,
            "city_hits": 0,
            "city_misses": 0,
        }
        self.disk_cache = self._init_disk_cache(
            cache_enabled=cache_enabled,
            cache_dir=cache_dir,
            disk_cache=disk_cache,
        )
        self.full_recall = full_recall
        self._profile_search_available = bool(user_token)

    def collect(self, request: SearchRequest) -> tuple[list[AccountCandidate], list[SearchLogEntry]]:
        if "vk" not in request.platforms:
            return [], []

        candidates: dict[tuple[str, str, int], AccountCandidate] = {}
        search_log: list[SearchLogEntry] = []
        end_at = datetime.now(UTC)
        start_at = _request_start_at(end_at, request.period_days)
        extra_markers_by_service = {service.name: service.markers for service in request.services}

        for service in request.services:
            for city in request.cities:
                query_batches = self._build_query_batches(service.name, city, service.markers)
                if query_batches:
                    self._collect_discovery_batch_safely(
                        queries=query_batches[0],
                        service_name=service.name,
                        city=city,
                        start_at=start_at,
                        end_at=end_at,
                        candidates=candidates,
                        search_log=search_log,
                        extra_markers=service.markers,
                        top_n=request.top_n,
                    )
                self._collect_seed_profiles(
                    service_name=service.name,
                    city=city,
                    candidates=candidates,
                    search_log=search_log,
                )
                for queries in query_batches[1:]:
                    if self._has_enough_profile_candidates(
                        candidates=candidates,
                        service_name=service.name,
                        city=city,
                        extra_markers=service.markers,
                        top_n=request.top_n,
                    ):
                        break
                    self._collect_discovery_batch_safely(
                        queries=queries,
                        service_name=service.name,
                        city=city,
                        start_at=start_at,
                        end_at=end_at,
                        candidates=candidates,
                        search_log=search_log,
                        extra_markers=service.markers,
                        top_n=request.top_n,
                    )

        for candidate in candidates.values():
            cache_key = candidate.username_or_id
            cached_posts = self._wall_cache.get(cache_key) if cache_key in self._wall_cache else None
            if cached_posts is None and self.disk_cache is not None:
                cached_posts = self.disk_cache.get_wall_posts(
                    cache_key,
                    max_age_hours=self.wall_cache_ttl_hours,
                )
                if cached_posts is not None:
                    self.cache_stats["wall_hits"] += 1
                    self._wall_cache[cache_key] = cached_posts
                else:
                    self.cache_stats["wall_misses"] += 1
            if cached_posts is None and self._should_fetch_wall_posts(
                candidate,
                extra_markers=extra_markers_by_service.get(candidate.service, []),
            ):
                try:
                    cached_posts = self._fetch_wall_posts(candidate)
                except VkApiError as exc:
                    search_log.append(
                        SearchLogEntry(
                            city=candidate.city,
                            service=candidate.service,
                            platform="vk",
                            query=f"wall:{candidate.username_or_id}",
                            source="vk.wall.get.error",
                            discovery_mode=self._newsfeed_discovery_mode(),
                            details=str(exc),
                        )
                    )
                    print(f"VK wall fetch failed for {candidate.username_or_id}: {exc}", file=sys.stderr)
                    cached_posts = []
                self._wall_cache[cache_key] = cached_posts
                if self.disk_cache is not None:
                    self.disk_cache.set_wall_posts(cache_key, cached_posts)
            if cached_posts:
                candidate.posts = self._merge_posts(candidate.posts, cached_posts)
            if not candidate.contacts:
                candidate.contacts = extract_contacts([candidate.description] + [post.text for post in candidate.posts])

        return list(candidates.values()), search_log

    def _collect_discovery_batch_safely(
        self,
        *,
        queries: list[str],
        service_name: str,
        city: str,
        start_at: datetime,
        end_at: datetime,
        candidates: dict[tuple[str, str, int], AccountCandidate],
        search_log: list[SearchLogEntry],
        extra_markers: list[str],
        top_n: int,
    ) -> None:
        try:
            self._collect_discovery_batch(
                queries=queries,
                service_name=service_name,
                city=city,
                start_at=start_at,
                end_at=end_at,
                candidates=candidates,
                search_log=search_log,
                extra_markers=extra_markers,
                top_n=top_n,
            )
        except VkApiError as exc:
            search_log.append(
                SearchLogEntry(
                    city=city,
                    service=service_name,
                    platform="vk",
                    query=f"discovery_batch:{' | '.join(queries)}",
                    source="vk.discovery.error",
                    discovery_mode=self._newsfeed_discovery_mode(),
                    details=str(exc),
                )
            )
            print(f"VK discovery batch failed for {city}/{service_name}: {exc}", file=sys.stderr)

    def _collect_discovery_batch(
        self,
        *,
        queries: list[str],
        service_name: str,
        city: str,
        start_at: datetime,
        end_at: datetime,
        candidates: dict[tuple[str, str, int], AccountCandidate],
        search_log: list[SearchLogEntry],
        extra_markers: list[str],
        top_n: int,
    ) -> None:
        if self._profile_search_enabled():
            try:
                self._collect_profile_search_batch(
                    queries=queries,
                    service_name=service_name,
                    city=city,
                    candidates=candidates,
                    search_log=search_log,
                )
            except VkApiError as exc:
                if exc.code in {4, 5, 7, 15, 27, 28, 29}:
                    search_log.append(
                        SearchLogEntry(
                            city=city,
                            service=service_name,
                            platform="vk",
                            query=f"profile_search_batch:{' | '.join(queries)}",
                            source="vk.profile_search.error",
                            discovery_mode=self._profile_discovery_mode(),
                            details=f"{exc}; fallback={self._newsfeed_discovery_mode()}",
                        )
                    )
                    print(
                        f"VK profile discovery disabled, falling back to service-token discovery: {exc}",
                        file=sys.stderr,
                    )
                    self._profile_search_available = False
                else:
                    raise
            else:
                if self._has_enough_profile_candidates(
                    candidates=candidates,
                    service_name=service_name,
                    city=city,
                    extra_markers=extra_markers,
                    top_n=top_n,
                ):
                    return
        self._collect_query_batch(
            queries=queries,
            service_name=service_name,
            city=city,
            start_at=start_at,
            end_at=end_at,
            candidates=candidates,
            search_log=search_log,
        )

    def _collect_query_batch(
        self,
        *,
        queries: list[str],
        service_name: str,
        city: str,
        start_at: datetime,
        end_at: datetime,
        candidates: dict[tuple[str, str, int], AccountCandidate],
        search_log: list[SearchLogEntry],
    ) -> None:
        for query in self._newsfeed_batch_queries(queries, city=city):
            source = "vk.newsfeed.search"
            mode = self._newsfeed_discovery_mode()
            search_log.append(
                SearchLogEntry(
                    city=city,
                    service=service_name,
                    platform="vk",
                    query=query,
                    source=source,
                    discovery_mode=mode,
                )
            )
            self._collect_query(
                query=query,
                service_name=service_name,
                city=city,
                start_at=start_at,
                end_at=end_at,
                candidates=candidates,
                source=source,
                discovery_mode=mode,
            )

    def _collect_profile_search_batch(
        self,
        *,
        queries: list[str],
        service_name: str,
        city: str,
        candidates: dict[tuple[str, str, int], AccountCandidate],
        search_log: list[SearchLogEntry],
    ) -> None:
        city_id = self._resolve_city_id(city)
        for query in queries:
            profile_term = self._profile_query_term(query, city)
            self._collect_group_profile_search(
                query=profile_term,
                service_name=service_name,
                city=city,
                city_id=city_id,
                candidates=candidates,
                search_log=search_log,
            )
            self._collect_user_profile_search(
                query=profile_term,
                service_name=service_name,
                city=city,
                city_id=city_id,
                candidates=candidates,
                search_log=search_log,
            )

    def _collect_query(
        self,
        *,
        query: str,
        service_name: str,
        city: str,
        start_at: datetime,
        end_at: datetime,
        candidates: dict[tuple[str, str, int], AccountCandidate],
        source: str,
        discovery_mode: str,
    ) -> None:
        start_from: str | None = None
        query_owner_ids: set[int] = set()

        for _ in range(self.max_search_pages):
            response = self.api_client.call_with_retry(
                "newsfeed.search",
                {
                    "q": query,
                    "extended": True,
                    "count": self.search_page_size,
                    "start_time": int(start_at.timestamp()),
                    "end_time": int(end_at.timestamp()),
                    "start_from": start_from,
                    "fields": SEARCH_FIELDS,
                },
            )

            owner_meta = self._build_owner_meta_index(response)
            for item in self._response_items(response):
                owner_id = item.get("owner_id")
                if not isinstance(owner_id, int):
                    continue

                key = (service_name, city, owner_id)
                if key not in candidates and len(query_owner_ids) >= self.max_accounts_per_query:
                    continue

                meta = owner_meta.get(owner_id) or self._fallback_owner_meta(owner_id)
                candidate = candidates.get(key)
                if candidate is None:
                    candidate = self._build_candidate(
                        service_name=service_name,
                        city=city,
                        owner_meta=meta,
                    )
                    candidates[key] = candidate
                    query_owner_ids.add(owner_id)
                else:
                    self._merge_candidate_from_meta(candidate, meta)

                self._append_discovery_trace(candidate, query=query, source=source, discovery_mode=discovery_mode)
                post = self._post_from_wall_item(item)
                if post is not None:
                    candidate.posts = self._merge_posts(candidate.posts, [post])

            start_from = self._response_next_from(response)
            if not start_from or len(query_owner_ids) >= self.max_accounts_per_query:
                break

    def _build_query_batches(self, service_name: str, city: str, markers: list[str]) -> list[list[str]]:
        return service_search_query_plan(
            service_name,
            city,
            markers,
            alias_limit=3,
            discovery_limit=4,
            marker_limit=2,
        )

    def _newsfeed_batch_queries(self, queries: list[str], *, city: str) -> list[str]:
        expanded: list[str] = []
        for query in queries:
            if query and query not in expanded:
                expanded.append(query)
            city_first = self._city_first_query(query, city=city)
            if city_first and city_first not in expanded:
                expanded.append(city_first)
        return expanded

    @staticmethod
    def _city_first_query(query: str, *, city: str) -> str | None:
        stripped_query = query.strip()
        stripped_city = city.strip()
        if not stripped_query or not stripped_city:
            return None
        if not stripped_query.endswith(stripped_city):
            return None
        service_part = stripped_query[: -len(stripped_city)].strip()
        if not service_part:
            return None
        return f"{stripped_city} {service_part}".strip()

    def _profile_search_enabled(self) -> bool:
        return self._profile_search_available and self.profile_api_client is not None

    def _has_enough_profile_candidates(
        self,
        *,
        candidates: dict[tuple[str, str, int], AccountCandidate],
        service_name: str,
        city: str,
        extra_markers: list[str],
        top_n: int,
    ) -> bool:
        if self.full_recall:
            return False
        target = min(self.max_accounts_per_query, max(2, min(top_n, self.query_expansion_candidate_target)))
        matched = 0
        for candidate in candidates.values():
            if candidate.service != service_name or candidate.city != city:
                continue
            if not self._profile_prefilter_matches(candidate, extra_markers=extra_markers):
                continue
            matched += 1
            if matched >= target:
                return True
        return False

    def _collect_group_profile_search(
        self,
        *,
        query: str,
        service_name: str,
        city: str,
        city_id: int | None,
        candidates: dict[tuple[str, str, int], AccountCandidate],
        search_log: list[SearchLogEntry],
    ) -> None:
        params: dict[str, object] = {
            "q": query,
            "count": self.profile_search_page_size,
        }
        if city_id is not None:
            params["city_id"] = city_id
        search_log.append(
            SearchLogEntry(
                city=city,
                service=service_name,
                platform="vk",
                query=f"profile_groups:{query}",
                source="vk.groups.search",
                discovery_mode=self._profile_discovery_mode(),
            )
        )
        discovered_for_query = 0
        for page in range(self.profile_search_max_pages):
            page_params = dict(params)
            page_params["offset"] = page * self.profile_search_page_size
            response = self._profile_client().call_with_retry("groups.search", page_params)
            items = self._response_items(response)
            if not items:
                break
            for item in items:
                group_id = item.get("id")
                if not isinstance(group_id, int):
                    continue
                owner_id = -group_id
                key = (service_name, city, owner_id)
                screen_name_hint = item.get("screen_name") or item.get("domain")
                meta = self._fetch_owner_meta(owner_id, screen_name_hint=screen_name_hint)
                candidate = candidates.get(key)
                if candidate is None:
                    candidate = self._build_candidate(
                        service_name=service_name,
                        city=city,
                        owner_meta=meta,
                    )
                    candidates[key] = candidate
                    discovered_for_query += 1
                else:
                    self._merge_candidate_from_meta(candidate, meta)
                self._append_discovery_trace(
                    candidate,
                    query=f"profile_groups:{query}",
                    source="vk.groups.search",
                    discovery_mode=self._profile_discovery_mode(),
                )
            if len(items) < self.profile_search_page_size or discovered_for_query >= self.max_accounts_per_query:
                break

    def _collect_user_profile_search(
        self,
        *,
        query: str,
        service_name: str,
        city: str,
        city_id: int | None,
        candidates: dict[tuple[str, str, int], AccountCandidate],
        search_log: list[SearchLogEntry],
    ) -> None:
        params: dict[str, object] = {
            "q": query,
            "count": self.profile_search_page_size,
            "fields": PROFILE_USER_SEARCH_FIELDS,
        }
        if city_id is not None:
            params["city"] = city_id
        search_log.append(
            SearchLogEntry(
                city=city,
                service=service_name,
                platform="vk",
                query=f"profile_users:{query}",
                source="vk.users.search",
                discovery_mode=self._profile_discovery_mode(),
            )
        )
        discovered_for_query = 0
        for page in range(self.profile_search_max_pages):
            page_params = dict(params)
            page_params["offset"] = page * self.profile_search_page_size
            response = self._profile_client().call_with_retry("users.search", page_params)
            items = self._response_items(response)
            if not items:
                break
            for item in items:
                profile_id = item.get("id")
                if not isinstance(profile_id, int):
                    continue
                key = (service_name, city, profile_id)
                meta = self._owner_meta_from_profile(item)
                candidate = candidates.get(key)
                if candidate is None:
                    candidate = self._build_candidate(
                        service_name=service_name,
                        city=city,
                        owner_meta=meta,
                    )
                    candidates[key] = candidate
                    discovered_for_query += 1
                else:
                    self._merge_candidate_from_meta(candidate, meta)
                self._append_discovery_trace(
                    candidate,
                    query=f"profile_users:{query}",
                    source="vk.users.search",
                    discovery_mode=self._profile_discovery_mode(),
                )
            if len(items) < self.profile_search_page_size or discovered_for_query >= self.max_accounts_per_query:
                break

    def _collect_seed_profiles(
        self,
        *,
        service_name: str,
        city: str,
        candidates: dict[tuple[str, str, int], AccountCandidate],
        search_log: list[SearchLogEntry],
    ) -> None:
        for raw_url in self.profile_seed_store.urls_for(city, service_name):
            screen_name = self._seed_screen_name(raw_url)
            if not screen_name:
                continue
            search_log.append(
                SearchLogEntry(
                    city=city,
                    service=service_name,
                    platform="vk",
                    query=f"seed:{raw_url}",
                    source="vk.seed",
                    discovery_mode=self._seed_discovery_mode(),
                )
            )
            owner_id = self._seed_owner_id(screen_name)
            if owner_id is None:
                continue
            key = (service_name, city, owner_id)
            meta = self._fetch_owner_meta(owner_id, screen_name_hint=screen_name)
            candidate = candidates.get(key)
            if candidate is None:
                candidate = self._build_candidate(
                    service_name=service_name,
                    city=city,
                    owner_meta=meta,
                )
                candidates[key] = candidate
            else:
                self._merge_candidate_from_meta(candidate, meta)
            self._append_discovery_trace(
                candidate,
                query=f"seed:{screen_name}",
                source="vk.seed",
                discovery_mode=self._seed_discovery_mode(),
            )

    def _should_fetch_wall_posts(self, candidate: AccountCandidate, *, extra_markers: list[str]) -> bool:
        return self._profile_prefilter_matches(candidate, extra_markers=extra_markers)

    def _profile_prefilter_matches(self, candidate: AccountCandidate, *, extra_markers: list[str]) -> bool:
        profile_texts = [
            candidate.account_name,
            candidate.username_or_id,
            candidate.description,
        ]
        if candidate.city not in city_hits(profile_texts, [candidate.city]):
            return False
        if not service_profile_hits(profile_texts, candidate.service, extra_markers):
            return False

        header_noise = marker_hits([candidate.account_name, candidate.description], self.rule_config.hard_noise_markers)
        appointment_hits = marker_hits(profile_texts, self.rule_config.provider_appointment_markers)
        retail_hits = marker_hits(profile_texts, self.rule_config.service_retail_markers)
        training_hits = marker_hits(profile_texts, self.rule_config.service_training_markers)
        pet_hits = marker_hits(profile_texts, self.rule_config.pet_grooming_markers)
        hospitality_hits = hospitality_amenity_hits(profile_texts)
        official_hits = official_signal_hits(profile_texts)
        header_commercial = marker_hits(
            [candidate.account_name, candidate.description],
            self.rule_config.commercial_markers + extra_markers,
        )
        identity_service_matches = service_profile_hits(
            [candidate.account_name, candidate.username_or_id],
            candidate.service,
            extra_markers,
        )

        if any(marker in CRITICAL_PROFILE_NOISE for marker in header_noise):
            return False
        if is_food_service(candidate.service) and hospitality_hits and not identity_service_matches:
            return False
        if len(pet_hits) >= 2:
            return False
        if len(retail_hits) >= 3 and len(appointment_hits) < 2:
            return False
        if len(training_hits) >= 3 and len(appointment_hits) < 2:
            return False
        if header_noise and len(header_commercial) < 1 and len(official_hits) < 1:
            return False
        return True

    def _build_owner_meta_index(self, response: dict[str, Any] | list[dict[str, Any]]) -> dict[int, OwnerMeta]:
        index: dict[int, OwnerMeta] = {}
        if not isinstance(response, dict):
            return index

        for profile in response.get("profiles", []):
            if not isinstance(profile, dict):
                continue
            profile_id = profile.get("id")
            if not isinstance(profile_id, int):
                continue
            index[profile_id] = self._owner_meta_from_profile(profile)

        for group in response.get("groups", []):
            if not isinstance(group, dict):
                continue
            group_id = group.get("id")
            if not isinstance(group_id, int):
                continue
            owner_id = -group_id
            index[owner_id] = OwnerMeta(
                owner_id=owner_id,
                kind="group",
                name=group.get("name", f"club{group_id}"),
                screen_name=group.get("screen_name") or group.get("domain"),
                description=self._group_description(group),
                followers=self._first_int(group, "members_count"),
                contacts=self._group_contacts(group),
                api_city=self._city_title(group.get("city")) or None,
            )
        return index

    def _owner_meta_from_profile(self, profile: dict[str, Any]) -> OwnerMeta:
        profile_id = profile.get("id")
        if not isinstance(profile_id, int):
            raise TypeError("Profile id must be int")
        return OwnerMeta(
            owner_id=profile_id,
            kind="user",
            name=self._profile_name(profile),
            screen_name=profile.get("screen_name") or profile.get("domain"),
            description=self._profile_description(profile),
            followers=self._first_int(profile, "followers_count"),
            contacts=extract_contacts(
                [
                    profile.get("about", ""),
                    profile.get("status", ""),
                    profile.get("site", ""),
                ]
            ),
            api_city=self._city_title(profile.get("city")) or None,
        )

    def _build_candidate(
        self,
        *,
        service_name: str,
        city: str,
        owner_meta: OwnerMeta,
    ) -> AccountCandidate:
        account_url, username_or_id = self._account_url(owner_meta)
        return AccountCandidate(
            service=service_name,
            city=city,
            platform="vk",
            account_name=owner_meta.name,
            account_url=account_url,
            username_or_id=username_or_id,
            description=owner_meta.description,
            followers=owner_meta.followers,
            contacts=owner_meta.contacts,
            api_city=owner_meta.api_city,
            api_address=owner_meta.api_address,
        )

    def _merge_candidate_from_meta(self, candidate: AccountCandidate, owner_meta: OwnerMeta) -> None:
        if not candidate.description and owner_meta.description:
            candidate.description = owner_meta.description
        if candidate.followers is None and owner_meta.followers is not None:
            candidate.followers = owner_meta.followers
        if not candidate.contacts and owner_meta.contacts:
            candidate.contacts = owner_meta.contacts
        if candidate.api_city is None and owner_meta.api_city is not None:
            candidate.api_city = owner_meta.api_city
        if candidate.api_address is None and owner_meta.api_address is not None:
            candidate.api_address = owner_meta.api_address

    def _fetch_wall_posts(self, candidate: AccountCandidate) -> list[PostRecord]:
        try:
            response = self.api_client.call_with_retry(
                "wall.get",
                {
                    "domain": candidate.username_or_id,
                    "count": self.wall_post_limit,
                    "filter": "owner",
                },
            )
        except VkApiError as exc:
            if exc.code in {15, 18, 30, 100, 113}:
                return []
            raise
        return [
            post
            for item in self._response_items(response)
            if (post := self._post_from_wall_item(item)) is not None
        ]

    def _post_from_wall_item(self, item: dict[str, Any]) -> PostRecord | None:
        owner_id = item.get("owner_id")
        post_id = item.get("id")
        timestamp = item.get("date")
        if not isinstance(owner_id, int) or not isinstance(post_id, int) or not isinstance(timestamp, int):
            return None

        return PostRecord(
            url=f"https://vk.com/wall{owner_id}_{post_id}",
            text=item.get("text", "") or "",
            published_at=datetime.fromtimestamp(timestamp, UTC),
            likes=self._nested_int(item, "likes", "count"),
            comments=self._nested_int(item, "comments", "count"),
            reposts=self._nested_int(item, "reposts", "count"),
            views=self._nested_int(item, "views", "count"),
        )

    def _group_description(self, group: dict[str, Any]) -> str:
        parts = [
            group.get("description", ""),
            group.get("status", ""),
            group.get("site", ""),
            self._city_title(group.get("city")),
        ]
        for contact in group.get("contacts", []) or []:
            for key in ("phone", "email", "desc"):
                value = contact.get(key)
                if value:
                    parts.append(str(value))
        return " | ".join(part for part in parts if part)

    def _profile_description(self, profile: dict[str, Any]) -> str:
        occupation = profile.get("occupation", {}) or {}
        parts = [
            profile.get("about", ""),
            profile.get("status", ""),
            profile.get("site", ""),
            self._city_title(profile.get("city")),
            occupation.get("name", ""),
        ]
        return " | ".join(part for part in parts if part)

    def _group_contacts(self, group: dict[str, Any]) -> dict[str, list[str]]:
        values: dict[str, list[str]] = {}
        phones: set[str] = set()
        emails: set[str] = set()
        for contact in group.get("contacts", []) or []:
            phone = contact.get("phone")
            email = contact.get("email")
            if phone:
                phones.add(str(phone))
            if email:
                emails.add(str(email))
        if phones:
            values["phone"] = sorted(phones)
        if emails:
            values["email"] = sorted(emails)

        extracted = extract_contacts([self._group_description(group)])
        for key, items in extracted.items():
            values.setdefault(key, [])
            for item in items:
                if item not in values[key]:
                    values[key].append(item)
        return values

    def _account_url(self, owner_meta: OwnerMeta) -> tuple[str, str]:
        if owner_meta.screen_name:
            return f"https://vk.com/{owner_meta.screen_name}", owner_meta.screen_name
        numeric = abs(owner_meta.owner_id)
        if owner_meta.kind == "group":
            username = f"club{numeric}"
        else:
            username = f"id{numeric}"
        return f"https://vk.com/{username}", username

    def _fallback_owner_meta(self, owner_id: int) -> OwnerMeta:
        kind = "group" if owner_id < 0 else "user"
        numeric = abs(owner_id)
        return OwnerMeta(
            owner_id=owner_id,
            kind=kind,
            name=f"{kind}_{numeric}",
            screen_name=None,
            description="",
            followers=None,
            contacts={},
        )

    def _seed_screen_name(self, value: str) -> str | None:
        token = value.strip()
        if not token:
            return None
        match = VK_PROFILE_URL_PATTERN.search(token)
        if match:
            return match.group(1)
        return token.strip("/")

    def _seed_owner_id(self, screen_name: str) -> int | None:
        if screen_name.startswith("club") and screen_name[4:].isdigit():
            return -int(screen_name[4:])
        if screen_name.startswith("public") and screen_name[6:].isdigit():
            return -int(screen_name[6:])
        if screen_name.startswith("id") and screen_name[2:].isdigit():
            return int(screen_name[2:])
        try:
            response = self.api_client.call_with_retry(
                "utils.resolveScreenName",
                {"screen_name": screen_name},
            )
        except VkApiError:
            return None
        if not isinstance(response, dict):
            return None
        resolved_type = response.get("type")
        object_id = response.get("object_id")
        if not isinstance(object_id, int):
            return None
        if resolved_type == "group":
            return -object_id
        if resolved_type == "user":
            return object_id
        return None

    def _fetch_owner_meta(self, owner_id: int, *, screen_name_hint: str | None = None) -> OwnerMeta:
        cached = self._owner_meta_cache.get(owner_id)
        if cached is not None:
            return cached
        if self.disk_cache is not None:
            cached_payload = self.disk_cache.get_owner_meta(
                owner_id,
                max_age_hours=self.owner_cache_ttl_hours,
            )
            if cached_payload is not None:
                try:
                    cached_meta = self._owner_meta_from_cache_payload(cached_payload)
                except TypeError:
                    cached_meta = None
                if cached_meta is not None:
                    self.cache_stats["owner_hits"] += 1
                    self._owner_meta_cache[owner_id] = cached_meta
                    return cached_meta
            self.cache_stats["owner_misses"] += 1

        try:
            if owner_id < 0:
                response = self.api_client.call_with_retry(
                    "groups.getById",
                    {
                        "group_id": abs(owner_id),
                        "fields": SEED_GROUP_FIELDS,
                    },
                )
                group = response[0] if isinstance(response, list) else (response.get("groups") or [response])[0]
                meta = OwnerMeta(
                    owner_id=owner_id,
                    kind="group",
                    name=group.get("name", f"club{abs(owner_id)}"),
                    screen_name=group.get("screen_name") or group.get("domain") or screen_name_hint,
                    description=self._group_description(group),
                    followers=self._first_int(group, "members_count"),
                    contacts=self._group_contacts(group),
                    api_city=self._city_title(group.get("city")) or None,
                )
            else:
                response = self.api_client.call_with_retry(
                    "users.get",
                    {
                        "user_ids": owner_id,
                        "fields": SEED_USER_FIELDS,
                    },
                )
                profile = response[0] if isinstance(response, list) else response
                meta = OwnerMeta(
                    owner_id=owner_id,
                    kind="user",
                    name=self._profile_name(profile),
                    screen_name=profile.get("screen_name") or profile.get("domain") or screen_name_hint,
                    description=self._profile_description(profile),
                    followers=self._first_int(profile, "followers_count"),
                    contacts=extract_contacts(
                        [
                            profile.get("about", ""),
                            profile.get("status", ""),
                            profile.get("site", ""),
                        ]
                    ),
                    api_city=self._city_title(profile.get("city")) or None,
                )
        except (VkApiError, KeyError, IndexError, TypeError):
            meta = self._fallback_owner_meta(owner_id)
            if screen_name_hint and not meta.screen_name:
                meta = OwnerMeta(
                    owner_id=meta.owner_id,
                    kind=meta.kind,
                    name=meta.name,
                    screen_name=screen_name_hint,
                    description=meta.description,
                    followers=meta.followers,
                    contacts=meta.contacts,
                )

        self._owner_meta_cache[owner_id] = meta
        if self.disk_cache is not None:
            self.disk_cache.set_owner_meta(owner_id, self._owner_meta_to_cache_payload(meta))
        return meta

    def _profile_name(self, profile: dict[str, Any]) -> str:
        first_name = profile.get("first_name", "")
        last_name = profile.get("last_name", "")
        return " ".join(part for part in [first_name, last_name] if part).strip() or str(profile.get("id"))

    def _resolve_city_id(self, city: str) -> int | None:
        if city in self._city_id_cache:
            return self._city_id_cache[city]
        if self.disk_cache is not None:
            cached_city_id = self.disk_cache.get_city_id(
                city,
                max_age_hours=self.city_cache_ttl_hours,
            )
            if cached_city_id is not Ellipsis:
                self.cache_stats["city_hits"] += 1
                self._city_id_cache[city] = cached_city_id
                return cached_city_id
            self.cache_stats["city_misses"] += 1

        try:
            response = self._profile_client().call_with_retry(
                "database.getCities",
                {
                    "country_id": 1,
                    "q": city,
                    "need_all": 1,
                    "count": 20,
                },
            )
        except VkApiError:
            self._city_id_cache[city] = None
            return None

        items = self._response_items(response)
        matched_id: int | None = None
        aliases = {normalize_text(city), *[normalize_text(alias) for alias in CITY_ALIAS_MAP.get(city, [])]}
        aliases = {alias for alias in aliases if alias}
        for item in items:
            city_id = item.get("id")
            title = item.get("title")
            if not isinstance(city_id, int) or not isinstance(title, str):
                continue
            normalized_title = normalize_text(title)
            if normalized_title in aliases:
                matched_id = city_id
                break
        if matched_id is None:
            first_item = next((item for item in items if isinstance(item.get("id"), int)), None)
            matched_id = first_item.get("id") if first_item else None

        self._city_id_cache[city] = matched_id
        if self.disk_cache is not None:
            self.disk_cache.set_city_id(city, matched_id)
        return matched_id

    def _profile_query_term(self, query: str, city: str) -> str:
        normalized_query = normalize_text(query)
        normalized_city = normalize_text(city)
        suffix = f" {normalized_city}"
        if normalized_query.endswith(suffix):
            return query[: -len(city)].strip()
        return query.strip()

    def _city_title(self, city: Any) -> str:
        if isinstance(city, dict):
            title = city.get("title")
            if isinstance(title, str):
                return title
        return ""

    def _first_int(self, data: dict[str, Any], key: str) -> int | None:
        value = data.get(key)
        return value if isinstance(value, int) else None

    def _nested_int(self, data: dict[str, Any], *path: str) -> int | None:
        current: Any = data
        for part in path:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current if isinstance(current, int) else None

    def _merge_posts(self, current: list[PostRecord], extra: list[PostRecord]) -> list[PostRecord]:
        merged = {post.url: post for post in current}
        for post in extra:
            merged[post.url] = post
        return sorted(merged.values(), key=lambda post: post.published_at, reverse=True)

    def _append_discovery_trace(
        self,
        candidate: AccountCandidate,
        *,
        query: str,
        source: str,
        discovery_mode: str,
    ) -> None:
        candidate.search_queries.append(query)
        if source and source not in candidate.discovery_sources:
            candidate.discovery_sources.append(source)
        if discovery_mode and discovery_mode not in candidate.discovery_modes:
            candidate.discovery_modes.append(discovery_mode)

    def _profile_discovery_mode(self) -> str:
        if self.user_token:
            return "vk_user_token"
        return "vk_profile_unknown"

    def _newsfeed_discovery_mode(self) -> str:
        if self.service_token:
            return "vk_service_token"
        if self.community_token:
            return "vk_community_token"
        if self.user_token:
            return "vk_user_token"
        return "vk_unknown"

    def _seed_discovery_mode(self) -> str:
        if self.service_token:
            return "vk_seed_service_token"
        if self.user_token:
            return "vk_seed_user_token"
        return "vk_seed_unknown"

    def _profile_client(self) -> VkApiClient:
        if self.profile_api_client is None:
            raise VkApiError("Profile search is not configured.")
        return self.profile_api_client

    def _init_disk_cache(
        self,
        *,
        cache_enabled: bool,
        cache_dir: str | Path | None,
        disk_cache: VkDiskCache | None,
    ) -> VkDiskCache | None:
        if not cache_enabled:
            return None
        if disk_cache is not None:
            return disk_cache
        if cache_dir is None:
            return None
        return VkDiskCache(cache_dir)

    def _owner_meta_from_cache_payload(self, payload: dict[str, Any]) -> OwnerMeta:
        owner_id = payload.get("owner_id")
        if not isinstance(owner_id, int):
            raise TypeError("Cached owner meta missing owner_id")
        kind = payload.get("kind")
        if kind not in {"group", "user"}:
            kind = "group" if owner_id < 0 else "user"
        contacts = payload.get("contacts")
        return OwnerMeta(
            owner_id=owner_id,
            kind=kind,
            name=str(payload.get("name") or ""),
            screen_name=str(payload.get("screen_name") or "") or None,
            description=str(payload.get("description") or ""),
            followers=self._optional_int(payload.get("followers")),
            contacts=contacts if isinstance(contacts, dict) else {},
            api_city=str(payload.get("api_city") or "") or None,
            api_address=str(payload.get("api_address") or "") or None,
        )

    def _owner_meta_to_cache_payload(self, meta: OwnerMeta) -> dict[str, Any]:
        return {
            "owner_id": meta.owner_id,
            "kind": meta.kind,
            "name": meta.name,
            "screen_name": meta.screen_name or "",
            "description": meta.description,
            "followers": meta.followers,
            "contacts": meta.contacts,
            "api_city": meta.api_city or "",
            "api_address": meta.api_address or "",
        }

    def _optional_int(self, value: object) -> int | None:
        return value if isinstance(value, int) else None

    def _response_items(self, response: Any) -> list[dict[str, Any]]:
        raw_items: Any
        if isinstance(response, dict):
            raw_items = response.get("items", [])
        elif isinstance(response, list):
            raw_items = response
        else:
            return []
        if not isinstance(raw_items, list):
            return []
        return [item for item in raw_items if isinstance(item, dict)]

    def _response_next_from(self, response: Any) -> str | None:
        if not isinstance(response, dict):
            return None
        value = response.get("next_from")
        return value if isinstance(value, str) and value else None


def _request_start_at(end_at: datetime, period_days: int) -> datetime:
    if is_all_time_period(period_days):
        return datetime(2006, 1, 1, tzinfo=UTC)
    return end_at - timedelta(days=period_days)
