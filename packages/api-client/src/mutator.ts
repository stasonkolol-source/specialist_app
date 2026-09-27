// Mutator orval: единственное место, где Mini App ходит в сеть (DEVELOPMENT_PLAN 0.20, ADR-0009).
//
// - Пути уже содержат /api/v1 (контракт backend/openapi.json); origin — тот же, что у Mini App.
// - Токены живут только в памяти процесса: ни localStorage, ни cookies.
// - Заголовки: Accept-Language, X-Client, Authorization: Bearer, Idempotency-Key для POST.
// - 401 token_expired → одно обновление на все параллельные запросы (single-flight) и повтор;
//   не вышло или сессия отозвана → колбэк onReauth от apps/tma (новый обмен initData через
//   packages/platform: сам api-client от platform не зависит).
// - 403 restricted, 426, 429 → типизированные ошибки; 429 с коротким Retry-After — ждём и повторяем.
import type { ApiError } from './errors.ts';
import { NetworkError, RateLimitedError, errorFromProblem, syntheticProblem } from './errors.ts';
import type { ProblemOut, TokensOut } from './generated/model/index.ts';

/** Тип ошибки хуков orval: ApiError с телом ProblemOut из схемы операции. */
export type ErrorType<Problem> = ApiError & { readonly problem: Problem };

export interface Session {
  accessToken: string;
  refreshToken: string;
}

export interface ApiClientConfig {
  /** Origin API; пусто — тот же origin, что у страницы (Mini App и /api за одним доменом). */
  baseUrl: string;
  /** Значение X-Client: `tma/1.3.0`. */
  client: string;
  /** Язык ответа (ru | sr-Latn | sr-Cyrl | en). */
  locale: () => string;
  /** Сессия потеряна: вернуть true, если приложение вошло заново и запрос можно повторить. */
  onReauth: () => Promise<boolean>;
  /** Дольше не ждём повтора после 429, а отдаём RateLimitedError (секунды). */
  maxRetryAfter: number;
  fetch: typeof fetch;
  /** Задержка перед повтором после 429 (в тестах — мгновенная). */
  sleep: (ms: number) => Promise<void>;
}

const AUTH_PATHS = ['/api/v1/auth/telegram', '/api/v1/auth/refresh'];
const REFRESH_PATH = '/api/v1/auth/refresh';
const REFRESH_CODES = new Set(['token_expired']);

const defaults: ApiClientConfig = {
  baseUrl: '',
  client: 'tma/0.0.0',
  locale: () => 'ru',
  onReauth: async () => false,
  maxRetryAfter: 10,
  fetch: (...args) => globalThis.fetch(...args),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
};

let config: ApiClientConfig = defaults;
let session: Session | null = null;
let refreshing: Promise<boolean> | null = null;

export const configureApiClient = (overrides: Partial<ApiClientConfig>): void => {
  config = { ...defaults, ...overrides };
};

export const setSession = (next: Session | null): void => {
  session = next;
};

export const getSession = (): Session | null => session;

/** Сбросить состояние между тестами. */
export const resetApiClient = (): void => {
  config = defaults;
  session = null;
  refreshing = null;
};

export const apiFetch = async <T>(url: string, init: RequestInit = {}): Promise<T> => {
  const headers = new Headers(init.headers);
  const method = (init.method ?? 'GET').toUpperCase();
  const isAuth = AUTH_PATHS.includes(url);
  if (method === 'POST' && !isAuth && !headers.has('Idempotency-Key')) {
    // один ключ на все повторы этого вызова: сервер не создаст ресурс дважды
    headers.set('Idempotency-Key', crypto.randomUUID());
  }
  return send<T>(url, { ...init, method, headers }, { isAuth, reauthed: false, waited: false });
};

interface Attempt {
  isAuth: boolean;
  reauthed: boolean;
  waited: boolean;
}

const send = async <T>(url: string, init: RequestInit, attempt: Attempt): Promise<T> => {
  const response = await request(url, init, attempt.isAuth);
  if (response.ok) return parseBody<T>(response);

  const problem = await parseProblem(response);
  if (response.status === 401 && !attempt.isAuth && !attempt.reauthed) {
    const renewed = REFRESH_CODES.has(problem.code) && (await refreshOnce());
    if (renewed || (await config.onReauth())) {
      return send<T>(url, init, { ...attempt, reauthed: true });
    }
  }
  const retryAfter = retryAfterSeconds(response);
  if (response.status === 429 && !attempt.waited && retryAfter !== null) {
    if (retryAfter <= config.maxRetryAfter) {
      await config.sleep(retryAfter * 1000);
      return send<T>(url, init, { ...attempt, waited: true });
    }
    throw new RateLimitedError(problem, retryAfter);
  }
  throw errorFromProblem(problem, retryAfter);
};

const request = async (url: string, init: RequestInit, isAuth: boolean): Promise<Response> => {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json, application/problem+json');
  headers.set('Accept-Language', config.locale());
  headers.set('X-Client', config.client);
  if (session && !isAuth) headers.set('Authorization', `Bearer ${session.accessToken}`);
  try {
    return await config.fetch(`${config.baseUrl}${url}`, { ...init, headers });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new NetworkError('network request failed', { cause: error });
  }
};

/** Одно обновление на все параллельные 401: остальные ждут его результата. */
const refreshOnce = (): Promise<boolean> => {
  refreshing ??= refreshSession().finally(() => {
    refreshing = null;
  });
  return refreshing;
};

const refreshSession = async (): Promise<boolean> => {
  const current = session;
  if (!current) return false;
  const response = await request(
    REFRESH_PATH,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: current.refreshToken }),
    },
    true,
  ).catch(() => null);
  if (!response?.ok) {
    session = null;
    return false;
  }
  const tokens = (await response.json()) as TokensOut;
  session = { accessToken: tokens.access_token, refreshToken: tokens.refresh_token };
  return true;
};

const parseBody = async <T>(response: Response): Promise<T> => {
  if (response.status === 204 || response.headers.get('Content-Length') === '0') {
    return undefined as T;
  }
  try {
    return (await response.json()) as T;
  } catch (error) {
    throw new NetworkError('response is not JSON', { cause: error });
  }
};

const parseProblem = async (response: Response): Promise<ProblemOut> => {
  try {
    const body = (await response.json()) as Partial<ProblemOut>;
    if (typeof body.code === 'string' && typeof body.status === 'number') {
      return body as ProblemOut;
    }
  } catch {
    // тело не JSON: ответ прокси или обрыв — ниже синтетическая ошибка по статусу
  }
  return syntheticProblem(response.status, response.headers.get('X-Request-ID'));
};

const retryAfterSeconds = (response: Response): number | null => {
  const raw = response.headers.get('Retry-After');
  if (raw === null) return null;
  const seconds = Number(raw);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.ceil(seconds) : null;
};
