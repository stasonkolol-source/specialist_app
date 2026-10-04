// Mini App на Workers Static Assets (DEVELOPMENT_PLAN 0.25d, ADR-0012). Статику (apps/tma/dist
// с _headers: CSP, кэш) отдаёт сам Cloudflare, сюда приходят только /api/* — run_worker_first в
// wrangler.jsonc. Один origin для SPA и API: без CORS и preflight (ADR-0011, Bot API 10.2).
// API_ORIGIN — https://stage-api.<домен> (--var при wrangler deploy): прокси по TLS, путь и query
// без изменений, редиректы API — клиенту как есть.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith('/api/')) {
      return env.ASSETS.fetch(request);
    }
    if (!env.API_ORIGIN) {
      return new Response('API_ORIGIN is not configured', { status: 500 });
    }
    const upstream = new URL(url.pathname + url.search, env.API_ORIGIN);
    return fetch(new Request(upstream, request), { redirect: 'manual' });
  },
};
