// Системные состояния S49 (DEVELOPMENT_PLAN 1.5a): какую ошибку как показать. Решение принимается
// здесь, по типам ошибок mutator api-client, а экраны только рисуют: одно правило на Mini App и
// будущее мобильное приложение.
import type { ClientConfigOut } from '@sosed/api-client';
import {
  ApiError,
  MaintenanceError,
  NetworkError,
  RestrictedError,
  UpgradeRequiredError,
} from '@sosed/api-client';

import type { ClientVersions } from '../config/clientConfig.ts';
import { FLAGS, requiredUpdate } from '../config/clientConfig.ts';

/** Виды санкций identity (RestrictionKind backend). */
export type Restriction =
  'posting_blocked' | 'responding_blocked' | 'messaging_blocked' | 'suspended' | 'banned';

/** Санкции, которые закрывают весь аккаунт: вход и любое действие (ADR-0009). */
export const ACCOUNT_BLOCKING: readonly Restriction[] = ['suspended', 'banned'];

const RESTRICTIONS: readonly string[] = [
  'posting_blocked',
  'responding_blocked',
  'messaging_blocked',
  'suspended',
  'banned',
];

export function isRestriction(value: unknown): value is Restriction {
  return typeof value === 'string' && RESTRICTIONS.includes(value);
}

export type SystemState =
  /** S49a: нет сети — «Повторить». */
  | { kind: 'offline' }
  /** Техработы: 503 `maintenance` или флаг `platform.maintenance` в client-config. */
  | { kind: 'maintenance' }
  /** Обновить Telegram (Bot API ниже минимума) или перезагрузить бандл Mini App (426). */
  | { kind: 'update'; target: 'telegram' | 'app' }
  /** S49b: 403 `restricted`. `restriction: null` — вид санкции клиенту неизвестен. */
  | { kind: 'restricted'; restriction: Restriction | null; until: Date | null; blocking: boolean }
  /** Прочее: «Что-то пошло не так» с повтором. */
  | { kind: 'error'; traceId: string | null };

/** Состояние S49 для ошибки запроса или рендера. */
export function systemStateOf(error: unknown): SystemState {
  if (error instanceof NetworkError) return { kind: 'offline' };
  if (error instanceof MaintenanceError) return { kind: 'maintenance' };
  if (error instanceof UpgradeRequiredError) return { kind: 'update', target: 'app' };
  if (error instanceof RestrictedError) {
    const restriction = isRestriction(error.restriction) ? error.restriction : null;
    return {
      kind: 'restricted',
      restriction,
      until: error.until,
      blocking: restriction !== null && ACCOUNT_BLOCKING.includes(restriction),
    };
  }
  return { kind: 'error', traceId: error instanceof ApiError ? error.traceId : null };
}

/** Состояния, которые закрывают всё приложение, а не один экран. */
export function isAppWide(state: SystemState): boolean {
  return (
    state.kind === 'maintenance' ||
    state.kind === 'update' ||
    (state.kind === 'restricted' && state.blocking)
  );
}

/** Что показать при старте по client-config: обновление важнее техработ. */
export function startupState(
  config: ClientConfigOut | undefined,
  versions: ClientVersions,
): SystemState | null {
  const update = requiredUpdate(config, versions);
  if (update) return { kind: 'update', target: update };
  if (config?.flags[FLAGS.maintenance] === true) return { kind: 'maintenance' };
  return null;
}
