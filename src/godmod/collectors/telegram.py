from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from telethon import TelegramClient, functions, types
from telethon.sessions import StringSession

from godmod.markers import extract_contacts, telegram_search_queries
from godmod.models import AccountCandidate, PostRecord, SearchLogEntry, SearchRequest
from godmod.request_options import is_all_time_period
from godmod.telegram_profile_seeds import TelegramProfileSeedStore


@dataclass(slots=True)
class TelegramOwnerMeta:
    entity_id: int
    title: str
    username: str
    description: str
    followers: int | None
    contacts: dict[str, list[str]]


class TelegramCollector:
    platform_name = "telegram"

    def __init__(
        self,
        *,
        api_id: int | None = None,
        api_hash: str | None = None,
        session_string: str | None = None,
        client_factory: Callable[[], Any] | None = None,
        profile_seed_store: TelegramProfileSeedStore | None = None,
        search_limit: int = 50,
        history_limit: int = 30,
        max_accounts_per_query: int = 50,
    ) -> None:
        if client_factory is None and not (api_id and api_hash and session_string):
            raise ValueError("Telegram collector requires api_id, api_hash and session_string.")

        self.api_id = api_id
        self.api_hash = api_hash
        self.session_string = session_string
        self.client_factory = client_factory
        self.profile_seed_store = profile_seed_store or TelegramProfileSeedStore()
        self.search_limit = search_limit
        self.history_limit = history_limit
        self.max_accounts_per_query = max_accounts_per_query

    def collect(self, request: SearchRequest) -> tuple[list[AccountCandidate], list[SearchLogEntry]]:
        if "telegram" not in request.platforms:
            return [], []
        return asyncio.run(self._collect_async(request))

    async def _collect_async(self, request: SearchRequest) -> tuple[list[AccountCandidate], list[SearchLogEntry]]:
        candidates: dict[tuple[str, str, int], AccountCandidate] = {}
        search_log: list[SearchLogEntry] = []
        current_time = datetime.now(UTC)
        start_at = _request_start_at(current_time, request.period_days)

        async with self._client_context() as client:
            for service in request.services:
                for city in request.cities:
                    queries = self._build_queries(service.name, city, service.markers)
                    for query in queries:
                        search_log.append(
                            SearchLogEntry(
                                city=city,
                                service=service.name,
                                platform="telegram",
                                query=query,
                                source="telegram.search",
                                discovery_mode="mtproto",
                            )
                        )
                        await self._collect_query(
                            client=client,
                            query=query,
                            service_name=service.name,
                            city=city,
                            start_at=start_at,
                            end_at=current_time,
                            candidates=candidates,
                        )
                    await self._collect_seed_urls(
                        client=client,
                        service_name=service.name,
                        city=city,
                        candidates=candidates,
                        search_log=search_log,
                    )

            for candidate in candidates.values():
                await self._enrich_candidate(client, candidate)

        return list(candidates.values()), search_log

    def _build_client(self) -> Any:
        if self.client_factory is not None:
            return self.client_factory()
        assert self.api_id is not None
        assert self.api_hash is not None
        assert self.session_string is not None
        return TelegramClient(StringSession(self.session_string), self.api_id, self.api_hash)

    @asynccontextmanager
    async def _client_context(self):
        if self.client_factory is not None:
            async with self.client_factory() as client:
                yield client
            return

        client = self._build_client()
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError(
                    "Telegram MTProto session is not authorized. "
                    "Regenerate TELEGRAM_USER_SESSION with scripts/generate_telegram_session.py."
                )
            yield client
        finally:
            await client.disconnect()

    async def _collect_query(
        self,
        *,
        client: Any,
        query: str,
        service_name: str,
        city: str,
        start_at: datetime,
        end_at: datetime,
        candidates: dict[tuple[str, str, int], AccountCandidate],
    ) -> None:
        try:
            response = await client(
                functions.messages.SearchGlobalRequest(
                    q=query,
                    filter=types.InputMessagesFilterEmpty(),
                    min_date=start_at,
                    max_date=end_at,
                    offset_rate=0,
                    offset_peer=types.InputPeerEmpty(),
                    offset_id=0,
                    limit=self.search_limit,
                )
            )
        except Exception:
            return

        chat_index = {getattr(chat, "id", None): chat for chat in getattr(response, "chats", [])}
        query_accounts = 0

        for message in getattr(response, "messages", []):
            channel_id = self._channel_id_from_peer(getattr(message, "peer_id", None))
            if channel_id is None:
                continue

            entity = chat_index.get(channel_id)
            username = self._entity_username(entity)
            if entity is None or not username:
                continue

            key = (service_name, city, channel_id)
            if key not in candidates and query_accounts >= self.max_accounts_per_query:
                continue

            candidate = candidates.get(key)
            if candidate is None:
                meta = self._owner_meta(entity)
                candidate = AccountCandidate(
                    service=service_name,
                    city=city,
                    platform="telegram",
                    account_name=meta.title,
                    account_url=f"https://t.me/{meta.username}",
                    username_or_id=meta.username,
                    description=meta.description,
                    followers=meta.followers,
                    contacts=meta.contacts,
                    api_city=city if city in meta.description else None,
                )
                candidates[key] = candidate
                query_accounts += 1

            if query not in candidate.search_queries:
                candidate.search_queries.append(query)
            if "telegram.search" not in candidate.discovery_sources:
                candidate.discovery_sources.append("telegram.search")
            if "mtproto" not in candidate.discovery_modes:
                candidate.discovery_modes.append("mtproto")
            post = self._message_to_post(message, username)
            if post is not None:
                candidate.posts = self._merge_posts(candidate.posts, [post])

    async def _collect_seed_urls(
        self,
        *,
        client: Any,
        service_name: str,
        city: str,
        candidates: dict[tuple[str, str, int], AccountCandidate],
        search_log: list[SearchLogEntry],
    ) -> None:
        for raw_url in self.profile_seed_store.urls_for(city, service_name):
            username = self._seed_username(raw_url)
            if not username:
                continue
            search_log.append(
                SearchLogEntry(
                    city=city,
                    service=service_name,
                    platform="telegram",
                    query=f"seed:{raw_url}",
                    source="telegram.seed",
                    discovery_mode="telegram_seed",
                )
            )
            try:
                entity = await client.get_entity(username)
            except Exception:
                continue
            resolved_username = self._entity_username(entity)
            if not resolved_username:
                continue
            entity_id = int(getattr(entity, "id", 0) or 0)
            key = (service_name, city, entity_id)
            candidate = candidates.get(key)
            if candidate is None:
                meta = self._owner_meta(entity)
                candidate = AccountCandidate(
                    service=service_name,
                    city=city,
                    platform="telegram",
                    account_name=meta.title,
                    account_url=f"https://t.me/{meta.username}",
                    username_or_id=meta.username,
                    description=meta.description,
                    followers=meta.followers,
                    contacts=meta.contacts,
                    api_city=city if city in meta.description else None,
                )
                candidates[key] = candidate
            if raw_url not in candidate.search_queries:
                candidate.search_queries.append(raw_url)
            if "telegram.seed" not in candidate.discovery_sources:
                candidate.discovery_sources.append("telegram.seed")
            if "telegram_seed" not in candidate.discovery_modes:
                candidate.discovery_modes.append("telegram_seed")

    async def _enrich_candidate(self, client: Any, candidate: AccountCandidate) -> None:
        try:
            entity = await client.get_entity(candidate.username_or_id)
        except Exception:
            entity = None

        if entity is not None:
            candidate.followers = getattr(entity, "participants_count", None) or candidate.followers

        full_chat = None
        if entity is not None:
            try:
                full = await client(functions.channels.GetFullChannelRequest(channel=entity))
                full_chat = getattr(full, "full_chat", None)
            except Exception:
                full_chat = None

        if full_chat is not None:
            about = getattr(full_chat, "about", "") or ""
            if about:
                candidate.description = about if not candidate.description else f"{candidate.description} | {about}"
            participants_count = getattr(full_chat, "participants_count", None)
            if isinstance(participants_count, int):
                candidate.followers = participants_count

        if entity is not None:
            try:
                history = await client.get_messages(entity, limit=self.history_limit)
            except Exception:
                history = []
            extra_posts = [
                post
                for message in history
                if (post := self._message_to_post(message, candidate.username_or_id)) is not None
            ]
            candidate.posts = self._merge_posts(candidate.posts, extra_posts)

        candidate.contacts = extract_contacts([candidate.description] + [post.text for post in candidate.posts])

    def _build_queries(self, service_name: str, city: str, markers: list[str]) -> list[str]:
        return telegram_search_queries(service_name, city, markers)

    def _owner_meta(self, entity: Any) -> TelegramOwnerMeta:
        username = self._entity_username(entity) or str(getattr(entity, "id", "unknown"))
        title = getattr(entity, "title", None) or getattr(entity, "username", None) or username
        description_parts = [
            getattr(entity, "title", ""),
            getattr(entity, "username", ""),
        ]
        description = " | ".join(part for part in description_parts if part)
        return TelegramOwnerMeta(
            entity_id=int(getattr(entity, "id", 0) or 0),
            title=str(title),
            username=username,
            description=description,
            followers=getattr(entity, "participants_count", None),
            contacts=extract_contacts([description]),
        )

    def _message_to_post(self, message: Any, username: str) -> PostRecord | None:
        message_id = getattr(message, "id", None)
        published_at = getattr(message, "date", None)
        if not isinstance(message_id, int) or published_at is None:
            return None
        return PostRecord(
            url=f"https://t.me/{username}/{message_id}",
            text=getattr(message, "message", "") or "",
            published_at=published_at,
            likes=self._reactions_count(getattr(message, "reactions", None)),
            comments=self._comments_count(getattr(message, "replies", None)),
            reposts=getattr(message, "forwards", None),
            views=getattr(message, "views", None),
        )

    def _merge_posts(self, current: list[PostRecord], extra: list[PostRecord]) -> list[PostRecord]:
        merged = {post.url: post for post in current}
        for post in extra:
            merged[post.url] = post
        return sorted(merged.values(), key=lambda post: post.published_at, reverse=True)

    def _channel_id_from_peer(self, peer: Any) -> int | None:
        for attr in ("channel_id", "chat_id"):
            value = getattr(peer, attr, None)
            if isinstance(value, int):
                return value
        return None

    def _entity_username(self, entity: Any) -> str | None:
        username = getattr(entity, "username", None)
        if isinstance(username, str) and username:
            return username
        usernames = getattr(entity, "usernames", None) or []
        for item in usernames:
            value = getattr(item, "username", None)
            if isinstance(value, str) and value:
                return value
        return None

    def _reactions_count(self, reactions: Any) -> int | None:
        if reactions is None:
            return None
        results = getattr(reactions, "results", None) or []
        total = 0
        found = False
        for item in results:
            count = getattr(item, "count", None)
            if isinstance(count, int):
                total += count
                found = True
        return total if found else None

    def _comments_count(self, replies: Any) -> int | None:
        if replies is None:
            return None
        count = getattr(replies, "replies", None)
        return count if isinstance(count, int) else None

    def _seed_username(self, raw_url: str) -> str | None:
        token = raw_url.strip().rstrip("/")
        if token.startswith("https://t.me/"):
            token = token.removeprefix("https://t.me/")
        elif token.startswith("http://t.me/"):
            token = token.removeprefix("http://t.me/")
        elif token.startswith("t.me/"):
            token = token.removeprefix("t.me/")
        token = token.strip().lstrip("@")
        if "/" in token:
            token = token.split("/", 1)[0]
        return token or None


def _request_start_at(end_at: datetime, period_days: int) -> datetime:
    if is_all_time_period(period_days):
        return datetime(2006, 1, 1, tzinfo=UTC)
    return end_at - timedelta(days=period_days)
