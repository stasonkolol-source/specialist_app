// Клиент API «Соседа» (DEVELOPMENT_PLAN 0.20): хуки и функции из OpenAPI, ошибки, сессия.
export * from './generated/endpoints/index.ts';
export * from './generated/model/index.ts';
export {
  ApiError,
  NetworkError,
  RateLimitedError,
  RestrictedError,
  UpgradeRequiredError,
} from './errors.ts';
export { configureApiClient, getSession, setSession } from './mutator.ts';
/** Вызов вне OpenAPI — только dev-спайки (0.24 `/__spike`); экраны ходят через хуки orval. */
export { apiFetch } from './mutator.ts';
export type { ApiClientConfig, Session } from './mutator.ts';
