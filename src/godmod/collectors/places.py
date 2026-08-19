from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from godmod.markers import extract_contacts, normalize_slug, service_search_queries
from godmod.models import AccountCandidate, SearchLogEntry, SearchRequest
from godmod.places_api import DEFAULT_TEXT_SEARCH_FIELD_MASK, GooglePlacesApiClient


@dataclass(slots=True)
class PlaceMeta:
    place_id: str
    title: str
    account_url: str
    description: str
    contacts: dict[str, list[str]]
    address: str | None = None
    geo_coordinates: str | None = None
    business_categories: str | None = None
    rating_details: str | None = None
    working_hours: str | None = None
    price_details: str | None = None


class PlacesCollector:
    platform_name = "places"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_client: GooglePlacesApiClient | None = None,
        page_size: int = 10,
        include_pure_service_area_businesses: bool = True,
        field_mask: str = DEFAULT_TEXT_SEARCH_FIELD_MASK,
    ) -> None:
        if not api_key and api_client is None:
            raise ValueError("Places collector requires GOOGLE_PLACES_API_KEY.")

        self.api_client = api_client or GooglePlacesApiClient(api_key or "")
        self.page_size = page_size
        self.include_pure_service_area_businesses = include_pure_service_area_businesses
        self.field_mask = field_mask

    def collect(self, request: SearchRequest) -> tuple[list[AccountCandidate], list[SearchLogEntry]]:
        if "places" not in request.platforms:
            return [], []

        candidates: dict[tuple[str, str, str], AccountCandidate] = {}
        search_log: list[SearchLogEntry] = []

        for service in request.services:
            for city in request.cities:
                queries = self._build_queries(service.name, city, service.markers)
                for query in queries:
                    search_log.append(
                        SearchLogEntry(
                            city=city,
                            service=service.name,
                            platform="places",
                            query=query,
                            source="places.text_search",
                            discovery_mode="google_places",
                        )
                    )
                    self._collect_query(
                        query=query,
                        service_name=service.name,
                        city=city,
                        candidates=candidates,
                    )

        return list(candidates.values()), search_log

    def _collect_query(
        self,
        *,
        query: str,
        service_name: str,
        city: str,
        candidates: dict[tuple[str, str, str], AccountCandidate],
    ) -> None:
        response = self.api_client.search_text_with_retry(
            {
                "textQuery": query,
                "languageCode": "ru",
                "regionCode": "RU",
                "pageSize": self.page_size,
                "includePureServiceAreaBusinesses": self.include_pure_service_area_businesses,
            },
            field_mask=self.field_mask,
        )
        for raw_place in response.get("places", []) or []:
            meta = self._place_meta(raw_place, service_name=service_name)
            key = (service_name, city, meta.place_id)
            candidate = candidates.get(key)
            if candidate is None:
                candidate = AccountCandidate(
                    service=service_name,
                    city=city,
                    platform="places",
                    account_name=meta.title,
                    account_url=meta.account_url,
                    username_or_id=meta.place_id,
                    description=meta.description,
                    contacts=meta.contacts,
                    search_queries=[query],
                    discovery_sources=["places.text_search"],
                    discovery_modes=["google_places"],
                    api_city=city,
                    api_address=meta.address,
                    geo_coordinates=meta.geo_coordinates,
                    business_categories=meta.business_categories,
                    rating_details=meta.rating_details,
                    working_hours=meta.working_hours,
                    price_details=meta.price_details,
                )
                candidates[key] = candidate
            else:
                if len(meta.description) > len(candidate.description):
                    candidate.description = meta.description
                if not candidate.contacts and meta.contacts:
                    candidate.contacts = meta.contacts
                if meta.address and not candidate.api_address:
                    candidate.api_address = meta.address
                if meta.geo_coordinates and not candidate.geo_coordinates:
                    candidate.geo_coordinates = meta.geo_coordinates
                if meta.business_categories and (
                    not candidate.business_categories or len(meta.business_categories) > len(candidate.business_categories)
                ):
                    candidate.business_categories = meta.business_categories
                if meta.rating_details and (
                    not candidate.rating_details or len(meta.rating_details) > len(candidate.rating_details)
                ):
                    candidate.rating_details = meta.rating_details
                if meta.working_hours and (
                    not candidate.working_hours or len(meta.working_hours) > len(candidate.working_hours)
                ):
                    candidate.working_hours = meta.working_hours
                if meta.price_details and (not candidate.price_details or len(meta.price_details) > len(candidate.price_details)):
                    candidate.price_details = meta.price_details
            if query not in candidate.search_queries:
                candidate.search_queries.append(query)

    def _build_queries(self, service_name: str, city: str, markers: list[str]) -> list[str]:
        return service_search_queries(service_name, city, markers)

    def _place_meta(self, raw_place: dict[str, Any], *, service_name: str) -> PlaceMeta:
        place_id = str(raw_place.get("id") or raw_place.get("name") or normalize_slug(service_name) or "place")
        display_name = raw_place.get("displayName", {}) or {}
        title = str(display_name.get("text") or raw_place.get("formattedAddress") or place_id)
        account_url = (
            raw_place.get("googleMapsUri")
            or raw_place.get("searchUri")
            or f"https://www.google.com/maps/search/?api=1&query_place_id={place_id}"
        )

        address = str(raw_place.get("formattedAddress") or "").strip()
        business_status = str(raw_place.get("businessStatus") or "").strip()
        primary_type_display = raw_place.get("primaryTypeDisplayName", {}) or {}
        primary_type_title = str(primary_type_display.get("text") or raw_place.get("primaryType") or "").strip()
        raw_types = [str(value).strip() for value in raw_place.get("types", []) or [] if str(value).strip()]
        phone = str(
            raw_place.get("internationalPhoneNumber")
            or raw_place.get("nationalPhoneNumber")
            or ""
        ).strip()
        website = str(raw_place.get("websiteUri") or "").strip()
        rating = raw_place.get("rating")
        user_rating_count = raw_place.get("userRatingCount")
        price_level = str(raw_place.get("priceLevel") or "").strip()
        opening_hours = raw_place.get("regularOpeningHours", {}) or {}
        open_now = opening_hours.get("openNow")
        weekday_descriptions = opening_hours.get("weekdayDescriptions") or []
        geo_coordinates = _extract_geo_coordinates(raw_place)
        price_details = _format_price_details(price_level)
        rating_summary = _format_rating_summary(rating, user_rating_count)
        hours_summary = _format_opening_hours(open_now, weekday_descriptions)
        business_categories = ", ".join([value for value in [primary_type_title, *raw_types] if value][:4])

        description_parts = [
            "Карточка Google Places.",
            f"Категории: {business_categories}." if business_categories else "",
            f"Статус: {business_status}." if business_status else "",
            f"Рейтинг: {rating_summary}." if rating_summary else "",
            f"Часы: {hours_summary}." if hours_summary else "",
            f"Адрес: {address}." if address else "",
            f"Координаты: {geo_coordinates}." if geo_coordinates else "",
            f"Телефон: {phone}." if phone else "",
            f"Сайт: {website}." if website else "",
            f"Цены: {price_details}." if price_details else "",
        ]
        description = " ".join(part for part in description_parts if part).strip()
        contacts = extract_contacts([description])
        if phone:
            contacts.setdefault("phone", [])
            if phone not in contacts["phone"]:
                contacts["phone"].append(phone)
                contacts["phone"] = sorted(set(contacts["phone"]))

        return PlaceMeta(
            place_id=place_id,
            title=title,
            account_url=str(account_url),
            description=description,
            contacts=contacts,
            address=address or None,
            geo_coordinates=geo_coordinates,
            business_categories=business_categories or None,
            rating_details=rating_summary or None,
            working_hours=hours_summary or None,
            price_details=price_details,
        )


def _extract_geo_coordinates(raw_place: dict[str, Any]) -> str | None:
    location = raw_place.get("location", {}) or {}
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if latitude is None or longitude is None:
        return None
    return f"{latitude}, {longitude}"


def _format_rating_summary(rating: Any, user_rating_count: Any) -> str:
    score = None
    if isinstance(rating, (int, float)):
        score = f"{float(rating):.1f}"
    reviews = None
    if isinstance(user_rating_count, int) and user_rating_count > 0:
        reviews = f"{user_rating_count} отзывов"
    if score and reviews:
        return f"{score} ({reviews})"
    return score or reviews or ""


def _format_opening_hours(open_now: Any, weekday_descriptions: list[Any]) -> str:
    parts: list[str] = []
    if isinstance(open_now, bool):
        parts.append("открыто сейчас" if open_now else "сейчас закрыто")
    if weekday_descriptions:
        first_day = str(weekday_descriptions[0]).strip()
        if first_day:
            parts.append(first_day)
    return "; ".join(parts)


def _format_price_details(price_level: str) -> str | None:
    if not price_level:
        return None
    labels = {
        "PRICE_LEVEL_FREE": "бесплатно",
        "PRICE_LEVEL_INEXPENSIVE": "низкий чек",
        "PRICE_LEVEL_MODERATE": "средний чек",
        "PRICE_LEVEL_EXPENSIVE": "высокий чек",
        "PRICE_LEVEL_VERY_EXPENSIVE": "очень высокий чек",
    }
    return labels.get(price_level, price_level)
