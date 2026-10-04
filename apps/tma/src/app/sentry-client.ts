// Ленивый чанк Sentry (DEVELOPMENT_PLAN 3.3): его грузит app/sentry.ts после первого экрана и
// только при DSN. Релиз и окружение задаёт сборка (deploy.yml): релиз — sha деплоя, как APP_RELEASE
// backend, — по нему Sentry находит source maps; локально и в e2e — dev.
import type { Breadcrumb, BrowserOptions, ErrorEvent } from '@sentry/react';
import { init } from '@sentry/react';

/** initData Telegram в адресе (`#tgWebAppData=…`, `?initData=…`, в том числе внутри закодированного
 *  адреса): если вход не удался, роутер hash не заменяет, и он остаётся в location.href. */
const LAUNCH_DATA = /(tgWebAppData|initData)(=|%3D)[^&#\s]*/gi;
/** Сама строка initData (`query_id=…&user=…&auth_date=…&hash=…`) — как в backend masking.py. */
const RAW_INIT_DATA =
  /(?:query_id|user|auth_date|signature|hash|chat_instance)=[^&\s]+(?:&[^&\s]+)*/g;

export function scrubText(text: string): string {
  return text.replace(LAUNCH_DATA, '$1$2[Filtered]').replace(RAW_INIT_DATA, '[init-data]');
}

/** Крошки с адресом: navigation (from, to), xhr и fetch (url), console (message). Аргументы console
 *  не трогаем — это живые объекты приложения; в событие они попадут уже через beforeSend. */
function scrubBreadcrumb(breadcrumb: Breadcrumb): Breadcrumb {
  if (breadcrumb.message) breadcrumb.message = scrubText(breadcrumb.message);
  const data = breadcrumb.data;
  for (const key of ['url', 'from', 'to']) {
    const value: unknown = data?.[key];
    if (data && typeof value === 'string') data[key] = scrubText(value);
  }
  return breadcrumb;
}

/** Каждая строка события (request.url, Referer, крошки, тексты исключений, кадры стека): к
 *  beforeSend SDK его уже нормализовал, JSON-копия безопасна. Служебные sdkProcessingMetadata (в
 *  них бывают объекты Scope) SDK не отправляет — их не копируем. Чистка не удалась — события нет. */
function scrubEvent(event: ErrorEvent): ErrorEvent | null {
  const { sdkProcessingMetadata, ...sent } = event;
  try {
    const clean = JSON.parse(JSON.stringify(sent), (_key, value: unknown) =>
      typeof value === 'string' ? scrubText(value) : value,
    ) as ErrorEvent;
    return { ...clean, sdkProcessingMetadata };
  } catch {
    return null;
  }
}

export function sentryOptions(dsn: string): BrowserOptions {
  return {
    dsn,
    release: import.meta.env.VITE_SENTRY_RELEASE || 'dev',
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || 'dev',
    sendDefaultPii: false,
    tracesSampleRate: 0,
    beforeBreadcrumb: scrubBreadcrumb,
    beforeSend: scrubEvent,
  };
}

export function startSentry(dsn: string): void {
  init(sentryOptions(dsn));
}
