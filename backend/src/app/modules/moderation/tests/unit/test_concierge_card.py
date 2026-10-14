"""Карточка concierge (DEVELOPMENT_PLAN 7.1; аудит роста п. 1): заявка двадцать минут без
откликов — в чат модераторов, с категорией, районом, бюджетом, срочностью, «0 откликов за 20 мин»,
«разослано подписчикам: N» и ссылкой `j_`; закрытая, прямой запрос, с откликом и повторная
публикация — без карточки; название экранировано."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from app.modules.catalog.api import CatalogApi
from app.modules.geo.api import CitySummary, DistrictSummary, GeoApi
from app.modules.jobs.api import JobReach, JobsApi
from app.modules.moderation.application.concierge_card import quiet_job_buttons, quiet_job_text
from app.modules.moderation.application.dto import QuietJob
from app.modules.moderation.application.use_cases.post_concierge_card import (
    PostConciergeCard,
    PostConciergeCardCommand,
)
from app.modules.moderation.tasks import post_concierge_card
from app.platform.contracts.events.jobs import JobPublished
from app.platform.i18n.translator import Translator
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId, new_id
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param
from app.platform.telegram.port import LinkButton
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 14, 13, 20, tzinfo=UTC)  # 15:20 в Белграде
PUBLISHED = NOW - timedelta(minutes=20)
BOT = "sosedi_test_bot"
CATEGORY, CITY, DISTRICT = CategoryId(7), CityId(1), DistrictId(11)
JOB_ID = new_id()


def reach(**changes: object) -> JobReach:
    job = JobReach(
        client_id=UserId(new_id()),
        title="Повесить люстру <в спальне>",
        status="published",
        direct=False,
        category_id=CATEGORY,
        city_id=CITY,
        district_id=DISTRICT,
        budget_type="fixed",
        budget_min=500_000,
        budget_max=None,
        budget_unit="job",
        urgency="asap",
        preferred_from=None,
        preferred_to=None,
        published_at=PUBLISHED,
        expires_at=NOW + timedelta(days=1),
        notified_count=7,
        responses=0,
        pending_responses=0,
    )
    return replace(job, **changes)  # type: ignore[arg-type]


@dataclass
class Facades:
    """JobsApi, CatalogApi и GeoApi — только то, что читает карточка."""

    job: JobReach | None

    async def job_reach(self, job_id: UUID) -> JobReach | None:
        return self.job if job_id == JOB_ID else None

    async def labels(self, category_ids: object) -> dict[CategoryId, LocalizedText]:
        return {CATEGORY: LocalizedText({Locale.RU: "Мастер на час", Locale.SR_CYRL: "Мајстор"})}

    async def city(self, city_id: CityId) -> CitySummary | None:
        return CitySummary(
            id=CITY, slug="novi-sad", name=LocalizedText({Locale.RU: "Нови-Сад"}), is_active=True
        )

    async def districts(self, district_ids: object) -> dict[DistrictId, DistrictSummary]:
        district = DistrictSummary(
            id=DISTRICT,
            city_id=CITY,
            slug="liman-3",
            name=LocalizedText({Locale.RU: "Лиман"}),
            center=GeoPoint(lat=45.24, lon=19.84),
        )
        return {DISTRICT: district}


@dataclass
class Chat:
    enabled: bool = True
    posted: list[QuietJob] = field(default_factory=list)

    async def post_quiet_job(self, job: QuietJob) -> int | None:
        self.posted.append(job)
        return 1


def use_case(facades: Facades, chat: Chat) -> PostConciergeCard:
    return PostConciergeCard(
        cast(JobsApi, facades),
        cast(CatalogApi, facades),
        cast(GeoApi, facades),
        chat,  # type: ignore[arg-type]
        FakeClock(NOW),
    )


async def test_quiet_job_goes_to_the_chat_with_what_where_and_reach() -> None:
    chat = Chat()

    posted = await use_case(Facades(reach(pending_responses=1)), chat)(
        PostConciergeCardCommand(job_id=JOB_ID, published_at=PUBLISHED)
    )

    assert posted
    [job] = chat.posted
    assert (job.title, job.category, job.place) == (
        "Повесить люстру <в спальне>",
        "Мастер на час",
        "Лиман, Нови-Сад",
    )
    assert (job.waited, job.notified, job.pending) == (timedelta(minutes=20), 7, 1)


@pytest.mark.parametrize(
    "job",
    [
        None,
        reach(status="closed"),
        reach(status="pending_moderation"),
        reach(direct=True),
        reach(responses=1),
    ],
    ids=["deleted", "closed", "on-review", "direct", "responded"],
)
async def test_no_card_when_the_job_is_gone_or_answered(job: JobReach | None) -> None:
    chat = Chat()

    posted = await use_case(Facades(job), chat)(
        PostConciergeCardCommand(job_id=JOB_ID, published_at=PUBLISHED)
    )

    assert not posted
    assert chat.posted == []


async def test_no_card_without_the_moderators_chat() -> None:
    chat = Chat(enabled=False)

    await use_case(Facades(reach()), chat)(
        PostConciergeCardCommand(job_id=JOB_ID, published_at=PUBLISHED)
    )

    assert chat.posted == []


@dataclass
class Recorder:
    commands: list[PostConciergeCardCommand] = field(default_factory=list)

    async def __call__(self, cmd: PostConciergeCardCommand) -> bool:
        self.commands.append(cmd)
        return True


@pytest.mark.parametrize(
    ("republished", "direct", "posted"),
    [(False, False, 1), (True, False, 0), (False, True, 0)],
    ids=["first", "republished", "direct"],
)
async def test_only_the_first_public_publication_is_checked(
    republished: bool, direct: bool, posted: int
) -> None:
    """Одна карточка на заявку: правка, продление и отмена сделки повторно её не шлют."""
    recorder = Recorder()
    event = JobPublished(
        job_id=JOB_ID,
        client_id=UserId(new_id()),
        category_id=CATEGORY,
        city_id=CITY,
        urgency="asap",
        republished=republished,
        direct=direct,
        occurred_at=PUBLISHED,
    )

    await post_concierge_card(event, recorder)  # type: ignore[arg-type]

    assert len(recorder.commands) == posted
    if posted:
        assert recorder.commands[0].published_at == PUBLISHED


def quiet(**changes: object) -> QuietJob:
    job = QuietJob(
        job_id=JOB_ID,
        title="Повесить люстру <в спальне>",
        category="Мастер на час",
        place="Лиман, Нови-Сад",
        budget_type="fixed",
        budget_min=500_000,
        budget_max=None,
        budget_unit="job",
        urgency="today",
        preferred_from=datetime(2026, 10, 14, 16, 0, tzinfo=UTC),
        preferred_to=datetime(2026, 10, 14, 19, 0, tzinfo=UTC),
        waited=timedelta(minutes=20, seconds=40),
        notified=7,
        pending=0,
    )
    return replace(job, **changes)  # type: ignore[arg-type]


def test_card_text_names_the_job_and_its_silence() -> None:
    link = "https://t.me/sosedi_test_bot?startapp=" + encode_start_param(
        StartLink(type=LinkType.JOB, id=JOB_ID)
    )

    text = quiet_job_text(quiet(), Translator.load(), now=NOW, bot_username=BOT)

    assert text.splitlines() == [
        "⏳ <b>Заявка без откликов</b>",
        "📄 <b>Повесить люстру &lt;в спальне&gt;</b>",
        "Мастер на час · Лиман, Нови-Сад",
        "5\u00a0000 RSD · сегодня 18:00–21:00",
        "0 откликов за 20 мин · разослано подписчикам: 7",
        f"🔗 {link}",
    ]
    assert quiet_job_buttons(quiet(), Translator.load(), BOT) == (
        LinkButton(text="Открыть заявку", url=link),
    )
    urgent = quiet_job_text(quiet(urgency="asap"), Translator.load(), now=NOW, bot_username=BOT)
    assert urgent.splitlines()[3] == "5\u00a0000 RSD · срочно · сегодня 18:00–21:00"


def test_card_tells_about_responses_on_review_and_works_without_the_bot_name() -> None:
    text = quiet_job_text(
        quiet(pending=2, category=None, place=None, urgency="this_week", preferred_from=None),
        Translator.load(),
        now=NOW,
        bot_username=None,
    )

    lines = text.splitlines()
    assert lines[2] == "5\u00a0000 RSD · на этой неделе"
    assert lines[-1] == "0 откликов за 20 мин · разослано подписчикам: 7 · ждут проверки: 2"
    assert quiet_job_buttons(quiet(), Translator.load(), None) == ()
