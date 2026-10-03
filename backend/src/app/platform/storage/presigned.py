"""Повторное использование presigned GET (перф-аудит 2026-10).

Без CDN (dev и stage: S3_PUBLIC_BASE_URL не задан, файлы — по presigned GET) каждая выдача
медиа подписывала ссылку заново: новая подпись — новый адрес, браузер не берёт картинку из
своего кэша, а ETag ответов с фото (S05, S08, S13) не совпадает никогда. Ссылка на тот же объект
с тем же сроком переиспользуется первую половину срока: она по-прежнему выдаётся только после
проверок доступа вызывающего и действует ещё не меньше половины срока. Ссылок в памяти процесса
не больше SIZE (вытесняются давно не нужные).
"""

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from datetime import timedelta
from typing import Final

SIZE: Final = 4096
"""~2 МБ ссылок: превью ленты и карточек одного процесса с запасом."""


class PresignedUrls:
    def __init__(self, *, size: int = SIZE, monotonic: Callable[[], float] = time.monotonic):
        self._size, self._monotonic = size, monotonic
        self._urls: OrderedDict[Hashable, tuple[str, float]] = OrderedDict()

    def reuse(self, key: Hashable, ttl: timedelta, sign: Callable[[], str]) -> str:
        """Ссылка, подписанная меньше половины срока назад, — или новая подпись."""
        now = self._monotonic()
        found = self._urls.get(key)
        if found is not None and now - found[1] < ttl.total_seconds() / 2:
            self._urls.move_to_end(key)
            return found[0]
        url = sign()
        self._urls[key] = (url, now)
        self._urls.move_to_end(key)
        while len(self._urls) > self._size:
            self._urls.popitem(last=False)
        return url
