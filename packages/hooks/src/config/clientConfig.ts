// Конфиг клиента (DEVELOPMENT_PLAN 1.1): GET /client-config — минимальные версии, флаги, версии
// правовых документов. Публичный, с ETag и max-age 60: браузер сам делает условный запрос.
import type { ClientConfigOut } from '@sosed/api-client';
import { useSystemGetClientConfig } from '@sosed/api-client';

export const CLIENT_CONFIG_STALE_MS = 60_000;

/** Флаги, которые читает фронтенд. Ключ — `<модуль>.<флаг>` (ADR-0020 §10). */
export const FLAGS = {
  /** Переключатель «Услуги / Вещи» на главной (ADR-0019: раздел «Вещи» после MVP, в MVP — S58). */
  goodsSegment: 'goods.segment',
} as const;

export type FlagKey = (typeof FLAGS)[keyof typeof FLAGS];

export function useClientConfig() {
  return useSystemGetClientConfig({ query: { staleTime: CLIENT_CONFIG_STALE_MS } });
}

/** Флаг включён только явным `true` с сервера: пока конфиг грузится или недоступен — выключен. */
export function useFlag(key: FlagKey): boolean {
  const { data } = useClientConfig();
  return data?.flags[key] === true;
}

export type UpdateNeeded = 'telegram' | 'app' | null;

/** Минимальный Bot API клиента, если сервер не задал `min_versions.telegram`: фолбэки
 *  packages/platform опираются на CloudStorage и requestContact (6.9). */
export const DEFAULT_MIN_TELEGRAM = '6.9';

export interface ClientVersions {
  /** Версия Mini App (`X-Client: tma/<версия>`). */
  app: string;
  /** Bot API клиента Telegram; `null` — вне Telegram (браузер), проверка не нужна. */
  telegram: string | null;
}

/** Что обновить, чтобы продолжить: клиент Telegram, бандл Mini App (перезагрузка) или ничего. */
export function requiredUpdate(
  config: ClientConfigOut | undefined,
  versions: ClientVersions,
): UpdateNeeded {
  const minTelegram = config?.min_versions.telegram ?? DEFAULT_MIN_TELEGRAM;
  if (versions.telegram !== null && compareVersions(versions.telegram, minTelegram) < 0) {
    return 'telegram';
  }
  const minApp = config?.min_versions.tma;
  if (minApp && compareVersions(versions.app, minApp) < 0) return 'app';
  return null;
}

/** Сравнение версий `x.y.z` по числам: `1.10` больше `1.9`. */
export function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const diff = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (diff !== 0) return Math.sign(diff);
  }
  return 0;
}
