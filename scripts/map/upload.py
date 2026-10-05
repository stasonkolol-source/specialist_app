"""make map-upload ENV=stage|prod: ассеты карты в бакет media окружения (R2, EU) под map/<версия>/.

CDN окружения (stage-cdn.<домен>, cdn.<домен>) отдаёт их с HTTP Range — его требует PMTiles, а
статика Workers Mini App диапазоны не отдаёт (scripts/map/README.md). Версия — сборка Protomaps из
provenance.json; её же владелец ставит в Variable MAP_ASSETS_VERSION, и сборка Mini App берёт
адрес https://<cdn>/map/<версия>. Адрес не меняется, поэтому кэш — год и immutable, а объект с тем
же ключом и другим содержимым не перезаписывается: WebView мог закэшировать старый — нужна новая
версия (--version). Одинаковые файлы пропускаются (ETag = MD5), повторный запуск ничего не портит.

Окружение: R2_ACCOUNT_ID (или CLOUDFLARE_ACCOUNT_ID), S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY —
ключи R2 этого окружения (K13, менеджер паролей). Значения не печатаются.
Запуск: uv run --no-project --with boto3==… python scripts/map/upload.py --env stage
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "apps" / "tma" / "public" / "map"
# имена бакетов — infra/terraform/{stage,prod} (r2_bucket_prefix) и infra/kamal (S3_BUCKET_MEDIA)
BUCKETS = {"stage": "sosed-stage-media", "prod": "sosed-prod-media"}
CDN = {"stage": "https://stage-cdn.<домен>", "prod": "https://cdn.<домен>"}
IMMUTABLE = "public, max-age=31536000, immutable"
TYPES = {
    ".pmtiles": "application/vnd.pmtiles",
    ".pbf": "application/x-protobuf",
    ".json": "application/json",
    ".png": "image/png",
    ".txt": "text/plain; charset=utf-8",
}
PROVENANCE = "provenance.json"
"""Справка, а не ассет: дата сборки в нём меняется — перезаписывается и кэшируется ненадолго."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", choices=sorted(BUCKETS), required=True)
    parser.add_argument("--src", type=Path, default=SOURCE, help="каталог make map-assets")
    parser.add_argument("--version", help="по умолчанию — сборка Protomaps из provenance.json")
    args = parser.parse_args()

    provenance = json.loads((args.src / PROVENANCE).read_text(encoding="utf-8"))
    version = args.version or provenance["inputs"]["protomaps_build"]
    account = os.environ.get("R2_ACCOUNT_ID") or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    missing = [
        name
        for name, value in (
            ("R2_ACCOUNT_ID", account),
            ("S3_ACCESS_KEY_ID", os.environ.get("S3_ACCESS_KEY_ID")),
            ("S3_SECRET_ACCESS_KEY", os.environ.get("S3_SECRET_ACCESS_KEY")),
        )
        if not value
    ]
    if missing:
        sys.exit(f"map-upload: set {', '.join(missing)} in the environment (not printed)")

    s3 = boto3.client(
        "s3",
        # бакеты в EU jurisdiction (ADR-0007) — у них свой S3-адрес
        endpoint_url=f"https://{account}.eu.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        # без CRC-заголовков новых boto3, как в platform/storage/s3.py
        config=Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
    bucket = BUCKETS[args.env]
    uploaded = skipped = 0
    for path in sorted(p for p in args.src.rglob("*") if p.is_file()):
        name = path.relative_to(args.src).as_posix()
        key = f"map/{version}/{name}"
        body = path.read_bytes()
        try:
            etag = s3.head_object(Bucket=bucket, Key=key)["ETag"].strip('"')
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                raise
            etag = None
        if etag == hashlib.md5(body, usedforsecurity=False).hexdigest():
            skipped += 1
            continue
        if etag is not None and name != PROVENANCE:
            sys.exit(f"map-upload: {key} exists with other content — upload as a new --version")
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=TYPES.get(path.suffix, "application/octet-stream"),
            CacheControl="public, max-age=300" if name == PROVENANCE else IMMUTABLE,
        )
        uploaded += 1
    sys.stdout.write(
        f"map-upload: {bucket}/map/{version}/ — uploaded {uploaded}, unchanged {skipped}\n"
        f"  Variable environment {'production' if args.env == 'prod' else 'stage'}: "
        f"MAP_ASSETS_VERSION={version}\n"
        f"  Mini App: VITE_MAP_ASSETS_URL={CDN[args.env]}/map/{version}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
