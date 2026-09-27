"""Эндпоинты спайка 0.24 «загрузка медиа из WebView» — только APP_ENV=dev, вне OpenAPI.

Страница Mini App `/__spike/upload` грузит фото и видео прямо в Garage по presigned-ссылкам:
файл до PART_SIZE — одним PUT, больше — multipart по частям PART_SIZE. Ключи живут под
`spike/<user_id>/`: чужой ключ — 403. Настоящая загрузка с квотами, записью в БД и
обработкой — шаг 2.1 (modules/media); этот файл тогда удаляется.
"""

import math
import mimetypes
from datetime import datetime
from typing import Annotated

from botocore.exceptions import ClientError
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.errors import DomainValidationError, ForbiddenError, NotFoundError
from app.platform.kernel.ids import new_id
from app.platform.kernel.principal import Principal
from app.platform.storage.port import (
    MAX_PARTS,
    PART_SIZE,
    Bucket,
    PresignedRequest,
    StoragePort,
    UploadedPart,
)

MAX_SIZE = 1024 * 1024 * 1024
"""1 GiB: видео до ~2 минут 4K; настоящие лимиты по назначению — в 2.1."""
CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
        "video/mp4",
        "video/quicktime",
        "video/webm",
    }
)

router = APIRouter(
    prefix="/__spike/uploads", tags=["spike"], include_in_schema=False, dependencies=AUTHENTICATED
)


class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size: int = Field(ge=1, le=MAX_SIZE)


class SignedUrlOut(BaseModel):
    part_number: int | None
    url: str
    headers: dict[str, str]
    expires_at: datetime


class UploadOut(BaseModel):
    key: str
    upload_id: str | None
    """None — файл целиком одним PUT (единственный элемент `parts`)."""
    part_size: int
    parts: list[SignedUrlOut]


class SignIn(BaseModel):
    """Новая ссылка взамен просроченной или оборванной: целиком или на одну часть."""

    key: str
    content_type: str
    size: int = Field(ge=1, le=MAX_SIZE)
    upload_id: str | None = None
    part_number: int | None = Field(default=None, ge=1, le=MAX_PARTS)


class PartIn(BaseModel):
    part_number: int = Field(ge=1, le=MAX_PARTS)
    etag: str = Field(min_length=1, max_length=128)


class CompleteIn(BaseModel):
    key: str
    upload_id: str
    parts: list[PartIn] = Field(min_length=1, max_length=MAX_PARTS)


class AbortIn(BaseModel):
    key: str
    upload_id: str


class ObjectOut(BaseModel):
    key: str
    size: int
    content_type: str | None
    etag: str
    url: str
    """presigned GET на 5 минут: превью на странице спайка."""


@router.post("", status_code=status.HTTP_201_CREATED)
@inject
async def start_upload(
    body: UploadIn, principal: FromDishka[Principal], storage: FromDishka[StoragePort]
) -> UploadOut:
    content_type = _content_type(body.content_type, body.filename)
    key = f"{_prefix(principal)}{new_id()}{_extension(content_type, body.filename)}"
    if body.size <= PART_SIZE:
        signed = await storage.presign_put(
            Bucket.INCOMING, key, content_type=content_type, size=body.size
        )
        return UploadOut(key=key, upload_id=None, part_size=PART_SIZE, parts=[_out(signed, None)])
    count = math.ceil(body.size / PART_SIZE)
    upload_id = await storage.start_multipart(Bucket.INCOMING, key, content_type=content_type)
    parts = [
        _out(
            await storage.presign_part(
                Bucket.INCOMING,
                key,
                upload_id=upload_id,
                part_number=number,
                size=_part_size(body.size, number),
            ),
            number,
        )
        for number in range(1, count + 1)
    ]
    return UploadOut(key=key, upload_id=upload_id, part_size=PART_SIZE, parts=parts)


@router.post("/sign")
@inject
async def sign(
    body: SignIn, principal: FromDishka[Principal], storage: FromDishka[StoragePort]
) -> SignedUrlOut:
    _own(body.key, principal)
    if body.upload_id is None or body.part_number is None:
        if body.size > PART_SIZE:
            raise DomainValidationError(field="size")
        content_type = _content_type(body.content_type, body.key)
        signed = await storage.presign_put(
            Bucket.INCOMING, body.key, content_type=content_type, size=body.size
        )
        return _out(signed, None)
    if body.size > PART_SIZE:
        raise DomainValidationError(field="size")
    signed = await storage.presign_part(
        Bucket.INCOMING,
        body.key,
        upload_id=body.upload_id,
        part_number=body.part_number,
        size=body.size,
    )
    return _out(signed, body.part_number)


@router.post("/complete", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def complete(
    body: CompleteIn, principal: FromDishka[Principal], storage: FromDishka[StoragePort]
) -> None:
    _own(body.key, principal)
    parts = [UploadedPart(part_number=p.part_number, etag=p.etag) for p in body.parts]
    try:
        await storage.complete_multipart(
            Bucket.INCOMING, body.key, upload_id=body.upload_id, parts=parts
        )
    except ClientError as exc:
        # InvalidPart, NoSuchUpload: клиент прислал не те ETag или загрузку уже отменили
        raise DomainValidationError(field="parts", reason=_code(exc)) from exc


@router.post("/abort", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def abort(
    body: AbortIn, principal: FromDishka[Principal], storage: FromDishka[StoragePort]
) -> None:
    _own(body.key, principal)
    try:
        await storage.abort_multipart(Bucket.INCOMING, body.key, upload_id=body.upload_id)
    except ClientError as exc:
        raise DomainValidationError(field="upload_id", reason=_code(exc)) from exc


@router.get("")
@inject
async def get_object(
    key: Annotated[str, Query(max_length=512)],
    principal: FromDishka[Principal],
    storage: FromDishka[StoragePort],
) -> ObjectOut:
    _own(key, principal)
    stored = await storage.head(Bucket.INCOMING, key)
    if stored is None:
        raise NotFoundError()
    url = await storage.presign_get(Bucket.INCOMING, key)
    return ObjectOut(
        key=key, size=stored.size, content_type=stored.content_type, etag=stored.etag, url=url
    )


def _prefix(principal: Principal) -> str:
    return f"spike/{principal.user_id}/"


def _own(key: str, principal: Principal) -> None:
    if not key.startswith(_prefix(principal)) or ".." in key:
        raise ForbiddenError()


def _content_type(declared: str, filename: str) -> str:
    """Android WebView часто отдаёт HEIC без типа: тогда тип по расширению."""
    content_type = declared.strip().lower() or (mimetypes.guess_type(filename)[0] or "")
    if filename.lower().endswith((".heic", ".heif")) and not content_type:
        content_type = "image/heic"
    if content_type not in CONTENT_TYPES:
        raise DomainValidationError(field="content_type")
    return content_type


def _extension(content_type: str, filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix.isalnum() and len(suffix) <= 5:
        return f".{suffix}"
    return mimetypes.guess_extension(content_type) or ""


def _part_size(total: int, number: int) -> int:
    return min(PART_SIZE, total - (number - 1) * PART_SIZE)


def _out(signed: PresignedRequest, part_number: int | None) -> SignedUrlOut:
    return SignedUrlOut(
        part_number=part_number,
        url=signed.url,
        headers=dict(signed.headers),
        expires_at=signed.expires_at,
    )


def _code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", "unknown"))
