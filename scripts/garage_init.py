"""make garage-init: ключ доступа, бакеты и CORS в локальном Garage (DEVELOPMENT_PLAN 0.3).

Ключи пишутся в backend/.env без вывода. Повторный запуск идемпотентен.
Запуск: uv run --no-project --with boto3 python scripts/garage_init.py
"""

from __future__ import annotations

import re
import subprocess
import sys

from envfile import ROOT, update

COMPOSE = [
    "docker", "compose", "-p", "specialist-dev",
    "-f", str(ROOT / "infra" / "compose" / "docker-compose.dev.yml"),
    "--env-file", str(ROOT / "infra" / "compose" / ".env"),
]
KEY_NAME = "dev-app"
BUCKETS = ("incoming", "media", "private")
ENDPOINT = "http://127.0.0.1:59100"
REGION = "garage"


def garage(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — фиксированная команда docker compose
        [*COMPOSE, "exec", "-T", "garage", "/garage", *args],
        capture_output=True, text=True, check=check,
    )


def ensure_key() -> tuple[str, str]:
    info = garage("key", "info", "--show-secret", KEY_NAME, check=False)
    if info.returncode != 0:
        garage("key", "create", KEY_NAME)
        info = garage("key", "info", "--show-secret", KEY_NAME)
    key_id = re.search(r"Key ID:\s*(\S+)", info.stdout)
    secret = re.search(r"Secret key:\s*(\S+)", info.stdout)
    if not key_id or not secret:
        sys.exit("garage-init: cannot parse key info (garage CLI output changed?)")
    return key_id.group(1), secret.group(1)


def ensure_buckets() -> None:
    for bucket in BUCKETS:
        created = garage("bucket", "create", bucket, check=False)
        if created.returncode != 0 and "already" not in (created.stderr + created.stdout).lower():
            sys.exit(f"garage-init: cannot create bucket {bucket}")
        garage("bucket", "allow", "--read", "--write", "--owner", bucket, "--key", KEY_NAME)


def ensure_cors(key_id: str, secret: str) -> None:
    import boto3  # только в этом скрипте, через uv run --with boto3

    s3 = boto3.client(
        "s3", endpoint_url=ENDPOINT, region_name=REGION,
        aws_access_key_id=key_id, aws_secret_access_key=secret,
    )
    rules = {
        "CORSRules": [{
            "AllowedOrigins": ["*"],
            "AllowedMethods": ["GET", "PUT", "HEAD"],
            "AllowedHeaders": ["*"],
            "ExposeHeaders": ["ETag"],
            "MaxAgeSeconds": 3600,
        }]
    }
    for bucket in ("incoming", "media"):
        s3.put_bucket_cors(Bucket=bucket, CORSConfiguration=rules)


def main() -> int:
    key_id, secret = ensure_key()
    ensure_buckets()
    ensure_cors(key_id, secret)
    changed = update(
        ROOT / "backend" / ".env",
        {
            "S3_ENDPOINT_URL": ENDPOINT,
            "S3_REGION": REGION,
            "S3_ACCESS_KEY_ID": key_id,
            "S3_SECRET_ACCESS_KEY": secret,
            "S3_BUCKET_INCOMING": "incoming",
            "S3_BUCKET_MEDIA": "media",
            "S3_BUCKET_PRIVATE": "private",
        },
        overwrite=True,
    )
    sys.stdout.write(f"garage-init: buckets {', '.join(BUCKETS)} ready; "
                     f"backend/.env {'updated ' + ', '.join(changed) if changed else 'unchanged'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
