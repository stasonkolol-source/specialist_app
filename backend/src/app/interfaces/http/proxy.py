"""Адрес клиента за прокси (ARCHITECTURE §13.3, §16.3; DEVELOPMENT_PLAN 8.4).

Цепочка в проде: клиент → Cloudflare → kamal-proxy → web. Раньше адрес брал uvicorn с
`forwarded_allow_ips="*"`: при таком доверии он берёт ЛЕВЫЙ адрес X-Forwarded-For, а его пишет
сам клиент — лимиты `/auth/*` и гостевого поиска по IP обходились подменой заголовка.

Теперь uvicorn заголовкам не верит, а адрес выбирает этот middleware:
1. Соединение не от нашего прокси (`trusted_proxies`) — адрес соединения, заголовки не читаем.
2. Иначе идём по X-Forwarded-For справа налево и пропускаем свои прокси: первый чужой адрес —
   тот, кто подключился к kamal-proxy. Правые записи дописывают наши прокси, левые — кто угодно,
   поэтому левее первого чужого не смотрим.
3. Это край Cloudflare — клиент в CF-Connecting-IP: Cloudflare перезаписывает его всегда.
   Не край (обход Cloudflare по адресу origin, cloudflared локально) — сам этот адрес.

Схему (X-Forwarded-Proto) тоже принимаем только от своих прокси: TLS снимает kamal-proxy.
"""

from collections.abc import Sequence
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

Address = IPv4Address | IPv6Address
Network = IPv4Network | IPv6Network


def parse_ip(raw: str | None) -> Address | None:
    """Адрес из заголовка или соединения; IPv4 внутри IPv6 (::ffff:1.2.3.4) — как IPv4."""
    if not raw:
        return None
    try:
        address = ip_address(raw.strip())
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _within(address: Address, networks: Sequence[Network]) -> bool:
    return any(address.version == net.version and address in net for net in networks)


def resolve_client(
    peer: str | None,
    headers: Headers,
    *,
    trusted_proxies: Sequence[Network],
    cloudflare: Sequence[Network],
) -> str | None:
    """Адрес клиента по правилам модуля; None — адреса нет (соединение без адреса)."""
    peer_ip = parse_ip(peer)
    if peer_ip is None or not _within(peer_ip, trusted_proxies):
        return peer
    hop = _first_untrusted_hop(headers, peer_ip, trusted_proxies)
    if _within(hop, cloudflare):
        connecting = parse_ip(headers.get("cf-connecting-ip"))
        return str(connecting or hop)
    return str(hop)


def _first_untrusted_hop(
    headers: Headers, peer_ip: Address, trusted_proxies: Sequence[Network]
) -> Address:
    """Кто подключился к нашему прокси: первый справа адрес X-Forwarded-For не из своих.
    Одни свои прокси — запрос изнутри, берём самый левый; заголовка нет — адрес соединения."""
    hops = [hop for value in headers.getlist("x-forwarded-for") for hop in value.split(",")]
    found = peer_ip
    for raw in reversed(hops):
        hop = parse_ip(raw)
        if hop is None:
            # правее первого чужого адреса пишут только наши прокси: мусор — цепочке не верим
            return peer_ip
        found = hop
        if not _within(hop, trusted_proxies):
            break
    return found


class ClientAddressMiddleware:
    """Подменяет `scope["client"]` и `scope["scheme"]` настоящими (см. модуль). Внешний слой
    приложения: лимиты, журнал согласий и всё остальное видят уже правильный адрес."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        trusted_proxies: Sequence[Network],
        cloudflare: Sequence[Network],
    ) -> None:
        self.app = app
        self.trusted_proxies = tuple(trusted_proxies)
        self.cloudflare = tuple(cloudflare)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            peer, port = client if client else (None, 0)
            headers = Headers(scope=scope)
            host = resolve_client(
                peer, headers, trusted_proxies=self.trusted_proxies, cloudflare=self.cloudflare
            )
            if host is not None and host != peer:
                scope["client"] = (host, port)
            peer_ip = parse_ip(peer)
            if peer_ip is not None and _within(peer_ip, self.trusted_proxies):
                proto = headers.get("x-forwarded-proto", "").rsplit(",", 1)[-1].strip().lower()
                if proto in ("http", "https"):
                    scope["scheme"] = proto if scope["type"] == "http" else _ws(proto)
        await self.app(scope, receive, send)


def _ws(proto: str) -> str:
    return "wss" if proto == "https" else "ws"
