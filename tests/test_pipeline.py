from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from godmod.config import RuntimeConfig
from godmod.collectors.base import Collector
from godmod.collectors.mock import MockCollector
from godmod.models import AccountCandidate, PostRecord, SearchLogEntry, SearchRequest, ServiceQuery
from godmod.pipeline import run_pipeline


class MixedCityCollector(Collector):
    platform_name = "mixed"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Маникюр Салехард",
                    account_url="https://vk.com/salekhard_nails",
                    username_or_id="salekhard_nails",
                    description="Маникюр в Салехарде, запись в лс",
                    posts=[
                        PostRecord(
                            url="https://vk.com/salekhard_nails/1",
                            text="Свободные окна, Салехард, цена 2500",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Маникюр Ямал",
                    account_url="https://vk.com/yamal_nails",
                    username_or_id="yamal_nails",
                    description="Маникюр по всему Ямалу, запись в лс",
                    posts=[
                        PostRecord(
                            url="https://vk.com/yamal_nails/1",
                            text="Работаем по ЯНАО, запись открыта",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                )
            ],
        )


class BoardVsServiceCollector(Collector):
    platform_name = "board"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Маникюр Салехард Studio",
                    account_url="https://vk.com/nails_salehard",
                    username_or_id="nails_salehard",
                    description="Маникюр Салехард, прайс, запись в лс, отзывы",
                    posts=[
                        PostRecord(
                            url="https://vk.com/nails_salehard/1",
                            text="Маникюр Салехард, свободные окна, цена 2500",
                            published_at=now - timedelta(days=2),
                        )
                    ],
                ),
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Объявления Салехард",
                    account_url="https://vk.com/ads_salehard",
                    username_or_id="ads_salehard",
                    description="Объявления, барахолка, новости Салехарда",
                    posts=[
                        PostRecord(
                            url="https://vk.com/ads_salehard/1",
                            text="Маникюр Салехард, пишите в сообщения, объявления города",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                )
            ],
        )


class PostOnlyMatchCollector(Collector):
    platform_name = "post_only"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Ольга Иванова",
                    account_url="https://vk.com/olga_private",
                    username_or_id="olga_private",
                    description="Личный профиль, Салехард",
                    posts=[
                        PostRecord(
                            url="https://vk.com/olga_private/1",
                            text="Маникюр Салехард, запись в лс, цена 2500",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                )
            ],
        )


class CityOnlyInPostsCollector(Collector):
    platform_name = "city_post_only"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Маникюр Studio",
                    account_url="https://vk.com/studio_without_city",
                    username_or_id="studio_without_city",
                    description="Маникюр, запись в лс, прайс",
                    posts=[
                        PostRecord(
                            url="https://vk.com/studio_without_city/1",
                            text="Салехард, свободные окна, цена 2500",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                )
            ],
        )


class MarkerBackedProfileCollector(Collector):
    platform_name = "marker_backed"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Nails Salehard",
                    account_url="https://vk.com/nails_salehard",
                    username_or_id="nails_salehard",
                    description="Nails studio, запись в лс, Салехард",
                    posts=[
                        PostRecord(
                            url="https://vk.com/nails_salehard/1",
                            text="Свободные окна, цена 2500, отзывы клиентов",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард nails",
                )
            ],
        )


class MultiServiceDuplicateCollector(Collector):
    platform_name = "multi_service_duplicate"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Beauty Loft Салехард",
                    account_url="https://vk.com/beauty_loft_shd",
                    username_or_id="beauty_loft_shd",
                    description="Маникюр, педикюр, запись в лс, прайс, Салехард",
                    posts=[
                        PostRecord(
                            url="https://vk.com/beauty_loft_shd/1",
                            text="Маникюр и педикюр, свободные окна, Салехард",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                    search_queries=["маникюр Салехард"],
                ),
                AccountCandidate(
                    service="педикюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Beauty Loft Салехард",
                    account_url="https://vk.com/beauty_loft_shd",
                    username_or_id="beauty_loft_shd",
                    description="Маникюр, педикюр, запись в лс, прайс, Салехард",
                    posts=[
                        PostRecord(
                            url="https://vk.com/beauty_loft_shd/1",
                            text="Маникюр и педикюр, свободные окна, Салехард",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                    search_queries=["педикюр Салехард"],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                ),
                SearchLogEntry(
                    city="Салехард",
                    service="педикюр",
                    platform="vk",
                    query="педикюр Салехард",
                ),
            ],
        )


class ServiceBoardCollector(Collector):
    platform_name = "service_board"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Маникюр Салехард | Объявления",
                    account_url="https://vk.com/nails_board",
                    username_or_id="nails_board",
                    description="Каталог мастеров, объявления, товары и услуги города",
                    posts=[
                        PostRecord(
                            url="https://vk.com/nails_board/1",
                            text="Маникюр Салехард, запись в лс, цена 2500",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                )
            ],
        )


class OfficialSignalsCollector(Collector):
    platform_name = "official_signals"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="ремонт",
                    city="Салехард",
                    platform="vk",
                    account_name="Ремонт ИП Иванов",
                    account_url="https://vk.com/remont_ip",
                    username_or_id="remont_ip",
                    description="ИП Иванов, ИНН 8901000000, работаем по договору, адрес Салехард",
                    posts=[
                        PostRecord(
                            url="https://vk.com/remont_ip/1",
                            text="Ремонт квартир, запись, цена, договор",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
                AccountCandidate(
                    service="ремонт",
                    city="Салехард",
                    platform="vk",
                    account_name="Ремонт Салехард Частный мастер",
                    account_url="https://vk.com/remont_private",
                    username_or_id="remont_private",
                    description="Частный мастер по ремонту, запись в лс, Салехард",
                    posts=[
                        PostRecord(
                            url="https://vk.com/remont_private/1",
                            text="Ремонт квартир, цена, отзывы",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="ремонт",
                    platform="vk",
                    query="ремонт Салехард",
                )
            ],
        )


class AllTimeCollector(Collector):
    platform_name = "all_time"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Маникюр Салехард Архив",
                    account_url="https://vk.com/nails_archive",
                    username_or_id="nails_archive",
                    description="Маникюр Салехард, прайс, запись в лс, отзывы",
                    posts=[
                        PostRecord(
                            url="https://vk.com/nails_archive/1",
                            text="Маникюр Салехард, цена, запись, отзывы клиентов",
                            published_at=now - timedelta(days=120),
                        )
                    ],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                )
            ],
        )


class PlacesSeedCollector(Collector):
    platform_name = "places_seed"

    def collect(self, request: SearchRequest):
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="places",
                    account_name="Nails Studio Салехард",
                    account_url="https://maps.google.com/?cid=123",
                    username_or_id="place-1",
                    description=(
                        "Карточка Google Places. "
                        "Категория: салон красоты. "
                        "Адрес: ул. Ленина, 10, Салехард. "
                        "Телефон: +7 900 000-00-00. "
                        "Сайт: https://nails.example.com."
                    ),
                    contacts={"phone": ["+7 900 000-00-00"]},
                    search_queries=["маникюр Салехард"],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="places",
                    query="маникюр Салехард",
                )
            ],
        )


class PetGroomingCollector(Collector):
    platform_name = "pet_grooming"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Груминг Салехард",
                    account_url="https://vk.com/groomlovee",
                    username_or_id="groomlovee",
                    description=(
                        "Груминг салон для собак и кошек в Салехарде. "
                        "Маникюр-чистка когтей, уход за лапами, запись по телефону."
                    ),
                    posts=[
                        PostRecord(
                            url="https://vk.com/groomlovee/1",
                            text="Запись открыта, цена, салехард, груминг собак и кошек",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                )
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                )
            ],
        )


class RetailStoreCollector(Collector):
    platform_name = "retail_store"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Всё для маникюра",
                    account_url="https://vk.com/beauty__buffet",
                    username_or_id="beauty__buffet",
                    description=(
                        "Ногтевой магазин в Салехарде. "
                        "Товары, материалы и оборудование для nail-мастеров."
                    ),
                    posts=[
                        PostRecord(
                            url="https://vk.com/beauty__buffet/1",
                            text="Материалы для мастеров, товары в наличии, цена по запросу",
                            published_at=now - timedelta(days=3),
                        )
                    ],
                )
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                )
            ],
        )


class TrainingFirstCollector(Collector):
    platform_name = "training_first"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Маникюр / Курсы",
                    account_url="https://vk.com/manicur_ksd",
                    username_or_id="manicur_ksd",
                    description=(
                        "Инструктор по маникюру. Обучение, курс с нуля, повышение квалификации, "
                        "научу тонким ногтям и укреплению. Работаю в Салехарде."
                    ),
                    posts=[
                        PostRecord(
                            url="https://vk.com/manicur_ksd/1",
                            text="Курс по маникюру, обучение, набор учеников",
                            published_at=now - timedelta(days=5),
                        )
                    ],
                )
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард",
                )
            ],
        )


class HotelCoffeeAmenityCollector(Collector):
    platform_name = "hotel_coffee"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="кофейня",
                    city="Салехард",
                    platform="vk",
                    account_name="Гостиница Арктика Салехард",
                    account_url="https://vk.com/arktika_89",
                    username_or_id="arktika_89",
                    description="Гостиница, проживание, номера, ресторан и кофейня на территории.",
                    posts=[
                        PostRecord(
                            url="https://vk.com/arktika_89/1",
                            text="Бронирование номеров и ресторан для гостей открыты.",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                )
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="кофейня",
                    platform="vk",
                    query="кофейня Салехард",
                )
            ],
        )


class TwoGisRestaurantCardCollector(Collector):
    platform_name = "2gis_restaurant"

    def collect(self, request: SearchRequest):
        return (
            [
                AccountCandidate(
                    service="кофейня",
                    city="Салехард",
                    platform="2gis",
                    account_name="Трактир на Ямальской, ресторан",
                    account_url="https://2gis.ru/search/70000001023485165",
                    username_or_id="70000001023485165",
                    description=(
                        "Карточка 2GIS. "
                        "Категории: Рестораны. "
                        "Адрес: Салехард, улица Ямальская, 21. "
                        "Координаты: 66.62825, 66.534409."
                    ),
                    business_categories="Рестораны",
                    search_queries=["кофейня Салехард"],
                )
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="кофейня",
                    platform="2gis",
                    query="кофейня Салехард",
                )
            ],
        )


class VkCoffeehouseProfileCollector(Collector):
    platform_name = "vk_coffeehouse"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="кофейня",
                    city="Салехард",
                    platform="vk",
                    account_name="Дай Дай | Кофейня в Салехарде",
                    account_url="https://vk.com/dai2shd",
                    username_or_id="dai2shd",
                    description=(
                        "«Дай Дай» — кофейня в Салехарде. "
                        "Адрес: улица Матросова, дом 31. "
                        "Время работы: с 8:30 до 21:00. "
                        "Telegram: t.me/Daidaishdbot"
                    ),
                    posts=[
                        PostRecord(
                            url="https://vk.com/dai2shd/1",
                            text="Сегодня варим фильтр и готовим тосты.",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
                AccountCandidate(
                    service="кофейня",
                    city="Салехард",
                    platform="vk",
                    account_name="DO.BRO Кофе | Салехард",
                    account_url="https://vk.com/do.bro_salekhard",
                    username_or_id="do.bro_salekhard",
                    description=(
                        "Наш адрес ул. Матросова, д. 35. "
                        "Режим работы с 8:00 до 20:00 ежедневно. "
                        "Taplink: https://taplink.cc/do.bro_salekhard"
                    ),
                    posts=[
                        PostRecord(
                            url="https://vk.com/do.bro_salekhard/1",
                            text="Ждем за чашкой вкусного кофе каждый день.",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="кофейня",
                    platform="vk",
                    query="кофейня Салехард",
                )
            ],
        )


class VkServiceProfilesCollector(Collector):
    platform_name = "vk_service_profiles"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        requested_service = request.services[0].name
        requested_city = request.cities[0]
        candidates: list[AccountCandidate] = []
        search_log: list[SearchLogEntry] = []

        if requested_city == "Новый Уренгой" and requested_service == "маникюр":
            candidates.append(
                AccountCandidate(
                    service="маникюр",
                    city="Новый Уренгой",
                    platform="vk",
                    account_name="Nails Studio | Новый Уренгой",
                    account_url="https://vk.com/nails_nur",
                    username_or_id="nails_nur",
                    description=(
                        "Маникюр и педикюр. "
                        "Адрес: Новый Уренгой, Ленинградский проспект, 1. "
                        "Запись: https://n123.yclients.com"
                    ),
                    posts=[
                        PostRecord(
                            url="https://vk.com/nails_nur/1",
                            text="Свежая работа мастера.",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                )
            )
            search_log.append(
                SearchLogEntry(
                    city="Новый Уренгой",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Новый Уренгой",
                )
            )

        if requested_city == "Тарко-Сале" and requested_service == "ремонт":
            candidates.append(
                AccountCandidate(
                    service="ремонт",
                    city="Тарко-Сале",
                    platform="vk",
                    account_name="Ремонт квартир Тарко-Сале",
                    account_url="https://vk.com/remont_tarko",
                    username_or_id="remont_tarko",
                    description=(
                        "Ремонт квартир под ключ. "
                        "Адрес: Тарко-Сале. "
                        "Телефон +7 900 000-00-01. "
                        "Работаем по договору."
                    ),
                    posts=[
                        PostRecord(
                            url="https://vk.com/remont_tarko/1",
                            text="Показываем ход работ на объекте.",
                            published_at=now - timedelta(days=2),
                        )
                    ],
                )
            )
            search_log.append(
                SearchLogEntry(
                    city="Тарко-Сале",
                    service="ремонт",
                    platform="vk",
                    query="ремонт Тарко-Сале",
                )
            )

        return candidates, search_log


class VkInferredServiceProfileCollector(Collector):
    platform_name = "vk_inferred_service"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="кофейня",
                    city="Тарко-Сале",
                    platform="vk",
                    account_name="Чашечкой кофе",
                    account_url="https://vk.com/chashechkoykofe_business",
                    username_or_id="chashechkoykofe_business",
                    description=(
                        "Адрес: Тарко-Сале, ул. Геологов, 7. "
                        "Режим работы: ежедневно с 08:00 до 21:00. "
                        "Telegram: t.me/chashechkoykofe"
                    ),
                    contacts={"telegram": ["@chashechkoykofe"]},
                    posts=[
                        PostRecord(
                            url="https://vk.com/chashechkoykofe_business/1",
                            text="Сегодня варим кофе, готовим десерты и ждём гостей в кофейне.",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                    api_address="Тарко-Сале, ул. Геологов, 7",
                    working_hours="ежедневно 08:00-21:00",
                    search_queries=["кофейня Тарко-Сале"],
                ),
            ],
            [
                SearchLogEntry(
                    city="Тарко-Сале",
                    service="кофейня",
                    platform="vk",
                    query="кофейня Тарко-Сале",
                )
            ],
        )


class VkWeakProfileSignalCollector(Collector):
    platform_name = "vk_weak_profile"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="vk",
                    account_name="Nails by Anna | Салехард",
                    account_url="https://vk.com/nails_by_anna_shd",
                    username_or_id="nails_by_anna_shd",
                    description="Телефон для записи: +7 900 000-11-22. Работаем ежедневно.",
                    contacts={"phone": ["+7 900 000-11-22"]},
                    posts=[
                        PostRecord(
                            url="https://vk.com/nails_by_anna_shd/1",
                            text="Маникюр, свободные окна, запись на этой неделе открыта.",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                    working_hours="ежедневно 10:00-20:00",
                    search_queries=["маникюр Салехард nails"],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="vk",
                    query="маникюр Салехард nails",
                )
            ],
        )


class TelegramWeakProfileSignalCollector(Collector):
    platform_name = "telegram_weak_profile"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="telegram",
                    account_name="Маникюр Салехард",
                    account_url="https://t.me/nails_salehard",
                    username_or_id="nails_salehard",
                    description="Запись по телефону +7 900 000-11-22",
                    contacts={"phone": ["+7 900 000-11-22"]},
                    posts=[
                        PostRecord(
                            url="https://t.me/nails_salehard/1",
                            text="Свободные окна на этой неделе.",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                    search_queries=["маникюр Салехард", "Салехард маникюр"],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="telegram",
                    query="маникюр Салехард",
                )
            ],
        )


class TelegramChatNoiseCollector(Collector):
    platform_name = "telegram_chat_noise"

    def collect(self, request: SearchRequest):
        now = datetime.now(UTC)
        return (
            [
                AccountCandidate(
                    service="маникюр",
                    city="Салехард",
                    platform="telegram",
                    account_name="Чат маникюр Салехард",
                    account_url="https://t.me/manicure_salehard_chat",
                    username_or_id="manicure_salehard_chat",
                    description="Чат для поиска мастеров и обсуждения услуг, телефон +7 900 000-11-22",
                    contacts={"phone": ["+7 900 000-11-22"]},
                    posts=[
                        PostRecord(
                            url="https://t.me/manicure_salehard_chat/1",
                            text="Обсуждаем мастеров и свободные слоты.",
                            published_at=now - timedelta(days=1),
                        )
                    ],
                    search_queries=["маникюр Салехард"],
                ),
            ],
            [
                SearchLogEntry(
                    city="Салехард",
                    service="маникюр",
                    platform="telegram",
                    query="маникюр Салехард",
                )
            ],
        )


class FailureAwareCollector(Collector):
    platform_name = "failure_aware"

    def __init__(self) -> None:
        self.platform_failures = [{"platform": "vk", "error": "upstream unavailable"}]
        self.platform_metrics = [{"platform": "vk", "duration_seconds": 1.25, "candidates": 0, "search_log": 0, "failed": True}]
        self.cache_stats = {"wall_hits": 3}
        self.cache_ttls = {"vk_wall_cache_ttl_hours": 24}

    def collect(self, request: SearchRequest):
        return [], []


class PipelineTests(unittest.TestCase):
    def test_pipeline_returns_ranked_accounts(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр", markers=["шеллак"])],
            period_days=60,
            platforms=["vk", "telegram"],
            top_n=5,
        )
        result = run_pipeline(request, collector=MockCollector(), config=RuntimeConfig())
        self.assertGreater(len(result.bundle.ranked_accounts), 0)
        top_score = result.bundle.ranked_accounts[0].score.total
        bottom_score = result.bundle.ranked_accounts[-1].score.total
        self.assertGreaterEqual(top_score, bottom_score)

    def test_pipeline_collapses_same_account_found_for_multiple_services(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр"), ServiceQuery(name="педикюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=MultiServiceDuplicateCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        candidate = result.bundle.ranked_accounts[0].candidate
        self.assertEqual(candidate.account_url, "https://vk.com/beauty_loft_shd")
        self.assertEqual(candidate.matched_services, ["маникюр", "педикюр"])
        self.assertEqual(result.bundle.duplicates_review, [])

    def test_pipeline_carries_platform_failures_into_report_meta(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=5,
        )

        result = run_pipeline(request, collector=FailureAwareCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.report_meta["platform_failures_total"], 1)
        self.assertEqual(
            result.bundle.report_meta["platform_failures"],
            [{"platform": "vk", "error": "upstream unavailable"}],
        )
        self.assertEqual(
            result.bundle.report_meta["platform_metrics"],
            [{"platform": "vk", "duration_seconds": 1.25, "candidates": 0, "search_log": 0, "failed": True}],
        )
        self.assertEqual(result.bundle.report_meta["wall_hits"], 3)
        self.assertEqual(result.bundle.report_meta["vk_wall_cache_ttl_hours"], 24)

    def test_pipeline_keeps_only_accounts_with_explicit_selected_city(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=MixedCityCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        self.assertEqual(result.bundle.ranked_accounts[0].candidate.account_name, "Маникюр Салехард")

    def test_pipeline_excludes_boards_and_keeps_real_service_pages(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=BoardVsServiceCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        self.assertEqual(result.bundle.ranked_accounts[0].candidate.account_name, "Маникюр Салехард Studio")

    def test_pipeline_excludes_accounts_where_service_exists_only_in_posts(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=PostOnlyMatchCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])

    def test_pipeline_excludes_accounts_where_city_exists_only_in_posts(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=CityOnlyInPostsCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])

    def test_pipeline_accepts_profiles_matched_by_service_marker(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр", markers=["nails"])],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=MarkerBackedProfileCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        self.assertEqual(result.bundle.ranked_accounts[0].candidate.account_name, "Nails Salehard")

    def test_pipeline_excludes_service_catalogs_even_if_service_is_in_profile(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=ServiceBoardCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])

    def test_pipeline_official_only_mode_keeps_only_medium_and_strong_official_accounts(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="ремонт")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
            report_mode="official_only",
        )

        result = run_pipeline(request, collector=OfficialSignalsCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        self.assertEqual(result.bundle.ranked_accounts[0].candidate.account_name, "Ремонт ИП Иванов")

    def test_pipeline_all_time_period_uses_full_collected_history(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=0,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=AllTimeCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        self.assertEqual(result.bundle.ranked_accounts[0].metrics.posts_in_period, 1)

    def test_pipeline_records_city_filter_reason_in_debug_sheet(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=CityOnlyInPostsCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])
        self.assertEqual(len(result.bundle.filter_debug), 1)
        self.assertEqual(result.bundle.filter_debug[0].decision_stage, "city_filter")
        self.assertEqual(result.bundle.filter_debug[0].status, "excluded")
        self.assertIn("В профиле нет явного сигнала выбранного города", result.bundle.filter_debug[0].reason)

    def test_pipeline_records_service_filter_reason_and_included_items(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=BoardVsServiceCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        self.assertEqual(len(result.bundle.filter_debug), 2)
        stages = {item.account_name: item.decision_stage for item in result.bundle.filter_debug}
        statuses = {item.account_name: item.status for item in result.bundle.filter_debug}
        self.assertEqual(stages["Маникюр Салехард Studio"], "final")
        self.assertEqual(statuses["Маникюр Салехард Studio"], "included")
        self.assertEqual(stages["Объявления Салехард"], "service_filter")
        self.assertEqual(statuses["Объявления Салехард"], "excluded")

    def test_pipeline_keeps_places_business_cards_with_contacts(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=90,
            platforms=["places"],
            top_n=10,
        )

        result = run_pipeline(request, collector=PlacesSeedCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        self.assertEqual(result.bundle.ranked_accounts[0].candidate.platform, "places")
        self.assertEqual(result.bundle.filter_debug[-1].status, "included")
        self.assertIn("Карточка Google Places прошла фильтр", result.bundle.filter_debug[-1].reason)

    def test_pipeline_excludes_pet_grooming_false_positive_for_manicure(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=90,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=PetGroomingCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])
        self.assertIn("pet/grooming", result.bundle.filter_debug[0].reason)

    def test_pipeline_excludes_retail_store_for_manicure_service_request(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=90,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=RetailStoreCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])
        self.assertIn("магазин материалов", result.bundle.filter_debug[0].reason)

    def test_pipeline_excludes_training_first_profile_without_booking_signal(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=90,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=TrainingFirstCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])
        self.assertIn("обучение или курсы", result.bundle.filter_debug[0].reason)

    def test_pipeline_excludes_hotel_with_coffee_amenity_for_coffeehouse_request(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="кофейня")],
            period_days=90,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=HotelCoffeeAmenityCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])
        self.assertIn("гостиницу/отель", result.bundle.filter_debug[0].reason)

    def test_pipeline_excludes_2gis_restaurant_card_for_coffeehouse_request(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="кофейня")],
            period_days=90,
            platforms=["2gis"],
            top_n=10,
        )

        result = run_pipeline(request, collector=TwoGisRestaurantCardCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])
        self.assertIn("Услуга не заявлена", result.bundle.filter_debug[0].reason)

    def test_pipeline_keeps_vk_coffeehouses_with_strong_profile_business_signals(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="кофейня")],
            period_days=0,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=VkCoffeehouseProfileCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 2)
        urls = {item.candidate.account_url for item in result.bundle.ranked_accounts}
        self.assertIn("https://vk.com/dai2shd", urls)
        self.assertIn("https://vk.com/do.bro_salekhard", urls)

    def test_pipeline_keeps_strong_vk_business_profiles_for_multiple_services_and_cities(self) -> None:
        first_request = SearchRequest(
            cities=["Новый Уренгой"],
            services=[ServiceQuery(name="маникюр")],
            period_days=0,
            platforms=["vk"],
            top_n=10,
        )
        second_request = SearchRequest(
            cities=["Тарко-Сале"],
            services=[ServiceQuery(name="ремонт")],
            period_days=0,
            platforms=["vk"],
            top_n=10,
        )

        first_result = run_pipeline(first_request, collector=VkServiceProfilesCollector(), config=RuntimeConfig())
        second_result = run_pipeline(second_request, collector=VkServiceProfilesCollector(), config=RuntimeConfig())

        first_urls = {item.candidate.account_url for item in first_result.bundle.ranked_accounts}
        second_urls = {item.candidate.account_url for item in second_result.bundle.ranked_accounts}

        self.assertEqual(first_urls, {"https://vk.com/nails_nur"})
        self.assertEqual(second_urls, {"https://vk.com/remont_tarko"})

    def test_pipeline_keeps_vk_profile_when_service_is_inferred_from_context_and_business_header(self) -> None:
        request = SearchRequest(
            cities=["Тарко-Сале"],
            services=[ServiceQuery(name="кофейня")],
            period_days=0,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=VkInferredServiceProfileCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        self.assertEqual(result.bundle.ranked_accounts[0].candidate.account_url, "https://vk.com/chashechkoykofe_business")

    def test_pipeline_keeps_vk_profile_with_weak_header_signal_when_context_confirms_service(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=0,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=VkWeakProfileSignalCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        self.assertEqual(result.bundle.ranked_accounts[0].candidate.account_url, "https://vk.com/nails_by_anna_shd")

    def test_pipeline_keeps_telegram_profile_with_weak_business_header_when_contact_structure_exists(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["telegram"],
            top_n=10,
        )

        result = run_pipeline(request, collector=TelegramWeakProfileSignalCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.ranked_accounts), 1)
        self.assertEqual(result.bundle.ranked_accounts[0].candidate.account_url, "https://t.me/nails_salehard")

    def test_pipeline_still_excludes_telegram_chat_noise_with_service_words(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["telegram"],
            top_n=10,
        )

        result = run_pipeline(request, collector=TelegramChatNoiseCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])

    def test_pipeline_keeps_raw_candidates_before_filters(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        result = run_pipeline(request, collector=BoardVsServiceCollector(), config=RuntimeConfig())

        self.assertEqual(len(result.bundle.raw_candidates), 2)
        self.assertEqual(result.bundle.raw_candidates[0].service, "маникюр")

    def test_pipeline_excludes_profiles_with_personal_blog_marker_from_rule_config(self) -> None:
        request = SearchRequest(
            cities=["Салехард"],
            services=[ServiceQuery(name="маникюр")],
            period_days=30,
            platforms=["vk"],
            top_n=10,
        )

        class PersonalBlogCollector(Collector):
            platform_name = "personal_blog"

            def collect(self, request: SearchRequest):
                now = datetime.now(UTC)
                return (
                    [
                        AccountCandidate(
                            service="маникюр",
                            city="Салехард",
                            platform="vk",
                            account_name="Анна Nails",
                            account_url="https://vk.com/anna_blog",
                            username_or_id="anna_blog",
                            description="Личный блог. Маникюр в Салехарде, запись в лс",
                            posts=[
                                PostRecord(
                                    url="https://vk.com/anna_blog/1",
                                    text="Запись на маникюр открыта",
                                    published_at=now - timedelta(days=1),
                                )
                            ],
                        )
                    ],
                    [SearchLogEntry(city="Салехард", service="маникюр", platform="vk", query="маникюр Салехард")],
                )

        result = run_pipeline(request, collector=PersonalBlogCollector(), config=RuntimeConfig())

        self.assertEqual(result.bundle.ranked_accounts, [])
        self.assertIn("личной/некоммерческой", result.bundle.filter_debug[0].reason)


if __name__ == "__main__":
    unittest.main()
