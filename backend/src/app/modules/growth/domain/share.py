"""Ссылка «Поделиться» (ARCHITECTURE §11.4, DEVELOPMENT_PLAN 7.4).

Делятся только публичным: карточкой специалиста (`s_`) и заявкой (`j_`). У вошедшего к коду
добавляется его код приглашения `_r<code>`: новый пользователь по такой ссылке получит его в
первом касании (`growth.attributions.referral_code`) — так считается K-фактор шаринга.
"""

import secrets
from typing import Final
from uuid import UUID

from app.platform.telegram.deeplinks import (
    BASE62_ALPHABET,
    LinkType,
    StartLink,
    encode_start_param,
)

REFERRAL_CODE_LENGTH: Final = 8
"""62^8 ≈ 2·10^14 кодов: подбором чужой не найти, а ссылка короче 64 символов с запасом."""


def new_referral_code() -> str:
    """Код приглашения: только `[A-Za-z0-9]` — `_` отделяет суффикс от кода экрана."""
    return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(REFERRAL_CODE_LENGTH))


def share_start_param(link_type: LinkType, entity_id: UUID, *, ref: str | None) -> str:
    """Код startapp ссылки: `s_<base62>` или `j_<base62>` и, у вошедшего, `_r<code>`."""
    return encode_start_param(StartLink(type=link_type, id=entity_id, ref=ref))


def share_url(bot_username: str, start_param: str) -> str:
    """`https://t.me/<bot>?startapp=<код>`: открывает Mini App на экране кода (§11.4)."""
    return f"https://t.me/{bot_username}?startapp={start_param}"
