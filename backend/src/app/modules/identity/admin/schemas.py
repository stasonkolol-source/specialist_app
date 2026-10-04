"""Схемы Admin API identity (ADR-0020 §10: <Имя>In / <Имя>Out): карточка пользователя, санкции."""

from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from app.modules.identity.application.dto import PersonalData, RestrictionRecord
from app.modules.identity.application.use_cases.inspect_user import UserInspection
from app.modules.identity.domain.restriction import RestrictionKind, RestrictionSource
from app.modules.identity.domain.user import UserIntent, UserStatus
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Role


class RestrictionOut(BaseModel):
    id: UUID
    kind: RestrictionKind
    reason_code: str
    source: RestrictionSource
    case_id: UUID | None
    starts_at: datetime
    ends_at: datetime | None
    lifted_at: datetime | None
    created_by: UUID | None

    @classmethod
    def of(cls, item: RestrictionRecord) -> RestrictionOut:
        return cls(
            id=item.id,
            kind=item.kind,
            reason_code=item.reason_code,
            source=item.source,
            case_id=item.case_id,
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            lifted_at=item.lifted_at,
            created_by=item.created_by,
        )


class ActivityOut(BaseModel):
    created_at: datetime
    last_seen_at: datetime | None
    last_login_at: datetime | None
    active_sessions: int
    completed_deals: int


class PersonalDataOut(BaseModel):
    display_name: str
    phone_e164: str | None
    telegram_id: int | None
    telegram_username: str | None
    telegram_name: str | None

    @classmethod
    def of(cls, data: PersonalData) -> PersonalDataOut:
        return cls(
            display_name=data.display_name,
            phone_e164=data.phone_e164,
            telegram_id=data.telegram_id,
            telegram_username=data.telegram_username,
            telegram_name=data.telegram_name,
        )


class UserCardOut(BaseModel):
    """Карточка пользователя. `personal_data` — только support и admin (у moderator — null); каждый
    такой ответ пишет `identity.user.pii_viewed` в журнал аудита. История модерации —
    `GET /cases?subject_id=` и `GET /reports?reporter_id=`."""

    id: UUID
    status: UserStatus
    trust_level: int
    ui_locale: Locale
    home_city_id: int | None
    intent: UserIntent | None
    phone_verified: bool
    roles: list[Role]
    trust_penalty_at: datetime | None
    deleted_at: datetime | None
    activity: ActivityOut
    restrictions: list[RestrictionOut] = Field(description="Новые первыми, со снятыми")
    personal_data: PersonalDataOut | None

    @classmethod
    def of(cls, found: UserInspection) -> UserCardOut:
        card = found.card
        return cls(
            id=card.id,
            status=card.status,
            trust_level=card.trust_level,
            ui_locale=card.ui_locale,
            home_city_id=card.home_city_id,
            intent=card.intent,
            phone_verified=card.phone_verified,
            roles=sorted(card.roles),
            trust_penalty_at=card.trust_penalty_at,
            deleted_at=card.deleted_at,
            activity=ActivityOut(
                created_at=card.created_at,
                last_seen_at=card.last_seen_at,
                last_login_at=card.last_login_at,
                active_sessions=card.active_sessions,
                completed_deals=card.completed_deals,
            ),
            restrictions=[RestrictionOut.of(item) for item in card.restrictions],
            personal_data=(
                PersonalDataOut.of(found.personal_data) if found.personal_data is not None else None
            ),
        )


class RestrictionIn(BaseModel):
    """Санкция от имени сотрудника — тем же путём, что решение модерации (UserRestricted)."""

    kind: RestrictionKind
    reason_code: str = Field(
        min_length=1, max_length=64, description="Машинный код причины: `spam`, `prepayment_scam`"
    )
    ends_at: AwareDatetime | None = Field(default=None, description="null — бессрочно")


class RestrictionCreatedOut(BaseModel):
    id: UUID
