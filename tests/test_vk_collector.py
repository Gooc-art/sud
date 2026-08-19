from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from godmod.collectors.vk import VkCollector
from godmod.models import AccountCandidate, PostRecord, SearchRequest, ServiceQuery
from godmod.vk_api import VkApiError
from godmod.vk_profile_seeds import VkProfileSeedEntry, VkProfileSeedStore


class FakeVkApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
        self.calls.append((method, params))
        if method == "newsfeed.search":
            return {
                "items": [
                    {
                        "owner_id": -123,
                        "id": 1,
                        "date": 1_710_000_000,
                        "text": "Маникюр Салехард, запись в лс, цена 2500",
                        "likes": {"count": 10},
                        "comments": {"count": 2},
                        "reposts": {"count": 1},
                        "views": {"count": 150},
                    }
                ],
                "groups": [
                    {
                        "id": 123,
                        "name": "Nails Studio",
                        "screen_name": "nails_studio",
                        "description": "Маникюр в Салехарде",
                        "members_count": 777,
                        "city": {"title": "Салехард"},
                        "contacts": [{"phone": "+7 900 000-00-00"}],
                    }
                ],
                "profiles": [],
            }
        if method == "wall.get":
            return {
                "count": 2,
                "items": [
                    {
                        "owner_id": -123,
                        "id": 2,
                        "date": 1_710_100_000,
                        "text": "Отзывы клиентов и свободные окна",
                        "likes": {"count": 5},
                        "comments": {"count": 1},
                        "reposts": {"count": 0},
                        "views": {"count": 100},
                    }
                ],
            }
        raise AssertionError(f"Unexpected method: {method}")


class VkCollectorTests(unittest.TestCase):
    def test_collect_builds_candidates_from_newsfeed_and_wall(self) -> None:
        collector = VkCollector(api_client=FakeVkApiClient())
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр", markers=["запись"])],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertEqual(len(search_log), 15)
        self.assertEqual(len(candidates), 1)
        queries = [entry.query for entry in search_log]
        self.assertIn("Салехард маникюр", queries)
        self.assertIn("nails Салехард", queries)
        self.assertIn("Салехард nails", queries)
        self.assertIn("ногти Салехард", queries)
        self.assertIn("мастер маникюра Салехард", queries)
        self.assertTrue(all(entry.source == "vk.newsfeed.search" for entry in search_log))
        self.assertTrue(all(entry.discovery_mode == "vk_unknown" for entry in search_log))
        candidate = candidates[0]
        self.assertEqual(candidate.account_url, "https://vk.com/nails_studio")
        self.assertEqual(candidate.followers, 777)
        self.assertEqual(len(candidate.posts), 2)
        self.assertIn("Маникюр в Салехарде", candidate.description)
        self.assertIn("+7 900 000-00-00", candidate.contacts["phone"])

    def test_collect_tolerates_list_newsfeed_payload(self) -> None:
        class ListNewsfeedVkApiClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object] | None]] = []

            def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
                self.calls.append((method, params))
                if method == "newsfeed.search":
                    return [
                        {
                            "owner_id": -123,
                            "id": 1,
                            "date": 1_710_000_000,
                            "text": "Маникюр Салехард, запись в лс, цена 2500",
                            "likes": {"count": 10},
                            "comments": {"count": 2},
                            "reposts": {"count": 1},
                            "views": {"count": 150},
                        }
                    ]
                raise AssertionError(f"Unexpected method: {method}")

        collector = VkCollector(api_client=ListNewsfeedVkApiClient())
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр", markers=["запись"])],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertEqual(len(search_log), 15)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].account_url, "https://vk.com/club123")
        self.assertEqual(len(candidates[0].posts), 1)

    def test_collect_uses_early_start_date_for_all_time_period(self) -> None:
        api_client = FakeVkApiClient()
        collector = VkCollector(api_client=api_client)
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=0,
            platforms=["vk"],
            top_n=10,
        )

        collector.collect(request)

        newsfeed_calls = [params for method, params in api_client.calls if method == "newsfeed.search"]
        self.assertTrue(newsfeed_calls)
        self.assertEqual(
            newsfeed_calls[0]["start_time"],
            int(datetime(2006, 1, 1, tzinfo=UTC).timestamp()),
        )

    def test_collect_includes_seeded_profiles_when_newsfeed_search_misses_them(self) -> None:
        class SeedOnlyVkApiClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object] | None]] = []

            def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
                self.calls.append((method, params))
                if method == "newsfeed.search":
                    return {"items": [], "groups": [], "profiles": []}
                if method == "utils.resolveScreenName":
                    return {"type": "group", "object_id": 321}
                if method == "groups.getById":
                    return [
                        {
                            "id": 321,
                            "name": "Loft Nails Салехард",
                            "screen_name": "loft_shd",
                            "description": "Маникюр в Салехарде, запись в лс",
                            "members_count": 456,
                            "city": {"title": "Салехард"},
                            "contacts": [{"phone": "+7 900 111-22-33"}],
                        }
                    ]
                if method == "wall.get":
                    return {
                        "count": 1,
                        "items": [
                            {
                                "owner_id": -321,
                                "id": 7,
                                "date": 1_710_100_000,
                                "text": "Свободные окна, запись в сообщения, цена 2500",
                                "likes": {"count": 8},
                                "comments": {"count": 1},
                                "reposts": {"count": 0},
                                "views": {"count": 90},
                            }
                        ],
                    }
                raise AssertionError(f"Unexpected method: {method}")

        collector = VkCollector(
            api_client=SeedOnlyVkApiClient(),
            profile_seed_store=VkProfileSeedStore(
                [VkProfileSeedEntry(city="Салехард", service="маникюр", urls=["https://vk.ru/loft_shd"])]
            ),
        )
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=90,
            platforms=["vk"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].account_url, "https://vk.com/loft_shd")
        self.assertEqual(candidates[0].followers, 456)
        self.assertEqual(len(candidates[0].posts), 1)
        self.assertIn("+7 900 111-22-33", candidates[0].contacts["phone"])
        self.assertIn("seed:https://vk.ru/loft_shd", [entry.query for entry in search_log])

    def test_collect_skips_wall_fetch_for_profile_that_fails_prefilter(self) -> None:
        class NoisyProfileVkApiClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object] | None]] = []

            def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
                self.calls.append((method, params))
                if method == "newsfeed.search":
                    return {
                        "items": [
                            {
                                "owner_id": -555,
                                "id": 1,
                                "date": 1_710_000_000,
                                "text": "Маникюр Салехард, запись в лс, цена 2500",
                                "likes": {"count": 4},
                                "comments": {"count": 1},
                                "reposts": {"count": 0},
                                "views": {"count": 50},
                            }
                        ],
                        "groups": [
                            {
                                "id": 555,
                                "name": "Объявления Салехард",
                                "screen_name": "salehard_board",
                                "description": "Барахолка, объявления города и товары и услуги",
                                "members_count": 5000,
                                "city": {"title": "Салехард"},
                            }
                        ],
                        "profiles": [],
                    }
                if method == "wall.get":
                    raise AssertionError("wall.get must be skipped for obvious noise profiles")
                raise AssertionError(f"Unexpected method: {method}")

        api_client = NoisyProfileVkApiClient()
        collector = VkCollector(api_client=api_client)
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=90,
            platforms=["vk"],
            top_n=10,
        )

        candidates, _ = collector.collect(request)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].account_url, "https://vk.com/salehard_board")
        self.assertEqual(len(candidates[0].posts), 1)
        self.assertEqual([method for method, _ in api_client.calls].count("wall.get"), 0)

    def test_collect_falls_back_to_service_token_when_user_profile_search_auth_fails(self) -> None:
        class InvalidUserProfileApiClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object] | None]] = []

            def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
                self.calls.append((method, params))
                raise VkApiError("User authorization failed: invalid access_token (4). (code=5)", code=5)

        collector = VkCollector(
            user_token="broken-user-token",
            service_token="service-token",
            api_client=FakeVkApiClient(),
            profile_api_client=InvalidUserProfileApiClient(),
        )
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр", markers=["запись"])],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].account_url, "https://vk.com/nails_studio")
        self.assertIn("маникюр Салехард", [entry.query for entry in search_log])
        error_entries = [entry for entry in search_log if entry.source == "vk.profile_search.error"]
        self.assertEqual(len(error_entries), 1)
        self.assertIn("fallback=vk_service_token", error_entries[0].details)
        self.assertIn("profile_search_batch:", error_entries[0].query)
        newsfeed_entries = [entry for entry in search_log if entry.source == "vk.newsfeed.search"]
        self.assertTrue(newsfeed_entries)
        self.assertTrue(all(entry.discovery_mode == "vk_service_token" for entry in newsfeed_entries))

    def test_collect_keeps_partial_results_when_discovery_batch_times_out(self) -> None:
        class TimeoutThenSuccessCollector(VkCollector):
            def __init__(self) -> None:
                super().__init__(api_client=FakeVkApiClient())
                self.batch_calls = 0

            def _build_query_batches(self, service_name: str, city: str, markers: list[str]) -> list[list[str]]:
                return [["маникюр Салехард"], ["ногти Салехард"]]

            def _collect_discovery_batch(self, **kwargs) -> None:
                self.batch_calls += 1
                if self.batch_calls == 1:
                    raise VkApiError("Network error: read timed out", retryable=True)
                return super()._collect_discovery_batch(**kwargs)

        collector = TimeoutThenSuccessCollector()
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].account_url, "https://vk.com/nails_studio")
        error_entries = [entry for entry in search_log if entry.source == "vk.discovery.error"]
        self.assertEqual(len(error_entries), 1)
        self.assertIn("read timed out", error_entries[0].details)

    def test_disk_cache_reuses_owner_wall_and_city_between_collectors(self) -> None:
        class CacheAwareVkApiClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
                self.calls.append(method)
                if method == "groups.getById":
                    return [
                        {
                            "id": 123,
                            "name": "Nails Studio",
                            "screen_name": "nails_studio",
                            "description": "Маникюр в Салехарде",
                            "members_count": 777,
                            "city": {"title": "Салехард"},
                            "contacts": [{"phone": "+7 900 000-00-00"}],
                        }
                    ]
                if method == "wall.get":
                    return {
                        "count": 1,
                        "items": [
                            {
                                "owner_id": -123,
                                "id": 2,
                                "date": 1_710_100_000,
                                "text": "Отзывы клиентов и свободные окна",
                                "likes": {"count": 5},
                                "comments": {"count": 1},
                                "reposts": {"count": 0},
                                "views": {"count": 100},
                            }
                        ],
                    }
                if method == "database.getCities":
                    return {"items": [{"id": 20950, "title": "Салехард"}]}
                raise AssertionError(f"Unexpected method: {method}")

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "vk-cache"
            client_first = CacheAwareVkApiClient()
            collector_first = VkCollector(api_client=client_first, profile_api_client=client_first, cache_dir=cache_dir)

            meta = collector_first._fetch_owner_meta(-123)
            city_id = collector_first._resolve_city_id("Салехард")
            posts = collector_first._fetch_wall_posts(
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name=meta.name,
                    account_url="https://vk.com/nails_studio",
                    username_or_id="nails_studio",
                    description=meta.description,
                )
            )
            collector_first.disk_cache.set_wall_posts("nails_studio", posts)

            self.assertEqual(city_id, 20950)
            self.assertEqual(
                client_first.calls.count("groups.getById") + client_first.calls.count("wall.get") + client_first.calls.count("database.getCities"),
                3,
            )

            client_second = CacheAwareVkApiClient()
            collector_second = VkCollector(api_client=client_second, profile_api_client=client_second, cache_dir=cache_dir)
            cached_meta = collector_second._fetch_owner_meta(-123)
            cached_city_id = collector_second._resolve_city_id("Салехард")
            cached_posts = collector_second.disk_cache.get_wall_posts("nails_studio") if collector_second.disk_cache else None

        self.assertEqual(cached_meta.name, "Nails Studio")
        self.assertEqual(cached_city_id, 20950)
        self.assertIsNotNone(cached_posts)
        self.assertEqual(len(cached_posts or []), 1)
        self.assertEqual(client_second.calls, [])

    def test_stale_wall_cache_triggers_refetch(self) -> None:
        class WallOnlyVkApiClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
                self.calls.append(method)
                if method == "wall.get":
                    return {
                        "count": 1,
                        "items": [
                            {
                                "owner_id": -123,
                                "id": 2,
                                "date": 1_710_100_000,
                                "text": "Свежий пост после протухшего кэша",
                            }
                        ],
                    }
                raise AssertionError(f"Unexpected method: {method}")

        now = datetime.now(UTC)
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "vk-cache"
            collector_first = VkCollector(api_client=WallOnlyVkApiClient(), cache_dir=cache_dir)
            collector_first.disk_cache.set_wall_posts(
                "nails_studio",
                [
                    PostRecord(
                        url="https://vk.com/wall-123_1",
                        text="Старый кэшированный пост",
                        published_at=now - timedelta(days=10),
                    )
                ],
                cached_at=now - timedelta(hours=3),
            )

            client_second = WallOnlyVkApiClient()
            collector_second = VkCollector(
                api_client=client_second,
                cache_dir=cache_dir,
                wall_cache_ttl_hours=1,
            )
            posts = collector_second._fetch_wall_posts(
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Nails Studio",
                    account_url="https://vk.com/nails_studio",
                    username_or_id="nails_studio",
                    description="Маникюр в Салехарде",
                )
            )
            stale_cached = collector_second.disk_cache.get_wall_posts("nails_studio", max_age_hours=1)

        self.assertIsNone(stale_cached)
        self.assertEqual(client_second.calls, ["wall.get"])
        self.assertEqual(len(posts), 1)

    def test_collect_stops_query_expansion_after_enough_seeded_profiles(self) -> None:
        class SeedBoostVkApiClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object] | None]] = []

            def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
                self.calls.append((method, params))
                if method == "newsfeed.search":
                    return {
                        "items": [
                            {
                                "owner_id": -100,
                                "id": 1,
                                "date": 1_710_000_000,
                                "text": "Маникюр Салехард, запись в лс",
                            }
                        ],
                        "groups": [
                            {
                                "id": 100,
                                "name": "Маникюр Studio Салехард",
                                "screen_name": "manikur_100",
                                "description": "Маникюр в Салехарде, запись открыта",
                                "members_count": 100,
                                "city": {"title": "Салехард"},
                            }
                        ],
                        "profiles": [],
                    }
                if method == "groups.getById":
                    group_id = int(params["group_id"])
                    return [
                        {
                            "id": group_id,
                            "name": f"Маникюр Studio {group_id} Салехард",
                            "screen_name": f"club{group_id}",
                            "description": "Маникюр в Салехарде, запись открыта",
                            "members_count": 100 + group_id,
                            "city": {"title": "Салехард"},
                        }
                    ]
                if method == "wall.get":
                    return {"count": 0, "items": []}
                raise AssertionError(f"Unexpected method: {method}")

        seed_urls = [
            "https://vk.com/club321",
            "https://vk.com/club322",
            "https://vk.com/club323",
            "https://vk.com/club324",
        ]
        api_client = SeedBoostVkApiClient()
        collector = VkCollector(
            api_client=api_client,
            query_expansion_candidate_target=4,
            profile_seed_store=VkProfileSeedStore(
                [VkProfileSeedEntry(city="Салехард", service="маникюр", urls=seed_urls)]
            ),
        )
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=90,
            platforms=["vk"],
            top_n=20,
        )

        candidates, search_log = collector.collect(request)

        self.assertGreaterEqual(len(candidates), 5)
        self.assertEqual([method for method, _ in api_client.calls].count("newsfeed.search"), 2)
        self.assertIn("seed:https://vk.com/club321", [entry.query for entry in search_log])

    def test_collect_uses_profile_search_when_user_token_is_available(self) -> None:
        class UserSearchVkApiClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object] | None]] = []

            def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
                self.calls.append((method, params))
                if method == "database.getCities":
                    return {"count": 1, "items": [{"id": 20950, "title": "Новый Уренгой"}]}
                if method == "groups.search":
                    return {
                        "count": 1,
                        "items": [
                            {
                                "id": 700,
                                "screen_name": "salon_tvoy",
                            }
                        ],
                    }
                if method == "users.search":
                    return {
                        "count": 1,
                        "items": [
                            {
                                "id": 800,
                                "first_name": "Анна",
                                "last_name": "Ногти",
                                "screen_name": "anna_nails_nur",
                                "about": "Маникюр, Новый Уренгой, запись открыта",
                                "city": {"title": "Новый Уренгой"},
                                "followers_count": 321,
                                "site": "https://dikidi.net/123",
                                "status": "Запись в лс",
                            }
                        ],
                    }
                if method == "groups.getById":
                    return [
                        {
                            "id": 700,
                            "name": 'Салон красоты "ТВОЙ" - Новый Уренгой',
                            "screen_name": "salon_tvoy",
                            "description": "Маникюр / Педикюр | Новый Уренгой | Запись открыта",
                            "members_count": 1303,
                            "city": {"title": "Новый Уренгой"},
                            "site": "https://dikidi.net/19456",
                        }
                    ]
                if method == "wall.get":
                    return {"count": 0, "items": []}
                if method == "newsfeed.search":
                    raise AssertionError("newsfeed.search should be skipped when profile search is enough")
                raise AssertionError(f"Unexpected method: {method}")

        api_client = UserSearchVkApiClient()
        collector = VkCollector(
            user_token="vk-user",
            api_client=api_client,
            query_expansion_candidate_target=2,
        )
        request = SearchRequest(
            cities=["Новый Уренгой"],
            services=[ServiceQuery(name="маникюр")],
            period_days=90,
            platforms=["vk"],
            top_n=20,
        )

        candidates, search_log = collector.collect(request)

        self.assertEqual(len(candidates), 2)
        urls = {candidate.account_url for candidate in candidates}
        self.assertIn("https://vk.com/salon_tvoy", urls)
        self.assertIn("https://vk.com/anna_nails_nur", urls)
        self.assertEqual([method for method, _ in api_client.calls].count("newsfeed.search"), 0)
        self.assertIn("profile_groups:маникюр", [entry.query for entry in search_log])
        self.assertIn("profile_users:маникюр", [entry.query for entry in search_log])
        profile_entries = [entry for entry in search_log if entry.source in {"vk.groups.search", "vk.users.search"}]
        self.assertTrue(profile_entries)
        self.assertTrue(all(entry.discovery_mode == "vk_user_token" for entry in profile_entries))

    def test_full_recall_still_runs_newsfeed_even_with_user_token(self) -> None:
        class FullRecallVkApiClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object] | None]] = []

            def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
                self.calls.append((method, params))
                if method == "database.getCities":
                    return {"count": 1, "items": [{"id": 20950, "title": "Новый Уренгой"}]}
                if method == "groups.search":
                    return {
                        "count": 1,
                        "items": [
                            {
                                "id": 700,
                                "screen_name": "salon_tvoy",
                            }
                        ],
                    }
                if method == "users.search":
                    return {
                        "count": 1,
                        "items": [
                            {
                                "id": 800,
                                "first_name": "Анна",
                                "last_name": "Ногти",
                                "screen_name": "anna_nails_nur",
                                "about": "Маникюр, Новый Уренгой, запись открыта",
                                "city": {"title": "Новый Уренгой"},
                                "followers_count": 321,
                                "site": "https://dikidi.net/123",
                                "status": "Запись в лс",
                            }
                        ],
                    }
                if method == "groups.getById":
                    return [
                        {
                            "id": 700,
                            "name": 'Салон красоты "ТВОЙ" - Новый Уренгой',
                            "screen_name": "salon_tvoy",
                            "description": "Маникюр / Педикюр | Новый Уренгой | Запись открыта",
                            "members_count": 1303,
                            "city": {"title": "Новый Уренгой"},
                            "site": "https://dikidi.net/19456",
                        }
                    ]
                if method == "wall.get":
                    return {"count": 0, "items": []}
                if method == "newsfeed.search":
                    return {"items": [], "groups": [], "profiles": []}
                raise AssertionError(f"Unexpected method: {method}")

        api_client = FullRecallVkApiClient()
        collector = VkCollector(
            user_token="vk-user",
            api_client=api_client,
            query_expansion_candidate_target=2,
            full_recall=True,
        )
        request = SearchRequest(
            cities=["Новый Уренгой"],
            services=[ServiceQuery(name="маникюр")],
            period_days=90,
            platforms=["vk"],
            top_n=20,
        )

        collector.collect(request)

        self.assertGreater([method for method, _ in api_client.calls].count("newsfeed.search"), 0)

    def test_collect_profile_search_paginates_for_sparse_city_queries(self) -> None:
        class PaginatedUserSearchVkApiClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object] | None]] = []

            def call_with_retry(self, method: str, params: dict[str, object] | None = None, **_: object):
                self.calls.append((method, params))
                if method == "database.getCities":
                    return {"count": 1, "items": [{"id": 20800, "title": "Тарко-Сале"}]}
                if method == "groups.search":
                    if params and params.get("offset") == 200:
                        return {"count": 201, "items": [{"id": 910, "screen_name": "coffee_tarko"}]}
                    return {"count": 201, "items": [{"id": index} for index in range(1, 201)]}
                if method == "users.search":
                    if params and params.get("offset") == 200:
                        return {
                            "count": 201,
                            "items": [
                                {
                                    "id": 920,
                                    "first_name": "Coffee",
                                    "last_name": "Master",
                                    "screen_name": "coffee_master_tarko",
                                    "about": "Кофейня Тарко-Сале, режим работы, запись и доставка",
                                    "city": {"title": "Тарко-Сале"},
                                    "followers_count": 42,
                                    "site": "https://taplink.cc/coffee_master_tarko",
                                }
                            ],
                        }
                    return {"count": 201, "items": [{"id": index} for index in range(1, 201)]}
                if method == "groups.getById":
                    group_id = int(params["group_id"])
                    if group_id == 910:
                        return [
                            {
                                "id": 910,
                                "name": "Coffee Tarko",
                                "screen_name": "coffee_tarko",
                                "description": "Кофейня Тарко-Сале, кофе с собой, режим работы 08:00-22:00",
                                "members_count": 555,
                                "city": {"title": "Тарко-Сале"},
                                "site": "https://coffee-tarko.ru",
                            }
                        ]
                    return [
                        {
                            "id": group_id,
                            "name": f"Noise {group_id}",
                            "screen_name": f"noise_{group_id}",
                            "description": "Справочник услуг без города",
                        }
                    ]
                if method == "wall.get":
                    return {"count": 0, "items": []}
                if method == "newsfeed.search":
                    raise AssertionError("newsfeed.search should be skipped when paginated profile search is enough")
                raise AssertionError(f"Unexpected method: {method}")

        api_client = PaginatedUserSearchVkApiClient()
        collector = VkCollector(
            user_token="vk-user",
            api_client=api_client,
            query_expansion_candidate_target=2,
            max_accounts_per_query=260,
        )
        request = SearchRequest(
            cities=["Тарко-Сале"],
            services=[ServiceQuery(name="кофейня")],
            period_days=0,
            platforms=["vk"],
            top_n=20,
        )

        candidates, search_log = collector.collect(request)

        urls = {candidate.account_url for candidate in candidates}
        self.assertIn("https://vk.com/coffee_tarko", urls)
        self.assertIn("https://vk.com/coffee_master_tarko", urls)
        group_search_offsets = [params.get("offset", 0) for method, params in api_client.calls if method == "groups.search"]
        user_search_offsets = [params.get("offset", 0) for method, params in api_client.calls if method == "users.search"]
        self.assertIn(200, group_search_offsets)
        self.assertIn(200, user_search_offsets)
        self.assertIn("profile_groups:кофейня", [entry.query for entry in search_log])
        self.assertIn("profile_users:кофейня", [entry.query for entry in search_log])


if __name__ == "__main__":
    unittest.main()
