"""Представления снимка справочника (перф-аудит 2026-10): тело ответа с ETag строится один раз
на снимок, а не на каждый запрос перед проверкой If-None-Match. Без зависимостей: порты
модулей возвращают его из application."""

from collections.abc import Callable, Hashable
from typing import cast

MAX_ITEMS = 256
"""Представлений на снимок не больше: ключ включает ввод клиента (slug города), и мусорные
значения не должны раздувать память до следующего обновления."""


class Memo:
    def __init__(self, *, limit: int = MAX_ITEMS) -> None:
        self._items: dict[Hashable, object] = {}
        self._limit = limit

    def get[R](self, key: Hashable, build: Callable[[], R]) -> R:
        """Представление по ключу: построить один раз; сверх лимита — строится без запоминания."""
        if key in self._items:
            return cast(R, self._items[key])
        value = build()
        if len(self._items) < self._limit:
            self._items[key] = value
        return value
