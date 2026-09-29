"""HTTP media: загрузка по presigned URL (ARCHITECTURE §10.2, ADR-0007, DEVELOPMENT_PLAN 2.1).

Тонкие обработчики: разобрать запрос, лимиты, use case, ответ. Файл — только свой: чужой
или удалённый — 404. Антиспам (§13.3): 50 загрузок в час — здесь, 1 GB в сутки — в use case
после проверки файла (порт UploadQuota).
"""

from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Path, Response, status

from app.modules.media.application.dto import MediaView, UploadPlan
from app.modules.media.application.queries import MediaQueries
from app.modules.media.application.use_cases.complete_upload import (
    CompleteUpload,
    CompleteUploadCommand,
)
from app.modules.media.application.use_cases.delete_media import DeleteMedia, DeleteMediaCommand
from app.modules.media.application.use_cases.sign_upload_parts import (
    SignUploadParts,
    SignUploadPartsCommand,
)
from app.modules.media.application.use_cases.start_upload import StartUpload, StartUploadCommand
from app.modules.media.domain.asset import VariantName
from app.modules.media.http.schemas import (
    CompleteIn,
    MediaOut,
    PartsIn,
    SignedPartOut,
    UploadIn,
    UploadOut,
    VariantOut,
)
from app.platform.http.idempotency import idempotent_router
from app.platform.http.ratelimit import RateLimit
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import MediaId
from app.platform.kernel.principal import Principal
from app.platform.ratelimit import Rate
from app.platform.storage.port import UploadedPart

UPLOADS_PER_USER = Rate("media.uploads", "50/hour")

router = APIRouter(tags=["media"], dependencies=AUTHENTICATED)
creating = idempotent_router()
MediaPath = Annotated[UUID, Path()]


@creating.post(
    "/media/uploads",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimit(UPLOADS_PER_USER))],
)
@inject
async def start_upload(
    body: UploadIn, principal: FromDishka[Principal], start: FromDishka[StartUpload]
) -> UploadOut:
    plan = await start(
        StartUploadCommand(
            owner_id=principal.user_id,
            purpose=body.purpose,
            mime_type=body.mime_type,
            size_bytes=body.size_bytes,
        )
    )
    return _upload_out(plan)


router.include_router(creating)


@router.post("/media/uploads/{media_id}/parts")
@inject
async def sign_upload_parts(
    media_id: MediaPath,
    body: PartsIn,
    principal: FromDishka[Principal],
    sign: FromDishka[SignUploadParts],
) -> UploadOut:
    numbers = tuple(body.part_numbers) if body.part_numbers is not None else None
    plan = await sign(
        SignUploadPartsCommand(
            owner_id=principal.user_id, media_id=MediaId(media_id), part_numbers=numbers
        )
    )
    return _upload_out(plan)


@router.post("/media/uploads/{media_id}/complete")
@inject
async def complete_upload(
    media_id: MediaPath,
    body: CompleteIn,
    principal: FromDishka[Principal],
    complete: FromDishka[CompleteUpload],
    queries: FromDishka[MediaQueries],
) -> MediaOut:
    parts = tuple(UploadedPart(part_number=p.part_number, etag=p.etag) for p in body.parts)
    asset = await complete(
        CompleteUploadCommand(owner_id=principal.user_id, media_id=MediaId(media_id), parts=parts)
    )
    return _media_out(await queries.view(asset))


@router.get("/media/{media_id}")
@inject
async def get_media(
    media_id: MediaPath, principal: FromDishka[Principal], queries: FromDishka[MediaQueries]
) -> MediaOut:
    return _media_out(await queries.get(principal.user_id, MediaId(media_id)))


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_media(
    media_id: MediaPath, principal: FromDishka[Principal], delete: FromDishka[DeleteMedia]
) -> Response:
    await delete(DeleteMediaCommand(owner_id=principal.user_id, media_id=MediaId(media_id)))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _upload_out(plan: UploadPlan) -> UploadOut:
    return UploadOut(
        media_id=plan.media_id,
        multipart=plan.multipart,
        part_size=plan.part_size,
        parts=[
            SignedPartOut(part_number=p.part_number, url=p.url, headers=dict(p.headers))
            for p in plan.parts
        ],
        expires_at=plan.expires_at,
    )


def _media_out(view: MediaView) -> MediaOut:
    return MediaOut(
        id=view.id,
        kind=view.kind,
        purpose=view.purpose,
        status=view.status,
        mime_type=view.mime_type,
        size_bytes=view.size_bytes,
        moderation_status=view.moderation_status,
        created_at=view.created_at,
        uploaded_at=view.uploaded_at,
        preview_url=view.preview_url,
        width=view.width,
        height=view.height,
        placeholder=view.placeholder,
        variants=[
            VariantOut(name=VariantName(v.name), url=v.url, width=v.width, height=v.height)
            for v in view.variants
        ],
        failure_reason=view.failure_reason,
    )
