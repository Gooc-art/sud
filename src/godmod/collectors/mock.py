from __future__ import annotations

from datetime import UTC, datetime, timedelta

from godmod.markers import extract_contacts
from godmod.models import AccountCandidate, PostRecord, SearchLogEntry, SearchRequest


class MockCollector:
    platform_name = "mock"

    def collect(self, request: SearchRequest) -> tuple[list[AccountCandidate], list[SearchLogEntry]]:
        accounts: list[AccountCandidate] = []
        log: list[SearchLogEntry] = []
        now = datetime.now(UTC)

        for service in request.services:
            for city in request.cities:
                for platform in request.platforms:
                    query = f"{service.name} {city}"
                    log.append(
                        SearchLogEntry(
                            city=city,
                            service=service.name,
                            platform=platform,
                            query=query,
                            source="mock",
                            discovery_mode="mock_data",
                        )
                    )
                    accounts.extend(self._build_accounts(service.name, city, platform, now))
        return accounts, log

    def _build_accounts(
        self,
        service: str,
        city: str,
        platform: str,
        now: datetime,
    ) -> list[AccountCandidate]:
        slug = f"{service}-{city}".replace(" ", "-").lower()
        if platform == "vk":
            main_url = f"https://vk.com/{slug}"
            backup_url = f"https://vk.com/{slug}-studio"
        elif platform == "telegram":
            main_url = f"https://t.me/{slug.replace('ё', 'e')}"
            backup_url = f"https://t.me/{slug.replace('ё', 'e')}_pro"
        else:
            main_url = f"https://www.google.com/maps/search/?api=1&query={slug}"
            backup_url = f"https://www.google.com/maps/search/?api=1&query={slug}-studio"

        active = AccountCandidate(
            service=service,
            city=city,
            platform=platform,
            account_name=f"{service.title()} {city} Studio",
            account_url=main_url,
            username_or_id=main_url.rsplit("/", 1)[-1],
            description=(
                f"{service.title()} в {city}. Прайс, запись в лс, отзывы клиентов, "
                "свободные окна, принимаю ежедневно. Телефон +7 (912) 555-00-11"
            ),
            followers=1250 if platform == "vk" else 980,
            posts=[
                PostRecord(
                    url=f"{main_url}/post1",
                    text=f"{service.title()} {city}: свободные окна на этой неделе, запись в лс, цена от 2500",
                    published_at=now - timedelta(days=3),
                    likes=42,
                    comments=8,
                    reposts=2,
                    views=730,
                ),
                PostRecord(
                    url=f"{main_url}/post2",
                    text=f"Отзывы клиентов и портфолио работ, {city}, запись по телефону +7 (912) 555-00-11",
                    published_at=now - timedelta(days=11),
                    likes=38,
                    comments=5,
                    reposts=1,
                    views=650,
                ),
                PostRecord(
                    url=f"{main_url}/post3",
                    text=f"Ищем мастера в команду, {city}, график сменный",
                    published_at=now - timedelta(days=19),
                    likes=30,
                    comments=3,
                    reposts=0,
                    views=580,
                ),
            ],
            search_queries=[f"{service} {city}"],
            discovery_sources=["mock"],
            discovery_modes=["mock_data"],
            api_city=city,
        )
        active.contacts = extract_contacts([active.description] + [post.text for post in active.posts])

        medium = AccountCandidate(
            service=service,
            city=city,
            platform=platform,
            account_name=f"{service.title()} {city} Pro",
            account_url=backup_url,
            username_or_id=backup_url.rsplit("/", 1)[-1],
            description=f"{service.title()} {city}. Портфолио и запись в сообщения.",
            followers=430 if platform == "vk" else 290,
            posts=[
                PostRecord(
                    url=f"{backup_url}/post1",
                    text=f"{service.title()} в {city}. Портфолио, запись в сообщения.",
                    published_at=now - timedelta(days=10),
                    likes=12,
                    comments=1,
                    reposts=0,
                    views=160,
                ),
                PostRecord(
                    url=f"{backup_url}/post2",
                    text=f"Работаю по {city} и району. Цена обсуждается в лс.",
                    published_at=now - timedelta(days=37),
                    likes=7,
                    comments=0,
                    reposts=0,
                    views=90,
                ),
            ],
            search_queries=[f"{service} {city}"],
            discovery_sources=["mock"],
            discovery_modes=["mock_data"],
            api_city=city,
        )
        medium.contacts = extract_contacts([medium.description] + [post.text for post in medium.posts])

        weak = AccountCandidate(
            service=service,
            city=city,
            platform=platform,
            account_name=f"Личный блог {service} {city}",
            account_url=f"{backup_url}-blog",
            username_or_id=f"{backup_url.rsplit('/', 1)[-1]}-blog",
            description=f"Личная страница, иногда пишу про {service}.",
            followers=115,
            posts=[
                PostRecord(
                    url=f"{backup_url}-blog/post1",
                    text="Сегодня был длинный день, устал.",
                    published_at=now - timedelta(days=45),
                    likes=2,
                    comments=0,
                    reposts=0,
                    views=25,
                )
            ],
            search_queries=[f"{service} {city}"],
            discovery_sources=["mock"],
            discovery_modes=["mock_data"],
            api_city=city,
        )
        weak.contacts = extract_contacts([weak.description] + [post.text for post in weak.posts])

        return [active, medium, weak]
