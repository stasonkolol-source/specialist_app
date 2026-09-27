// Headless-хуки сценариев (ADR-0020 §13): api-client + domain, без DOM и Telegram — их
// переиспользует мобильное приложение (этап 2).
export type { ClientVersions, FlagKey, UpdateNeeded } from './config/clientConfig.ts';
export {
  CLIENT_CONFIG_STALE_MS,
  DEFAULT_MIN_TELEGRAM,
  FLAGS,
  compareVersions,
  requiredUpdate,
  useClientConfig,
  useFlag,
} from './config/clientConfig.ts';
