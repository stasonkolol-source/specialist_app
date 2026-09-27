"""Заголовки клиента: `X-Client` и `Accept-Language` (ARCHITECTURE §8.1).

`X-Client: tma/1.3.0` (или `ios/…`, `android/…`) — по нему сервер решает про forced
update (426) и собирает статистику версий. Нет заголовка — клиент не наш (curl, мониторинг),
проверка версии не нужна. Минимальные версии пока из настроек, с шага 1.1 — из client-config.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.platform.kernel.localized import Locale

Version = tuple[int, int, int]

_CLIENT = re.compile(r"(?P<platform>[a-z]+)/(?P<version>\d{1,5}(?:\.\d{1,5}){0,2})")
DEFAULT_LOCALE = Locale.RU
"""Как `users.ui_locale DEFAULT 'ru'`: основная аудитория — русскоязычные."""


def parse_version(raw: str) -> Version:
    parts = [int(part) for part in raw.split(".")]
    major, minor, patch = [*parts, 0, 0][:3]
    return major, minor, patch


def format_version(version: Version) -> str:
    return ".".join(str(part) for part in version)


@dataclass(frozen=True, slots=True)
class ClientInfo:
    platform: str
    version: Version

    @classmethod
    def parse(cls, raw: str) -> ClientInfo | None:
        """None — заголовок не по формату `<platform>/<major>[.<minor>[.<patch>]]`."""
        match = _CLIENT.fullmatch(raw.strip())
        if match is None:
            return None
        return cls(platform=match["platform"], version=parse_version(match["version"]))


class ClientPolicy:
    """Минимальные поддерживаемые версии клиентов по платформам."""

    def __init__(self, min_versions: Mapping[str, str]) -> None:
        self._min = {platform: parse_version(v) for platform, v in min_versions.items()}

    def required_upgrade(self, client: ClientInfo) -> Version | None:
        """Минимальная версия, если клиент старше неё; иначе None."""
        minimum = self._min.get(client.platform)
        if minimum is not None and client.version < minimum:
            return minimum
        return None


def negotiate_locale(header: str | None) -> Locale:
    """Локаль из `Accept-Language` с учётом q. Сербский без письма — латиница (§7.4)."""
    if not header:
        return DEFAULT_LOCALE
    ranked: list[tuple[float, int, Locale]] = []
    for index, item in enumerate(header.split(",")):
        tag, _, params = item.strip().partition(";")
        locale = _locale_of(tag.strip())
        if locale is None:
            continue
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                continue
        if quality > 0:
            ranked.append((-quality, index, locale))
    return min(ranked)[2] if ranked else DEFAULT_LOCALE


def _locale_of(tag: str) -> Locale | None:
    parts = tag.lower().replace("_", "-").split("-")
    match parts:
        case ["ru", *_]:
            return Locale.RU
        case ["sr", "cyrl", *_]:
            return Locale.SR_CYRL
        case ["sr", *_]:
            return Locale.SR_LATN
        case ["en", *_]:
            return Locale.EN
        case _:
            return None
