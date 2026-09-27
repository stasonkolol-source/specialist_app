"""Схемы HTTP identity (ADR-0020 §10: <Имя>In / <Имя>Out)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.identity.application.dto import MeView, SessionTokens
from app.modules.identity.domain.user import MAX_DISPLAY_NAME
from app.platform.kernel.localized import Locale


class MeOut(BaseModel):
    id: UUID
    display_name: str
    ui_locale: Locale
    trust_level: int
    phone_verified: bool
    created_at: datetime

    @classmethod
    def of(cls, view: MeView) -> MeOut:
        return cls(
            id=view.id,
            display_name=view.display_name,
            ui_locale=view.ui_locale,
            trust_level=view.trust_level,
            phone_verified=view.phone_verified,
            created_at=view.created_at,
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
    display_name: str | None = Field(default=None, min_length=1, max_length=MAX_DISPLAY_NAME)
    ui_locale: Locale | None = None
