from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, parse, request


DEFAULT_TWOGIS_FIELDS = ",".join(
    [
        "items.point",
        "items.address",
        "items.adm_div",
        "items.address_name",
        "items.full_address_name",
        "items.rubrics",
        "items.org",
        "items.description",
        "items.summary",
        "items.schedule",
        "items.reviews",
        "items.flags",
        "items.attribute_groups",
        "items.contact_groups",
        "items.itin",
        "items.trade_license",
        "items.employees_org_count",
        "items.fias_code",
        "items.fns_code",
        "items.okato",
        "items.oktmo",
    ]
)


class TwoGisApiError(RuntimeError):
    """2GIS Places API transport or response error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TwoGisApiClient:
    def __init__(self, api_key: str, *, timeout: int = 30) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = "https://catalog.api.2gis.com/3.0/items"

    def search_items(
        self,
        params: dict[str, object],
        *,
        fields: str = DEFAULT_TWOGIS_FIELDS,
    ) -> dict[str, Any]:
        query = dict(params)
        query["key"] = self.api_key
        query["fields"] = fields
        encoded = parse.urlencode(query, doseq=True)
        http_request = request.Request(f"{self.base_url}?{encoded}", method="GET")
        try:
            with request.urlopen(http_request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404:
                try:
                    payload = json.loads(details)
                except json.JSONDecodeError:
                    payload = None
                if _is_item_not_found_payload(payload):
                    return _empty_search_payload(payload)
            raise TwoGisApiError(f"HTTP {exc.code}: {details}", status_code=exc.code) from exc
        except error.URLError as exc:
            raise TwoGisApiError(f"Network error: {exc}") from exc

        if not isinstance(data, dict):
            raise TwoGisApiError(f"Unexpected 2GIS API response: {data}")
        meta = data.get("meta", {})
        if _is_item_not_found_payload(data):
            return _empty_search_payload(data)
        if isinstance(meta, dict) and int(meta.get("code", 200) or 200) >= 400:
            code = int(meta.get("code", 500) or 500)
            raise TwoGisApiError(f"2GIS API error: {meta}", status_code=code)
        return data

    def search_items_with_retry(
        self,
        params: dict[str, object],
        *,
        fields: str = DEFAULT_TWOGIS_FIELDS,
        retries: int = 2,
        retry_delay: float = 0.5,
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                return self.search_items(params, fields=fields)
            except TwoGisApiError as exc:
                if attempt >= retries or exc.status_code not in {408, 429, 500, 502, 503, 504}:
                    raise
                time.sleep(retry_delay * (attempt + 1))
                attempt += 1


def _is_item_not_found_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    meta = payload.get("meta", {})
    if not isinstance(meta, dict):
        return False
    code = int(meta.get("code", 200) or 200)
    error_block = meta.get("error", {})
    error_type = error_block.get("type") if isinstance(error_block, dict) else ""
    return code == 404 and error_type == "itemNotFound"


def _empty_search_payload(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {"code": 404}
    return {
        "meta": meta,
        "result": {
            "items": [],
        },
    }
