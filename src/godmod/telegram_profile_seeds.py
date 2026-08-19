from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .markers import normalize_text, service_search_terms


@dataclass(slots=True)
class TelegramProfileSeedEntry:
    city: str
    service: str
    service_aliases: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)


class TelegramProfileSeedStore:
    def __init__(self, entries: list[TelegramProfileSeedEntry] | None = None) -> None:
        self.entries = entries or []

    def urls_for(self, city: str, service: str) -> list[str]:
        requested_city = normalize_text(city)
        requested_service_terms = _expanded_service_terms(service)
        urls: list[str] = []
        for entry in self.entries:
            if normalize_text(entry.city) != requested_city:
                continue
            seed_service_terms = _expanded_service_terms(entry.service, entry.service_aliases)
            if requested_service_terms.isdisjoint(seed_service_terms) and not _fuzzy_service_overlap(
                requested_service_terms,
                seed_service_terms,
            ):
                continue
            for url in entry.urls:
                if url not in urls:
                    urls.append(url)
        return urls

    def merge_entries(self, entries: list[TelegramProfileSeedEntry]) -> None:
        for entry in entries:
            self._merge_entry(entry)

    def to_payload(self) -> dict[str, object]:
        return {
            "entries": [
                {
                    "city": entry.city,
                    "service": entry.service,
                    "service_aliases": list(entry.service_aliases),
                    "urls": list(entry.urls),
                }
                for entry in self.entries
            ]
        }

    def _merge_entry(self, entry: TelegramProfileSeedEntry) -> None:
        city_key = normalize_text(entry.city)
        service_key = normalize_text(entry.service)
        normalized_aliases = {
            normalize_text(alias): alias.strip()
            for alias in entry.service_aliases
            if alias.strip()
        }
        normalized_urls = {
            _normalize_seed_url(url): url.strip()
            for url in entry.urls
            if url.strip()
        }
        if not city_key or not service_key or not normalized_urls:
            return

        for existing in self.entries:
            if normalize_text(existing.city) != city_key or normalize_text(existing.service) != service_key:
                continue
            existing_aliases = {normalize_text(alias) for alias in existing.service_aliases}
            for alias_key, alias_value in normalized_aliases.items():
                if alias_key and alias_key not in existing_aliases:
                    existing.service_aliases.append(alias_value)
                    existing_aliases.add(alias_key)
            existing_urls = {_normalize_seed_url(url) for url in existing.urls}
            for url_key, url_value in normalized_urls.items():
                if url_key and url_key not in existing_urls:
                    existing.urls.append(url_value)
                    existing_urls.add(url_key)
            return

        self.entries.append(
            TelegramProfileSeedEntry(
                city=entry.city.strip(),
                service=entry.service.strip(),
                service_aliases=list(normalized_aliases.values()),
                urls=list(normalized_urls.values()),
            )
        )


def load_telegram_profile_seed_store(path: str | Path | None) -> TelegramProfileSeedStore:
    if path is None:
        return TelegramProfileSeedStore()

    seed_path = Path(path)
    if not seed_path.exists():
        return TelegramProfileSeedStore()

    raw_data = json.loads(seed_path.read_text(encoding="utf-8"))
    raw_entries = raw_data.get("entries", []) if isinstance(raw_data, dict) else []
    entries: list[TelegramProfileSeedEntry] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        city = str(item.get("city", "")).strip()
        service = str(item.get("service", "")).strip()
        service_aliases = [str(alias).strip() for alias in item.get("service_aliases", []) if str(alias).strip()]
        urls = [str(url).strip() for url in item.get("urls", []) if str(url).strip()]
        if city and service and urls:
            entries.append(
                TelegramProfileSeedEntry(
                    city=city,
                    service=service,
                    service_aliases=service_aliases,
                    urls=urls,
                )
            )
    return TelegramProfileSeedStore(entries)


def save_telegram_profile_seed_store(path: str | Path, store: TelegramProfileSeedStore) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(store.to_payload(), ensure_ascii=False, indent=2), encoding="utf-8")


def merge_telegram_profile_seed_entries(path: str | Path, entries: list[TelegramProfileSeedEntry]) -> TelegramProfileSeedStore:
    target = Path(path)
    store = load_telegram_profile_seed_store(target)
    store.merge_entries(entries)
    save_telegram_profile_seed_store(target, store)
    return store


def telegram_seed_url(value: str) -> str | None:
    normalized = _normalize_seed_url(value)
    if not normalized:
        return None
    if normalized.startswith("https://t.me/"):
        return normalized
    if normalized.startswith("@") and len(normalized) > 1:
        return f"https://t.me/{normalized.removeprefix('@')}"
    return None


def _expanded_service_terms(service: str, service_aliases: list[str] | None = None) -> set[str]:
    return {
        normalize_text(term)
        for term in [service, *service_search_terms(service), *(service_aliases or [])]
        if normalize_text(term)
    }


def _fuzzy_service_overlap(left_terms: set[str], right_terms: set[str]) -> bool:
    left_tokens = _service_tokens(left_terms)
    right_tokens = _service_tokens(right_terms)
    if not left_tokens or not right_tokens:
        return False
    for left in left_tokens:
        for right in right_tokens:
            if left == right:
                return True
            prefix_len = min(len(left), len(right), 5)
            if prefix_len >= 4 and left[:prefix_len] == right[:prefix_len]:
                return True
    return False


def _service_tokens(terms: set[str]) -> set[str]:
    tokens: set[str] = set()
    for term in terms:
        parts = [part for part in term.split() if len(part) >= 4]
        if parts:
            tokens.update(parts)
        elif len(term) >= 4:
            tokens.add(term)
    return tokens


def _normalize_seed_url(value: str) -> str:
    token = value.strip().rstrip("/").casefold()
    if token.startswith("https://t.me/"):
        return token
    if token.startswith("http://t.me/"):
        return "https://" + token.removeprefix("http://")
    if token.startswith("t.me/"):
        return "https://" + token
    return token
