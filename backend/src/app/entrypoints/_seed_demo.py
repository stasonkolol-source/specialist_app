"""`cli seed-demo` (DEVELOPMENT_PLAN 2.8c, 5.1): демо-специалисты для dev и stage — профиль, прайс,
районы, портфолио и «доступен сегодня» — и демо-клиенты с опубликованными заявками, созданные
теми же use cases, что и в Mini App.

- Детерминированно: каждый специалист и клиент — из генератора `random.Random` с фиксированным
  seed и его номером, а узнаётся по Telegram ID из своего диапазона. Повторный запуск пропускает
  готовых (клиента — если заявки у него уже есть) и доделывает прерванных специалистов:
  количества не меняются.
- Модерация — «одобрить всё»: сид сам одобряет отправленный профиль и заявку через фасады
  specialists и jobs, а контейнер сида собран без подписки `moderation.auto_check` — в очереди
  модераторов демо-кейсов нет. Без подписок аналитики, уведомлений и атрибуции: демо-люди не
  портят воронки и не наполняют ленты. Обработка фото и проекции (поиск, 4.1) — остаются.
- Фото работ (`small`) — JPEG-заглушки цвета категории: загрузка и обработка — обычные (кладёт
  сервер, обрабатывает worker-media). Без хранилища (S3 не настроен) — без фото.
- `lab` — объём лаборатории (research/07 §2.7): 50 000 специалистов, без фото.
- На проде команда не работает.
"""

import io
import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import time
from typing import Final

from dishka import AsyncContainer
from PIL import Image, ImageDraw

from app.entrypoints._seed_demo_content import (
    CATEGORIES,
    CLOSERS,
    FIRST_NAMES,
    INITIALS,
    JOBS,
    OPENERS,
    RESPONSE_MESSAGES,
    RESPONSE_WHEN,
    DemoCategory,
    DemoJob,
    DemoService,
    Lang,
)
from app.modules.catalog.application.ports import CatalogQuery
from app.modules.deals.application.use_cases.complete_deal import (
    CompleteDeal,
    CompleteDealCommand,
)
from app.modules.geo.application.ports import GeoQuery
from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.ports import IdentityQuery
from app.modules.identity.application.use_cases.accept_consents import (
    AcceptConsents,
    AcceptConsentsCommand,
)
from app.modules.identity.application.use_cases.authenticate_telegram import (
    AuthenticateTelegram,
    AuthenticateTelegramCommand,
)
from app.modules.identity.application.use_cases.update_profile import (
    UpdateProfile,
    UpdateProfileCommand,
)
from app.modules.identity.domain.user import UserIntent
from app.modules.jobs.api import JobsApi
from app.modules.jobs.application.content import JobDraft
from app.modules.jobs.application.ports import JobQueries
from app.modules.jobs.application.use_cases.accept_response import (
    AcceptResponse,
    AcceptResponseCommand,
)
from app.modules.jobs.application.use_cases.create_job import CreateJob, CreateJobCommand
from app.modules.jobs.application.use_cases.respond import TRUSTED_LEVEL, Respond, RespondCommand
from app.modules.jobs.domain.job import Budget, BudgetType, BudgetUnit, JobId, Urgency
from app.modules.jobs.domain.response import Offer, ResponsePriceType
from app.modules.jobs.errors import AlreadyRespondedError, JobFullError, OwnJobResponseError
from app.modules.media.application.ports import MediaQuery
from app.modules.media.application.use_cases.complete_upload import (
    CompleteUpload,
    CompleteUploadCommand,
)
from app.modules.media.application.use_cases.start_upload import StartUpload, StartUploadCommand
from app.modules.media.domain.policy import MediaPurpose
from app.modules.pricing.application.use_cases.add_service import AddService, AddServiceCommand
from app.modules.pricing.domain.service import PriceType
from app.modules.specialists.api import PriceList, SpecialistsApi
from app.modules.specialists.application.use_cases.add_portfolio_work import (
    AddPortfolioWork,
    AddPortfolioWorkCommand,
)
from app.modules.specialists.application.use_cases.create_profile import (
    CreateProfile,
    CreateProfileCommand,
)
from app.modules.specialists.application.use_cases.edit_profile import (
    EditProfile,
    EditProfileCommand,
)
from app.modules.specialists.application.use_cases.set_availability import (
    SetAvailability,
    SetAvailabilityCommand,
)
from app.modules.specialists.application.use_cases.set_profile_areas import (
    SetProfileAreas,
    SetProfileAreasCommand,
)
from app.modules.specialists.application.use_cases.set_profile_categories import (
    SetProfileCategories,
    SetProfileCategoriesCommand,
)
from app.modules.specialists.application.use_cases.submit_profile import (
    SubmitProfile,
    SubmitProfileCommand,
)
from app.modules.specialists.domain.profile import ProfileKind
from app.platform.config.port import LegalVersions
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import BUSINESS_TZ, Clock
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId
from app.platform.kernel.principal import Platform
from app.platform.settings import Environment, Settings
from app.platform.storage.port import Bucket, StoragePort

DEMO_TELEGRAM_BASE: Final = 5_000_000_000_000_000
"""Telegram ID демо-пользователя — база плюс номер. У настоящих пользователей ID не длиннее 52
бит (< 4,6·10¹⁵): войти под демо-ID из Telegram нельзя, даже на общем stage."""
DEMO_CLIENT_BASE: Final = DEMO_TELEGRAM_BASE + 100_000_000
"""Telegram ID демо-клиента — база плюс номер: специалистов даже в `lab` меньше ста миллионов."""
SEED: Final = "sosed-demo-v1"
CITY: Final = "novi-sad"
PHOTO_SIZE: Final = (1200, 900)
AVAILABILITY_HOURS: Final = (18, 20, 22)


@dataclass(frozen=True, slots=True)
class Scale:
    specialists: int
    photos: bool
    start: int = 0
    """Номер первого специалиста и клиента: тесты на общей базе берут свои номера."""
    clients: int = 0
    """Демо-клиенты с опубликованными заявками (5.1): лента и экраны заявок на стенде."""
    jobs_each: int | None = None
    """Заявок у каждого клиента; None — одна-две, как у людей."""


SCALES: Final = {
    "small": Scale(60, photos=True, clients=20),
    # лента 5.3: тысяча заявок для замера выдачи
    "lab": Scale(50_000, photos=False, clients=500, jobs_each=2),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class DemoSpecialist:
    """План одного демо-специалиста — чистая функция номера (`plan`)."""

    number: int
    lang: Lang
    first_name: str
    last_initial: str
    kind: ProfileKind
    categories: tuple[DemoCategory, ...]
    headline: str
    about: str
    languages: tuple[str, ...]
    work_modes: tuple[str, ...]
    travel_radius_km: int | None
    district_picks: tuple[int, ...]
    """Индексы районов города (по порядку id): сами id — из базы."""
    services: tuple[tuple[DemoCategory, DemoService], ...]
    photos: tuple[tuple[DemoCategory, str], ...]
    """Категория (тон заглушки) и подпись каждой работы."""
    available_hour: int | None

    @property
    def telegram_id(self) -> int:
        return DEMO_TELEGRAM_BASE + self.number

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_initial}."


def plan(number: int) -> DemoSpecialist:
    """Демо-специалист номер `number`: тот же номер — тот же человек при каждом запуске."""
    rng = random.Random(f"{SEED}:{number}")  # noqa: S311 — демо-данные, не криптография
    lang: Lang = "ru" if rng.random() < 0.5 else "sr"
    primary = rng.choice(CATEGORIES)
    female = rng.random() < primary.female_share
    group = [c for c in CATEGORIES if c.slug != primary.slug and _root(c) == _root(primary)]
    extra = rng.sample(group, k=min(len(group), rng.choice((0, 0, 1, 1, 2))))
    categories = (primary, *extra)
    kind = ProfileKind.PRO if rng.random() < 0.75 else ProfileKind.CASUAL
    since = rng.randint(2008, 2024)
    about = " ".join(
        (
            rng.choice(OPENERS[lang]).format(since=since) + ", " + primary.skill[lang] + ".",
            rng.choice(CLOSERS[lang]),
        )
    )
    others = {"ru": ["sr", "en", "uk"], "sr": ["en", "ru"]}[lang]
    languages = (lang, *[other for other in others if rng.random() < 0.3])
    mode = rng.random()
    work_modes = (
        ("at_client",)
        if mode < 0.7
        else ("at_own_place",)
        if mode < 0.85
        else ("at_client", "at_own_place")
    )
    services: list[tuple[DemoCategory, DemoService]] = []
    for category in categories:
        count = (
            rng.randint(2, len(category.services)) if kind is ProfileKind.PRO else rng.randint(0, 1)
        )
        services.extend((category, service) for service in rng.sample(category.services, k=count))
    if kind is ProfileKind.PRO and not services:
        services.append((primary, primary.services[0]))
    captions = list(primary.captions[lang])
    rng.shuffle(captions)
    photos = (
        tuple((primary, caption) for caption in captions[: rng.randint(0, 4)])
        if kind is ProfileKind.PRO
        else ()
    )
    return DemoSpecialist(
        number=number,
        lang=lang,
        first_name=rng.choice(FIRST_NAMES[(lang, female)]),
        last_initial=rng.choice(INITIALS[lang]),
        kind=kind,
        categories=categories,
        headline=primary.headline[lang],
        about=about,
        languages=languages,
        work_modes=work_modes,
        travel_radius_km=rng.choice((3, 5, 10)) if "at_client" in work_modes else None,
        district_picks=tuple(rng.randrange(1_000_000) for _ in range(rng.randint(1, 4))),
        services=tuple(services),
        photos=photos,
        available_hour=rng.choice(AVAILABILITY_HOURS) if rng.random() < 0.3 else None,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class DemoClient:
    """План демо-клиента — чистая функция номера (`client_plan`)."""

    number: int
    lang: Lang
    first_name: str
    last_initial: str
    jobs: tuple[DemoJob, ...]
    district_picks: tuple[int, ...]
    """Район каждой заявки — индекс среди районов города (по порядку id)."""

    @property
    def telegram_id(self) -> int:
        return DEMO_CLIENT_BASE + self.number


def client_plan(number: int, jobs_each: int | None = None) -> DemoClient:
    """Демо-клиент номер `number`: одна-две заявки (или `jobs_each`) на своём языке, каждая в
    своём районе."""
    rng = random.Random(f"{SEED}:client:{number}")  # noqa: S311 — демо-данные, не криптография
    lang: Lang = "ru" if rng.random() < 0.5 else "sr"
    female = rng.random() < 0.5
    jobs = tuple(rng.sample(JOBS, k=jobs_each or rng.choice((1, 1, 2))))
    return DemoClient(
        number=number,
        lang=lang,
        first_name=rng.choice(FIRST_NAMES[(lang, female)]),
        last_initial=rng.choice(INITIALS[lang]),
        jobs=jobs,
        district_picks=tuple(rng.randrange(1_000_000) for _ in jobs),
    )


def _root(category: DemoCategory) -> str:
    """Группа каталога: соседние листья одной группы — правдоподобный набор умений."""
    for root, slugs in ROOTS.items():
        if category.slug in slugs:
            return root
    return category.slug


ROOTS: Final = {
    "handyman": ("small-repairs", "furniture-assembly", "plumbing", "electrical"),
    "beauty": ("nails", "brows-and-lashes", "hair"),
    "cleaning": ("regular-cleaning", "deep-cleaning"),
    "moving": ("apartment-move", "movers"),
    "lessons": ("serbian-language", "foreign-languages"),
}


def placeholder_photo(color: tuple[int, int, int], number: int) -> bytes:
    """JPEG-заглушка работы: градиент цвета категории и пара фигур — у каждой своё."""
    rng = random.Random(f"{SEED}:photo:{number}")  # noqa: S311 — заглушка, не криптография
    width, height = PHOTO_SIZE
    image = Image.new("RGB", PHOTO_SIZE, color)
    draw = ImageDraw.Draw(image)
    for y in range(0, height, 6):
        shade = 0.75 + 0.35 * y / height
        draw.rectangle((0, y, width, y + 6), fill=tuple(min(255, int(c * shade)) for c in color))
    for _ in range(3):
        x, y = rng.randrange(width), rng.randrange(height)
        r = rng.randrange(80, 260)
        tone = tuple(min(255, c + rng.randrange(20, 60)) for c in color)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=tone)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=82)
    return out.getvalue()


class SeedDemoRefusedError(RuntimeError):
    """seed-demo на проде: демо-данные там недопустимы."""


@dataclass(slots=True)
class SeedReport:
    created: int = 0
    skipped: int = 0
    photos: int = 0
    jobs: int = 0
    """Заявок демо-клиентов создано в этот запуск."""
    responses: int = 0
    """Откликов демо-специалистов на эти заявки (5.4)."""
    deals: int = 0
    """Сделок по этим заявкам: клиент выбрал первый отклик (6.1a)."""
    completed: int = 0
    """Из них завершённых: «Работа выполнена» от обеих сторон."""


@dataclass(frozen=True, slots=True)
class _World:
    city_id: CityId
    districts: tuple[DistrictId, ...]
    centers: dict[DistrictId, GeoPoint]
    categories: dict[str, CategoryId]
    terms: str
    privacy: str


class DemoSeeder:
    def __init__(
        self, container: AsyncContainer, *, photos: bool, echo: Callable[[str], None]
    ) -> None:
        self._container, self._photos, self._echo = container, photos, echo

    async def run(self, scale: Scale) -> SeedReport:
        world = await self._world()
        report = SeedReport()
        photos = scale.photos and self._photos
        for done, number in enumerate(range(scale.start, scale.start + scale.specialists), 1):
            created, added = await self._specialist(plan(number), world, photos=photos)
            report.created += created
            report.skipped += not created
            report.photos += added
            if done % 500 == 0:
                self._echo(f"seed-demo: {done}/{scale.specialists}")
        performers = range(scale.start, scale.start + scale.specialists)
        for number in range(scale.start, scale.start + scale.clients):
            demo = client_plan(number, scale.jobs_each)
            made = await self._client(demo, world)
            report.jobs += len(made)
            for index, (job_id, job) in enumerate(made):
                responded = await self._responses(
                    job_id, job, demo, performers, seed=number * 10 + index
                )
                report.responses += responded
                # каждая третья заявка с откликами — «в работе», каждая шестая — уже выполнена
                if responded and (number + index) % 3 == 0:
                    complete = (number + index) % 6 == 0
                    await self._deal(job_id, demo, complete=complete)
                    report.deals += 1
                    report.completed += complete
        return report

    async def _world(self) -> _World:
        async with self._container() as request:
            geo = await request.get(GeoQuery)
            city = next((c for c in await geo.cities() if c.slug == CITY), None)
            if city is None:
                raise RuntimeError(f"city {CITY} is not seeded: run `make seed` first")
            districts = await geo.districts(city.id)
            neighborhoods = [d for d in districts if d.kind == "neighborhood"] or districts
            tree = await (await request.get(CatalogQuery)).tree()
            legal = await (await request.get(LegalVersions)).legal_versions()
        slugs = {node.slug: node.id for root in tree for node in (root, *root.children)}
        missing = [c.slug for c in CATEGORIES if c.slug not in slugs]
        if missing:
            raise RuntimeError(f"catalog has no {', '.join(missing)}: run `make seed` first")
        return _World(
            city_id=city.id,
            districts=tuple(sorted(d.id for d in neighborhoods)),
            centers={d.id: d.center for d in neighborhoods},
            categories=slugs,
            terms=legal["terms"],
            privacy=legal["privacy"],
        )

    async def _specialist(
        self, demo: DemoSpecialist, world: _World, *, photos: bool
    ) -> tuple[bool, int]:
        """(создан ли сейчас, сколько фото загружено)."""
        async with self._container() as request:
            existing = await (await request.get(IdentityQuery)).by_telegram(demo.telegram_id)
            specialists = await request.get(SpecialistsApi)
            draft = await specialists.profile_of(existing.id) if existing else None
            if draft is not None and draft.status != "draft":
                return False, 0
            # прерванный запуск доделывается: вход и согласия идемпотентны, профиль — уже есть
            intent = UserIntent.PRO if demo.kind is ProfileKind.PRO else UserIntent.CASUAL
            user_id = await self._sign_up(
                request,
                TelegramProfile(
                    id=demo.telegram_id,
                    first_name=demo.first_name,
                    last_name=f"{demo.last_initial}.",
                    language_code=demo.lang,
                ),
                intent,
                world,
            )
            await self._profile(request, user_id, demo, world)
            fresh = draft is None
            added = await self._portfolio(request, user_id, demo) if photos and fresh else 0
            await (await request.get(SubmitProfile))(SubmitProfileCommand(actor_id=user_id))
            profile = await specialists.profile_of(user_id)
            if profile is None:
                raise RuntimeError(f"demo profile {demo.number} vanished")
            uow = await request.get(UnitOfWork)
            async with uow:
                await specialists.approve_profile(profile.id, version=None)
            await self._availability(request, user_id, demo)
        return True, added

    async def _sign_up(
        self,
        request: AsyncContainer,
        profile: TelegramProfile,
        intent: UserIntent,
        world: _World,
    ) -> UserId:
        auth = await request.get(AuthenticateTelegram)
        result = await auth(AuthenticateTelegramCommand(profile=profile, platform=Platform.TMA))
        user_id = result.tokens.user_id
        await (await request.get(AcceptConsents))(
            AcceptConsentsCommand(
                actor_id=user_id,
                terms_version=world.terms,
                privacy_version=world.privacy,
                source=Platform.TMA,
            )
        )
        await (await request.get(UpdateProfile))(
            UpdateProfileCommand(actor_id=user_id, home_city_id=world.city_id, intent=intent)
        )
        return user_id

    async def _client(self, demo: DemoClient, world: _World) -> list[tuple[JobId, DemoJob]]:
        """Заявки, созданные сейчас; у клиента, у которого заявки уже есть, — ни одной."""
        async with self._container() as request:
            existing = await (await request.get(IdentityQuery)).by_telegram(demo.telegram_id)
            if existing is not None and await (await request.get(JobQueries)).own(
                existing.id, [], limit=1
            ):
                return []
            user_id = await self._sign_up(
                request,
                TelegramProfile(
                    id=demo.telegram_id,
                    first_name=demo.first_name,
                    last_name=f"{demo.last_initial}.",
                    language_code=demo.lang,
                ),
                UserIntent.CLIENT,
                world,
            )
            create, jobs = await request.get(CreateJob), await request.get(JobsApi)
            uow = await request.get(UnitOfWork)
            created: list[tuple[JobId, DemoJob]] = []
            for job, pick in zip(demo.jobs, demo.district_picks, strict=True):
                district = world.districts[pick % len(world.districts)]
                job_id = await create(
                    CreateJobCommand(
                        actor_id=user_id,
                        trust_level=0,
                        draft=JobDraft(
                            title=job.title[demo.lang],
                            description=job.description[demo.lang],
                            category_id=world.categories[job.category],
                            urgency=Urgency(job.urgency),
                            budget=_budget(job),
                            city_id=world.city_id,
                            content_lang=demo.lang,
                            district_id=district,
                            point=world.centers[district],
                            languages=(demo.lang,),
                        ),
                    )
                )
                async with uow:
                    await jobs.approve_job(job_id, version=None)
                created.append((job_id, job))
        return created

    async def _responses(
        self,
        job_id: JobId,
        job: DemoJob,
        client: DemoClient,
        performers: range,
        *,
        seed: int,
    ) -> int:
        """Ноль–три отклика демо-специалистов на заявку (5.4), сразу прошедшие проверку: экраны
        откликов на стенде не пустые. Цена — около бюджета заявки."""
        if not performers:
            return 0
        rng = random.Random(f"{SEED}:responses:{seed}")  # noqa: S311 — демо-данные
        count = 0
        for number in rng.sample(performers, k=min(rng.choice((0, 1, 2, 3)), len(performers))):
            async with self._container() as request:
                performer = await (await request.get(IdentityQuery)).by_telegram(
                    DEMO_TELEGRAM_BASE + number
                )
                if performer is None:
                    continue
                respond = await request.get(Respond)
                try:
                    _, response_id = await respond(
                        RespondCommand(
                            actor_id=performer.id,
                            trust_level=TRUSTED_LEVEL,
                            job_id=job_id,
                            offer=_offer(job, client.lang, rng),
                        )
                    )
                except JobFullError, AlreadyRespondedError, OwnJobResponseError:
                    continue
                jobs, uow = await request.get(JobsApi), await request.get(UnitOfWork)
                async with uow:
                    await jobs.approve_response(response_id, version=None)
            count += 1
        return count

    async def _deal(self, job_id: JobId, client: DemoClient, *, complete: bool) -> None:
        """Клиент выбирает первый отклик (6.1a); `complete` — обе стороны отметили «Работа
        выполнена». Заявка станет «завершена», когда воркер выполнит `jobs.complete_job`."""
        async with self._container() as request:
            owner = await (await request.get(IdentityQuery)).by_telegram(client.telegram_id)
            responses = await (await request.get(JobQueries)).job_responses(job_id)
            if owner is None or not responses:
                return
            chosen = responses[0]
            accepted = await (await request.get(AcceptResponse))(
                AcceptResponseCommand(actor_id=owner.id, response_id=chosen.id)
            )
        if not complete:
            return
        for actor in (owner.id, chosen.performer_id):
            async with self._container() as request:
                await (await request.get(CompleteDeal))(
                    CompleteDealCommand(actor_id=actor, deal_id=accepted.deal_id)
                )

    async def _profile(
        self, request: AsyncContainer, user_id: UserId, demo: DemoSpecialist, world: _World
    ) -> None:
        specialists = await request.get(SpecialistsApi)
        profile = await specialists.profile_of(user_id)
        if profile is None:
            await (await request.get(CreateProfile))(
                CreateProfileCommand(
                    actor_id=user_id,
                    kind=demo.kind,
                    city_id=world.city_id,
                    display_name=demo.display_name,
                )
            )
            profile = await specialists.profile_of(user_id)
            if profile is None:
                raise RuntimeError(f"demo profile {demo.number} was not created")
        await (await request.get(EditProfile))(
            EditProfileCommand(
                actor_id=user_id,
                headline=demo.headline,
                about=demo.about,
                languages=demo.languages,
                work_modes=demo.work_modes,
                travel_radius_km=demo.travel_radius_km,
            )
        )
        await (await request.get(SetProfileCategories))(
            SetProfileCategoriesCommand(
                actor_id=user_id,
                category_ids=[world.categories[c.slug] for c in demo.categories],
            )
        )
        districts = list(
            dict.fromkeys(
                world.districts[pick % len(world.districts)] for pick in demo.district_picks
            )
        )
        await (await request.get(SetProfileAreas))(
            SetProfileAreasCommand(actor_id=user_id, district_ids=districts)
        )
        if await (await request.get(PriceList)).has_items(profile.id):
            return  # прайс уже есть: прерванный запуск не плодит дубли
        add = await request.get(AddService)
        for category, service in demo.services:
            await add(
                AddServiceCommand(
                    actor_id=user_id,
                    title=service.title[demo.lang],
                    price_type=PriceType(service.price_type),
                    price_min=service.dinars * 100,
                    category_id=world.categories[category.slug],
                    unit=service.unit,
                    duration_min=service.duration_min,
                    description=service.description[demo.lang] if service.description else None,
                )
            )

    async def _portfolio(
        self, request: AsyncContainer, user_id: UserId, demo: DemoSpecialist
    ) -> int:
        storage = await request.get(StoragePort)
        query = await request.get(MediaQuery)
        start, complete = await request.get(StartUpload), await request.get(CompleteUpload)
        add = await request.get(AddPortfolioWork)
        for index, (category, caption) in enumerate(demo.photos):
            body = placeholder_photo(category.color, demo.number * 10 + index)
            upload = await start(
                StartUploadCommand(
                    owner_id=user_id,
                    purpose=MediaPurpose.PORTFOLIO,
                    mime_type="image/jpeg",
                    size_bytes=len(body),
                )
            )
            media_id = MediaId(upload.media_id)
            asset = await query.asset(user_id, media_id)
            if asset is None:
                raise RuntimeError(f"demo upload {media_id} vanished")
            await storage.put(
                Bucket(asset.bucket), asset.object_key, body, content_type="image/jpeg"
            )
            await complete(CompleteUploadCommand(owner_id=user_id, media_id=media_id))
            await add(AddPortfolioWorkCommand(actor_id=user_id, media_id=media_id, caption=caption))
        return len(demo.photos)

    async def _availability(
        self, request: AsyncContainer, user_id: UserId, demo: DemoSpecialist
    ) -> None:
        if demo.available_hour is None:
            return
        now = (await request.get(Clock)).now().astimezone(BUSINESS_TZ)
        if now.hour >= demo.available_hour:
            return  # срок уже прошёл сегодня — не включаем
        await (await request.get(SetAvailability))(
            SetAvailabilityCommand(actor_id=user_id, until=time(demo.available_hour))
        )


async def seed_demo(settings: Settings, scale: Scale, *, echo: Callable[[str], None]) -> SeedReport:
    """Демо-специалисты и клиенты в базу окружения `settings`; на проде — SeedDemoRefusedError."""
    if settings.app.env is Environment.PRODUCTION:
        raise SeedDemoRefusedError("seed-demo is for dev and stage only")
    from app.entrypoints._wiring import build_event_registry, make_container

    # «одобрить всё»: профили и заявки одобряет сид, автопроверка с кейсами в очереди не нужна
    registry = build_event_registry().without(
        "moderation.auto_check", "analytics.", "notifications.", "growth."
    )
    container = make_container(settings, registry=registry)
    try:
        storage = settings.s3.endpoint_url is not None
        photos = scale.photos and storage
        if scale.photos and not photos:
            echo("seed-demo: S3 is not configured — portfolio photos are skipped")
        if scale.clients and not storage:  # заявка проверяет фото через media, а ему нужно S3
            echo("seed-demo: S3 is not configured — demo jobs are skipped")
            scale = replace(scale, clients=0)
        return await DemoSeeder(container, photos=photos, echo=echo).run(scale)
    finally:
        await container.close()


def _offer(job: DemoJob, lang: Lang, rng: random.Random) -> Offer:
    """Отклик демо-специалиста: сообщение, «когда смогу» и цена около бюджета заявки."""
    base = job.dinars[0] if job.dinars else rng.choice((2000, 3000, 5000))
    amount = round(base * rng.choice((0.8, 1.0, 1.2)) / 100) * 100 * 100
    price = ResponsePriceType.FIXED if job.dinars else ResponsePriceType.FROM
    return Offer(
        message=rng.choice(RESPONSE_MESSAGES[lang]),
        price_type=price,
        price_amount=amount,
        availability_note=rng.choice(RESPONSE_WHEN[lang]),
    )


def _budget(job: DemoJob) -> Budget:
    amounts = [dinars * 100 for dinars in job.dinars]
    return Budget(
        type=BudgetType(job.budget_type),
        min=amounts[0] if amounts else None,
        max=amounts[1] if len(amounts) > 1 else None,
        unit=BudgetUnit(job.unit),
    )
