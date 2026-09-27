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
export type { LegalDocumentKey, LegalTextView } from './legal/useLegalDocument.ts';
export {
  LEGAL_DOCUMENTS,
  isLegalDocument,
  legalText,
  useLegalDocument,
} from './legal/useLegalDocument.ts';
export type { Restriction, SystemState } from './system/systemState.ts';
export {
  ACCOUNT_BLOCKING,
  isAppWide,
  isRestriction,
  startupState,
  systemStateOf,
} from './system/systemState.ts';
