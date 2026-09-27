// Ошибки API (RFC 9457, ARCHITECTURE §8.3, ADR-0020 §9): клиент ветвится по code, а не по тексту.
import type { FieldErrorOut, ProblemOut } from './generated/model/index.ts';

/** Ответ сервера с ошибкой. `problem` — тело application/problem+json как пришло. */
export class ApiError extends Error {
  override readonly name: string = 'ApiError';
  readonly status: number;
  readonly code: string;
  readonly errors: readonly FieldErrorOut[];
  readonly traceId: string | null;
  readonly problem: ProblemOut;

  constructor(problem: ProblemOut) {
    super(`${problem.status} ${problem.code}`);
    this.status = problem.status;
    this.code = problem.code;
    this.errors = problem.errors ?? [];
    this.traceId = problem.trace_id;
    this.problem = problem;
  }
}

/** 403 `restricted`: действует санкция (экран S49b). `until = null` — бессрочно. */
export class RestrictedError extends ApiError {
  override readonly name = 'RestrictedError';
  readonly restriction: string;
  readonly until: Date | null;

  constructor(problem: ProblemOut) {
    super(problem);
    this.restriction = problem.restriction ?? 'restricted';
    this.until = problem.until ? new Date(problem.until) : null;
  }
}

/** 426: версия клиента ниже минимальной — «обновите Telegram». */
export class UpgradeRequiredError extends ApiError {
  override readonly name = 'UpgradeRequiredError';
  readonly minVersion: string | null;

  constructor(problem: ProblemOut) {
    super(problem);
    this.minVersion = problem.min_version ?? null;
  }
}

/** 429, когда ждать дольше допустимого: `retryAfter` — секунды из Retry-After. */
export class RateLimitedError extends ApiError {
  override readonly name = 'RateLimitedError';
  readonly retryAfter: number;

  constructor(problem: ProblemOut, retryAfter: number) {
    super(problem);
    this.retryAfter = retryAfter;
  }
}

/** 503 `maintenance`: идут техработы (флаг `platform.maintenance`), экран S49 «техработы».
 *  `retryAfter` — секунды из Retry-After, если сервер их прислал. */
export class MaintenanceError extends ApiError {
  override readonly name = 'MaintenanceError';
  readonly retryAfter: number | null;

  constructor(problem: ProblemOut, retryAfter: number | null) {
    super(problem);
    this.retryAfter = retryAfter;
  }
}

/** Нет сети или ответ — не JSON (прокси, обрыв). Экран S49a «нет сети». */
export class NetworkError extends Error {
  override readonly name = 'NetworkError';
}

export const errorFromProblem = (problem: ProblemOut, retryAfter: number | null): ApiError => {
  if (problem.status === 403 && problem.code === 'restricted') return new RestrictedError(problem);
  if (problem.status === 426) return new UpgradeRequiredError(problem);
  if (problem.status === 429) return new RateLimitedError(problem, retryAfter ?? 0);
  if (problem.status === 503 && problem.code === 'maintenance') {
    return new MaintenanceError(problem, retryAfter);
  }
  return new ApiError(problem);
};

/** Тело без RFC 9457 (например, 502 от прокси) — ошибка с кодом http_<статус>. */
export const syntheticProblem = (status: number, traceId: string | null = null): ProblemOut => ({
  type: 'about:blank',
  title: `HTTP ${status}`,
  status,
  code: `http_${status}`,
  trace_id: traceId,
});
