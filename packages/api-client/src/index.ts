// Клиент API «Соседей» (DEVELOPMENT_PLAN 0.20): хуки и функции из OpenAPI, ошибки, сессия.
export * from './generated/endpoints/index.ts';
export * from './generated/model/index.ts';
export {
  ApiError,
  MaintenanceError,
  NetworkError,
  RateLimitedError,
  RestrictedError,
  UpgradeRequiredError,
} from './errors.ts';
export { configureApiClient, getSession, setSession } from './mutator.ts';
export type { ApiClientConfig, Session } from './mutator.ts';
