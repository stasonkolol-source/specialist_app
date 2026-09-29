"""Порт объектного хранилища S3/R2 (ADR-0007, ARCHITECTURE §10.2, спайк 0.24).

Файлы идут с телефона прямо в хранилище по подписанным ссылкам: web выдаёт presigned PUT
(10 минут), для больших файлов — multipart по частям, потом проверяет HEAD (размер и тип)
и отдаёт presigned GET (5 минут). Бакеты: incoming — сырые загрузки, media — обработанное,
private — документы.

Подпись PUT включает Content-Type и Content-Length: файл другого размера или типа хранилище
отвергает (403). HEAD после загрузки остаётся второй проверкой. Просроченная ссылка — 400 у
Garage и 403 у R2: клиент просит новую (docs/spikes/0.24-webview-upload.md).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

PUT_TTL = timedelta(minutes=10)
GET_TTL = timedelta(minutes=5)
IMMUTABLE = "public, max-age=31536000, immutable"
"""Cache-Control публичных вариантов: ключ неизменяемый, новая версия — новый ключ (§10.4)."""
PRIVATE = "private, max-age=300"
"""Cache-Control приватных объектов: ссылка живёт 5 минут, общие кэши их не хранят."""
PART_SIZE = 8 * 1024 * 1024
"""Часть multipart: 8 MiB (минимум S3 — 5 MiB, кроме последней)."""
MAX_PARTS = 1000


class StorageRejectedError(Exception):
    """Хранилище отвергло запрос (4xx): не те части или ETag, отменённая загрузка. Повтор
    того же запроса не поможет. Сбой хранилища (5xx, сеть) — ExternalServiceError."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Bucket(StrEnum):
    INCOMING = "incoming"
    MEDIA = "media"
    PRIVATE = "private"


@dataclass(frozen=True, slots=True, kw_only=True)
class PresignedRequest:
    method: str
    url: str
    expires_at: datetime
    headers: Mapping[str, str] = field(default_factory=dict)
    """Заголовки, которые клиент обязан отправить как есть (подпись их учитывает)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UploadedPart:
    part_number: int
    etag: str


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredObject:
    key: str
    size: int
    content_type: str | None
    etag: str


class StoragePort(Protocol):
    async def presign_put(
        self, bucket: Bucket, key: str, *, content_type: str, size: int, ttl: timedelta = PUT_TTL
    ) -> PresignedRequest:
        """Ссылка на загрузку файла целиком ровно `size` байт типа `content_type`."""
        ...

    async def start_multipart(self, bucket: Bucket, key: str, *, content_type: str) -> str:
        """upload_id новой multipart-загрузки."""
        ...

    async def presign_part(
        self,
        bucket: Bucket,
        key: str,
        *,
        upload_id: str,
        part_number: int,
        size: int,
        ttl: timedelta = PUT_TTL,
    ) -> PresignedRequest:
        """Ссылка на часть `part_number` (с 1) ровно `size` байт."""
        ...

    async def complete_multipart(
        self, bucket: Bucket, key: str, *, upload_id: str, parts: Sequence[UploadedPart]
    ) -> None: ...

    async def abort_multipart(self, bucket: Bucket, key: str, *, upload_id: str) -> None: ...

    async def head(self, bucket: Bucket, key: str) -> StoredObject | None:
        """Метаданные объекта; None — объекта нет."""
        ...

    async def presign_get(self, bucket: Bucket, key: str, *, ttl: timedelta = GET_TTL) -> str: ...

    async def get(
        self, bucket: Bucket, key: str, *, max_bytes: int, etag: str | None = None
    ) -> bytes:
        """Содержимое объекта целиком (файлы до лимитов §10.1 помещаются в память).

        `etag` — только эта версия (If-Match): объект подменили — StorageRejectedError
        `PreconditionFailed`. Нет объекта — `NoSuchKey`, больше `max_bytes` — `TooLarge`.
        """
        ...

    async def put(
        self,
        bucket: Bucket,
        key: str,
        body: bytes,
        *,
        content_type: str,
        cache_control: str | None = None,
    ) -> None:
        """Записать объект с сервера (варианты после обработки); тот же ключ — перезапись."""
        ...

    async def copy(self, bucket: Bucket, key: str, *, to: Bucket) -> bool:
        """Копия объекта в другом бакете под тем же ключом (на стороне хранилища).
        False — объекта нет: копировать нечего."""
        ...

    async def delete(self, bucket: Bucket, key: str) -> None:
        """Удалить объект; объекта нет — не ошибка."""
        ...
