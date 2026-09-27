"""Denylist сессий в Valkey (DEVELOPMENT_PLAN 0.14, ADR-0009)."""

import pytest
from redis.asyncio import Redis

from app.entrypoints._wiring import make_web_container
from app.platform.kernel.ids import new_id
from app.platform.security.denylist import SessionDenylist
from app.platform.settings import Settings

pytestmark = pytest.mark.integration


async def test_revoked_session_is_denied_for_access_ttl(settings: Settings) -> None:
    container = make_web_container(settings)
    try:
        denylist = await container.get(SessionDenylist)
        revoked, other = new_id().hex, new_id().hex
        await denylist.revoke(revoked)

        assert await denylist.is_revoked(revoked)
        assert not await denylist.is_revoked(other)
        ttl = await (await container.get(Redis)).ttl(f"auth:revoked:{revoked}")
        assert settings.jwt.access_ttl_seconds - 5 <= ttl <= settings.jwt.access_ttl_seconds
    finally:
        await container.close()
