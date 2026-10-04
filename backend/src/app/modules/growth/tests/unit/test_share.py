"""Ссылка «Поделиться» (DEVELOPMENT_PLAN 7.4): код экрана и суффикс `_r` — тем же кодеком, что
разбирает атрибуция; код приглашения — без `_`."""

import re

import pytest

from app.modules.growth.domain.attribution import AttributionSource, FirstTouch
from app.modules.growth.domain.share import (
    REFERRAL_CODE_LENGTH,
    new_referral_code,
    share_start_param,
    share_url,
)
from app.platform.contracts.events.identity import EntryPoint
from app.platform.kernel.ids import new_id
from app.platform.telegram.deeplinks import (
    START_PARAM_MAX_LENGTH,
    LinkType,
    parse_start_param,
)

pytestmark = pytest.mark.unit


def test_referral_code_is_alphanumeric() -> None:
    codes = {new_referral_code() for _ in range(50)}
    assert len(codes) == 50
    assert all(re.fullmatch(rf"[A-Za-z0-9]{{{REFERRAL_CODE_LENGTH}}}", code) for code in codes)


@pytest.mark.parametrize(
    ("link_type", "source"),
    [(LinkType.SPECIALIST, AttributionSource.SPECIALIST), (LinkType.JOB, AttributionSource.JOB)],
)
def test_shared_link_brings_the_sharer_code_to_attribution(
    link_type: LinkType, source: AttributionSource
) -> None:
    entity_id, ref = new_id(), new_referral_code()
    code = share_start_param(link_type, entity_id, ref=ref)

    assert len(code) <= START_PARAM_MAX_LENGTH
    link = parse_start_param(code)
    assert link is not None
    assert (link.type, link.id, link.ref) == (link_type, entity_id, ref)
    touch = FirstTouch.of(code, entry_point=EntryPoint.MINI_APP)
    assert (touch.source, touch.referral_code) == (source, ref)


def test_guest_link_has_no_suffix() -> None:
    entity_id = new_id()
    code = share_start_param(LinkType.JOB, entity_id, ref=None)
    assert code.startswith("j_")
    assert "_r" not in code.removeprefix("j_")
    assert share_url("sosed_rs_bot", code) == f"https://t.me/sosed_rs_bot?startapp={code}"
