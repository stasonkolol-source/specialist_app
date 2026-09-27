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
export {
  CITIES_STALE_MS,
  citiesQueryKey,
  defaultCity,
  isSelectableCity,
  useCities,
} from './geo/cities.ts';
export type { LegalDocumentKey, LegalTextView } from './legal/useLegalDocument.ts';
export {
  LEGAL_DOCUMENTS,
  isLegalDocument,
  legalText,
  useLegalDocument,
} from './legal/useLegalDocument.ts';
export type { ConsentGate, OnboardingStep } from './onboarding/onboarding.ts';
export {
  ONBOARDING_STEPS,
  consentGate,
  nextOnboardingStep,
  onboardingStep,
  useConsentGate,
} from './onboarding/onboarding.ts';
export type { Restriction, SystemState } from './system/systemState.ts';
export {
  ACCOUNT_BLOCKING,
  isAppWide,
  isRestriction,
  startupState,
  systemStateOf,
} from './system/systemState.ts';
