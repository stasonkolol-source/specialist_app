"""Контекст и отправка карточки кейса (DEVELOPMENT_PLAN 2.5b): CaseContextQuery на PostgreSQL —
жалобы и их тексты, жалобы на человека, обжалованное решение из своих таблиц, остальное — фейки
фасадов; PostCaseCard шлёт кейс о фото самим фото с подписью через записывающий отправитель,
скрытое фото — текстом, отвергнутое Bot API фото — тоже текстом. Контактов пользователя адаптер
не спрашивает вовсе (граница приватности)."""

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import timedelta
from typing import cast
from uuid import UUID

import pytest

from app.modules.catalog.api import CatalogApi
from app.modules.geo.api import DistrictSummary, GeoApi
from app.modules.jobs.api import ChatResponse, JobForReview, JobsApi
from app.modules.media.api import ImageForCheck, MediaApi
from app.modules.messaging.api import MessageForReview, MessagingApi
from app.modules.moderation.application.case_card import CAPTION_LIMIT, visible_length
from app.modules.moderation.application.use_cases.create_report import CreateReportCommand
from app.modules.moderation.application.use_cases.open_case import OpenCaseCommand
from app.modules.moderation.application.use_cases.post_case_card import (
    PostCaseCard,
    PostCaseCardCommand,
)
from app.modules.moderation.domain.cases import Case, CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.reports import ReportReason
from app.modules.moderation.infrastructure.case_context import (
    FacadeCaseContext,
    MediaCasePhotos,
)
from app.modules.moderation.infrastructure.chat import TelegramModeratorsChat
from app.modules.moderation.tests.fakes import FakeIdentity
from app.modules.reviews.api import PublicReview, ReviewForCheck, ReviewsApi
from app.modules.specialists.api import ProfileForIndex, ProfileRef, SpecialistsApi
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import CaseId, CategoryId, DistrictId, MediaId, UserId, new_id
from app.platform.kernel.localized import LocalizedText
from app.platform.telegram.port import LinkButton
from app.platform.testing.telegram import RecordingTelegramSender

from .conftest import Moderation

pytestmark = pytest.mark.integration

CHAT = -1_001_234_567_890
ADMIN = "https://admin.sosedi.example/admin"
PHOTO = b"RIFF-webp-md-variant"


class PrivateIdentity(FakeIdentity):
    """Контакты и Telegram пользователей карточке не нужны: спросил — тест упал."""

    async def telegram_contacts(self, user_ids: Collection[UserId]) -> dict[UserId, str]:
        raise AssertionError("карточка кейса не читает Telegram пользователей")

    async def telegram_chat_id(self, user_id: UserId) -> int | None:
        raise AssertionError("карточка кейса не читает Telegram пользователей")


@dataclass
class Facades:
    """Фасады модулей-владельцев для карточки: только то, что она спрашивает."""

    profiles: dict[UserId, ProfileRef] = field(default_factory=dict)
    jobs: dict[UUID, JobForReview] = field(default_factory=dict)
    images: dict[MediaId, bytes] = field(default_factory=dict)
    read_images: list[MediaId] = field(default_factory=list)

    async def profiles_of(self, user_ids: Collection[UserId]) -> dict[UserId, ProfileRef]:
        return {u: self.profiles[u] for u in user_ids if u in self.profiles}

    async def profiles_for_index(self, profile_ids: Collection[UUID]) -> list[ProfileForIndex]:
        return []

    async def job_for_review(self, job_id: UUID) -> JobForReview | None:
        return self.jobs.get(job_id)

    async def chat_response(self, response_id: UUID) -> ChatResponse | None:
        return None

    async def message_for_card(self, message_id: UUID) -> MessageForReview | None:
        return None

    async def review_for_check(self, review_id: UUID) -> ReviewForCheck | None:
        return None

    async def published_review(self, review_id: UUID) -> PublicReview | None:
        return None

    async def image_for_card(self, media_id: MediaId) -> ImageForCheck | None:
        self.read_images.append(media_id)
        body = self.images.get(media_id)
        return ImageForCheck(body=body, content_type="image/webp") if body else None

    async def labels(self, category_ids: Collection[CategoryId]) -> dict[CategoryId, LocalizedText]:
        return {}

    async def district(self, district_id: DistrictId) -> DistrictSummary | None:
        return None


@pytest.fixture
def facades() -> Facades:
    return Facades()


@pytest.fixture
def contexts(moderation: Moderation, facades: Facades) -> FacadeCaseContext:
    identity = PrivateIdentity(moderation.session, known=moderation.identity.known)
    return FacadeCaseContext(
        moderation.session,
        identity,
        cast(SpecialistsApi, facades),
        cast(JobsApi, facades),
        cast(MessagingApi, facades),
        cast(ReviewsApi, facades),
        MediaCasePhotos(cast(MediaApi, facades)),
        moderation.deals,
        cast(CatalogApi, facades),
        cast(GeoApi, facades),
    )


def post(
    moderation: Moderation, contexts: FacadeCaseContext, sender: RecordingTelegramSender
) -> PostCaseCard:
    chat = TelegramModeratorsChat(
        sender, Translator.load(), CHAT, clock=moderation.clock, admin_url=ADMIN
    )
    return PostCaseCard(moderation.uow, moderation.cases, contexts, chat)


async def stored(moderation: Moderation, case_id: CaseId) -> Case:
    case = await moderation.cases.get(case_id)
    assert case is not None
    return case


async def photo_case(moderation: Moderation, owner: UserId, *, hidden: bool) -> CaseId:
    media_id = MediaId(new_id())
    return await moderation.open(
        OpenCaseCommand(
            queue=Queue.SAFETY if hidden else Queue.PREMOD,
            entity_type=EntityType.MEDIA,
            entity_id=media_id,
            subject_id=owner,
            trigger=CaseTrigger.AUTO_FLAG,
            details={
                "event": f"image:{media_id}",
                "signals": ["image:sexual:0.91" if hidden else "image:violence:0.74"],
                "purpose": "portfolio",
                "hidden": hidden,
            },
            media_ids=(media_id,),
        )
    )


async def test_report_context_has_roles_comments_and_complaints(
    moderation: Moderation, contexts: FacadeCaseContext, facades: Facades
) -> None:
    reporter, author, other = (
        await moderation.user(),
        await moderation.user(),
        await moderation.user(),
    )
    facades.profiles[reporter] = ProfileRef(id=new_id(), kind="pro", status="published")
    moderation.deals.completed[author] = 4
    job = new_id()
    facades.jobs[job] = JobForReview(
        client_id=author,
        text="Покрасить стены\n\nПредоплата на карту",
        version=1,
        media_ids=(),
        risk_level=0,
        title="Покрасить стены",
        description="Предоплата на карту",
        budget_type="fixed",
        budget_min=500_000,
        budget_unit="work",
    )
    moderation.report_targets.authors[job] = author
    filed = await moderation.report(
        CreateReportCommand(
            reporter_id=reporter,
            target_type=EntityType.JOB,
            target_id=job,
            reason=ReportReason.FRAUD,
            comment="Просит предоплату до встречи",
        )
    )
    moderation.report_targets.authors[author] = author  # жалоба на сам аккаунт — ещё одна
    await moderation.report(
        CreateReportCommand(
            reporter_id=other,
            target_type=EntityType.USER,
            target_id=author,
            reason=ReportReason.SPAM,
        )
    )
    assert filed.report.case_id is not None
    case = await stored(moderation, filed.report.case_id)

    context = await contexts.context(case)

    assert context.subject.name == "Ana"
    assert (context.subject.role, context.subject.deals_done) == ("client", 4)
    assert (context.subject.complaints_open, context.subject.complaints_total) == (2, 2)
    [report] = context.reports
    assert (report.reason, report.reporter_role) == ("fraud", "pro")
    assert report.comment == "Просит предоплату до встречи"
    assert context.object.kind == "job"
    assert [f.name for f in context.object.fields] == ["title", "description"]
    assert context.object.budget is not None
    assert context.object.budget.low == 500_000
    assert context.photo is None


async def test_photo_case_is_sent_as_a_photo_with_the_card(
    moderation: Moderation, contexts: FacadeCaseContext, facades: Facades
) -> None:
    owner = await moderation.user()
    case_id = await photo_case(moderation, owner, hidden=False)
    case = await stored(moderation, case_id)
    facades.images[MediaId(case.entity_id)] = PHOTO
    sender = RecordingTelegramSender()

    assert await post(moderation, contexts, sender)(PostCaseCardCommand(case_id=case_id))

    assert sender.sent == []
    [photo] = sender.photos
    assert (photo.chat_id, photo.photo, photo.filename) == (CHAT, PHOTO, f"case-{case_id}.webp")
    assert photo.caption.startswith("<b>P2 · Премодерация</b> · фото: флаг автопроверки")
    assert "📄 <b>Фото в портфолио</b>" in photo.caption
    assert "фото: насилие 0.74" in photo.caption
    assert visible_length(photo.caption) <= CAPTION_LIMIT
    buttons = [b for line in photo.buttons for b in (line if isinstance(line, tuple) else (line,))]
    assert [b.text for b in buttons] == [
        "Одобрить",
        "Отклонить с причиной",
        "Эскалировать",
        "Открыть в админке",
    ]
    assert isinstance(buttons[-1], LinkButton)
    assert buttons[-1].url == f"{ADMIN}/decide-case?case_id={case_id}"


async def test_rejected_photo_falls_back_to_a_text_card(
    moderation: Moderation, contexts: FacadeCaseContext, facades: Facades
) -> None:
    case_id = await photo_case(moderation, await moderation.user(), hidden=False)
    facades.images[MediaId((await stored(moderation, case_id)).entity_id)] = PHOTO
    sender = RecordingTelegramSender(photo_rejected=True)

    assert await post(moderation, contexts, sender)(PostCaseCardCommand(case_id=case_id))

    assert sender.photos == []
    [card] = sender.sent
    assert "📄 <b>Фото в портфолио</b>" in card.text


async def test_hidden_photo_never_reaches_the_chat(
    moderation: Moderation, contexts: FacadeCaseContext, facades: Facades
) -> None:
    case_id = await photo_case(moderation, await moderation.user(), hidden=True)
    sender = RecordingTelegramSender()

    assert await post(moderation, contexts, sender)(PostCaseCardCommand(case_id=case_id))

    assert facades.read_images == []  # скрытое фото даже не читаем
    assert sender.photos == []
    [card] = sender.sent
    assert card.text.startswith("<b>P0 · Безопасность</b> · фото скрыто автоматически")
    assert "🔒 Фото скрыто автоматически — смотреть в админке" in card.text


async def test_appeal_context_names_the_decision(
    moderation: Moderation, contexts: FacadeCaseContext
) -> None:
    subject = await moderation.user()
    decision_id = await moderation.case(subject, entity_type=EntityType.USER, entity_id=subject)
    decision = await stored(moderation, decision_id)
    moderation.clock.advance(timedelta(minutes=5))
    async with moderation.uow:
        decision.decide(
            verdict=ModerationDecision.REJECTED,
            reason_code="spam_ad",
            policy_version="test",
            now=moderation.clock.now(),
            by=None,
        )
        await moderation.cases.save(decision)
    appeal = Case.open(
        queue=Queue.APPEALS,
        entity_type=EntityType.USER,
        entity_id=subject,
        subject_id=subject,
        trigger=CaseTrigger.APPEAL,
        now=moderation.clock.now(),
        details={"appeal_of": str(decision_id), "reason_code": "spam_ad"},
        appeal_of=decision_id,
    )

    context = await contexts.context(appeal)

    assert context.appeal is not None
    assert context.appeal.reason_code == "spam_ad"
    assert context.appeal.decided_at == moderation.clock.now()
