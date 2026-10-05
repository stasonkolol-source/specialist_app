// Headless-хуки сценариев (ADR-0020 §13): api-client + domain, без DOM и Telegram — их
// переиспользует мобильное приложение (этап 2).
export {
  DICTIONARY_STALE_MS,
  categoriesQueryKey,
  categoriesQueryOptions,
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
  clientConfigQueryOptions,
  compareVersions,
  requiredUpdate,
  useClientConfig,
  useFlag,
  useSupportLink,
} from './config/clientConfig.ts';
export {
  CITIES_STALE_MS,
  citiesQueryKey,
  citiesQueryOptions,
  defaultCity,
  isSelectableCity,
  useCities,
} from './geo/cities.ts';
export type { LegalDocumentKey, LegalTextView } from './legal/useLegalDocument.ts';
export {
  LEGAL_DOCUMENTS,
  isLegalDocument,
  legalDocumentsQueryOptions,
  legalText,
  useLegalDocument,
} from './legal/useLegalDocument.ts';
export type { MediaApi, MediaTransport, Prepared, PutResult } from './media/upload.ts';
export { useUpdatePrivacy } from './account/privacy.ts';
export type { ChatEntry, PendingMessage } from './messages/chat.ts';
export {
  CHAT_PAGE_SIZE,
  CHAT_POLL_MS,
  MAX_MESSAGE,
  chatQueryKey,
  chatQueryOptions,
  useChat,
  useProposeDeal,
  useShareContact,
} from './messages/chat.ts';
export { BADGES_POLL_MS, useBadges } from './messages/badges.ts';
export type { ChatRole, ConversationPages, DealState } from './messages/conversations.ts';
export {
  CONVERSATIONS_KEY,
  CONVERSATIONS_PAGE_SIZE,
  conversationItems,
  conversationsQueryKey,
  dealState,
  refreshInbox,
  useConversations,
  useStartConversation,
} from './messages/conversations.ts';
export type { DayKey, NotificationDay, NotificationFeed } from './notifications/notifications.ts';
export type { NotificationChannel, SettingsChange } from './notifications/settings.ts';
export {
  applyChange,
  settingsIn,
  useUpdateNotificationSettings,
} from './notifications/settings.ts';
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
export { useCancelDeletion, useRequestDeletion } from './account/deletion.ts';
export { useSetAvailability } from './specialist/availability.ts';
export type {
  PortfolioRoom,
  PortfolioUploads,
  PortfolioUploadsOptions,
} from './specialist/portfolio.ts';
export {
  PORTFOLIO_ACCEPT,
  PORTFOLIO_POLL_MS,
  broken,
  fitFiles,
  hiddenByModerator,
  onReview,
  portfolioRoom,
  processing,
  useMyPortfolio,
  usePortfolioUploads,
  workKindOf,
} from './specialist/portfolio.ts';
export type { PricedService, ServiceGroup } from './specialist/prices.ts';
export { groupServices, moveService, servicePrice, useMyServices } from './specialist/prices.ts';
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
export type { SpecialistQuery, SpecialistResults } from './search/search.ts';
export {
  CATEGORY_COUNTS_STALE_MS,
  SEARCH_PAGE_SIZE,
  SUGGEST_MIN,
  SUGGEST_STALE_MS,
  TODAY_PREVIEW,
  availableTodayQueryOptions,
  countQuery,
  countsByCategory,
  resultItems,
  resultSummary,
  specialistsQueryKey,
  useAvailableToday,
  useCategoryCounts,
  useSpecialistCount,
  useSpecialistSearch,
  useSuggest,
} from './search/search.ts';
export { distanceMeters, nearestDistrict } from './geo/districts.ts';
export { cachedConversation, cachedJobCard, cachedSpecialistCard } from './previews.ts';
export type { PriceGroup } from './card/card.ts';
export {
  CARD_STALE_MS,
  cardVariants,
  isUnavailable,
  largestVariant,
  priceGroups,
  specialistCardQueryKey,
  specialistCardQueryOptions,
  specialistServicesQueryKey,
  useSpecialistCard,
  useSpecialistReviews,
  useSpecialistServices,
  useSpecialistWorks,
} from './card/card.ts';
export type { FavoriteToggle } from './favorites/favorites.ts';
export {
  favoriteIds,
  favoritesQueryKey,
  searchCardOf,
  useFavorites,
  useToggleFavorite,
} from './favorites/favorites.ts';
export type {
  DirectTarget,
  DraftLanguage,
  DraftPhoto,
  DraftProblem,
  DraftUnit,
  JobDraft,
} from './jobs/draft.ts';
export {
  BUDGET_DIGITS,
  DRAFT_LANGUAGES,
  DRAFT_STORAGE_KEY,
  DRAFT_TTL_MS,
  DRAFT_UNITS,
  JOB_ADDRESS_MAX,
  JOB_DESCRIPTION_MAX,
  JOB_PHOTOS_MAX,
  JOB_TITLE_MAX,
  JOB_TITLE_MIN,
  amountOf,
  budgetProblems,
  draftOfJob,
  draftSlot,
  jobInOf,
  newDraft,
  parseDraft,
  whatProblems,
  whenProblems,
} from './jobs/draft.ts';
export type { PublishJob } from './jobs/jobs.ts';
export { jobQueryKey, jobQueryOptions, useCreateJob, useJob } from './jobs/jobs.ts';
export type { FeedPages, FeedQuery } from './jobs/feed.ts';
export { FEED_PAGE_SIZE, feedQueryKey, jobCards, useHideJob, useJobsFeed } from './jobs/feed.ts';
export { NEW_JOBS_HOURS, jobsCountQueryOptions, useJobsCount } from './jobs/count.ts';
export type { OfferDraft, OfferProblem } from './jobs/offer.ts';
export {
  RESPONSE_AVAILABILITY_MAX,
  RESPONSE_MESSAGE_MAX,
  RESPONSE_PRICE_TYPES,
  TEMPLATES_MAX,
  TEMPLATE_TITLE_MAX,
  emptyOffer,
  offerDraftOf,
  offerIn,
  offerPriceOf,
  offerProblems,
  sameOffer,
  templateTitleOf,
} from './jobs/offer.ts';
export type {
  MyResponsesPages,
  ReviseResponse,
  SendResponse,
  WithdrawResponse,
} from './jobs/responses.ts';
export {
  MY_RESPONSES_PAGE_SIZE,
  myResponseItems,
  myResponsesQueryKey,
  useMyResponse,
  useMyResponses,
  useRespond,
  useReviseResponse,
  useWithdrawResponse,
} from './jobs/responses.ts';
export type { CancelDeal, DecideResponse } from './deals/deals.ts';
export type { HistoryPages, MyReviewsPages } from './reviews/reviews.ts';
export {
  DEAL_HISTORY_KEY,
  MY_REVIEWS_KEY,
  pagedItems,
  useDealHistory,
  useLeaveReview,
  useMyReviews,
  useReplyToReview,
} from './reviews/reviews.ts';
export {
  INVITE_BODY_MAX,
  INVITE_NAME_MAX,
  INVITE_WORK_MAX,
  REVIEW_INVITES_LIMIT,
  reviewInvitesQueryKey,
  useCreateReviewInvite,
  useLeaveInviteReview,
  useReviewInvite,
  useReviewInvites,
  useRevokeReviewInvite,
} from './reviews/invites.ts';
export {
  MY_DEALS_KEY,
  dealCardQueryKey,
  useAcceptResponse,
  useAnswerProposal,
  useCancelDeal,
  useCompleteDeal,
  useDealCard,
  useDeclineResponse,
  useMyDeals,
} from './deals/deals.ts';
export { useOpenDispute, useRespondDispute, useWithdrawDispute } from './deals/disputes.ts';
export type { CloseJob, InviteSpecialists, UpdateJob } from './jobs/mine.ts';
export {
  RESPONSES_POLL_MS,
  jobInvitesQueryKey,
  myJobsQueryKey,
  myJobsQueryOptions,
  responseCardsQueryKey,
  useCloseJob,
  useExtendJob,
  useInviteSpecialists,
  useJobInvites,
  useMyJobs,
  useOwnJob,
  useResponseCards,
  useUpdateJob,
} from './jobs/mine.ts';
export type { CreateAlert, UpdateAlert } from './jobs/alerts.ts';
export {
  ALERTS_MAX,
  alertsQueryKey,
  receives,
  useCreateAlert,
  useDeleteAlert,
  useJobAlerts,
  useUpdateAlert,
} from './jobs/alerts.ts';
export type { CreateTemplate, UpdateTemplate } from './jobs/templates.ts';
export {
  templatesQueryKey,
  useCreateTemplate,
  useDeleteTemplate,
  useResponseTemplates,
  useUpdateTemplate,
} from './jobs/templates.ts';
export type { SavedJobToggle } from './jobs/saved.ts';
export {
  jobCardOf,
  savedJobIds,
  savedJobsQueryKey,
  useSavedJobs,
  useToggleSavedJob,
} from './jobs/saved.ts';
export type { BlockToggle } from './safety/blocks.ts';
export {
  blockedIds,
  blockedUserOf,
  blocksQueryKey,
  shortName,
  useBlocks,
  useToggleBlock,
} from './safety/blocks.ts';
export type { ReportTargetType } from './safety/reports.ts';
export {
  MAX_REPORT_COMMENT,
  REPORT_REASONS,
  allowedReason,
  reportQueue,
  useAppeal,
  useReport,
} from './safety/reports.ts';
export type { ReportTarget } from './safety/reportRequest.ts';
export { closeReport, openReport, useReportTarget } from './safety/reportRequest.ts';
export type { ShareChannel, ShareOutcome, ShareTargetRef } from './share/share.ts';
export { COPIED_TOAST_MS, shareVia, useShare, useShareLink } from './share/share.ts';
