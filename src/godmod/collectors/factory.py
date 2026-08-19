from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import sys
import time

from godmod.models import SearchLogEntry, SearchRequest
from godmod.settings import AppSettings
from godmod.telegram_profile_seeds import load_telegram_profile_seed_store
from godmod.vk_profile_seeds import load_vk_profile_seed_store

from .mock import MockCollector
from .places import PlacesCollector
from .twogis import TwoGisCollector
from .vk import VkCollector


class ConfiguredCollector:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.platform_failures: list[dict[str, str]] = []
        self.platform_metrics: list[dict[str, object]] = []
        self.cache_stats: dict[str, int] = {}
        self.cache_ttls: dict[str, object] = {}

    def collect(self, request: SearchRequest):
        candidates = []
        search_log = []
        self.platform_failures = []
        self.platform_metrics = []
        self.cache_stats = {}
        self.cache_ttls = {}

        requests_by_platform: dict[str, SearchRequest] = {}
        futures_by_platform: dict[str, Future[dict[str, object]]] = {}

        with ThreadPoolExecutor(max_workers=max(1, len(request.platforms))) as executor:
            for platform in request.platforms:
                platform_request = SearchRequest(
                    cities=request.cities,
                    services=request.services,
                    period_days=request.period_days,
                    platforms=[platform],
                    top_n=request.top_n,
                    report_mode=request.report_mode,
                )
                collector = self._collector_for_platform(platform)
                if collector is None:
                    continue
                requests_by_platform[platform] = platform_request
                futures_by_platform[platform] = executor.submit(
                    self._collect_platform,
                    platform=platform,
                    collector=collector,
                    request=platform_request,
                )

            for platform in request.platforms:
                future = futures_by_platform.get(platform)
                platform_request = requests_by_platform.get(platform)
                if future is None or platform_request is None:
                    continue
                result = future.result()
                self.platform_metrics.append(
                    {
                        "platform": platform,
                        "duration_seconds": result["duration_seconds"],
                        "candidates": len(result["candidates"]),
                        "search_log": len(result["search_log"]),
                        "failed": bool(result["error_text"]),
                    }
                )
                self._merge_cache_stats(result["cache_stats"])
                self.cache_ttls.update(result["cache_ttls"])
                error_text = str(result["error_text"] or "")
                if error_text:
                    print(
                        f"Collector failed for platform {platform}: {error_text}",
                        file=sys.stderr,
                    )
                    self.platform_failures.append({"platform": platform, "error": error_text})
                    search_log.extend(self._platform_failure_entries(platform_request, platform=platform, error_text=error_text))
                    continue
                candidates.extend(result["candidates"])
                search_log.extend(result["search_log"])

        return candidates, search_log

    def _collect_platform(self, *, platform: str, collector, request: SearchRequest) -> dict[str, object]:
        started_at = time.perf_counter()
        try:
            platform_candidates, platform_log = collector.collect(request)
        except Exception as exc:  # noqa: BLE001
            return {
                "platform": platform,
                "candidates": [],
                "search_log": [],
                "error_text": str(exc),
                "duration_seconds": round(time.perf_counter() - started_at, 3),
                "cache_stats": dict(getattr(collector, "cache_stats", {})),
                "cache_ttls": self._collector_cache_ttls(collector),
            }
        return {
            "platform": platform,
            "candidates": platform_candidates,
            "search_log": platform_log,
            "error_text": "",
            "duration_seconds": round(time.perf_counter() - started_at, 3),
            "cache_stats": dict(getattr(collector, "cache_stats", {})),
            "cache_ttls": self._collector_cache_ttls(collector),
        }

    def _merge_cache_stats(self, raw_stats: object) -> None:
        if not isinstance(raw_stats, dict):
            return
        for key, value in raw_stats.items():
            if not isinstance(key, str):
                continue
            try:
                numeric_value = int(value)
            except (TypeError, ValueError):
                continue
            self.cache_stats[key] = self.cache_stats.get(key, 0) + numeric_value

    def _collector_cache_ttls(self, collector) -> dict[str, object]:
        return {
            "vk_wall_cache_ttl_hours": getattr(collector, "wall_cache_ttl_hours", ""),
            "vk_owner_cache_ttl_hours": getattr(collector, "owner_cache_ttl_hours", ""),
            "vk_city_cache_ttl_hours": getattr(collector, "city_cache_ttl_hours", ""),
            "twogis_search_cache_ttl_hours": getattr(collector, "search_cache_ttl_hours", ""),
        }

    def _platform_failure_entries(
        self,
        request: SearchRequest,
        *,
        platform: str,
        error_text: str,
    ) -> list[SearchLogEntry]:
        entries: list[SearchLogEntry] = []
        for city in request.cities:
            for service in request.services:
                entries.append(
                    SearchLogEntry(
                        city=city,
                        service=service.name,
                        platform=platform,
                        query=f"collector:{platform}",
                        source=f"{platform}.collector.error",
                        discovery_mode=f"{platform}_collector",
                        details=error_text,
                    )
                )
        return entries

    def _collector_for_platform(self, platform: str):
        if platform == "vk":
            if self.settings.vk_api_token or self.settings.vk_service_token:
                return VkCollector(
                    user_token=self.settings.vk_api_token,
                    service_token=self.settings.vk_service_token,
                    community_token=self.settings.vk_community_token,
                    profile_seed_store=load_vk_profile_seed_store(self.settings.vk_profile_seeds_path),
                    rule_config=self.settings.runtime.rule_config,
                    cache_enabled=self.settings.runtime.cache_enabled,
                    cache_dir=self.settings.runtime.cache_dir / "vk",
                    wall_cache_ttl_hours=self.settings.runtime.vk_wall_cache_ttl_hours,
                    owner_cache_ttl_hours=self.settings.runtime.vk_owner_cache_ttl_hours,
                    city_cache_ttl_hours=self.settings.runtime.vk_city_cache_ttl_hours,
                    full_recall=self.settings.vk_full_recall,
                )
            if self.settings.use_mock_data:
                return MockCollector()
            return None

        if platform == "telegram":
            if self.settings.telegram_mtproto_ready:
                from .telegram import TelegramCollector

                return TelegramCollector(
                    api_id=self.settings.telegram_api_id,
                    api_hash=self.settings.telegram_api_hash,
                    session_string=self.settings.telegram_user_session,
                    profile_seed_store=load_telegram_profile_seed_store(self.settings.telegram_profile_seeds_path),
                )
            if self.settings.use_mock_data:
                return MockCollector()
            return None

        if platform == "places":
            if self.settings.google_places_ready:
                return PlacesCollector(
                    api_key=self.settings.google_places_api_key,
                )
            if self.settings.use_mock_data:
                return MockCollector()
        if platform == "2gis":
            if self.settings.twogis_ready:
                return TwoGisCollector(
                    api_key=self.settings.twogis_api_key,
                    cache_enabled=self.settings.runtime.cache_enabled,
                    cache_dir=self.settings.runtime.cache_dir / "2gis",
                    search_cache_ttl_hours=self.settings.runtime.twogis_search_cache_ttl_hours,
                )
            if self.settings.use_mock_data:
                return MockCollector()
        return None
