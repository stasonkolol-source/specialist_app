"""Кто выполняет действие (ADR-0009, ADR-0016). Строится из JWT в web и по telegram_id в боте."""

from dataclasses import dataclass, field
from enum import StrEnum

from app.platform.kernel.ids import UserId


class Role(StrEnum):
    """Роли персонала. У обычных пользователей ролей нет."""

    ADMIN = "admin"
    MODERATOR = "moderator"
    SUPPORT = "support"


class Platform(StrEnum):
    TMA = "tma"
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True, kw_only=True)
class Principal:
    user_id: UserId
    trust_level: int = 0
    roles: frozenset[Role] = field(default_factory=frozenset)
    platform: Platform = Platform.TMA
    session_id: str | None = None

    def has_role(self, role: Role) -> bool:
        return role in self.roles or Role.ADMIN in self.roles

    @property
    def is_staff(self) -> bool:
        return bool(self.roles)
