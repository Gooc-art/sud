from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from godmod.markers import extract_contacts, normalize_slug, twogis_search_queries
from godmod.models import AccountCandidate, SearchLogEntry, SearchRequest
from godmod.twogis_api import DEFAULT_TWOGIS_FIELDS, TwoGisApiClient
from godmod.twogis_cache import TwoGisDiskCache


@dataclass(slots=True)
class TwoGisPlaceMeta:
    place_id: str
    title: str
    account_url: str
    description: str
    contacts: dict[str, list[str]]
    api_city: str | None = None
    address: str | None = None
    geo_coordinates: str | None = None
    business_categories: str | None = None
    rating_details: str | None = None
    working_hours: str | None = None
    price_details: str | None = None
    official_requisites: str | None = None
    service_fields: str | None = None
    employee_count: int | None = None


class TwoGisCollector:
    platform_name = "2gis"
    max_page_size = 10

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_client: TwoGisApiClient | None = None,
        page_size: int = 10,
        fields: str = DEFAULT_TWOGIS_FIELDS,
        cache_enabled: bool = True,
        cache_dir: str | Path | None = None,
        disk_cache: TwoGisDiskCache | None = None,
        search_cache_ttl_hours: int = 6,
    ) -> None:
        if not api_key and api_client is None:
            raise ValueError("2GIS collector requires TWOGIS_API_KEY.")

        self.api_client = api_client or TwoGisApiClient(api_key or "")
        self.page_size = max(1, min(page_size, self.max_page_size))
        self.fields = fields
        self.search_cache_ttl_hours = search_cache_ttl_hours
        self.cache_stats: dict[str, int] = {
            "twogis_search_hits": 0,
            "twogis_search_misses": 0,
        }
        self.disk_cache = self._init_disk_cache(
            cache_enabled=cache_enabled,
            cache_dir=cache_dir,
            disk_cache=disk_cache,
        )

    def collect(self, request: SearchRequest) -> tuple[list[AccountCandidate], list[SearchLogEntry]]:
        if "2gis" not in request.platforms:
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
                            platform="2gis",
                            query=query,
                            source="2gis.places_api",
                            discovery_mode="2gis_places",
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
        params = {
            "q": query,
            "locale": "ru_RU",
            "type": "branch",
            "page_size": self.page_size,
        }
        response: dict[str, Any] | None = None
        if self.disk_cache is not None:
            response = self.disk_cache.get_search_payload(
                params,
                fields=self.fields,
                max_age_hours=self.search_cache_ttl_hours,
            )
            if response is not None:
                self.cache_stats["twogis_search_hits"] += 1
            else:
                self.cache_stats["twogis_search_misses"] += 1
        if response is None:
            response = self.api_client.search_items_with_retry(params, fields=self.fields)
            if self.disk_cache is not None:
                self.disk_cache.set_search_payload(params, response, fields=self.fields)
        items = ((response.get("result", {}) or {}).get("items", [])) or []
        for raw_place in items:
            meta = self._place_meta(raw_place, service_name=service_name)
            key = (service_name, city, meta.place_id)
            candidate = candidates.get(key)
            if candidate is None:
                candidate = AccountCandidate(
                    service=service_name,
                    city=city,
                    platform="2gis",
                    account_name=meta.title,
                    account_url=meta.account_url,
                    username_or_id=meta.place_id,
                    description=meta.description,
                    contacts=meta.contacts,
                    search_queries=[query],
                    discovery_sources=["2gis.places_api"],
                    discovery_modes=["2gis_places"],
                    api_city=meta.api_city,
                    api_address=meta.address,
                    geo_coordinates=meta.geo_coordinates,
                    business_categories=meta.business_categories,
                    rating_details=meta.rating_details,
                    working_hours=meta.working_hours,
                    price_details=meta.price_details,
                    official_requisites=meta.official_requisites,
                    service_fields=meta.service_fields,
                    employee_count=meta.employee_count,
                )
                candidates[key] = candidate
            else:
                if len(meta.description) > len(candidate.description):
                    candidate.description = meta.description
                if meta.api_city and not candidate.api_city:
                    candidate.api_city = meta.api_city
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
                if meta.official_requisites and (
                    not candidate.official_requisites or len(meta.official_requisites) > len(candidate.official_requisites)
                ):
                    candidate.official_requisites = meta.official_requisites
                if meta.service_fields and (not candidate.service_fields or len(meta.service_fields) > len(candidate.service_fields)):
                    candidate.service_fields = meta.service_fields
                if meta.employee_count is not None and candidate.employee_count is None:
                    candidate.employee_count = meta.employee_count
                if not candidate.contacts and meta.contacts:
                    candidate.contacts = meta.contacts
            if query not in candidate.search_queries:
                candidate.search_queries.append(query)

    def _build_queries(self, service_name: str, city: str, markers: list[str]) -> list[str]:
        return twogis_search_queries(service_name, city, markers)

    def _init_disk_cache(
        self,
        *,
        cache_enabled: bool,
        cache_dir: str | Path | None,
        disk_cache: TwoGisDiskCache | None,
    ) -> TwoGisDiskCache | None:
        if disk_cache is not None:
            return disk_cache
        if not cache_enabled or cache_dir is None:
            return None
        return TwoGisDiskCache(cache_dir)

    def _place_meta(self, raw_place: dict[str, Any], *, service_name: str) -> TwoGisPlaceMeta:
        place_id = str(raw_place.get("id") or raw_place.get("alias") or normalize_slug(service_name) or "2gis-place")
        title = str(
            raw_place.get("name")
            or ((raw_place.get("name_ex", {}) or {}).get("primary"))
            or ((raw_place.get("org", {}) or {}).get("name"))
            or raw_place.get("full_address_name")
            or place_id
        )
        account_url = f"https://2gis.ru/search/{place_id}"
        address = str(raw_place.get("full_address_name") or raw_place.get("address_name") or "").strip()
        rubrics = raw_place.get("rubrics", []) or []
        rubric_names = [str(item.get("name", "")).strip() for item in rubrics if isinstance(item, dict) and item.get("name")]
        reviews = raw_place.get("reviews", {}) or {}
        schedule = raw_place.get("schedule", {}) or {}
        schedule_description = str(schedule.get("description") or "").strip()
        rating = str(reviews.get("general_rating") or reviews.get("rating") or "").strip()
        review_count = str(reviews.get("review_count") or "").strip()
        rating_details = _compose_rating_details(rating, review_count)
        business_categories = ", ".join(rubric_names[:4]) or None
        contact_groups = raw_place.get("contact_groups", []) or []
        api_city = self._extract_api_city(raw_place)
        geo_coordinates = self._extract_geo_coordinates(raw_place)
        price_details = self._extract_price_details(raw_place)
        official_requisites = self._extract_official_requisites(raw_place)
        service_fields = self._extract_service_fields(raw_place)
        employee_count = self._extract_employee_count(raw_place)

        contacts = self._extract_contact_groups(contact_groups)
        description_parts = [
            "Карточка 2GIS.",
            f"Категории: {business_categories}." if business_categories else "",
            f"Город API: {api_city}." if api_city else "",
            f"Адрес: {address}." if address else "",
            f"Координаты: {geo_coordinates}." if geo_coordinates else "",
            f"Рейтинг: {rating_details}." if rating_details else "",
            f"График: {schedule_description}." if schedule_description else "",
            f"Цены: {price_details}." if price_details else "",
            f"Реквизиты: {official_requisites}." if official_requisites else "",
            f"Служебные поля: {service_fields}." if service_fields else "",
            f"Сотрудников: {employee_count}." if employee_count is not None else "",
        ]
        description = " ".join(part for part in description_parts if part).strip()
        merged_contacts = extract_contacts([description])
        for key, values in contacts.items():
            merged_contacts.setdefault(key, [])
            for value in values:
                if value not in merged_contacts[key]:
                    merged_contacts[key].append(value)
            merged_contacts[key] = sorted(set(merged_contacts[key]))

        return TwoGisPlaceMeta(
            place_id=place_id,
            title=title,
            account_url=account_url,
            description=description,
            contacts=merged_contacts,
            api_city=api_city,
            address=address or None,
            geo_coordinates=geo_coordinates,
            business_categories=business_categories,
            rating_details=rating_details,
            working_hours=schedule_description or None,
            price_details=price_details,
            official_requisites=official_requisites,
            service_fields=service_fields,
            employee_count=employee_count,
        )

    def _extract_contact_groups(self, contact_groups: list[dict[str, Any]]) -> dict[str, list[str]]:
        contacts: dict[str, list[str]] = {}
        for group in contact_groups:
            if not isinstance(group, dict):
                continue
            for contact in group.get("contacts", []) or []:
                if not isinstance(contact, dict):
                    continue
                contact_type = str(contact.get("type") or "").strip().lower()
                value = str(contact.get("value") or contact.get("url") or contact.get("text") or "").strip()
                if not value:
                    continue
                if contact_type == "phone":
                    key = "phone"
                elif contact_type == "email":
                    key = "email"
                elif contact_type == "telegram" or value.startswith("@") or value.startswith("https://t.me/"):
                    key = "telegram"
                elif contact_type in {"website", "site"}:
                    key = "website"
                else:
                    key = "website" if value.startswith(("http://", "https://")) else "other"
                contacts.setdefault(key, [])
                if value not in contacts[key]:
                    contacts[key].append(value)
        return contacts

    def _extract_price_details(self, raw_place: dict[str, Any]) -> str | None:
        details: list[str] = []
        flags = raw_place.get("flags", {}) or {}
        if flags.get("has_avg_bill"):
            details.append("есть данные по среднему чеку")

        for text in self._price_text_candidates(raw_place):
            normalized = " ".join(text.split())
            if normalized and normalized not in details:
                details.append(normalized)

        return "; ".join(details[:6]) or None

    def _extract_api_city(self, raw_place: dict[str, Any]) -> str | None:
        for item in raw_place.get("adm_div", []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                return name
        address = raw_place.get("address", {}) or {}
        for component in address.get("components", []) or []:
            if not isinstance(component, dict):
                continue
            component_name = str(component.get("name") or "").strip()
            component_type = str(component.get("type") or "").strip().casefold()
            if component_name and component_type in {"city", "settlement", "locality"}:
                return component_name
        full_address = str(raw_place.get("full_address_name") or "").strip()
        if full_address and "," in full_address:
            return full_address.split(",", 1)[0].strip()
        return None

    def _extract_geo_coordinates(self, raw_place: dict[str, Any]) -> str | None:
        point = raw_place.get("point", {}) or {}
        lon = point.get("lon")
        lat = point.get("lat")
        if lon is None or lat is None:
            return None
        return f"{lon}, {lat}"

    def _extract_official_requisites(self, raw_place: dict[str, Any]) -> str | None:
        parts: list[str] = []
        itin = str(raw_place.get("itin") or "").strip()
        trade_license = str(raw_place.get("trade_license") or "").strip()
        if itin:
            parts.append(f"ИНН: {itin}")
        if trade_license:
            parts.append(f"Лицензия: {trade_license}")
        return "; ".join(parts) or None

    def _extract_service_fields(self, raw_place: dict[str, Any]) -> str | None:
        labeled_values = [
            ("ФИАС", raw_place.get("fias_code")),
            ("ФНС", raw_place.get("fns_code")),
            ("ОКАТО", raw_place.get("okato")),
            ("ОКТМО", raw_place.get("oktmo")),
        ]
        parts = [f"{label}: {str(value).strip()}" for label, value in labeled_values if str(value or "").strip()]
        return "; ".join(parts) or None

    def _extract_employee_count(self, raw_place: dict[str, Any]) -> int | None:
        value = raw_place.get("employees_org_count")
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _price_text_candidates(self, raw_place: dict[str, Any]) -> list[str]:
        results: list[str] = []
        for attribute_group in raw_place.get("attribute_groups", []) or []:
            if not isinstance(attribute_group, dict):
                continue
            for attribute in attribute_group.get("attributes", []) or []:
                if not isinstance(attribute, dict):
                    continue
                text = self._price_text_from_attribute(attribute)
                if text and text not in results:
                    results.append(text)

        for text in self._price_texts_from_descriptions(raw_place):
            if text not in results:
                results.append(text)
        return results

    def _price_text_from_attribute(self, attribute: dict[str, Any]) -> str | None:
        tag = str(attribute.get("tag") or "").strip()
        name = str(attribute.get("name") or "").strip()
        value = str(
            attribute.get("value")
            or attribute.get("text")
            or attribute.get("display_value")
            or attribute.get("option_name")
            or ""
        ).strip()
        haystack = " ".join(part for part in [tag, name, value] if part).casefold()
        if not self._looks_like_price_signal(haystack):
            return None
        if value and name and value.casefold() not in name.casefold():
            return f"{name}: {value}"
        return value or name or tag or None

    def _price_texts_from_descriptions(self, raw_place: dict[str, Any]) -> list[str]:
        texts = [
            str(raw_place.get("description") or "").strip(),
            str((raw_place.get("summary", {}) or {}).get("text") or "").strip(),
        ]
        results: list[str] = []
        price_pattern = r"\d[\d\s]{0,8}(?:[,.]\d+)?\s?(?:₽|руб\.?|р\b)"
        for text in texts:
            if not text:
                continue
            for match in re.findall(price_pattern, text, flags=re.IGNORECASE):
                normalized = " ".join(str(match).split())
                if normalized and normalized not in results:
                    results.append(normalized)
        return results

    def _looks_like_price_signal(self, text: str) -> bool:
        return any(
            marker in text
            for marker in {
                "price",
                "avg_bill",
                "avg_price",
                "average bill",
                "average price",
                "bill",
                "чек",
                "цена",
                "стоимость",
                "прайс",
                "₽",
                "руб",
            }
        )


def _compose_rating_details(rating: str, review_count: str) -> str | None:
    rating_token = rating.strip()
    review_token = review_count.strip()
    if rating_token and review_token:
        return f"{rating_token} ({review_token} отзывов)"
    return rating_token or (f"{review_token} отзывов" if review_token else None)
