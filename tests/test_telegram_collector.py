from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from godmod.collectors.telegram import TelegramCollector
from godmod.models import SearchRequest, ServiceQuery
from godmod.telegram_profile_seeds import TelegramProfileSeedEntry, TelegramProfileSeedStore


class FakeTelegramClient:
    def __init__(self) -> None:
        self.entity = SimpleNamespace(id=777, title="Nails TG", username="nails_tg")
        self.requests: list[object] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def __call__(self, request):
        self.requests.append(request)
        request_name = type(request).__name__
        if request_name == "SearchGlobalRequest":
            now = datetime.now(UTC)
            message = SimpleNamespace(
                id=101,
                peer_id=SimpleNamespace(channel_id=777),
                message="Маникюр Новый Уренгой, запись в лс, цена 2500",
                date=now - timedelta(days=2),
                views=230,
                forwards=4,
                replies=SimpleNamespace(replies=3),
                reactions=SimpleNamespace(results=[SimpleNamespace(count=8)]),
            )
            chat = SimpleNamespace(
                id=777,
                title="Nails TG",
                username="nails_tg",
                participants_count=1200,
            )
            return SimpleNamespace(messages=[message], chats=[chat])
        if request_name == "GetFullChannelRequest":
            full_chat = SimpleNamespace(about="Маникюр в Новом Уренгое, телефон +7 900 000-00-00", participants_count=1400)
            return SimpleNamespace(full_chat=full_chat)
        raise AssertionError(f"Unexpected request: {request_name}")

    async def get_entity(self, username: str):
        assert username == "nails_tg"
        return self.entity

    async def get_messages(self, entity, limit: int):
        now = datetime.now(UTC)
        return [
            SimpleNamespace(
                id=102,
                peer_id=SimpleNamespace(channel_id=777),
                message="Отзывы клиентов и свободные окна на этой неделе",
                date=now - timedelta(days=1),
                views=180,
                forwards=1,
                replies=SimpleNamespace(replies=2),
                reactions=SimpleNamespace(results=[SimpleNamespace(count=5)]),
            )
        ]


class FakeUnauthorizedTelegramClient:
    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        self.connected = True

    async def is_user_authorized(self) -> bool:
        return False

    async def disconnect(self) -> None:
        self.disconnected = True


class TelegramCollectorTests(unittest.TestCase):
    def test_collect_builds_candidates_from_search_and_history(self) -> None:
        collector = TelegramCollector(client_factory=FakeTelegramClient)
        request = SearchRequest(
            cities=["Новый Уренгой"],
            services=[ServiceQuery(name="маникюр", markers=["запись"])],
            period_days=30,
            platforms=["telegram"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertGreaterEqual(len(search_log), 8)
        self.assertEqual(len(candidates), 1)
        queries = [entry.query for entry in search_log]
        self.assertIn("Новый Уренгой маникюр", queries)
        self.assertIn("nails Новый Уренгой", queries)
        self.assertIn("Новый Уренгой nails", queries)
        self.assertIn("мастер маникюра Новый Уренгой", queries)
        self.assertIn("Новый Уренгой мастер маникюра", queries)
        candidate = candidates[0]
        self.assertEqual(candidate.account_url, "https://t.me/nails_tg")
        self.assertEqual(candidate.followers, 1400)
        self.assertEqual(len(candidate.posts), 2)
        self.assertIn("Маникюр в Новом Уренгое", candidate.description)
        self.assertIn("+7 900 000-00-00", candidate.contacts["phone"])

    def test_collect_uses_early_start_date_for_all_time_period(self) -> None:
        client = FakeTelegramClient()
        collector = TelegramCollector(client_factory=lambda: client)
        request = SearchRequest(
            cities=["Новый Уренгой"],
            services=[ServiceQuery(name="маникюр")],
            period_days=0,
            platforms=["telegram"],
            top_n=10,
        )

        collector.collect(request)

        search_requests = [request for request in client.requests if type(request).__name__ == "SearchGlobalRequest"]
        self.assertTrue(search_requests)
        self.assertEqual(search_requests[0].min_date, datetime(2006, 1, 1, tzinfo=UTC))

    def test_collect_includes_seeded_telegram_profile_when_search_is_empty(self) -> None:
        class SeedTelegramClient(FakeTelegramClient):
            async def __call__(self, request):
                self.requests.append(request)
                request_name = type(request).__name__
                if request_name == "SearchGlobalRequest":
                    return SimpleNamespace(messages=[], chats=[])
                if request_name == "GetFullChannelRequest":
                    full_chat = SimpleNamespace(about="Маникюр в Салехарде, запись в лс", participants_count=321)
                    return SimpleNamespace(full_chat=full_chat)
                raise AssertionError(f"Unexpected request: {request_name}")

            async def get_entity(self, username: str):
                assert username == "nails_tg"
                return self.entity

        collector = TelegramCollector(
            client_factory=SeedTelegramClient,
            profile_seed_store=TelegramProfileSeedStore(
                [TelegramProfileSeedEntry(city="Новый Уренгой", service="маникюр", urls=["https://t.me/nails_tg"])]
            ),
        )
        request = SearchRequest(
            cities=["Новый Уренгой"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["telegram"],
            top_n=10,
        )

        candidates, search_log = collector.collect(request)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].account_url, "https://t.me/nails_tg")
        self.assertIn("telegram.seed", candidates[0].discovery_sources)
        self.assertIn("seed:https://t.me/nails_tg", [entry.query for entry in search_log])

    def test_real_client_context_rejects_unauthorized_session_without_prompting(self) -> None:
        fake_client = FakeUnauthorizedTelegramClient()
        collector = TelegramCollector(api_id=123, api_hash="hash", session_string="session")

        with patch.object(collector, "_build_client", return_value=fake_client):
            with self.assertRaisesRegex(RuntimeError, "Telegram MTProto session is not authorized"):
                async def run_context() -> None:
                    async with collector._client_context():
                        raise AssertionError("unauthorized session should not yield a client")

                asyncio.run(run_context())

        self.assertTrue(fake_client.connected)
        self.assertTrue(fake_client.disconnected)


if __name__ == "__main__":
    unittest.main()
