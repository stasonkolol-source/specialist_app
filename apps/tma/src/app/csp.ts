// Content-Security-Policy Mini App (DEVELOPMENT_PLAN 0.21a). Заголовок ставит сервер: в разработке —
// Vite, на stage и prod — Cloudflare Workers (0.25d). frame-ancestors в <meta> не работает.

export interface CspOptions {
  /** Разработка: Vite вставляет inline-скрипт react-refresh и стили, HMR идёт по WebSocket. */
  dev: boolean;
  /** CDN медиа (R2 за Cloudflare). */
  mediaOrigins: readonly string[];
  /** S3 API хранилища (R2, в dev — туннель Garage): PUT по presigned-ссылкам и превью по
   *  presigned GET (0.24). */
  storageOrigins?: readonly string[];
  /** DSN Sentry фронта (VITE_SENTRY_DSN, 3.3): SDK шлёт события на адрес приёма из DSN — в
   *  connect-src ровно его origin. Без DSN SDK не грузится, и адреса в CSP нет. */
  sentryDsn?: string;
  /** База ассетов карты (VITE_MAP_ASSETS_URL, Q28, scripts/map/README.md). MapLibre запускает
   *  воркеры из blob: — worker-src (и child-src); тайлы PMTiles (Range), глифы и спрайт — fetch, в
   *  connect-src origin адреса, если он чужой (stage, prod: CDN R2). Путь от корня (`/map` в dev)
   *  — свой origin. Пусто — карты нет, и CSP та же, что без неё. */
  mapAssetsUrl?: string;
}

const SELF = "'self'";

/** Telegram Web (web.telegram.org) открывает Mini App во фрейме; нативные клиенты — в WebView. */
export const FRAME_ANCESTORS = ['https://web.telegram.org'] as const;

/** Origin приёма из DSN `https://<ключ>@o<орг>.ingest.de.sentry.io/<проект>`: SDK шлёт конверты на
 *  `/api/<проект>/envelope/` этого хоста, а не на *.sentry.io. Ключ и проект в CSP не попадают.
 *  Кривой DSN роняет сборку: иначе CSP молча отрезала бы события. */
export function sentryIngestOrigin(dsn: string): string {
  let origin: string | undefined;
  try {
    const url = new URL(dsn);
    // протоколы — как у SDK: другие он не примет
    if (url.protocol === 'https:' || url.protocol === 'http:') origin = url.origin;
  } catch {
    // не URL — та же ошибка ниже
  }
  // текст без самого DSN: логи CI публичного репозитория видны всем
  if (!origin) throw new Error('VITE_SENTRY_DSN: ожидается https://<ключ>@<хост приёма>/<проект>');
  return origin;
}

/** Origin ассетов карты: у абсолютного адреса — его origin, у пути от корня — null (свой origin).
 *  Кривой адрес роняет сборку: иначе CSP молча отрезала бы карту. */
export function mapAssetsOrigin(url: string): string | null {
  if (url.startsWith('/') && !url.startsWith('//')) return null;
  let origin: string | undefined;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === 'https:' || parsed.protocol === 'http:') origin = parsed.origin;
  } catch {
    // не URL — та же ошибка ниже
  }
  if (!origin) throw new Error('VITE_MAP_ASSETS_URL: ожидается https://<хост>/<путь> или /<путь>');
  return origin;
}

export function contentSecurityPolicy({
  dev,
  mediaOrigins,
  storageOrigins = [],
  sentryDsn,
  mapAssetsUrl,
}: CspOptions): string {
  const errorReporting = sentryDsn ? [sentryIngestOrigin(sentryDsn)] : [];
  const map = mapAssetsUrl?.trim();
  const mapOrigin = map ? mapAssetsOrigin(map) : null;
  const directives: Record<string, readonly string[]> = {
    'default-src': [SELF],
    'script-src': dev ? [SELF, "'unsafe-inline'"] : [SELF],
    'style-src': dev ? [SELF, "'unsafe-inline'"] : [SELF],
    // спрайт карты MapLibre качает fetch и рисует через ImageBitmap или blob: — хоста карты здесь нет
    'img-src': [SELF, 'data:', 'blob:', ...mediaOrigins, ...storageOrigins],
    'media-src': [SELF, 'blob:', ...mediaOrigins, ...storageOrigins],
    'font-src': [SELF],
    'connect-src': [
      SELF,
      ...(dev ? ['ws:', 'wss:'] : []),
      ...storageOrigins,
      ...(mapOrigin ? [mapOrigin] : []),
      ...errorReporting,
    ],
    // воркеры MapLibre — из blob:; Safari до 15.5 не знает worker-src и берёт child-src
    ...(map ? { 'worker-src': [SELF, 'blob:'], 'child-src': [SELF, 'blob:'] } : {}),
    'frame-ancestors': FRAME_ANCESTORS,
    'base-uri': [SELF],
    'form-action': [SELF],
    'object-src': ["'none'"],
  };
  return Object.entries(directives)
    .map(([name, values]) => `${name} ${values.join(' ')}`)
    .join('; ');
}
