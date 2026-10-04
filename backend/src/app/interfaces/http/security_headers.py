"""Заголовки безопасности ответов API (ARCHITECTURE §13.1, ASVS L2 V14.4 и V8.2; шаг 8.4).

API отдаёт только JSON, поэтому CSP запрещает всё: ответ нельзя ни исполнить, ни встроить во
фрейм, ни угадать ему другой тип. Исключение — Swagger UI на `/api/v1/docs` (не в проде): ему
нужны скрипты и стили, у него остаётся только запрет фреймов. Заголовок, который обработчик уже
поставил сам, не перезаписывается.

Ответы с персональными данными (запрос с Authorization) браузер и WebView не хранят:
`no-store`; с ETag — `private, no-cache`, чтобы условные запросы (If-None-Match) работали.
HSTS ставит и край Cloudflare; здесь — только по HTTPS (схему за прокси выбирает
ClientAddressMiddleware).
"""

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOCS_CSP = "frame-ancestors 'none'"
HSTS = "max-age=31536000"
"""Год, без includeSubDomains: поддомены (admin, cdn) живут своими правилами Cloudflare."""

COMMON = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, docs_path: str | None) -> None:
        self.app = app
        self.docs_path = docs_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        docs = self.docs_path is not None and path.startswith(self.docs_path)
        authorized = "authorization" in Headers(scope=scope)
        https = scope.get("scheme") == "https"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in COMMON.items():
                    headers.setdefault(name, value)
                headers.setdefault("Content-Security-Policy", DOCS_CSP if docs else API_CSP)
                if https:
                    headers.setdefault("Strict-Transport-Security", HSTS)
                if authorized and "cache-control" not in headers:
                    headers["Cache-Control"] = (
                        "private, no-cache" if "etag" in headers else "no-store"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)
