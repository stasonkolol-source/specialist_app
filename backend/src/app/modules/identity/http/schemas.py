"""Схемы HTTP identity (ADR-0020 §10: <Имя>In / <Имя>Out)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.identity.api import Action
from app.modules.identity.application.dto import AccessView, MeView, SessionTokens
from app.modules.identity.domain.consent import MAX_VERSION
from app.modules.identity.domain.user import MAX_DISPLAY_NAME, UserIntent
from app.platform.kernel.localized import Locale

INT4_MAX = 2**31 - 1
"""id справочников geo — int4 identity: больше — не id, а 422 (иначе ошибка БД и 500)."""


class MeOut(BaseModel):
    id: UUID
    display_name: str
    ui_locale: Locale
    trust_level: int
    phone_verified: bool
    created_at: datetime
    home_city_id: int | None
    intent: UserIntent | None
    consents: dict[str, str]
    """Принятые версии документов: `{"terms": "…", "privacy": "…", "age_18": "…"}`."""
    consent_required: bool
    """Нет согласия с действующими версиями из client-config: показать S02c."""
    can_post_jobs: bool
    can_respond: bool
    can_message: bool

    @classmethod
    def of(cls, view: MeView, access: AccessView) -> MeOut:
        return cls(
            id=view.id,
            display_name=view.display_name,
            ui_locale=view.ui_locale,
            trust_level=view.trust_level,
            phone_verified=view.phone_verified,
            created_at=view.created_at,
            home_city_id=view.home_city_id,
            intent=view.intent,
            consents={document.value: version for document, version in access.consents.items()},
            consent_required=access.consent_required,
            can_post_jobs=Action.POST in access.allowed,
            can_respond=Action.RESPOND in access.allowed,
            can_message=Action.MESSAGE in access.allowed,
        )


class TokensOut(BaseModel):
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105 — тип токена, не секрет
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime

    @classmethod
    def of(cls, tokens: SessionTokens) -> TokensOut:
        return cls(
            access_token=tokens.access_token,
            access_expires_at=tokens.access_expires_at,
            refresh_token=tokens.refresh_token,
            refresh_expires_at=tokens.refresh_expires_at,
        )


class AuthOut(TokensOut):
    is_new: bool
    user: MeOut


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=128)


class MeUpdateIn(BaseModel):
    """Поля, которых нет или которые null, не меняются."""

    display_name: str | None = Field(default=None, min_length=1, max_length=MAX_DISPLAY_NAME)
    ui_locale: Locale | None = None
    home_city_id: int | None = Field(default=None, ge=1, le=INT4_MAX)
    """Город из GET /cities со статусом active (онбординг S02a)."""
    intent: UserIntent | None = None
    """«Что вы хотите?» (онбординг S02b)."""


class ConsentsIn(BaseModel):
    """Галочка S02c: версии правил (с 18+) и политики из client-config, которые видел
    пользователь."""

    terms_version: str = Field(min_length=1, max_length=MAX_VERSION)
    privacy_version: str = Field(min_length=1, max_length=MAX_VERSION)
