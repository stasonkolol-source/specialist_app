// Content-Security-Policy Mini App (DEVELOPMENT_PLAN 0.21a). Заголовок ставит сервер: в разработке —
// Vite, на stage и prod — Cloudflare Workers (0.25d). frame-ancestors в <meta> не работает.

export interface CspOptions {
  /** Разработка: Vite вставляет inline-скрипт react-refresh и стили, HMR идёт по WebSocket. */
  dev: boolean;
  /** CDN медиа (R2 за Cloudflare); хост тайлов карты добавится в 5.2 (Q28). */
  mediaOrigins: readonly string[];
}

const SELF = "'self'";

/** Telegram Web (web.telegram.org) открывает Mini App во фрейме; нативные клиенты — в WebView. */
export const FRAME_ANCESTORS = ['https://web.telegram.org'] as const;

export function contentSecurityPolicy({ dev, mediaOrigins }: CspOptions): string {
  const directives: Record<string, readonly string[]> = {
    'default-src': [SELF],
    'script-src': dev ? [SELF, "'unsafe-inline'"] : [SELF],
    'style-src': dev ? [SELF, "'unsafe-inline'"] : [SELF],
    'img-src': [SELF, 'data:', 'blob:', ...mediaOrigins],
    'font-src': [SELF],
    'connect-src': dev ? [SELF, 'ws:', 'wss:'] : [SELF],
    'frame-ancestors': FRAME_ANCESTORS,
    'base-uri': [SELF],
    'form-action': [SELF],
    'object-src': ["'none'"],
  };
  return Object.entries(directives)
    .map(([name, values]) => `${name} ${values.join(' ')}`)
    .join('; ');
}
