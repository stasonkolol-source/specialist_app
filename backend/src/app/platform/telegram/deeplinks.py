"""Кодек deep links `t.me/<bot>?startapp=<код>` (ARCHITECTURE §11.4, ADR-0011).

Общий для бота (кнопка «Открыть приложение» несёт тот же код) и модуля growth (атрибуция
первого касания). Тот же кодек, что `packages/links` на фронтенде: golden-векторы
`packages/links/golden.json` общие, тесты сверяются с ними. Код — не длиннее 64 символов
`[A-Za-z0-9_-]`, без партнёрского префикса Telegram `_tgr_`:

- `j_<base62>`, `s_<base62>`, `c_<base62>`, `d_<base62>` — заявка, специалист, диалог, сделка;
- `h` — главная;
- `n` — новая заявка (мастер S20a; `/new` бота);
- `m_jobs` — свои заявки (S22; `/jobs` бота);
- `l_terms`, `l_privacy` — правила площадки и политика конфиденциальности (S48; `/terms` и
  `/privacy` бота);
- `g_`, `gu_`, `gh`, `gs_`, `gc_` — зарезервированы под раздел «Вещи» (после MVP);
- `…_r<code>` — суффикс реферала или атрибуции канала, только суффикс, не тип.

`<base62>` — UUID в base62 (алфавит 0-9A-Za-z, старшие разряды слева), ровно 22 символа.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.platform.telegram.errors import InvalidStartLinkError

BASE62_ALPHABET: Final = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE62_UUID_LENGTH: Final = 22
START_PARAM_MAX_LENGTH: Final = 64
TELEGRAM_RESERVED_PREFIX: Final = "_tgr_"
"""Префикс партнёрской программы Telegram: такие параметры не наши."""

_BASE62: Final = re.compile(r"[0-9A-Za-z]{22}")
_START_PARAM: Final = re.compile(r"[A-Za-z0-9_-]+")
_REF: Final = re.compile(r"[A-Za-z0-9]+")
"""Реферальный код или код канала: без `_`, иначе суффикс не отделить."""
_PAYLOAD: Final = re.compile(r"[A-Za-z0-9-]+")
"""Значение зарезервированного кода (`gs_<id>`, `gc_<code>`): без `_`, разбор однозначен."""
_MAX_UUID: Final = (1 << 128) - 1
_DIGITS: Final = {ch: i for i, ch in enumerate(BASE62_ALPHABET)}


class LinkType(StrEnum):
    JOB = "job"
    SPECIALIST = "specialist"
    CHAT = "chat"
    DEAL = "deal"
    HOME = "home"
    NEW_JOB = "new_job"
    MINE = "mine"
    LEGAL = "legal"
    RESERVED = "reserved"


class LinkDocument(StrEnum):
    """Документ ссылки `l_<документ>`: вкладка S48. Значения — как у LegalDocument."""

    TERMS = "terms"
    PRIVACY = "privacy"


class LinkSection(StrEnum):
    """Свой раздел ссылки `m_<раздел>`: `jobs` — «Мои заявки» (S22), `reviews` — «Мои отзывы»
    (S28, 7.3; кнопка «Ответить на отзыв» уведомления `review.published`), `settings` —
    настройки S43 и `deletion` — удаление аккаунта S45 (кнопки `/settings` бота, 4.9)."""

    JOBS = "jobs"
    REVIEWS = "reviews"
    SETTINGS = "settings"
    DELETION = "deletion"


class ReservedCode(StrEnum):
    """Префиксы раздела «Вещи» (ADR-0019 п. 15): `gh` и `h` — разные типы."""

    GOODS_LISTING = "g"
    GOODS_SELLER = "gu"
    GOODS_HOME = "gh"
    GOODS_SAVED_SEARCH = "gs"
    GOODS_PARTNER_CHAT = "gc"


ENTITY_PREFIX: Final[Mapping[LinkType, str]] = {
    LinkType.JOB: "j",
    LinkType.SPECIALIST: "s",
    LinkType.CHAT: "c",
    LinkType.DEAL: "d",
}
_ENTITY_BY_PREFIX: Final = {prefix: kind for kind, prefix in ENTITY_PREFIX.items()}
_HOME: Final = "h"
_NEW_JOB: Final = "n"
_MINE: Final = "m"
_LEGAL: Final = "l"


@dataclass(frozen=True, slots=True, kw_only=True)
class StartLink:
    """Разобранный код startapp.

    Сущность (`job`, `specialist`, `chat`, `deal`) — с `id`; `home` и `new_job` — без полей;
    `mine` — с `section`; `legal` — с `document`; `reserved` — с `code` и, кроме `gh`, со
    значением `value`. `ref` — суффикс `_r<code>`.
    """

    type: LinkType
    id: UUID | None = None
    code: ReservedCode | None = None
    value: str | None = None
    document: LinkDocument | None = None
    section: LinkSection | None = None
    ref: str | None = None

    def __post_init__(self) -> None:
        no_code = self.code is None and self.value is None
        no_document = self.document is None
        no_section = self.section is None
        if self.type in ENTITY_PREFIX:
            shape_ok = self.id is not None and no_code and no_document and no_section
        elif self.type in (LinkType.HOME, LinkType.NEW_JOB):
            shape_ok = self.id is None and no_code and no_document and no_section
        elif self.type is LinkType.MINE:
            shape_ok = self.id is None and no_code and no_document and not no_section
        elif self.type is LinkType.LEGAL:
            shape_ok = self.id is None and no_code and not no_document and no_section
        else:
            needs_value = self.code is not ReservedCode.GOODS_HOME
            shape_ok = (
                self.id is None
                and no_document
                and no_section
                and self.code is not None
                and needs_value == (self.value is not None)
                and (self.value is None or _PAYLOAD.fullmatch(self.value) is not None)
            )
        if not shape_ok:
            raise InvalidStartLinkError(reason="shape")
        if self.ref is not None and _REF.fullmatch(self.ref) is None:
            raise InvalidStartLinkError(reason="ref")


def uuid_to_base62(value: UUID) -> str:
    n = value.int
    digits: list[str] = []
    while n:
        n, rest = divmod(n, 62)
        digits.append(BASE62_ALPHABET[rest])
    return "".join(reversed(digits)).rjust(BASE62_UUID_LENGTH, "0")


def base62_to_uuid(value: str) -> UUID | None:
    """UUID из 22 символов base62; None — не base62-UUID или больше 2^128 − 1."""
    if _BASE62.fullmatch(value) is None:
        return None
    n = 0
    for ch in value:
        n = n * 62 + _DIGITS[ch]
    return UUID(int=n) if n <= _MAX_UUID else None


def is_valid_start_param(value: str) -> bool:
    """Синтаксис Telegram: длина, алфавит, не партнёрский `_tgr_`."""
    return (
        0 < len(value) <= START_PARAM_MAX_LENGTH
        and _START_PARAM.fullmatch(value) is not None
        and not value.startswith(TELEGRAM_RESERVED_PREFIX)
    )


def encode_start_param(link: StartLink) -> str:
    """Код startapp для ссылки; InvalidStartLinkError — длиннее 64 символов."""
    # форму ссылки проверил __post_init__: у reserved есть code, у сущности — id
    if link.code is not None:
        code = link.code.value if link.value is None else f"{link.code.value}_{link.value}"
    elif link.document is not None:
        code = f"{_LEGAL}_{link.document.value}"
    elif link.section is not None:
        code = f"{_MINE}_{link.section.value}"
    elif link.id is not None:
        code = f"{ENTITY_PREFIX[link.type]}_{uuid_to_base62(link.id)}"
    else:
        code = _NEW_JOB if link.type is LinkType.NEW_JOB else _HOME
    if link.ref is not None:
        code += f"_r{link.ref}"
    if not is_valid_start_param(code):
        raise InvalidStartLinkError(reason="length")
    return code


def parse_start_param(value: str | None) -> StartLink | None:
    """Разбор кода; None — неизвестный или битый код (приложение открывает главную)."""
    if not value or not is_valid_start_param(value):
        return None
    parts = value.split("_")
    plain = _parse_code(parts)
    if plain is not None:
        return plain
    # `…_r<code>` — суффикс, а не тип: пробуем отрезать его
    last = parts[-1]
    ref = last[1:]
    if len(parts) < 2 or not last.startswith("r") or _REF.fullmatch(ref) is None:
        return None
    link = _parse_code(parts[:-1])
    if link is None:
        return None
    return StartLink(
        type=link.type,
        id=link.id,
        code=link.code,
        value=link.value,
        document=link.document,
        section=link.section,
        ref=ref,
    )


class LinkSource(StrEnum):
    """Откуда пришёл человек по коду ссылки: источник атрибуции (growth) и свойство событий
    аналитики. Одна классификация на всех — иначе воронки и таблица атрибуции разойдутся."""

    ORGANIC = "organic"
    """Без кода: пришёл сам (поиск в Telegram, профиль бота, menu button)."""
    JOB = "job"
    SPECIALIST = "specialist"
    CHAT = "chat"
    DEAL = "deal"
    HOME = "home"
    NEW_JOB = "new_job"
    """«Разместить заявку» (`n`): её шлёт `/new` бота и пересылают в чаты."""
    MINE = "mine"
    """Свой раздел (`m_jobs`): кнопка `/jobs` бота."""
    LEGAL = "legal"
    """Ссылка на правила или политику (`l_terms`, `l_privacy`): её пересылают из бота."""
    GOODS = "goods"
    """Зарезервированные коды раздела «Вещи» (после MVP)."""
    UNKNOWN = "unknown"
    """Код есть, но не наш: битый, устаревший или партнёрский Telegram `_tgr_`."""


_SOURCE_BY_TYPE: Final[Mapping[LinkType, LinkSource]] = {
    LinkType.JOB: LinkSource.JOB,
    LinkType.SPECIALIST: LinkSource.SPECIALIST,
    LinkType.CHAT: LinkSource.CHAT,
    LinkType.DEAL: LinkSource.DEAL,
    LinkType.HOME: LinkSource.HOME,
    LinkType.NEW_JOB: LinkSource.NEW_JOB,
    LinkType.MINE: LinkSource.MINE,
    LinkType.LEGAL: LinkSource.LEGAL,
    LinkType.RESERVED: LinkSource.GOODS,
}


def link_source(start_param: str | None) -> LinkSource:
    """Источник по сырому коду `startapp` или payload `/start`."""
    if not start_param:
        return LinkSource.ORGANIC
    link = parse_start_param(start_param)
    return _SOURCE_BY_TYPE[link.type] if link is not None else LinkSource.UNKNOWN


def _parse_code(parts: Sequence[str]) -> StartLink | None:
    head, rest = parts[0], parts[1:]
    if head == _HOME:
        return StartLink(type=LinkType.HOME) if not rest else None
    if head == _NEW_JOB:
        return StartLink(type=LinkType.NEW_JOB) if not rest else None
    entity = _ENTITY_BY_PREFIX.get(head)
    if entity is not None:
        entity_id = base62_to_uuid(rest[0]) if len(rest) == 1 else None
        return StartLink(type=entity, id=entity_id) if entity_id is not None else None
    if head == _LEGAL:
        if len(rest) != 1:
            return None
        try:
            return StartLink(type=LinkType.LEGAL, document=LinkDocument(rest[0]))
        except ValueError:  # документа нет в S48
            return None
    if head == _MINE:
        if len(rest) != 1:
            return None
        try:
            return StartLink(type=LinkType.MINE, section=LinkSection(rest[0]))
        except ValueError:  # такого своего раздела нет
            return None
    try:
        code = ReservedCode(head)
    except ValueError:
        return None
    if code is ReservedCode.GOODS_HOME:
        return StartLink(type=LinkType.RESERVED, code=code) if not rest else None
    if len(rest) != 1 or _PAYLOAD.fullmatch(rest[0]) is None:
        return None
    return StartLink(type=LinkType.RESERVED, code=code, value=rest[0])
