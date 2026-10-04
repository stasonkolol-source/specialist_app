"""Адрес клиента за прокси и заголовки безопасности API (DEVELOPMENT_PLAN 8.4, ARCHITECTURE §13).

Цепочка прода: клиент → Cloudflare → kamal-proxy → web. Клиент пишет в X-Forwarded-For что
угодно — лимиты по IP не должны этому верить.
"""

from collections.abc import AsyncIterator
from ipaddress import ip_network

import httpx
import pytest
from fastapi import Request, Response
from starlette.datastructures import Headers

from app.interfaces.http.proxy import resolve_client
from app.interfaces.http.security_headers import API_CSP, FRAME_CSP
from app.platform.settings import CLOUDFLARE_IPS, PRIVATE_NETWORKS, Settings
from tests.plugins.http import http_client, sample_router

pytestmark = pytest.mark.unit

KAMAL_PROXY = "172.18.0.2"
CF_EDGE = "162.158.90.17"
VISITOR = "93.87.12.34"
SPOOFED = "1.2.3.4"

router = sample_router()


@router.get("/whoami")
async def whoami(request: Request) -> dict[str, str | None]:
    return {
        "ip": request.client.host if request.client else None,
        "scheme": request.url.scheme,
    }


@router.get("/tagged")
async def tagged(response: Response) -> dict[str, str]:
    response.headers["ETag"] = '"v1"'
    return {}


@router.get("/cached")
async def cached(response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "private, max-age=60"
    return {}


def _resolve(peer: str, headers: dict[str, str]) -> str | None:
    return resolve_client(
        peer, Headers(headers), trusted_proxies=PRIVATE_NETWORKS, cloudflare=CLOUDFLARE_IPS
    )


@pytest.mark.parametrize(
    ("peer", "headers", "expected"),
    [
        # прод, kamal-proxy пишет свой X-Forwarded-For: подключился край Cloudflare
        (KAMAL_PROXY, {"x-forwarded-for": CF_EDGE, "cf-connecting-ip": VISITOR}, VISITOR),
        # kamal-proxy дописывает цепочку: слева подделка клиента, правее — запись Cloudflare
        (
            KAMAL_PROXY,
            {"x-forwarded-for": f"{SPOOFED}, {VISITOR}, {CF_EDGE}", "cf-connecting-ip": VISITOR},
            VISITOR,
        ),
        # обход Cloudflare по адресу origin: CF-Connecting-IP подделан, верим только соединению
        (
            KAMAL_PROXY,
            {"x-forwarded-for": f"{SPOOFED}, {VISITOR}", "cf-connecting-ip": SPOOFED},
            VISITOR,
        ),
        # cloudflared на loopback (стенд разработки): Cloudflare уже дописал посетителя справа
        ("127.0.0.1", {"x-forwarded-for": f"{SPOOFED}, {VISITOR}"}, VISITOR),
        # клиент подключился напрямую: заголовки не читаем вовсе
        (VISITOR, {"x-forwarded-for": SPOOFED, "cf-connecting-ip": SPOOFED}, VISITOR),
        # подделка «я свой» левее настоящего адреса не помогает
        (KAMAL_PROXY, {"x-forwarded-for": f"10.0.0.5, {VISITOR}"}, VISITOR),
        # край Cloudflare без CF-Connecting-IP — адрес края, но не подделка
        (KAMAL_PROXY, {"x-forwarded-for": f"{SPOOFED}, {CF_EDGE}"}, CF_EDGE),
        # мусор в правой части цепочки — адрес нашего прокси, а не слова клиента
        (KAMAL_PROXY, {"x-forwarded-for": f"{SPOOFED}, not-an-ip"}, KAMAL_PROXY),
        # запрос изнутри сети через прокси
        (KAMAL_PROXY, {"x-forwarded-for": "10.0.0.7"}, "10.0.0.7"),
        (KAMAL_PROXY, {}, KAMAL_PROXY),
        # IPv6 край и IPv4 внутри IPv6
        (
            KAMAL_PROXY,
            {"x-forwarded-for": "2a06:98c1::1", "cf-connecting-ip": "2a02:1::5"},
            "2a02:1::5",
        ),
        ("::ffff:172.18.0.2", {"x-forwarded-for": VISITOR}, VISITOR),
    ],
)
def test_client_address_ignores_what_the_client_wrote(
    peer: str, headers: dict[str, str], expected: str
) -> None:
    assert _resolve(peer, headers) == expected


def test_several_forwarded_for_headers_form_one_chain() -> None:
    headers = Headers(
        raw=[(b"x-forwarded-for", SPOOFED.encode()), (b"x-forwarded-for", VISITOR.encode())]
    )
    assert (
        resolve_client(
            KAMAL_PROXY, headers, trusted_proxies=PRIVATE_NETWORKS, cloudflare=CLOUDFLARE_IPS
        )
        == VISITOR
    )


def test_trusted_proxies_are_configurable() -> None:
    # без своих прокси в списке даже loopback — обычный клиент
    resolved = resolve_client(
        "127.0.0.1",
        Headers({"x-forwarded-for": SPOOFED}),
        trusted_proxies=[ip_network("172.18.0.0/16")],
        cloudflare=CLOUDFLARE_IPS,
    )
    assert resolved == "127.0.0.1"


@pytest.fixture
def proxy_client_ip() -> str:
    return KAMAL_PROXY


@pytest.fixture
async def client(
    offline_settings: Settings, proxy_client_ip: str
) -> AsyncIterator[httpx.AsyncClient]:
    async with http_client(offline_settings, router, client_ip=proxy_client_ip) as client:
        yield client


async def test_app_sees_the_real_client_behind_cloudflare(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/test/whoami",
        headers={
            "x-forwarded-for": f"{SPOOFED}, {VISITOR}, {CF_EDGE}",
            "cf-connecting-ip": VISITOR,
            "x-forwarded-proto": "https",
        },
    )
    assert response.json() == {"ip": VISITOR, "scheme": "https"}
    assert response.headers["strict-transport-security"] == "max-age=31536000"


@pytest.mark.parametrize("proxy_client_ip", [VISITOR])
async def test_direct_client_cannot_spoof_address_or_scheme(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/test/whoami",
        headers={
            "x-forwarded-for": SPOOFED,
            "cf-connecting-ip": SPOOFED,
            "x-forwarded-proto": "https",
        },
    )
    assert response.json() == {"ip": VISITOR, "scheme": "http"}
    assert "strict-transport-security" not in response.headers


async def test_api_responses_carry_security_headers(client: httpx.AsyncClient) -> None:
    for path in ("/api/v1/test/whoami", "/api/v1/nope", "/up"):
        response = await client.get(path)
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
    assert (await client.get("/api/v1/nope")).headers["content-security-policy"] == API_CSP
    # вне API (healthcheck, будущий SQLAdmin) — свои страницы, только запрет фреймов
    assert (await client.get("/up")).headers["content-security-policy"] == FRAME_CSP


async def test_swagger_ui_keeps_its_scripts_but_not_frames(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/docs")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == FRAME_CSP


async def test_personal_responses_are_not_stored(client: httpx.AsyncClient) -> None:
    auth = {"authorization": "Bearer x"}
    assert (await client.get("/api/v1/test/whoami", headers=auth)).headers[
        "cache-control"
    ] == "no-store"
    tagged = await client.get("/api/v1/test/tagged", headers=auth)
    assert tagged.headers["cache-control"] == "private, no-cache"
    cached = await client.get("/api/v1/test/cached", headers=auth)
    assert cached.headers["cache-control"] == "private, max-age=60"
    # публичный ответ без Authorization политику кэша выбирает сам
    assert "cache-control" not in (await client.get("/api/v1/test/whoami")).headers
