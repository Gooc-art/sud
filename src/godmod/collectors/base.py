from __future__ import annotations

from typing import Protocol

from godmod.models import AccountCandidate, SearchLogEntry, SearchRequest


class Collector(Protocol):
    platform_name: str

    def collect(self, request: SearchRequest) -> tuple[list[AccountCandidate], list[SearchLogEntry]]:
        """Return candidates and search log entries for the request."""
