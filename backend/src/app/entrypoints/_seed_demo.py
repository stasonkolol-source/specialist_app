"""`cli seed-demo` (DEVELOPMENT_PLAN 2.8c, 5.1): демо-специалисты для dev и stage — профиль, прайс,
районы, портфолио, аватар и «доступен сегодня» — и демо-клиенты с опубликованными заявками,
созданные теми же use cases, что и в Mini App.

- Детерминированно: каждый специалист и клиент — из генератора `random.Random` с фиксированным
  seed и его номером, а узнаётся по Telegram ID из своего диапазона. Повторный запуск пропускает
  готовых (клиента — если заявки у него уже есть) и доделывает прерванных специалистов:
  количества не меняются.
- Модерация — «одобрить всё»: сид сам одобряет отправленный профиль и заявку через фасады
  specialists и jobs, а контейнер сида собран без подписки `moderation.auto_check` — в очереди
  модераторов демо-кейсов нет. Без подписок аналитики, уведомлений и атрибуции: демо-люди не
  портят воронки и не наполняют ленты. Обработка фото и проекции (поиск, 4.1) — остаются.
- Фото (`small`) — настоящие из кэша `backend/.cache/demo-media` (scripts/demo-media/fetch.py,
  `_seed_demo_media`): работы портфолио по категории, фото «проблем» к заявкам, рисованные
  аватары. Кэша нет — JPEG-заглушки цвета категории, без аватаров и фото заявок. Загрузка и
  обработка — обычные (кладёт сервер, обрабатывает worker-media). Без хранилища (S3 не
  настроен) — без фото.
- Отзывы (7.2) — только по выполненным сделкам: у специалиста `small` — история прошлых сделок
  с прошлыми клиентами (у популярных 10–40, у большинства 3–12, у новичков ни одной), каждая —
  заявка, отклик, выбор, «Работа выполнена» обеими сторонами и отзыв в прошлом (часы сида,
  `SeedClock`): на карточке месяцы отзывов разные. Часть отзывов — с ответом специалиста, у
  части специалистов — «отзывы до платформы» по ссылке-приглашению (7.6а). Сид сам одобряет
  отзывы и ответы и пересчитывает рейтинг.
- `lab` — объём лаборатории (research/07 §2.7): 50 000 специалистов, без фото и истории.
- Язык (`--lang`): по умолчанию все — русскоязычные жители Нови-Сада (`ru`); `sr` — все
  по-сербски, `mixed` — каждый второй. Имена, тексты, заявки, отклики и отзывы — на языке человека.
- `--replace` (только dev): сначала удалить прежних демо-людей обоих диапазонов обычным удалением
  аккаунта (`RequestDeletion` и `ProcessDeletions` сразу, без grace-периода): профиль, прайс,
  портфолио, заявки, отклики, чаты, сделки и отзывы удаляют подписчики UserDeleted в воркере,
  как у человека; их файлы сид снимает с показа сразу — иначе новые кадры тех же фото совпали
  бы со старыми (кейс «фейковое портфолио»). Новые демо-люди — с теми же Telegram ID: повторная
  регистрация после удаления не запрещена, а сигнал риска `reregistered_after_deletion`
  контейнер сида не пишет.
- На проде команда не работает.
"""

import io
import random
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Final, Literal
from uuid import UUID

from dishka import AsyncContainer, Provider, Scope, provide
from PIL import Image, ImageDraw

from app.entrypoints._seed_demo_content import (
    CATEGORIES,
    CATEGORY_REVIEWS,
    CLOSERS,
    FIRST_NAMES,
    INITIALS,
    JOBS,
    OPENERS,
    PRE_PLATFORM,
    REPLIES,
    RESPONSE_MESSAGES,
    RESPONSE_WHEN,
    REVIEW_TEXTS,
    DemoCategory,
    DemoJob,
    DemoService,
    Lang,
)
from app.entrypoints._seed_demo_media import CACHE, DemoMedia, MediaFile, PortfolioFrames, pick
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
from app.modules.identity.application.use_cases.process_deletions import (
    ProcessDeletions,
    ProcessDeletionsCommand,
)
from app.modules.identity.application.use_cases.request_deletion import (
    RequestDeletion,
    RequestDeletionCommand,
)
from app.modules.identity.application.use_cases.update_profile import (
    UpdateProfile,
    UpdateProfileCommand,
)
from app.modules.identity.domain.deletion import DeletionSource
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
from app.modules.jobs.domain.response import Offer, ResponseId, ResponsePriceType
from app.modules.jobs.errors import AlreadyRespondedError, JobFullError, OwnJobResponseError
from app.modules.media.application.ports import MediaQuery
from app.modules.media.application.use_cases.complete_upload import (
    CompleteUpload,
    CompleteUploadCommand,
)
from app.modules.media.application.use_cases.delete_media import DeleteMedia, DeleteMediaCommand
from app.modules.media.application.use_cases.start_upload import StartUpload, StartUploadCommand
from app.modules.media.domain.policy import MediaPurpose
from app.modules.media.errors import MediaNotFoundError
from app.modules.pricing.application.use_cases.add_service import AddService, AddServiceCommand
from app.modules.pricing.domain.service import PriceType
from app.modules.reviews.api import ReviewsApi
from app.modules.reviews.application.use_cases.create_review_invite import (
    CreateReviewInvite,
    CreateReviewInviteCommand,
)
from app.modules.reviews.application.use_cases.leave_invite_review import (
    LeaveInviteReview,
    LeaveInviteReviewCommand,
)
from app.modules.reviews.application.use_cases.leave_review import (
    LeaveReview,
    LeaveReviewCommand,
)
from app.modules.reviews.application.use_cases.recompute_rating import (
    RecomputeRating,
    RecomputeRatingCommand,
)
from app.modules.reviews.application.use_cases.reply_to_review import (
    ReplyToReview,
    ReplyToReviewCommand,
)
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
from app.modules.specialists.application.use_cases.set_profile_avatar import (
    SetProfileAvatar,
    SetProfileAvatarCommand,
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
from app.platform.kernel.clock import BUSINESS_TZ, Clock, SystemClock
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DealId, DistrictId, MediaId, UserId
from app.platform.kernel.principal import Platform
from app.platform.settings import Environment, Settings
from app.platform.storage.port import Bucket, StoragePort

DEMO_TELEGRAM_BASE: Final = 5_000_000_000_000_000
"""Telegram ID демо-пользователя — база плюс номер. У настоящих пользователей ID не длиннее 52
бит (< 4,6·10¹⁵): войти под демо-ID из Telegram нельзя, даже на общем stage."""
DEMO_CLIENT_BASE: Final = DEMO_TELEGRAM_BASE + 100_000_000
"""Telegram ID демо-клиента — база плюс номер: специалистов даже в `lab` меньше ста миллионов."""
DEMO_IDS: Final = (DEMO_TELEGRAM_BASE, DEMO_CLIENT_BASE + 100_000_000 - 1)
"""Telegram ID всех демо-людей, первый и последний: специалисты, затем клиенты (`--replace`)."""
SEED: Final = "sosed-demo-v1"
CITY: Final = "novi-sad"
PHOTO_SIZE: Final = (1200, 900)
AVAILABILITY_HOURS: Final = (17, 19, 20, 21, 22, 23)
NEWCOMERS: Final = 0.2
"""Доля специалистов без отзывов: только пришли на платформу."""
POPULAR: Final = 0.1
"""Доля популярных: у них 10–40 отзывов; у остальных — 3–12."""
HISTORY_DAYS: Final = 300
"""Прошлые сделки — за последние ~10 месяцев, самая свежая — не позже трёх дней назад."""
RATINGS: Final = ((5, 66), (4, 25), (3, 8), (2, 1))
"""Оценки отзывов и их веса: в основном 4–5, иногда 3."""

DemoLang = Literal["ru", "sr", "mixed"]
"""Язык демо-людей (`--lang`): все по-русски, все по-сербски или каждый второй."""


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
    past_clients: int = 0
    """Прошлые клиенты специалистов — авторы отзывов по прошлым сделкам (номера клиентов сразу
    после `clients`); 0 — без истории сделок и отзывов."""


SCALES: Final = {
    "small": Scale(60, photos=True, clients=20, past_clients=80),
    # лента 5.3: тысяча заявок для замера выдачи
    "lab": Scale(50_000, photos=False, clients=500, jobs_each=2),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class DemoSpecialist:
    """План одного демо-специалиста — чистая функция номера (`plan`)."""

    number: int
    lang: Lang
    female: bool
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
    """Заглушки портфолио без кэша фото: категория (тон) и подпись каждой работы."""
    portfolio: int
    """Сколько настоящих фото работ из кэша (3–8 у «Специалиста»)."""
    avatar: bool
    """Рисованный аватар из кэша; без него — инициалы, как у части настоящих людей."""
    available_hour: int | None
    reviews: int
    """Прошлых сделок с отзывом: у новичков 0, у большинства 3–12, у популярных 10–40."""
    pre_platform: int
    """«Отзывов до платформы» по ссылке-приглашению (7.6а)."""

    @property
    def telegram_id(self) -> int:
        return DEMO_TELEGRAM_BASE + self.number

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_initial}."


def plan(number: int, language: DemoLang = "ru") -> DemoSpecialist:
    """Демо-специалист номер `number`: тот же номер и язык — тот же человек при каждом запуске."""
    rng = random.Random(f"{SEED}:{number}")  # noqa: S311 — демо-данные, не криптография
    lang = _language(rng, language)
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
    first_name = rng.choice(FIRST_NAMES[(lang, female)])
    last_initial = rng.choice(INITIALS[lang])
    travel_radius_km = rng.choice((3, 5, 10)) if "at_client" in work_modes else None
    district_picks = tuple(rng.randrange(1_000_000) for _ in range(rng.randint(1, 4)))
    available_hour = rng.choice(AVAILABILITY_HOURS) if rng.random() < 0.4 else None
    # история — после всего прежнего: от неё не зависит, кто этот человек
    tier = rng.random()
    reviews = (
        0
        if tier < NEWCOMERS
        else rng.randint(10, 40)
        if tier >= 1 - POPULAR
        else rng.randint(3, 12)
    )
    pro = kind is ProfileKind.PRO
    return DemoSpecialist(
        number=number,
        lang=lang,
        female=female,
        first_name=first_name,
        last_initial=last_initial,
        kind=kind,
        categories=categories,
        headline=primary.headline[lang],
        about=about,
        languages=languages,
        work_modes=work_modes,
        travel_radius_km=travel_radius_km,
        district_picks=district_picks,
        services=tuple(services),
        photos=photos,
        portfolio=rng.randint(3, 8) if pro else 0,
        avatar=rng.random() < 0.85,
        available_hour=available_hour,
        reviews=reviews if pro else min(reviews, 4),
        pre_platform=rng.choice((0, 0, 0, 1, 2)) if pro else 0,
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


def client_plan(number: int, jobs_each: int | None = None, language: DemoLang = "ru") -> DemoClient:
    """Демо-клиент номер `number`: одна-две заявки (или `jobs_each`) на своём языке, каждая в
    своём районе. Заявки — по местам клиента в перемешанном списке (у номера n — места 2n и
    2n+1): у соседних клиентов они не совпадают, а в `small` не повторяются вовсе."""
    rng = random.Random(f"{SEED}:client:{number}")  # noqa: S311 — демо-данные, не криптография
    lang = _language(rng, language)
    female = rng.random() < 0.5
    slots = max(2, jobs_each or 0)
    first = number * slots
    count = jobs_each or rng.choice((1, 1, 2))
    jobs = tuple(JOBS[JOB_ORDER[(first + index) % len(JOBS)]] for index in range(count))
    return DemoClient(
        number=number,
        lang=lang,
        first_name=rng.choice(FIRST_NAMES[(lang, female)]),
        last_initial=rng.choice(INITIALS[lang]),
        jobs=jobs,
        district_picks=tuple(rng.randrange(1_000_000) for _ in jobs),
    )


JOB_ORDER: Final = tuple(
    random.Random(f"{SEED}:jobs").sample(range(len(JOBS)), len(JOBS))  # noqa: S311 — демо
)
"""Заявки в перемешанном порядке: по ним клиенты разбирают свои места (`client_plan`)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PastDeal:
    """Прошлая сделка специалиста с отзывом клиента — чистая функция (`history`)."""

    client: int
    """Номер прошлого клиента (демо-клиент из `Scale.past_clients`)."""
    job: DemoJob
    at: datetime
    """Когда клиент создал заявку; дальше — отклик, выбор, завершение и отзыв по порядку."""
    rating: int
    body: str | None
    """Текст на языке клиента; None — только оценка."""
    reply: str | None
    """Ответ специалиста на его языке; None — без ответа."""
    criteria: dict[str, int] = field(default_factory=dict)


def history(
    demo: DemoSpecialist, clients: range, now: datetime, language: DemoLang = "ru"
) -> tuple[PastDeal, ...]:
    """Прошлые сделки демо-специалиста по его категориям — старые первыми, за ~10 месяцев до
    `now`; клиенты — из `clients` (у кого-то и по второму разу: постоянные клиенты)."""
    if not clients or not demo.reviews:
        return ()
    rng = random.Random(f"{SEED}:history:{demo.number}")  # noqa: S311 — демо-данные
    slugs = {category.slug for category in demo.categories}
    jobs = [job for job in JOBS if job.category in slugs] or list(JOBS)
    days = sorted((rng.uniform(3, HISTORY_DAYS) for _ in range(demo.reviews)), reverse=True)
    deals = []
    for days_ago in days:
        number = rng.choice(clients)
        lang = client_plan(number, language=language).lang
        job = rng.choice(jobs)
        rating = rng.choices([r for r, _ in RATINGS], weights=[w for _, w in RATINGS])[0]
        body = review_text(rng, lang, rating, job.category) if rng.random() < 0.85 else None
        reply = (
            rng.choice(REPLIES[demo.lang][rating == 5]) if body and rng.random() < 0.35 else None
        )
        criteria = {
            name: max(1, min(5, rating + rng.choice((0, 0, 0, -1, 1))))
            for name in ("quality", "punctuality", "communication", "price")
            if rng.random() < 0.7
        }
        moment = now - timedelta(days=days_ago, minutes=rng.randint(0, 600))
        deals.append(
            PastDeal(
                client=number,
                job=job,
                at=moment,
                rating=rating,
                body=body,
                reply=reply,
                criteria=criteria,
            )
        )
    return tuple(deals)


def review_text(rng: random.Random, lang: Lang, rating: int, category: str) -> str:
    """Текст отзыва: по-русски на 4–5 — чаще о конкретной работе категории, иначе общий."""
    specific = CATEGORY_REVIEWS.get(category, {}).get(rating) if lang == "ru" else None
    if specific and rng.random() < 0.75:
        return rng.choice(specific)
    return rng.choice(REVIEW_TEXTS[lang][rating])


def _language(rng: random.Random, language: DemoLang) -> Lang:
    """Язык человека. Жребий тянется и при заданном языке: всё, что план вытягивает до
    языка-зависимых текстов (у специалиста — категории и вид профиля), от `--lang` не зависит."""
    coin = rng.random()
    if language == "mixed":
        return "ru" if coin < 0.5 else "sr"
    return language


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
    """seed-demo на проде (и `--replace` вне dev): демо-данные там недопустимы."""


class SeedClock:
    """Часы контейнера сида: настоящие, пока `at` не перенёс use cases в прошлое — история
    сделок и отзывов получает свои даты, как если бы всё было тогда."""

    def __init__(self) -> None:
        self._moment: datetime | None = None
        self._system = SystemClock()

    def now(self) -> datetime:
        return self._moment if self._moment is not None else self._system.now()

    @contextmanager
    def at(self, moment: datetime) -> Iterator[None]:
        self._moment = moment
        try:
            yield
        finally:
            self._moment = None


class _SeedClockProvider(Provider):
    """Clock контейнера сида — `SeedClock` (поверх SystemClock платформы)."""

    def __init__(self, clock: SeedClock) -> None:
        super().__init__(scope=Scope.APP)
        self._clock = clock

    @provide
    def clock(self) -> Clock:
        return self._clock


@dataclass(slots=True)
class SeedReport:
    removed: int = 0
    """Прежних демо-людей удалено (`--replace`)."""
    held: int = 0
    """Не удалены: о них открыт кейс модерации — удаление ждёт решения, как у людей."""
    created: int = 0
    skipped: int = 0
    photos: int = 0
    avatars: int = 0
    jobs: int = 0
    """Заявок демо-клиентов создано в этот запуск."""
    job_photos: int = 0
    responses: int = 0
    """Откликов демо-специалистов на эти заявки (5.4)."""
    deals: int = 0
    """Сделок по этим заявкам: клиент выбрал первый отклик (6.1a)."""
    completed: int = 0
    """Из них завершённых: «Работа выполнена» от обеих сторон."""
    past_deals: int = 0
    """Прошлых сделок специалистов — каждая с отзывом."""
    reviews: int = 0
    """Опубликованных отзывов по сделкам: прошлым и завершённым сейчас."""
    replies: int = 0
    pre_platform: int = 0


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
        self,
        container: AsyncContainer,
        *,
        photos: bool,
        echo: Callable[[str], None],
        language: DemoLang = "ru",
        clock: SeedClock,
        media: DemoMedia | None = None,
    ) -> None:
        """`clock` — тот же, что отдаёт контейнер (`_SeedClockProvider`): им история уходит в
        прошлое."""
        self._container, self._photos, self._echo = container, photos, echo
        self._language = language
        self._media = media if photos else None
        self._clock = clock
        self._frames = PortfolioFrames()
        self._avatars_taken: set[str] = set()
        self._past_users: dict[int, UserId] = {}
        self._report = SeedReport()

    async def run(self, scale: Scale) -> SeedReport:
        world = await self._world()
        report = self._report
        photos = scale.photos and self._photos
        past = range(scale.start + scale.clients, scale.start + scale.clients + scale.past_clients)
        for done, number in enumerate(range(scale.start, scale.start + scale.specialists), 1):
            specialist = plan(number, self._language)
            created, added = await self._specialist(specialist, world, photos=photos)
            report.created += created
            report.skipped += not created
            report.photos += added
            if created and past:
                await self._history(specialist, world, past)
            if done % 500 == 0:
                self._echo(f"seed-demo: {done}/{scale.specialists}")
        performers = range(scale.start, scale.start + scale.specialists)
        for number in range(scale.start, scale.start + scale.clients):
            demo = client_plan(number, scale.jobs_each, self._language)
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
                    await self._deal(job_id, job, demo, complete=complete)
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
            works = await self._portfolio(request, user_id, demo) if photos and fresh else []
            if photos and fresh:
                self._report.avatars += await self._avatar(request, user_id, demo)
            await (await request.get(SubmitProfile))(SubmitProfileCommand(actor_id=user_id))
            profile = await specialists.profile_of(user_id)
            if profile is None:
                raise RuntimeError(f"demo profile {demo.number} vanished")
            uow = await request.get(UnitOfWork)
            async with uow:
                await specialists.approve_profile(profile.id, version=None)
                for work_id in works:  # работы ждут проверки (6.7) — сид одобряет и их
                    await specialists.approve_work(work_id)
            await self._availability(request, user_id, demo)
        return True, len(works)

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
            for index, (job, pick_) in enumerate(zip(demo.jobs, demo.district_picks, strict=True)):
                district = world.districts[pick_ % len(world.districts)]
                media_ids = await self._job_photos(
                    request, user_id, job, seed=f"{demo.number}:{index}"
                )
                job_id = await create(
                    CreateJobCommand(
                        actor_id=user_id,
                        trust_level=0,
                        draft=_draft(job, demo.lang, world, district, media_ids),
                    )
                )
                async with uow:
                    await jobs.approve_job(job_id, version=None)
                created.append((job_id, job))
        return created

    async def _job_photos(
        self, request: AsyncContainer, user_id: UserId, job: DemoJob, *, seed: str
    ) -> tuple[MediaId, ...]:
        """Ноль–три фото «проблемы» к заявке из кэша: то, что на фото, — о чём заявка."""
        pool = (
            self._media.jobs.get((job.category, job.photos)) if self._media and job.photos else None
        )
        if not pool:
            return ()
        rng = random.Random(f"{SEED}:job-photos:{seed}")  # noqa: S311 — демо-данные
        count = rng.choices((0, 1, 2, 3), weights=(25, 35, 25, 15))[0]
        files = pick(pool, count, rng.randrange(len(pool)))
        media_ids = tuple(
            [
                await self._upload(
                    request, user_id, MediaPurpose.JOB, item.path.read_bytes(), item.mime
                )
                for item in files
            ]
        )
        self._report.job_photos += len(media_ids)
        return media_ids

    async def _responses(
        self,
        job_id: JobId,
        job: DemoJob,
        client: DemoClient,
        performers: range,
        *,
        seed: int,
    ) -> int:
        """Ноль–пять откликов демо-специалистов на заявку (5.4), сразу прошедшие проверку:
        экраны откликов на стенде не пустые, у части заявок — ни одного. Цена — около бюджета."""
        if not performers:
            return 0
        rng = random.Random(f"{SEED}:responses:{seed}")  # noqa: S311 — демо-данные
        count = 0
        wanted = rng.choice((0, 0, 1, 1, 2, 3, 3, 4, 5))
        for number in rng.sample(performers, k=min(wanted, len(performers))):
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

    async def _deal(
        self, job_id: JobId, job: DemoJob, client: DemoClient, *, complete: bool
    ) -> None:
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
        rng = random.Random(f"{SEED}:review:{client.number}:{job_id}")  # noqa: S311 — демо
        rating = rng.choices([r for r, _ in RATINGS], weights=[w for _, w in RATINGS])[0]
        body = review_text(rng, client.lang, rating, job.category) if rng.random() < 0.8 else None
        criteria = {
            name: max(1, min(5, rating + rng.choice((0, 0, 0, -1, 1))))
            for name in ("quality", "punctuality", "communication", "price")
            if rng.random() < 0.7
        }
        _, profile_id = await self._review(
            accepted.deal_id, owner.id, rating=rating, body=body, criteria=criteria
        )
        if profile_id is not None:
            await self._recompute(profile_id)

    async def _review(
        self,
        deal_id: DealId,
        client_id: UserId,
        *,
        rating: int,
        body: str | None,
        criteria: dict[str, int],
    ) -> tuple[UUID, UUID | None]:
        """Клиент оценивает выполненную сделку (7.2): сид сам одобряет отзыв (без очереди
        модерации). (отзыв, профиль, о ком он — его рейтинг пересчитать: `_recompute`)."""
        async with self._container() as request:
            review = await (await request.get(LeaveReview))(
                LeaveReviewCommand(
                    actor_id=client_id, deal_id=deal_id, rating=rating, criteria=criteria, body=body
                )
            )
        async with self._container() as request:
            uow, reviews = await request.get(UnitOfWork), await request.get(ReviewsApi)
            async with uow:
                await reviews.approve_review(review.id)
        self._report.reviews += 1
        return review.id, review.subject_profile_id

    async def _recompute(self, profile_id: UUID) -> None:
        """Рейтинг профиля по опубликованным отзывам — карточка и выдача сразу с оценкой."""
        async with self._container() as request:
            await (await request.get(RecomputeRating))(
                RecomputeRatingCommand(profile_id=profile_id)
            )

    async def _history(self, demo: DemoSpecialist, world: _World, clients: range) -> None:
        """Прошлые сделки специалиста с отзывами и ответами, затем «отзывы до платформы» —
        всё в прошлом по часам сида; рейтинг — один пересчёт в конце."""
        async with self._container() as request:
            performer = await (await request.get(IdentityQuery)).by_telegram(demo.telegram_id)
        if performer is None:
            return
        now = self._clock.now()
        profile_id = None
        for past in history(demo, clients, now, self._language):
            profile_id = await self._past_deal(demo, performer.id, past, world) or profile_id
        if profile_id is not None:
            await self._recompute(profile_id)
        await self._pre_platform(demo, performer.id, world, clients, now)

    async def _past_deal(
        self, demo: DemoSpecialist, performer_id: UserId, past: PastDeal, world: _World
    ) -> UUID | None:
        """Одна прошлая сделка: заявка → отклик через часы → выбор → «Работа выполнена» через
        дни → отзыв → иногда ответ. Каждый шаг — use case в своё время по часам сида."""
        rng = random.Random(f"{SEED}:past:{demo.number}:{past.at.isoformat()}")  # noqa: S311
        client = client_plan(past.client, language=self._language)
        client_id = await self._past_client(client, world, at=past.at)
        district = world.districts[rng.randrange(len(world.districts))]
        moment = past.at
        with self._clock.at(moment):
            async with self._container() as request:
                job_id = await (await request.get(CreateJob))(
                    CreateJobCommand(
                        actor_id=client_id,
                        trust_level=TRUSTED_LEVEL,  # история не упирается в лимит новичка
                        draft=_draft(past.job, client.lang, world, district, ()),
                    )
                )
                jobs, uow = await request.get(JobsApi), await request.get(UnitOfWork)
                async with uow:
                    await jobs.approve_job(job_id, version=None)
        moment += timedelta(minutes=rng.randint(10, 360))
        with self._clock.at(moment):
            response_id = await self._past_response(
                performer_id, job_id, past.job, client.lang, rng
            )
        moment += timedelta(minutes=rng.randint(20, 600))
        with self._clock.at(moment):
            async with self._container() as request:
                accepted = await (await request.get(AcceptResponse))(
                    AcceptResponseCommand(actor_id=client_id, response_id=response_id)
                )
        moment += timedelta(hours=rng.randint(4, 96))
        for actor in (performer_id, client_id):
            with self._clock.at(moment):
                async with self._container() as request:
                    await (await request.get(CompleteDeal))(
                        CompleteDealCommand(actor_id=actor, deal_id=accepted.deal_id)
                    )
            moment += timedelta(minutes=rng.randint(5, 240))
        with self._clock.at(moment + timedelta(hours=rng.randint(1, 60))):
            review_id, profile_id = await self._review(
                accepted.deal_id,
                client_id,
                rating=past.rating,
                body=past.body,
                criteria=past.criteria,
            )
            self._report.past_deals += 1
            if past.reply is not None:
                await self._reply(performer_id, review_id, past.reply)
        return profile_id

    async def _past_response(
        self,
        performer_id: UserId,
        job_id: JobId,
        job: DemoJob,
        lang: Lang,
        rng: random.Random,
    ) -> ResponseId:
        async with self._container() as request:
            _, response_id = await (await request.get(Respond))(
                RespondCommand(
                    actor_id=performer_id,
                    trust_level=TRUSTED_LEVEL,
                    job_id=job_id,
                    offer=_offer(job, lang, rng),
                )
            )
            jobs, uow = await request.get(JobsApi), await request.get(UnitOfWork)
            async with uow:
                await jobs.approve_response(response_id, version=None)
        return response_id

    async def _reply(self, performer_id: UserId, review_id: UUID, body: str) -> None:
        """Публичный ответ специалиста на отзыв (S28); проверку сид одобряет сам."""
        async with self._container() as request:
            await (await request.get(ReplyToReview))(
                ReplyToReviewCommand(actor_id=performer_id, review_id=review_id, body=body)
            )
        async with self._container() as request:
            uow, reviews = await request.get(UnitOfWork), await request.get(ReviewsApi)
            async with uow:
                await reviews.approve_reply(review_id)
        self._report.replies += 1

    async def _past_client(self, client: DemoClient, world: _World, *, at: datetime) -> UserId:
        """Аккаунт прошлого клиента: зарегистрирован тогда же, когда впервые понадобился."""
        known = self._past_users.get(client.number)
        if known is not None:
            return known
        with self._clock.at(at - timedelta(days=1)):
            async with self._container() as request:
                existing = await (await request.get(IdentityQuery)).by_telegram(client.telegram_id)
                user_id = (
                    existing.id
                    if existing is not None
                    else await self._sign_up(
                        request,
                        TelegramProfile(
                            id=client.telegram_id,
                            first_name=client.first_name,
                            last_name=f"{client.last_initial}.",
                            language_code=client.lang,
                        ),
                        UserIntent.CLIENT,
                        world,
                    )
                )
        self._past_users[client.number] = user_id
        return user_id

    async def _pre_platform(
        self,
        demo: DemoSpecialist,
        performer_id: UserId,
        world: _World,
        clients: range,
        now: datetime,
    ) -> None:
        """«Отзывы до платформы» (7.6а): специалист шлёт ссылку прошлому клиенту, тот оценивает
        прежнюю работу. В рейтинг они не входят; сид одобряет их сам (модерация обязательна)."""
        rng = random.Random(f"{SEED}:pre-platform:{demo.number}")  # noqa: S311 — демо-данные
        numbers = rng.sample(clients, k=min(demo.pre_platform, len(clients)))
        for number in numbers:
            client = client_plan(number, language=self._language)
            moment = now - timedelta(days=rng.uniform(HISTORY_DAYS, HISTORY_DAYS + 60))
            client_id = await self._past_client(client, world, at=moment)
            service = rng.choice([s for _, s in demo.services] or [demo.categories[0].services[0]])
            with self._clock.at(moment):
                async with self._container() as request:
                    invite = await (await request.get(CreateReviewInvite))(
                        CreateReviewInviteCommand(
                            actor_id=performer_id, client_name=client.first_name
                        )
                    )
                async with self._container() as request:
                    review = await (await request.get(LeaveInviteReview))(
                        LeaveInviteReviewCommand(
                            actor_id=client_id,
                            token=invite.token,
                            rating=rng.choice((5, 5, 5, 4)),
                            work_title=service.title[client.lang],
                            body=rng.choice(PRE_PLATFORM[client.lang]),
                        )
                    )
                async with self._container() as request:
                    uow, reviews = await request.get(UnitOfWork), await request.get(ReviewsApi)
                    async with uow:
                        await reviews.approve_review(review.id)
            self._report.pre_platform += 1

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
                world.districts[pick_ % len(world.districts)] for pick_ in demo.district_picks
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
    ) -> list[UUID]:
        """Работы — их id: настоящие фото категории из кэша (каждый показ фото — свой кадр,
        `PortfolioFrames`), без кэша — заглушки."""
        add = await request.get(AddPortfolioWork)
        works: list[UUID] = []
        for body, caption in self._works(demo):
            media_id = await self._upload(
                request, user_id, MediaPurpose.PORTFOLIO, body, "image/jpeg"
            )
            work = await add(
                AddPortfolioWorkCommand(actor_id=user_id, media_id=media_id, caption=caption)
            )
            works.append(work.id)
        return works

    def _works(self, demo: DemoSpecialist) -> Iterator[tuple[bytes, str]]:
        """(JPEG, подпись) работ специалиста: из кэша — у «Специалиста» 3–8 фото категории,
        у разных специалистов разные; кэша категории нет — заглушки по плану."""
        pool = self._media.portfolio.get(demo.categories[0].slug) if self._media else None
        if not pool:
            for index, (category, caption) in enumerate(demo.photos):
                yield placeholder_photo(category.color, demo.number * 10 + index), caption
            return
        rng = random.Random(f"{SEED}:portfolio:{demo.number}")  # noqa: S311 — демо-данные
        for item in pick(pool, demo.portfolio, rng.randrange(len(pool))):
            body = self._frames.unique_variant(item.path)
            if body is not None and item.caption is not None:
                yield body, item.caption[demo.lang]

    async def _avatar(self, request: AsyncContainer, user_id: UserId, demo: DemoSpecialist) -> int:
        """Рисованный аватар по полу — у каждого свой, пока хватает; 1 — поставлен."""
        pool = self._media.avatars.get("f" if demo.female else "m") if self._media else None
        if not pool or not demo.avatar:
            return 0
        rng = random.Random(f"{SEED}:avatar:{demo.number}")  # noqa: S311 — демо-данные
        start = rng.randrange(len(pool))
        ordered = [pool[(start + index) % len(pool)] for index in range(len(pool))]
        item: MediaFile = next((a for a in ordered if a.id not in self._avatars_taken), ordered[0])
        self._avatars_taken.add(item.id)
        media_id = await self._upload(
            request, user_id, MediaPurpose.AVATAR, item.path.read_bytes(), item.mime
        )
        await (await request.get(SetProfileAvatar))(
            SetProfileAvatarCommand(actor_id=user_id, media_id=media_id)
        )
        return 1

    async def _upload(
        self,
        request: AsyncContainer,
        user_id: UserId,
        purpose: MediaPurpose,
        body: bytes,
        mime_type: str,
    ) -> MediaId:
        """Файл пользователя через обычную загрузку media: старт, PUT в хранилище, завершение."""
        storage = await request.get(StoragePort)
        query = await request.get(MediaQuery)
        start, complete = await request.get(StartUpload), await request.get(CompleteUpload)
        upload = await start(
            StartUploadCommand(
                owner_id=user_id, purpose=purpose, mime_type=mime_type, size_bytes=len(body)
            )
        )
        media_id = MediaId(upload.media_id)
        asset = await query.asset(user_id, media_id)
        if asset is None:
            raise RuntimeError(f"demo upload {media_id} vanished")
        await storage.put(Bucket(asset.bucket), asset.object_key, body, content_type=mime_type)
        await complete(CompleteUploadCommand(owner_id=user_id, media_id=media_id))
        return media_id

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


async def remove_demo(container: AsyncContainer) -> tuple[int, int]:
    """Удалить всех демо-людей (`--replace`) обычным удалением аккаунта, но сразу: запрос, как
    из S45, и исполнение без grace-периода — только их запросов. Файлы удалённых сразу сняты с
    показа (`media.forget_owner` воркера сделал бы то же позже). (удалено, удержано)."""
    async with container() as request:
        users = await (await request.get(IdentityQuery)).telegram_range(*DEMO_IDS)
    for user_id in users:
        async with container() as request:
            await (await request.get(RequestDeletion))(
                RequestDeletionCommand(actor_id=user_id, source=DeletionSource.SUPPORT)
            )
    async with container() as request:
        report = await (await request.get(ProcessDeletions))(
            ProcessDeletionsCommand(expedite=tuple(users))
        )
        held = set(await (await request.get(IdentityQuery)).telegram_range(*DEMO_IDS))
    for user_id in users:
        if user_id not in held:
            await _discard_media(container, user_id)
    return report.deleted, report.held


async def _discard_media(container: AsyncContainer, user_id: UserId) -> None:
    """Файлы удалённого демо-аккаунта — удалить, как DELETE /media/{id} от владельца."""
    async with container() as request:
        media_ids = await (await request.get(MediaQuery)).owned_ids(user_id)
    for media_id in media_ids:
        async with container() as request:
            with suppress(MediaNotFoundError):
                await (await request.get(DeleteMedia))(
                    DeleteMediaCommand(owner_id=user_id, media_id=media_id)
                )


async def seed_demo(
    settings: Settings,
    scale: Scale,
    *,
    echo: Callable[[str], None],
    language: DemoLang = "ru",
    replace_existing: bool = False,
    media_root: Path | None = None,
) -> SeedReport:
    """Демо-специалисты и клиенты в базу окружения `settings`; на проде — SeedDemoRefusedError.
    `replace_existing` (только dev) — сначала удалить прежних демо-людей (`remove_demo`).
    `media_root` — кэш настоящих фото (по умолчанию backend/.cache/demo-media)."""
    if settings.app.env is Environment.PRODUCTION:
        raise SeedDemoRefusedError("seed-demo is for dev and stage only")
    if replace_existing and settings.app.env is not Environment.DEV:
        raise SeedDemoRefusedError("seed-demo --replace is for dev only")
    from app.entrypoints._wiring import build_event_registry, make_container

    removed = held = 0
    if replace_existing:
        # удаление — как у людей: полный реестр, подписчики UserDeleted всех модулей (воркер)
        container = make_container(settings)
        try:
            removed, held = await remove_demo(container)
        finally:
            await container.close()
        echo(
            f"seed-demo: {removed} demo accounts deleted ({held} held by an open moderation"
            " case); the worker removes their profiles, jobs, chats and reviews"
        )
    # «одобрить всё»: профили и заявки одобряет сид, автопроверка с кейсами в очереди не нужна;
    # повторная регистрация демо-ID после --replace — не сигнал риска
    registry = build_event_registry().without(
        "moderation.auto_check",
        "moderation.record_reregistration",
        "analytics.",
        "notifications.",
        "growth.",
    )
    clock = SeedClock()
    container = make_container(settings, _SeedClockProvider(clock), registry=registry)
    try:
        storage = settings.s3.endpoint_url is not None
        photos = scale.photos and storage
        if scale.photos and not photos:
            echo("seed-demo: S3 is not configured — portfolio photos are skipped")
        if scale.clients and not storage:  # заявка проверяет фото через media, а ему нужно S3
            echo("seed-demo: S3 is not configured — demo jobs are skipped")
            scale = replace(scale, clients=0)
        media = DemoMedia.load(media_root or CACHE) if photos else None
        if photos:
            echo(
                f"seed-demo: {media.size} real photos and avatars from {media_root or CACHE}"
                if media is not None
                else "seed-demo: no demo-media cache (scripts/demo-media/fetch.py) — placeholders"
            )
        seeder = DemoSeeder(
            container, photos=photos, echo=echo, language=language, media=media, clock=clock
        )
        report = await seeder.run(scale)
    finally:
        await container.close()
    report.removed, report.held = removed, held
    return report


def _draft(
    job: DemoJob, lang: Lang, world: _World, district: DistrictId, media_ids: tuple[MediaId, ...]
) -> JobDraft:
    return JobDraft(
        title=job.title[lang],
        description=job.description[lang],
        category_id=world.categories[job.category],
        urgency=Urgency(job.urgency),
        budget=_budget(job),
        city_id=world.city_id,
        content_lang=lang,
        district_id=district,
        point=world.centers[district],
        languages=(lang,),
        media_ids=media_ids,
    )


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
