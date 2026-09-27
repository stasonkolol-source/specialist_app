// Клиент API «Соседа» (DEVELOPMENT_PLAN 0.20): хуки и функции из OpenAPI, ошибки, сессия.
export * from './generated/endpoints';
export * from './generated/model';
export {
  ApiError,
  NetworkError,
  RateLimitedError,
  RestrictedError,
  UpgradeRequiredError,
} from './errors.ts';
export { configureApiClient, getSession, setSession } from './mutator.ts';
export type { ApiClientConfig, Session } from './mutator.ts';
