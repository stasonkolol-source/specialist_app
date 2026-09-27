"""StoragePort на boto3 (Garage в dev, R2 на stage и в prod), ADR-0007.

- Два клиента: служебный ходит в хранилище по внутреннему адресу (HEAD, multipart), а
  подписывающий строит ссылки на публичный адрес — его видит телефон (в dev — туннель
  Garage, S3_PUBLIC_ENDPOINT_URL). Подпись SigV4 включает хост, поэтому адрес подписи
  должен совпадать с тем, куда пойдёт клиент.
- Content-Length входит в подпись: браузер ставит его сам по размеру Blob, и хранилище
  отвергает файл другого размера ещё до записи.
- `request_checksum_calculation=when_required`: иначе новые boto3 добавляют в подпись
  заголовки CRC, которые не отправляет браузер, и Garage/R2 отвечают ошибкой подписи.
- boto3 блокирующий: сетевые вызовы — через asyncio.to_thread (ADR-0020 §10).
"""

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.platform.kernel.clock import Clock
from app.platform.settings import S3Settings
from app.platform.storage.port import (
    GET_TTL,
    PUT_TTL,
    Bucket,
    PresignedRequest,
    StoredObject,
    UploadedPart,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class StorageNotConfiguredError(RuntimeError):
    """Нет адреса или ключей S3: `make garage-init` (dev) или секреты окружения."""


def _config() -> Config:
    return Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=5,
        read_timeout=30,
    )


def _client(settings: S3Settings, endpoint_url: str) -> S3Client:
    if settings.access_key_id is None or settings.secret_access_key is None:
        raise StorageNotConfiguredError("S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY are not set")
    client: S3Client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=settings.region,
        aws_access_key_id=settings.access_key_id.get_secret_value(),
        aws_secret_access_key=settings.secret_access_key.get_secret_value(),
        config=_config(),
    )
    return client


class S3Storage:
    def __init__(self, settings: S3Settings, clock: Clock) -> None:
        if settings.endpoint_url is None:
            raise StorageNotConfiguredError("S3_ENDPOINT_URL is not set")
        self._names = {
            Bucket.INCOMING: settings.bucket_incoming,
            Bucket.MEDIA: settings.bucket_media,
            Bucket.PRIVATE: settings.bucket_private,
        }
        self._client = _client(settings, settings.endpoint_url)
        self._signer = _client(settings, settings.public_endpoint_url or settings.endpoint_url)
        self._clock = clock

    def close(self) -> None:
        self._client.close()
        self._signer.close()

    async def presign_put(
        self, bucket: Bucket, key: str, *, content_type: str, size: int, ttl: timedelta = PUT_TTL
    ) -> PresignedRequest:
        url = self._signer.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._names[bucket],
                "Key": key,
                "ContentType": content_type,
                "ContentLength": size,
            },
            ExpiresIn=int(ttl.total_seconds()),
        )
        return PresignedRequest(
            method="PUT",
            url=url,
            expires_at=self._expires(ttl),
            headers={"Content-Type": content_type},
        )

    async def start_multipart(self, bucket: Bucket, key: str, *, content_type: str) -> str:
        response = await asyncio.to_thread(
            self._client.create_multipart_upload,
            Bucket=self._names[bucket],
            Key=key,
            ContentType=content_type,
        )
        return response["UploadId"]

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
        url = self._signer.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self._names[bucket],
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
                "ContentLength": size,
            },
            ExpiresIn=int(ttl.total_seconds()),
        )
        return PresignedRequest(method="PUT", url=url, expires_at=self._expires(ttl))

    async def complete_multipart(
        self, bucket: Bucket, key: str, *, upload_id: str, parts: Sequence[UploadedPart]
    ) -> None:
        ordered = sorted(parts, key=lambda part: part.part_number)
        await asyncio.to_thread(
            self._client.complete_multipart_upload,
            Bucket=self._names[bucket],
            Key=key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [{"PartNumber": p.part_number, "ETag": p.etag} for p in ordered]
            },
        )

    async def abort_multipart(self, bucket: Bucket, key: str, *, upload_id: str) -> None:
        await asyncio.to_thread(
            self._client.abort_multipart_upload,
            Bucket=self._names[bucket],
            Key=key,
            UploadId=upload_id,
        )

    async def head(self, bucket: Bucket, key: str) -> StoredObject | None:
        try:
            response: Any = await asyncio.to_thread(
                self._client.head_object, Bucket=self._names[bucket], Key=key
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return StoredObject(
            key=key,
            size=int(response["ContentLength"]),
            content_type=response.get("ContentType"),
            etag=str(response["ETag"]).strip('"'),
        )

    async def presign_get(self, bucket: Bucket, key: str, *, ttl: timedelta = GET_TTL) -> str:
        return self._signer.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._names[bucket], "Key": key},
            ExpiresIn=int(ttl.total_seconds()),
        )

    def _expires(self, ttl: timedelta) -> datetime:
        return self._clock.now() + ttl
