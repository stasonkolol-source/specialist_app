// Headless-хуки сценариев (ADR-0020 §13): api-client + domain, без DOM и Telegram — их
// переиспользует мобильное приложение (этап 2).
export {
  DICTIONARY_STALE_MS,
  categoriesQueryKey,
  districtsQueryKey,
  leafCategories,
  selectableDistricts,
  useCategories,
  useDistricts,
} from './catalog/categories.ts';
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
export type { MediaApi, MediaTransport, Prepared, PutResult } from './media/upload.ts';
export type { DayKey, NotificationDay, NotificationFeed } from './notifications/notifications.ts';
export {
  NOTIFICATIONS_PAGE_SIZE,
  feedItems,
  groupByDay,
  markRead,
  notificationsQueryKey,
  unreadCount,
  useMarkNotificationsRead,
  useNotificationFeed,
} from './notifications/notifications.ts';
export {
  MediaRejectedError,
  MediaUpload,
  UploadCancelledError,
  UploadFailedError,
  contentTypeOf,
  mediaApi,
  waitForMedia,
} from './media/upload.ts';
export type {
  MediaUploads,
  MediaUploadsOptions,
  UploadItem,
  UploadStatus,
} from './media/useMediaUploads.ts';
export { UPLOADS_AT_ONCE, isRetryable, useMediaUploads } from './media/useMediaUploads.ts';
export type { ConsentGate, OnboardingStep } from './onboarding/onboarding.ts';
export {
  ONBOARDING_STEPS,
  consentGate,
  nextOnboardingStep,
  onboardingStep,
  useConsentGate,
} from './onboarding/onboarding.ts';
export { useSetAvailability } from './specialist/availability.ts';
export type { ServiceGroup } from './specialist/prices.ts';
export { groupServices, moveService, servicePrice } from './specialist/prices.ts';
export type { BecomeStep, ProfileState } from './specialist/profile.ts';
export {
  BECOME_STEPS,
  becomeStep,
  myProfileQueryKey,
  profileState,
  useMyProfile,
} from './specialist/profile.ts';
export type { Restriction, SystemState } from './system/systemState.ts';
export {
  ACCOUNT_BLOCKING,
  isAppWide,
  isRestriction,
  startupState,
  systemStateOf,
} from './system/systemState.ts';
