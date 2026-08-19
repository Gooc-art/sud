from __future__ import annotations

import re
from collections.abc import Iterable


DEFAULT_COMMERCIAL_MARKERS = [
    "цена",
    "прайс",
    "стоимость",
    "запись",
    "записаться",
    "свободные окна",
    "окна",
    "принимаю",
    "портфолио",
    "отзывы",
    "отзыв",
    "пишите в лс",
    "в личные сообщения",
    "директ",
    "whatsapp",
    "телефон",
    "заказать",
    "услуги",
    "мастер",
    "вакансия",
    "ищем мастера",
]

DEFAULT_NOISE_MARKERS = [
    "новости",
    "события",
    "афиша",
    "объявления",
    "барахолка",
    "куплю",
    "продам",
    "чат",
    "подслушано",
    "каталог",
    "справочник",
    "агрегатор",
    "маркетплейс",
]

HARD_NOISE_MARKERS = [
    "доска объявлений",
    "объявления города",
    "объявления",
    "барахолка",
    "подслушано",
    "чат",
    "каталог",
    "справочник",
    "агрегатор",
    "маркетплейс",
    "товары и услуги",
    "все объявления",
    "всё для города",
    "городской портал",
    "афиша",
    "новости",
    "события города",
]

PROVIDER_APPOINTMENT_MARKERS = [
    "запись",
    "записаться",
    "свободные окна",
    "прайс",
    "цена",
    "стоимость",
    "принимаю",
    "в студии",
    "ycients",
    "yclients",
]

SERVICE_RETAIL_MARKERS = [
    "магазин",
    "товары",
    "материалы",
    "оборудование",
    "для мастеров",
    "для nail мастеров",
    "для nail-мастеров",
    "купить",
    "продажа",
]

SERVICE_TRAINING_MARKERS = [
    "обучение",
    "курс",
    "курсы",
    "инструктор",
    "повышение квалификации",
    "научу",
    "ученик",
]

PET_GROOMING_MARKERS = [
    "груминг",
    "собак",
    "собака",
    "кошек",
    "кошки",
    "питомц",
    "лап",
    "когтей",
]

HOSPITALITY_AMENITY_MARKERS = [
    "гостиница",
    "отель",
    "hotel",
    "хостел",
    "апарт",
    "апартамент",
    "апартаменты",
    "номерной фонд",
    "номера",
    "заселение",
    "проживание",
]

FOOD_SERVICE_GROUP = [
    "общепит",
    "кафе",
    "кофейня",
    "ресторан",
    "пекарня",
    "доставка еды",
]

SERVICE_SYNONYM_GROUPS = [
    ("маникюр", ["nails", "nail", "ногти", "маник", "nail studio"]),
    ("педикюр", ["pedicure", "педик"]),
    ("салон красоты", ["beauty", "beauty studio", "студия красоты", "beauty salon"]),
    ("барбершоп", ["barbershop", "барбер", "мужские стрижки"]),
    ("фотограф", ["фотосъемка", "фотосъёмка", "съемка", "съёмка", "photo", "photographer"]),
    ("ремонт", ["ремонт квартир", "отделка", "отделочные работы", "мастер на час"]),
    ("автоэлектрик", ["автоэлектрика", "автодиагност", "автодиагностика"]),
    ("автосервис", ["сто", "авторемонт", "автосервис 89", "car service"]),
    ("автомойка", ["мойка авто", "автомойка самообслуживания", "car wash"]),
    ("шиномонтаж", ["переобувка", "замена резины", "tyre service"]),
    ("электрик", ["электромонтаж", "электромонтажные работы"]),
    ("сантехник", ["сантехника", "сантехнические работы"]),
    ("парикмахер", ["hair", "стрижки", "колорист", "hair stylist"]),
    ("брови", ["brow", "brows", "бровист"]),
    ("ресницы", ["lashes", "lash", "лэшмейкер"]),
    ("косметолог", ["cosmetology", "косметология"]),
    ("массаж", ["massage", "массажист"]),
    (
        "общепит",
        [
            "кафе",
            "кофейня",
            "ресторан",
            "пекарня",
            "доставка еды",
            "еда",
            "еда на заказ",
            "еда на вынос",
            "домашняя еда",
            "готовая еда",
            "восточная еда",
        ],
    ),
    ("кафе", ["cafe", "кафешка"]),
    ("кофейня", ["кофе", "coffee", "coffee shop", "кофе с собой"]),
    ("ресторан", ["restaurant", "restoran"]),
    ("пекарня", ["булочная", "выпечка", "bakery", "торты", "пироги", "кондитерская", "домашняя выпечка"]),
    (
        "доставка еды",
        [
            "доставка роллов",
            "доставка суши",
            "доставка пиццы",
            "food delivery",
            "еда на заказ",
            "еда на вынос",
            "домашняя еда",
            "готовая еда",
            "восточная еда",
            "доставка готовой еды",
        ],
    ),
    ("клининг", ["уборка", "генеральная уборка", "клининговая компания", "cleaning"]),
    ("химчистка", ["чистка одежды", "чистка мебели", "dry clean"]),
    ("стоматология", ["стоматолог", "зубной", "dental"]),
    ("фитнес", ["fitness", "фитнес клуб", "тренажерный зал"]),
    ("юрист", ["юридические услуги", "адвокат", "lawyer"]),
    ("бухгалтер", ["бухгалтерские услуги", "аутсорсинг бухгалтерии", "accounting"]),
]

SERVICE_DISCOVERY_HINT_GROUPS = [
    ("маникюр", ["ногти", "мастер маникюра", "студия маникюра"]),
    ("педикюр", ["мастер педикюра", "студия педикюра"]),
    ("салон красоты", ["студия красоты", "салон красоты", "beauty studio"]),
    ("барбершоп", ["барбер", "мужские стрижки", "barbershop"]),
    ("фотограф", ["фотосъемка", "фотосъёмка", "семейный фотограф"]),
    ("ремонт", ["ремонт квартир", "мастер на час", "отделка"]),
    ("автоэлектрик", ["автодиагностика", "мастер автоэлектрик"]),
    ("автосервис", ["сто", "авторемонт", "мастер автосервис"]),
    ("автомойка", ["мойка авто", "автомойка", "мойка самообслуживания"]),
    ("шиномонтаж", ["переобувка", "замена резины", "мастер шиномонтаж"]),
    ("электрик", ["электромонтаж", "мастер электрик"]),
    ("сантехник", ["сантехнические работы", "мастер сантехник"]),
    ("парикмахер", ["стрижки", "мастер по волосам", "салон красоты"]),
    ("брови", ["бровист", "студия бровей"]),
    ("ресницы", ["лэшмейкер", "студия ресниц"]),
    ("косметолог", ["косметология", "студия косметологии"]),
    ("массаж", ["массажист", "студия массажа"]),
    ("общепит", ["кафе", "кофейня", "ресторан", "еда", "домашняя еда", "еда на заказ", "еда на вынос"]),
    ("кафе", ["кафе", "семейное кафе", "кафе доставка"]),
    ("кофейня", ["кофе", "кофе с собой", "coffee shop", "кофейня"]),
    ("ресторан", ["ресторан", "банкетный зал", "кухня"]),
    ("пекарня", ["булочная", "выпечка", "пекарня", "торты", "пироги", "кондитерская"]),
    ("доставка еды", ["доставка суши", "доставка роллов", "доставка пиццы", "еда на заказ", "домашняя еда", "доставка"]),
    ("клининг", ["уборка квартир", "клининговая компания", "генеральная уборка"]),
    ("химчистка", ["чистка мебели", "химчистка салона", "чистка одежды"]),
    ("стоматология", ["стоматолог", "зубная клиника", "dental clinic"]),
    ("фитнес", ["фитнес клуб", "спортзал", "тренажерный зал"]),
    ("юрист", ["адвокат", "юридические услуги", "юридическая помощь"]),
    ("бухгалтер", ["бухгалтерские услуги", "главный бухгалтер", "ведение бухгалтерии"]),
]

TWOGIS_CATEGORY_HINT_GROUPS = [
    ("маникюр", ["ногтевая студия", "ногтевой сервис", "студия ногтей"]),
    ("педикюр", ["ногтевая студия", "подолог", "студия педикюра"]),
    ("салон красоты", ["салон красоты", "beauty studio", "студия красоты"]),
    ("барбершоп", ["barbershop", "барбершоп", "мужская парикмахерская"]),
    ("фотограф", ["фотостудия", "фотоуслуги"]),
    ("ремонт", ["ремонтно-строительная компания", "строительные и отделочные работы"]),
    ("автоэлектрик", ["автосервис", "автоэлектрика"]),
    ("автосервис", ["автосервис", "сто", "автотехцентр"]),
    ("автомойка", ["автомойка", "мойка самообслуживания"]),
    ("шиномонтаж", ["шиномонтаж", "автосервис"]),
    ("электрик", ["электромонтажные работы", "услуги электрика"]),
    ("сантехник", ["сантехнические работы", "услуги сантехника"]),
    ("парикмахер", ["парикмахерская", "салон красоты"]),
    ("брови", ["студия бровей", "салон красоты"]),
    ("ресницы", ["студия ресниц", "салон красоты"]),
    ("косметолог", ["косметология", "косметологическая клиника"]),
    ("массаж", ["массажный салон", "студия массажа"]),
    ("общепит", ["кафе", "кофейня", "ресторан", "пекарня"]),
    ("кафе", ["кафе", "семейное кафе", "кафе быстрого питания"]),
    ("кофейня", ["кофейня", "кофе", "кофе с собой", "coffee shop"]),
    ("ресторан", ["ресторан", "банкетный зал", "гриль-бар"]),
    ("пекарня", ["пекарня", "булочная", "кондитерская"]),
    ("доставка еды", ["доставка еды", "доставка суши", "доставка пиццы"]),
    ("клининг", ["клининговая компания", "уборка квартир"]),
    ("химчистка", ["химчистка", "чистка мебели", "чистка одежды"]),
    ("стоматология", ["стоматология", "зубная клиника"]),
    ("фитнес", ["фитнес-клуб", "тренажерный зал", "спортзал"]),
    ("юрист", ["юридические услуги", "адвокат"]),
    ("бухгалтер", ["бухгалтерские услуги", "аутсорсинг бухгалтерии"]),
]

OFFICIAL_STRONG_MARKERS = [
    "ип ",
    "ооо",
    "самозанятый",
    "инн",
    "огрн",
    "огрнип",
    "реквизиты",
    "по договору",
]

OFFICIAL_MEDIUM_MARKERS = [
    "договор",
    "чек",
    "касса",
    "адрес",
    "офис",
    "официально",
    "работаем официально",
]

GENERIC_REGION_SIGNALS = [
    ("ЯНАО/Ямал", ["янао", "ямал", "yamal"]),
]

CITY_ALIAS_MAP = {
    "Салехард": ["салехард", "#салехард", "salehard", "salekhard"],
    "Новый Уренгой": [
        "новый уренгой",
        "новыйуренгой",
        "н уренгой",
        "#новыйуренгой",
        "novyy urengoy",
        "novy urengoy",
        "novyi urengoy",
        "new urengoy",
    ],
    "Ноябрьск": ["ноябрьск", "#ноябрьск", "noyabrsk", "noiabrsk"],
    "Надым": ["надым", "#надым", "nadym"],
    "Муравленко": ["муравленко", "#муравленко", "muravlenko"],
    "Губкинский": ["губкинский", "#губкинский", "gubkinskiy", "gubkinsky"],
    "Лабытнанги": ["лабытнанги", "#лабытнанги", "labytnangi", "labytangi"],
    "Тарко-Сале": ["тарко-сале", "тарко сале", "таркосале", "#таркосале", "tarko-sale", "tarko sale"],
    "Тазовский": ["тазовский", "#тазовский", "tazovskiy", "tazovsky"],
    "Яр-Сале": ["яр-сале", "яр сале", "ярсале", "#ярсале", "yar-sale", "yar sale", "yarsale"],
    "Аксарка": ["аксарка", "#аксарка", "aksarka"],
    "Харп": ["харп", "#харп", "kharp", "harp"],
    "Мужи": ["мужи", "#мужи", "muzhi"],
    "Красноселькуп": ["красноселькуп", "#красноселькуп", "krasnoselkup", "krasnoselcup"],
}

_SERVICE_ALIAS_OVERRIDES: dict[str, list[str]] = {}
_SERVICE_DISCOVERY_HINT_OVERRIDES: dict[str, list[str]] = {}
_CITY_ALIAS_OVERRIDES: dict[str, list[str]] = {}


CONTACT_PATTERNS = {
    "phone": re.compile(r"(?:\+7|8)[\s\-()]*\d[\d\s\-()]{8,}"),
    "telegram": re.compile(r"@[\w\d_]{4,}"),
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
}

WEBSITE_PATTERN = re.compile(
    r"(?:https?://|www\.)[^\s<>()]+|[a-z0-9][a-z0-9.-]+\.(?:ru|рф|com|net|org|app|pro|me|online|link)\S*",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(
    r"(?:https?://|www\.)[^\s<>()]+|[a-z0-9][a-z0-9.-]+\.(?:ru|рф|com|net|org|app|pro|me|online|link)\S*",
    re.IGNORECASE,
)

BOOKING_URL_MARKERS = [
    "yclients",
    "dikidi",
    "arnica",
    "easyweek",
    "booksy",
    "altegio",
]

BOOKING_CONTEXT_MARKERS = [
    "запись",
    "записаться",
    "записаться онлайн",
    "онлайн запись",
    "онлайн запис",
    "круглосуточная онлайн запись",
    "book now",
]

SERVICE_STOP_WORDS = {
    "и",
    "или",
    "для",
    "по",
    "на",
    "в",
    "с",
    "со",
    "под",
    "без",
    "от",
    "до",
}


def normalize_text(value: str) -> str:
    cleaned = re.sub(r"[#./\\_-]+", " ", value.casefold())
    return re.sub(r"\s+", " ", cleaned).strip()


def configure_marker_alias_overrides(rule_config: object | None = None) -> None:
    global _SERVICE_ALIAS_OVERRIDES, _SERVICE_DISCOVERY_HINT_OVERRIDES, _CITY_ALIAS_OVERRIDES
    if rule_config is None:
        _SERVICE_ALIAS_OVERRIDES = {}
        _SERVICE_DISCOVERY_HINT_OVERRIDES = {}
        _CITY_ALIAS_OVERRIDES = {}
        return

    _SERVICE_ALIAS_OVERRIDES = _normalize_override_map(getattr(rule_config, "service_alias_overrides", {}))
    _SERVICE_DISCOVERY_HINT_OVERRIDES = _normalize_override_map(
        getattr(rule_config, "service_discovery_hint_overrides", {})
    )
    _CITY_ALIAS_OVERRIDES = _normalize_override_map(getattr(rule_config, "city_alias_overrides", {}))


def normalize_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9а-яё]+", "-", value.casefold()).strip("-")


def marker_hits(texts: Iterable[str], markers: Iterable[str]) -> list[str]:
    corpus = normalize_text(" ".join(filter(None, texts)))
    hits: list[str] = []
    for marker in markers:
        token = normalize_text(marker)
        if token and token in corpus:
            hits.append(marker)
    return sorted(set(hits))


def city_hits(texts: Iterable[str], cities: Iterable[str]) -> list[str]:
    corpus = normalize_text(" ".join(filter(None, texts)))
    hits: list[str] = []
    for city in cities:
        aliases = [
            *CITY_ALIAS_MAP.get(city, [city]),
            *_CITY_ALIAS_OVERRIDES.get(normalize_text(city), []),
        ]
        normalized_aliases = [normalize_text(alias) for alias in aliases if normalize_text(alias)]
        if any(alias in corpus for alias in normalized_aliases):
            hits.append(city)
    for signal_name, aliases in GENERIC_REGION_SIGNALS:
        normalized_aliases = [normalize_text(alias) for alias in aliases if normalize_text(alias)]
        if any(alias in corpus for alias in normalized_aliases):
            hits.append(signal_name)
    return sorted(set(hits))


def extract_contacts(texts: Iterable[str]) -> dict[str, list[str]]:
    corpus = "\n".join(filter(None, texts))
    contacts: dict[str, list[str]] = {}
    for kind, pattern in CONTACT_PATTERNS.items():
        found_items: list[str] = []
        for match in pattern.finditer(corpus):
            if kind == "telegram" and match.start() > 0 and corpus[match.start() - 1] not in {" ", "\n", "\t", "(", "[", "{", "|"}:
                continue
            found_items.append(match.group(0).strip())
        found = sorted(set(found_items))
        if found:
            contacts[kind] = found
    websites = extract_websites(texts)
    if websites:
        contacts["website"] = websites
    return contacts


def extract_websites(texts: Iterable[str]) -> list[str]:
    websites: list[str] = []
    for text in filter(None, texts):
        for match in WEBSITE_PATTERN.finditer(text):
            if match.start() > 0 and text[match.start() - 1] == "@":
                continue
            normalized_url = _normalize_url(match.group(0))
            if normalized_url and normalized_url not in websites:
                websites.append(normalized_url)
    return websites


def extract_booking_links(texts: Iterable[str]) -> list[str]:
    links: list[str] = []
    for text in filter(None, texts):
        for match in URL_PATTERN.finditer(text):
            normalized_url = _normalize_url(match.group(0))
            if not normalized_url:
                continue
            context = _booking_link_context(text, match.start(), match.end())
            if _is_booking_link(normalized_url, context) and normalized_url not in links:
                links.append(normalized_url)
    return links


def service_search_queries(
    service_name: str,
    city: str,
    extra_markers: Iterable[str] = (),
    *,
    alias_limit: int = 2,
    discovery_limit: int = 3,
    marker_limit: int = 2,
) -> list[str]:
    if is_food_service(service_name):
        alias_limit = max(alias_limit, 5)
        discovery_limit = max(discovery_limit, 5)
    return [
        query
        for batch in service_search_query_plan(
            service_name,
            city,
            extra_markers,
            alias_limit=alias_limit,
            discovery_limit=discovery_limit,
            marker_limit=marker_limit,
        )
        for query in batch
    ]


def telegram_search_queries(
    service_name: str,
    city: str,
    extra_markers: Iterable[str] = (),
    *,
    alias_limit: int = 3,
    discovery_limit: int = 4,
    marker_limit: int = 1,
) -> list[str]:
    if is_food_service(service_name):
        alias_limit = max(alias_limit, 6)
        discovery_limit = max(discovery_limit, 6)
    queries: list[str] = []
    batches = service_search_query_plan(
        service_name,
        city,
        extra_markers,
        alias_limit=alias_limit,
        discovery_limit=discovery_limit,
        marker_limit=marker_limit,
    )
    for batch in batches:
        for query in batch:
            queries.append(query)
            if query.endswith(city):
                service_part = query[: -len(city)].strip()
                reversed_query = f"{city} {service_part}".strip()
                if reversed_query:
                    queries.append(reversed_query)
    return _unique_preserve_order(query for query in queries if query)


def service_search_query_plan(
    service_name: str,
    city: str,
    extra_markers: Iterable[str] = (),
    *,
    alias_limit: int = 2,
    discovery_limit: int = 3,
    marker_limit: int = 2,
) -> list[list[str]]:
    terms = service_search_terms(service_name)
    batches: list[list[str]] = []

    if terms:
        batches.append(_unique_preserve_order([f"{terms[0]} {city}".strip()]))

    override_terms = _matching_service_override_values(service_name, _SERVICE_ALIAS_OVERRIDES)
    alias_terms = list(terms[1 : 1 + alias_limit]) + [term for term in override_terms if term not in terms[1 : 1 + alias_limit]]
    alias_queries = [f"{term} {city}".strip() for term in alias_terms]
    if alias_queries:
        batches.append(_unique_preserve_order(query for query in alias_queries if query))

    hints = service_discovery_hints(service_name)
    override_hints = _matching_service_override_values(service_name, _SERVICE_DISCOVERY_HINT_OVERRIDES)
    discovery_terms = list(hints[:discovery_limit]) + [hint for hint in override_hints if hint not in hints[:discovery_limit]]
    discovery_queries = [f"{hint} {city}".strip() for hint in discovery_terms]
    if discovery_queries:
        batches.append(_unique_preserve_order(query for query in discovery_queries if query))

    marker_queries = [
        f"{service_name} {city} {marker}".strip()
        for marker in list(_unique_preserve_order(extra_markers))[:marker_limit]
    ]
    if marker_queries:
        batches.append(_unique_preserve_order(query for query in marker_queries if query))

    return [batch for batch in batches if batch]


def service_search_terms(service_name: str) -> list[str]:
    normalized_service = normalize_text(service_name)
    terms = [service_name]
    family_keys = {normalized_service}
    for canonical, aliases in SERVICE_SYNONYM_GROUPS:
        normalized_family = [normalize_text(canonical), *[normalize_text(alias) for alias in aliases]]
        if normalized_service in normalized_family:
            terms.extend([canonical, *aliases])
            family_keys.update(normalized_family)
            break
    for key, aliases in _SERVICE_ALIAS_OVERRIDES.items():
        if key in family_keys or normalized_service == key:
            terms.extend(aliases)
    return _unique_preserve_order(term for term in terms if term)


def service_profile_terms(service_name: str) -> list[str]:
    normalized_service = normalize_text(service_name)
    terms = [service_name]
    family_keys = {normalized_service}

    if is_food_service(service_name) and normalized_service != normalize_text("общепит"):
        for canonical, aliases in SERVICE_SYNONYM_GROUPS:
            if normalize_text(canonical) == normalized_service:
                terms.extend([canonical, *aliases])
                family_keys.update([normalize_text(canonical), *[normalize_text(alias) for alias in aliases]])
                break
    else:
        for canonical, aliases in SERVICE_SYNONYM_GROUPS:
            normalized_family = [normalize_text(canonical), *[normalize_text(alias) for alias in aliases]]
            if normalized_service in normalized_family:
                terms.extend([canonical, *aliases])
                family_keys.update(normalized_family)
                break

    for key, aliases in _SERVICE_ALIAS_OVERRIDES.items():
        if key in family_keys or normalized_service == key:
            terms.extend(aliases)
    return _unique_preserve_order(term for term in terms if term)


def service_discovery_hints(service_name: str) -> list[str]:
    normalized_service = normalize_text(service_name)
    hints = []
    family_keys = {normalized_service}
    for canonical, group_hints in SERVICE_DISCOVERY_HINT_GROUPS:
        normalized_family = [normalize_text(canonical), *[normalize_text(alias) for alias in service_search_terms(canonical)]]
        if normalized_service in normalized_family:
            hints.extend(group_hints)
            family_keys.update(normalized_family)
            break
    for key, group_hints in _SERVICE_DISCOVERY_HINT_OVERRIDES.items():
        if key in family_keys or normalized_service == key:
            hints.extend(group_hints)
    return _unique_preserve_order(hint for hint in hints if hint)


def twogis_category_hints(service_name: str) -> list[str]:
    normalized_service = normalize_text(service_name)
    hints = []
    family_keys = {normalized_service}
    for canonical, group_hints in TWOGIS_CATEGORY_HINT_GROUPS:
        normalized_family = [normalize_text(canonical), *[normalize_text(alias) for alias in service_search_terms(canonical)]]
        if normalized_service in normalized_family:
            hints.extend(group_hints)
            family_keys.update(normalized_family)
            break
    for key, group_hints in _SERVICE_DISCOVERY_HINT_OVERRIDES.items():
        if key in family_keys or normalized_service == key:
            hints.extend(group_hints)
    return _unique_preserve_order(hint for hint in hints if hint)


def is_food_service(service_name: str) -> bool:
    return normalize_text(service_name) in {normalize_text(item) for item in FOOD_SERVICE_GROUP}


def hospitality_amenity_hits(texts: Iterable[str]) -> list[str]:
    return marker_hits(texts, HOSPITALITY_AMENITY_MARKERS)


def service_profile_hits(
    texts: Iterable[str],
    service_name: str,
    extra_markers: Iterable[str] = (),
) -> list[str]:
    corpus = normalize_text(" ".join(filter(None, texts)))
    if not corpus:
        return []

    hits: list[str] = []
    for term in service_profile_terms(service_name):
        normalized_term = normalize_text(term)
        if normalized_term and len(normalized_term) >= 4 and normalized_term in corpus:
            hits.append(term)

    for marker in _service_specific_markers(extra_markers):
        normalized_marker = normalize_text(marker)
        if normalized_marker and normalized_marker in corpus:
            hits.append(marker)

    significant_tokens = _service_tokens(service_name)
    if len(significant_tokens) > 1:
        token_hits = [token for token in significant_tokens if token in corpus]
        if len(token_hits) >= max(2, len(significant_tokens) - 1):
            hits.extend(token_hits)
    elif len(significant_tokens) == 1 and significant_tokens[0] in corpus:
        hits.append(significant_tokens[0])

    return _unique_preserve_order(hits)


def twogis_search_queries(
    service_name: str,
    city: str,
    extra_markers: Iterable[str] = (),
    *,
    alias_limit: int = 3,
    discovery_limit: int = 4,
    category_limit: int = 3,
    marker_limit: int = 2,
) -> list[str]:
    return [
        query
        for batch in twogis_search_query_plan(
            service_name,
            city,
            extra_markers,
            alias_limit=alias_limit,
            discovery_limit=discovery_limit,
            category_limit=category_limit,
            marker_limit=marker_limit,
        )
        for query in batch
    ]


def twogis_search_query_plan(
    service_name: str,
    city: str,
    extra_markers: Iterable[str] = (),
    *,
    alias_limit: int = 3,
    discovery_limit: int = 4,
    category_limit: int = 3,
    marker_limit: int = 2,
) -> list[list[str]]:
    terms = service_search_terms(service_name)
    batches: list[list[str]] = []

    if terms:
        batches.append(_city_ordered_queries(terms[0], city))

    override_terms = _matching_service_override_values(service_name, _SERVICE_ALIAS_OVERRIDES)
    alias_terms = list(terms[1 : 1 + alias_limit]) + [term for term in override_terms if term not in terms[1 : 1 + alias_limit]]
    alias_queries = [query for term in alias_terms for query in _city_ordered_queries(term, city)]
    if alias_queries:
        batches.append(_unique_preserve_order(alias_queries))

    hints = service_discovery_hints(service_name)
    override_hints = _matching_service_override_values(service_name, _SERVICE_DISCOVERY_HINT_OVERRIDES)
    discovery_terms = list(hints[:discovery_limit]) + [hint for hint in override_hints if hint not in hints[:discovery_limit]]
    discovery_queries = [query for hint in discovery_terms for query in _city_ordered_queries(hint, city)]
    if discovery_queries:
        batches.append(_unique_preserve_order(discovery_queries))

    category_terms = twogis_category_hints(service_name)[:category_limit]
    category_queries = [query for hint in category_terms for query in _city_ordered_queries(hint, city)]
    if category_queries:
        batches.append(_unique_preserve_order(category_queries))

    marker_queries = [
        f"{service_name} {city} {marker}".strip()
        for marker in list(_unique_preserve_order(extra_markers))[:marker_limit]
    ]
    if marker_queries:
        batches.append(_unique_preserve_order(query for query in marker_queries if query))

    return [batch for batch in batches if batch]


def official_signal_hits(texts: Iterable[str]) -> list[str]:
    raw_corpus = "\n".join(filter(None, texts))
    normalized_corpus = normalize_text(raw_corpus)
    hits: list[str] = []

    for marker in OFFICIAL_STRONG_MARKERS + OFFICIAL_MEDIUM_MARKERS:
        normalized_marker = normalize_text(marker)
        if normalized_marker and normalized_marker in normalized_corpus:
            hits.append(marker.strip())

    if WEBSITE_PATTERN.search(raw_corpus):
        hits.append("сайт/домен")

    return _unique_preserve_order(hits)


def _normalize_url(value: str) -> str:
    normalized = value.strip().strip("()[]{}<>\"'.,;!?:")
    if not normalized:
        return ""
    if normalized.startswith("www."):
        return f"https://{normalized}"
    if "://" not in normalized:
        return f"https://{normalized}"
    return normalized


def _booking_link_context(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    previous_line_end = max(line_start - 1, 0)
    previous_line_start = text.rfind("\n", 0, previous_line_end) + 1 if line_start > 0 else 0
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    return normalize_text(text[previous_line_start:line_end])


def _is_booking_link(url: str, context: str) -> bool:
    normalized_url = normalize_text(url)
    if any(marker in normalized_url for marker in BOOKING_URL_MARKERS):
        return True
    return any(normalize_text(marker) in context for marker in BOOKING_CONTEXT_MARKERS)


def official_signal_level(hits: Iterable[str]) -> str:
    unique_hits = _unique_preserve_order(hits)
    if not unique_hits:
        return "нет"

    strong_hits = {
        hit
        for hit in unique_hits
        if normalize_text(hit) in {normalize_text(marker) for marker in OFFICIAL_STRONG_MARKERS}
    }
    if len(strong_hits) >= 2:
        return "сильные"
    if strong_hits or len(unique_hits) >= 3:
        return "средние"
    return "слабые"


def _service_tokens(service_name: str) -> list[str]:
    tokens = [token for token in normalize_text(service_name).split() if token]
    return [
        token
        for token in tokens
        if len(token) >= 4 and token not in SERVICE_STOP_WORDS
    ]


def _service_specific_markers(markers: Iterable[str]) -> list[str]:
    commercial_tokens = {normalize_text(marker) for marker in DEFAULT_COMMERCIAL_MARKERS}
    noise_tokens = {normalize_text(marker) for marker in DEFAULT_NOISE_MARKERS}
    filtered: list[str] = []
    for marker in markers:
        normalized_marker = normalize_text(marker)
        if len(normalized_marker) < 4:
            continue
        if normalized_marker in commercial_tokens or normalized_marker in noise_tokens:
            continue
        filtered.append(marker)
    return _unique_preserve_order(filtered)


def _city_ordered_queries(term: str, city: str) -> list[str]:
    cleaned_term = term.strip()
    cleaned_city = city.strip()
    if not cleaned_term or not cleaned_city:
        return []
    return _unique_preserve_order(
        [
            f"{cleaned_term} {cleaned_city}".strip(),
            f"{cleaned_city} {cleaned_term}".strip(),
        ]
    )


def _unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_override_map(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, items in value.items():
        normalized_key = normalize_text(str(key))
        if not normalized_key or not isinstance(items, list):
            continue
        normalized_items = _unique_preserve_order(str(item).strip() for item in items if str(item).strip())
        if normalized_items:
            result[normalized_key] = normalized_items
    return result


def _matching_service_override_values(service_name: str, overrides: dict[str, list[str]]) -> list[str]:
    family_keys = {normalize_text(service_name)}
    for canonical, aliases in SERVICE_SYNONYM_GROUPS:
        normalized_family = [normalize_text(canonical), *[normalize_text(alias) for alias in aliases]]
        if normalize_text(service_name) in normalized_family:
            family_keys.update(normalized_family)
            break
    values: list[str] = []
    for key, override_values in overrides.items():
        if key in family_keys:
            values.extend(override_values)
    return _unique_preserve_order(values)
