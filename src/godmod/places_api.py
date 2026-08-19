from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, request


DEFAULT_TEXT_SEARCH_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.businessStatus",
        "places.googleMapsUri",
        "places.location",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.primaryType",
        "places.primaryTypeDisplayName",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.regularOpeningHours",
        "places.types",
        "places.websiteUri",
    ]
)


class GooglePlacesApiError(RuntimeError):
    """Google Places API transport or response error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GooglePlacesApiClient:
    def __init__(self, api_key: str, *, timeout: int = 30) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = "https://places.googleapis.com/v1/places:searchText"

    def search_text(
        self,
        payload: dict[str, object],
        *,
        field_mask: str = DEFAULT_TEXT_SEARCH_FIELD_MASK,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.base_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": field_mask,
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise GooglePlacesApiError(f"HTTP {exc.code}: {details}", status_code=exc.code) from exc
        except error.URLError as exc:
            raise GooglePlacesApiError(f"Network error: {exc}") from exc

        if isinstance(data, dict) and "error" in data:
            error_payload = data.get("error", {})
            status = error_payload.get("code")
            message = error_payload.get("message", "Google Places API error")
            raise GooglePlacesApiError(str(message), status_code=status if isinstance(status, int) else None)
        if not isinstance(data, dict):
            raise GooglePlacesApiError(f"Unexpected Google Places API response: {data}")
        return data

    def search_text_with_retry(
        self,
        payload: dict[str, object],
        *,
        field_mask: str = DEFAULT_TEXT_SEARCH_FIELD_MASK,
        retries: int = 2,
        retry_delay: float = 0.5,
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                return self.search_text(payload, field_mask=field_mask)
            except GooglePlacesApiError as exc:
                if attempt >= retries or exc.status_code not in {429, 500, 502, 503, 504}:
                    raise
                time.sleep(retry_delay * (attempt + 1))
                attempt += 1
