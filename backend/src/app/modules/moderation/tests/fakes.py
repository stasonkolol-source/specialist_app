"""Фейки фасадов и портов для тестов moderation (ADR-0020 §11)."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.api import Action, RestrictionIn, TelegramUserView, UserSummary
from app.modules.moderation.application.ports import ModerationTarget, TargetContent
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.pipeline import Route
from app.modules.moderation.domain.rules import ContentRule, RuleSet
from app.platform.ai.port import (
    ContentKind,
    ModerationResult,
    PolicyLabel,
    PolicyVerdict,
    Unavailable,
)
from app.platform.kernel.ids import CaseId, RestrictionId, UserId, new_id
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Role

START = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)  # 10:00 в Белграде


@dataclass
class FakeIdentity:
    """IdentityApi: санкция — строка identity.restrictions (FK из moderation.sanctions)."""

    session: AsyncSession
    known: set[UserId] = field(default_factory=set)
    trust: dict[UserId, int] = field(default_factory=dict)
    staff: dict[UserId, frozenset[Role]] = field(default_factory=dict)
    restricted: list[RestrictionIn] = field(default_factory=list)
    violations: list[UserId] = field(default_factory=list)
    lifted: list[CaseId] = field(default_factory=list)

    async def get_user(self, user_id: UserId) -> UserSummary | None:
        if user_id not in self.known:
            return None
        return UserSummary(
            id=user_id,
            display_name="Ana",
            ui_locale=Locale.SR_LATN,
            trust_level=self.trust.get(user_id, 0),
            phone_verified=False,
            is_deleted=False,
            created_at=START,
        )

    async def users(self, user_ids: Collection[UserId]) -> dict[UserId, UserSummary]:
        found = {user_id: await self.get_user(user_id) for user_id in user_ids}
        return {user_id: user for user_id, user in found.items() if user is not None}

    async def telegram_contacts(self, user_ids: Collection[UserId]) -> dict[UserId, str]:
        return {}

    async def by_telegram(self, telegram_id: int) -> TelegramUserView | None:
        return None

    async def telegram_chat_id(self, user_id: UserId) -> int | None:
        return None

    async def ensure_allowed(self, user_id: UserId, action: Action) -> None:
        return None

    async def roles(self, user_id: UserId) -> frozenset[Role]:
        return self.staff.get(user_id, frozenset())

    async def restrict(self, data: RestrictionIn) -> RestrictionId:
        self.restricted.append(data)
        restriction_id = RestrictionId(new_id())
        await self.session.execute(
            text(
                "INSERT INTO identity.restrictions"
                " (id, user_id, kind, reason_code, source, case_id, ends_at)"
                " VALUES (:id, :user_id, :kind, :reason, 'moderation', :case_id, :ends_at)"
            ),
            {
                "id": restriction_id,
                "user_id": data.user_id,
                "kind": data.kind.value,
                "reason": data.reason_code,
                "case_id": data.case_id,
                "ends_at": data.ends_at,
            },
        )
        return restriction_id

    async def lift_case_restrictions(self, case_id: CaseId) -> int:
        self.lifted.append(case_id)
        return 0

    async def record_violation(self, user_id: UserId) -> None:
        self.violations.append(user_id)

    async def hidden_from_search(
        self, user_ids: Collection[UserId]
    ) -> dict[UserId, datetime | None]:
        raise NotImplementedError


@dataclass
class FakePolicy:
    current: str = "draft-1"

    async def version(self) -> str:
        return self.current


@dataclass
class FakeOverflows:
    days: dict[date, dict[UserId, Mapping[str, int]]] = field(default_factory=dict)

    async def by_user(self, day: date) -> Mapping[UserId, Mapping[str, int]]:
        return self.days.get(day, {})


@dataclass
class FakeTarget(ModerationTarget):
    """Цель конвейера на фейках (план 2.6): объекты и что с ними сделала модерация."""

    objects: dict[UUID, TargetContent] = field(default_factory=dict)
    published: list[tuple[UUID, int | None]] = field(default_factory=list)
    hidden: list[tuple[UUID, str]] = field(default_factory=list)

    def add(
        self,
        author_id: UserId,
        text: str,
        *,
        kind: ContentKind = ContentKind.JOB,
        always_review: bool = False,
        risk_level: int = 0,
        media_ids: tuple[UUID, ...] = (),
        visible: bool = False,
    ) -> UUID:
        entity_id = new_id()
        self.objects[entity_id] = TargetContent(
            author_id=author_id,
            kind=kind,
            text=text,
            media_ids=tuple(media_ids),  # type: ignore[arg-type]  # MediaId — NewType UUID
            version=1,
            always_review=always_review,
            risk_level=risk_level,
            visible=visible,
        )
        return entity_id

    async def content(self, entity_id: UUID) -> TargetContent | None:
        return self.objects.get(entity_id)

    async def publish(self, entity_id: UUID, *, version: int | None = None) -> None:
        self.published.append((entity_id, version))

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:
        self.hidden.append((entity_id, reason_code))


@dataclass
class FakeTargets:
    targets: dict[EntityType, ModerationTarget] = field(default_factory=dict)

    def get(self, entity_type: EntityType) -> ModerationTarget | None:
        return self.targets.get(entity_type)


@dataclass
class FakeMetrics:
    routes: list[tuple[EntityType, Route]] = field(default_factory=list)

    def observe(self, entity_type: EntityType, route: Route) -> None:
        self.routes.append((entity_type, route))


@dataclass
class FakeFlags:
    values: dict[str, object] = field(default_factory=dict)

    async def is_enabled(self, key: str) -> bool:
        return key in self.values

    async def value(self, key: str) -> object | None:
        return self.values.get(key)


@dataclass
class FakeRuleSource:
    rules: Sequence[ContentRule] = ()

    async def current(self) -> RuleSet:
        return RuleSet(self.rules)


class NoVelocity:
    async def add(self, key: str, member: str, *, window: timedelta) -> int | None:
        return None


@dataclass
class FakeModeration:
    """omni-moderation: ответ задаёт тест; по умолчанию — чисто."""

    result: ModerationResult | Unavailable = field(
        default_factory=lambda: ModerationResult(flagged=False)
    )
    texts: list[str] = field(default_factory=list)

    async def check_text(self, text: str) -> ModerationResult | Unavailable:
        self.texts.append(text)
        return self.result

    async def check_image(self, url: str) -> ModerationResult | Unavailable:
        return self.result


@dataclass
class FakeClassifier:
    """Классификатор политики: ответ задаёт тест; по умолчанию — «ok» уверенно."""

    verdict: PolicyVerdict | Unavailable = field(
        default_factory=lambda: PolicyVerdict(
            label=PolicyLabel.OK, confidence=0.95, explanation="тест"
        )
    )
    calls: int = 0

    async def classify(self, text: str, *, kind: ContentKind) -> PolicyVerdict | Unavailable:
        self.calls += 1
        return self.verdict
