// Маршруты TanStack Router: связывают URL и экран, логики нет (ADR-0020 §13).
// Экраны грузятся отдельными чанками (code splitting по маршрутам), оболочка — в первом.
import { NetworkError } from '@sosed/api-client';
import type { RouteComponent } from '@tanstack/react-router';
import {
  Navigate,
  createRootRouteWithContext,
  createRoute,
  lazyRouteComponent,
} from '@tanstack/react-router';
import type { FunctionComponent } from 'react';

import { ACCOUNT_PATHS } from '../features/account/index.ts';
import {
  CARD_PATHS,
  CATALOG_PATHS,
  FAVORITES_PATH,
  portfolioSearch,
  resultsSearch,
} from '../features/catalog/index.ts';
import {
  CREATE_PATHS,
  JOBS_PATHS,
  SAVED_PATHS,
  createSearch,
  doneSearch,
  editSearch,
  feedSearch,
  historySearch,
  jobSearch,
  responsesSearch,
} from '../features/jobs/index.ts';
import { MESSAGES_PATHS, chatSearch } from '../features/messages/index.ts';
import { ONBOARDING_PATHS, onboardingSearch } from '../features/onboarding/index.ts';
import { BECOME_PATHS, CABINET_PATHS, becomeSearch } from '../features/specialist/index.ts';
import { HELP_PATH } from '../features/service/s47-help/paths.ts';
import { LEGAL_PATH } from '../features/service/s48-legal/paths.ts';
import { RESTRICTED_PATH } from '../features/service/s49-system/index.ts';
import { AppShell } from '../features/shell/index.ts';
import type { RouterContext } from './guards.ts';
import { requireConsent, requireUser } from './guards.ts';

/**
 * Экран отдельным чанком. Чанк не скачался без сети — NetworkError: экран ошибки покажет S49a
 * «Нет соединения» с «Повторить». Иначе lazyRouteComponent перезагрузил бы страницу, а без сети
 * Telegram показал бы свою страницу ошибки и Mini App потерял бы состояние. В сети перезагрузка
 * остаётся: так открытое приложение подхватывает новый деплой, когда старых чанков уже нет.
 */
function screen<K extends string>(
  importer: () => Promise<Record<NoInfer<K>, FunctionComponent>>,
  name: K,
): RouteComponent {
  return lazyRouteComponent(
    () =>
      importer().catch((error: unknown) => {
        throw navigator.onLine ? error : new NetworkError('screen chunk failed', { cause: error });
      }),
    name,
  );
}

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: AppShell,
  // Неизвестный путь (устаревшая ссылка, опечатка) — на главную, а не пустой экран
  notFoundComponent: () => <Navigate to="/" replace />,
});

// Главная S03 (4.8): точка входа клиента из блоков каталога — экран в фиче catalog
const home = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: screen(() => import('../features/catalog/s03-home/index.ts'), 'HomeScreen'),
});

// Вкладка «Заявки» (5.3): лента S13 открыта и гостю, фильтры — в параметрах адреса. Сегменты
// «Мои отклики» S17 (5.5, чип — в адресе) и «Мои заявки» S22 (5.6) — свои адреса
const jobs = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.feed,
  validateSearch: feedSearch,
  component: screen(() => import('../features/jobs/s13-feed/index.ts'), 'FeedScreen'),
});

const myResponses = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.responses,
  validateSearch: responsesSearch,
  component: screen(
    () => import('../features/jobs/s17-my-responses/index.ts'),
    'MyResponsesScreen',
  ),
});

// Шаблоны откликов S57 (5.5): из S16 и S17; создание шаблона — создающее действие
const templates = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.templates,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/jobs/s57-templates/index.ts'), 'TemplatesScreen'),
});

const myJobs = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.mine,
  component: screen(() => import('../features/jobs/s22-my-jobs/index.ts'), 'MyJobsScreen'),
});

// Заявка S15: из ленты (с точкой ленты — «≈ 1,2 км от вас») и по deep link `j_`
// (routes/startapp.ts); открыта и гостю. Статические /jobs/new, /jobs/mine… важнее параметра
const job = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.job,
  validateSearch: jobSearch,
  component: screen(() => import('../features/jobs/s15-job/index.ts'), 'JobScreen'),
});

// Своя заявка S23 (5.6): из «Моих заявок» S22, «К заявке» S21 и по deep link `j_` владельцу (S15
// перенаправляет); чужому — экран S15
const manage = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.manage,
  component: screen(() => import('../features/jobs/s23-manage-job/index.ts'), 'ManageJobScreen'),
});

// Отклик на свою заявку S24 со шторкой выбора S25 (6.2): из карточки отклика S23
const choice = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.response,
  component: screen(() => import('../features/jobs/s24-response/index.ts'), 'ChoiceScreen'),
});

// Сделка S26 (6.2): из S25, «Открыть сделку» S23 и S17 и по deep link `d_` (уведомления бота)
const deal = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.deal,
  component: screen(() => import('../features/jobs/s26-deal/index.ts'), 'DealScreen'),
});

// Спор S52 (6.1c): «Есть проблема» S26 и по deep link `p_` (бот); открыть спор и ответить —
// создающие действия: без согласия S02c
const dispute = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.dispute,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/jobs/s52-dispute/index.ts'), 'DisputeScreen'),
});

// Отзыв S27 (7.3): «Оставить отзыв» S26 и S28; создающее действие — без согласия S02c
const review = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.review,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/jobs/s27-review/index.ts'), 'ReviewScreen'),
});

// «Сделки и отзывы» S28 (7.3): строка S31, ссылка `m_reviews` — вкладка «Отзывы»
const history = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.history,
  validateSearch: historySearch,
  component: screen(() => import('../features/jobs/s28-history/index.ts'), 'HistoryScreen'),
});

// Отклик S16 (5.5) — из MainButton S15 и «Изменить» S17; создающее действие: без согласия — S02c
const respond = createRoute({
  getParentRoute: () => rootRoute,
  path: JOBS_PATHS.respond,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/jobs/s16-respond/index.ts'), 'RespondScreen'),
});

// Мастер «Создать заявку» S20a–d (5.2) — создающее действие: без согласия с правилами — S02c
// (routes/guards.ts). Вход — таббар и CTA с категорией и названием (`?category=&title=`).
const createWhat = createRoute({
  getParentRoute: () => rootRoute,
  path: CREATE_PATHS.what,
  validateSearch: createSearch,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/jobs/s20a-create-what/index.ts'), 'WhatScreen'),
});

const createWhen = createRoute({
  getParentRoute: () => rootRoute,
  path: CREATE_PATHS.when,
  validateSearch: editSearch,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/jobs/s20b-create-when/index.ts'), 'WhenScreen'),
});

const createBudget = createRoute({
  getParentRoute: () => rootRoute,
  path: CREATE_PATHS.budget,
  validateSearch: editSearch,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/jobs/s20c-create-budget/index.ts'), 'BudgetScreen'),
});

const createPreview = createRoute({
  getParentRoute: () => rootRoute,
  path: CREATE_PATHS.preview,
  validateSearch: editSearch,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/jobs/s20d-create-preview/index.ts'), 'PreviewScreen'),
});

// S21 итог публикации: `?job=` — созданная заявка
const createDone = createRoute({
  getParentRoute: () => rootRoute,
  path: CREATE_PATHS.done,
  validateSearch: doneSearch,
  beforeLoad: requireUser,
  component: screen(() => import('../features/jobs/s21-published/index.ts'), 'PublishedScreen'),
});

// Сообщения S29 (6.4) — вкладка таббара; гостю — пустой список
const messages = createRoute({
  getParentRoute: () => rootRoute,
  path: MESSAGES_PATHS.list,
  component: screen(() => import('../features/messages/s29-chats/index.ts'), 'ChatsScreen'),
});

// Диалог S30 (6.4): из S29, «Написать» на S08 и по deep link `c_`; без входа писать нечем
const chat = createRoute({
  getParentRoute: () => rootRoute,
  path: MESSAGES_PATHS.chat,
  validateSearch: chatSearch,
  beforeLoad: requireUser,
  component: screen(() => import('../features/messages/s30-chat/index.ts'), 'ChatScreen'),
});

const profile = createRoute({
  getParentRoute: () => rootRoute,
  path: ACCOUNT_PATHS.home,
  component: screen(() => import('../features/account/s31-account/index.ts'), 'AccountScreen'),
});

// Настройки S43 (4.9; раздел приватности — 6.5): из S31, шестерёнки S42 и кнопки бота
// `m_settings`; без входа настраивать нечего
const settings = createRoute({
  getParentRoute: () => rootRoute,
  path: ACCOUNT_PATHS.settings,
  beforeLoad: requireUser,
  component: screen(() => import('../features/account/s43-settings/index.ts'), 'SettingsScreen'),
});

// S45 удаление аккаунта (2.12a): из S43 и кнопки бота `m_deletion`; без входа удалять нечего
const deleteAccount = createRoute({
  getParentRoute: () => rootRoute,
  path: ACCOUNT_PATHS.delete,
  beforeLoad: requireUser,
  component: screen(() => import('../features/account/s45-delete/index.ts'), 'DeleteAccountScreen'),
});

// Мастер «Стать специалистом» S32a–c (2.9): вход — из S31. Профиль — создающее действие:
// без согласия с правилами — S02c
const becomeType = createRoute({
  getParentRoute: () => rootRoute,
  path: BECOME_PATHS.type,
  validateSearch: becomeSearch,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/specialist/s32a-type/index.ts'), 'TypeScreen'),
});

const becomeAbout = createRoute({
  getParentRoute: () => rootRoute,
  path: BECOME_PATHS.about,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/specialist/s32b-about/index.ts'), 'AboutScreen'),
});

const becomeArea = createRoute({
  getParentRoute: () => rootRoute,
  path: BECOME_PATHS.area,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/specialist/s32c-area/index.ts'), 'AreaScreen'),
});

// Кабинет специалиста S33 (2.10): из карточки на S31. Правка профиля S34 — изменение данных
// на площадке: без согласия с правилами — S02c
const cabinet = createRoute({
  getParentRoute: () => rootRoute,
  path: CABINET_PATHS.home,
  component: screen(() => import('../features/specialist/s33-cabinet/index.ts'), 'CabinetScreen'),
});

const cabinetAvailability = createRoute({
  getParentRoute: () => rootRoute,
  path: CABINET_PATHS.availability,
  component: screen(
    () => import('../features/specialist/s38-availability/index.ts'),
    'AvailabilityScreen',
  ),
});

// Прайс S35 и позиция S36 (2.11): правка прайса — изменение данных на площадке, как S34
const cabinetPrices = createRoute({
  getParentRoute: () => rootRoute,
  path: CABINET_PATHS.prices,
  component: screen(() => import('../features/specialist/s35-prices/index.ts'), 'PriceListScreen'),
});

const cabinetNewPrice = createRoute({
  getParentRoute: () => rootRoute,
  path: CABINET_PATHS.newPrice,
  beforeLoad: requireConsent,
  component: screen(
    () => import('../features/specialist/s36-price-item/index.ts'),
    'PriceItemScreen',
  ),
});

const cabinetPrice = createRoute({
  getParentRoute: () => rootRoute,
  path: CABINET_PATHS.price,
  beforeLoad: requireConsent,
  component: screen(
    () => import('../features/specialist/s36-price-item/index.ts'),
    'PriceItemScreen',
  ),
});

// Портфолио S37 и работа (2.11): загрузка работ — тоже данные на площадке
const cabinetPortfolio = createRoute({
  getParentRoute: () => rootRoute,
  path: CABINET_PATHS.portfolio,
  beforeLoad: requireConsent,
  component: screen(
    () => import('../features/specialist/s37-portfolio/index.ts'),
    'PortfolioScreen',
  ),
});

const cabinetWork = createRoute({
  getParentRoute: () => rootRoute,
  path: CABINET_PATHS.work,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/specialist/s37-work/index.ts'), 'WorkScreen'),
});

const cabinetProfile = createRoute({
  getParentRoute: () => rootRoute,
  path: CABINET_PATHS.profile,
  beforeLoad: requireConsent,
  component: screen(() => import('../features/specialist/s34-edit/index.ts'), 'EditProfileScreen'),
});

// S42 из профиля; нажатие на уведомление ведёт по его deep link (routes/notifications.tsx)
const notifications = createRoute({
  getParentRoute: () => rootRoute,
  path: '/notifications',
  component: screen(() => import('./notifications.tsx'), 'NotificationsRoute'),
});

// Онбординг S02a–c (1.5b): первый экран выбирает S01 (app/LaunchGate), S02c открывают ещё и
// создающие действия без согласия. `next` — куда вести после онбординга
const onboardingLanguage = createRoute({
  getParentRoute: () => rootRoute,
  path: ONBOARDING_PATHS.language,
  validateSearch: onboardingSearch,
  beforeLoad: requireUser,
  component: screen(
    () => import('../features/onboarding/s02a-language/index.ts'),
    'LanguageScreen',
  ),
});

const onboardingIntent = createRoute({
  getParentRoute: () => rootRoute,
  path: ONBOARDING_PATHS.intent,
  validateSearch: onboardingSearch,
  beforeLoad: requireUser,
  component: screen(() => import('../features/onboarding/s02b-intent/index.ts'), 'IntentScreen'),
});

const onboardingRules = createRoute({
  getParentRoute: () => rootRoute,
  path: ONBOARDING_PATHS.rules,
  validateSearch: onboardingSearch,
  beforeLoad: requireUser,
  component: screen(() => import('../features/onboarding/s02c-rules/index.ts'), 'RulesScreen'),
});

// Помощь S47 (4.9): из S31; открыта и гостю — вопросы и правила безопасности входа не требуют
const help = createRoute({
  getParentRoute: () => rootRoute,
  path: HELP_PATH,
  component: screen(() => import('../features/service/s47-help/index.ts'), 'HelpScreen'),
});

// S48 — своим чанком: документы приходят в client-config, без сети их всё равно не показать, а
// разбор Markdown первому экрану не нужен. Документ — в пути, чтобы S02c, S31 и deep link
// открывали нужный.
const legal = createRoute({
  getParentRoute: () => rootRoute,
  path: LEGAL_PATH,
  component: screen(() => import('../features/service/s48-legal/index.ts'), 'LegalScreen'),
});

// Каталог S04–S06 (4.4): открыт и гостю; фильтры и порядок выдачи — в параметрах адреса
const catalog = createRoute({
  getParentRoute: () => rootRoute,
  path: CATALOG_PATHS.categories,
  component: screen(
    () => import('../features/catalog/s04-categories/index.ts'),
    'CategoriesScreen',
  ),
});

const catalogResults = createRoute({
  getParentRoute: () => rootRoute,
  path: CATALOG_PATHS.results,
  validateSearch: resultsSearch,
  component: screen(() => import('../features/catalog/s05-results/index.ts'), 'ResultsScreen'),
});

// Карточка специалиста S08–S11 (4.5, 4.6): из выдачи и по deep link `s_` (routes/startapp.ts);
// открыта и гостю. Открытая работа просмотрщика — в параметрах адреса
const specialist = createRoute({
  getParentRoute: () => rootRoute,
  path: CARD_PATHS.profile,
  component: screen(() => import('../features/catalog/s08-profile/index.ts'), 'SpecialistScreen'),
});

const specialistServices = createRoute({
  getParentRoute: () => rootRoute,
  path: CARD_PATHS.services,
  component: screen(() => import('../features/catalog/s09-prices/index.ts'), 'PricesScreen'),
});

const specialistWorks = createRoute({
  getParentRoute: () => rootRoute,
  path: CARD_PATHS.portfolio,
  validateSearch: portfolioSearch,
  component: screen(() => import('../features/catalog/s10-portfolio/index.ts'), 'WorksScreen'),
});

const specialistReviews = createRoute({
  getParentRoute: () => rootRoute,
  path: CARD_PATHS.reviews,
  component: screen(() => import('../features/catalog/s11-reviews/index.ts'), 'ReviewsScreen'),
});

// Избранное S12 (4.6): из профиля S31; гостю — «Откройте в Telegram»
const favorites = createRoute({
  getParentRoute: () => rootRoute,
  path: FAVORITES_PATH,
  component: screen(() => import('../features/catalog/s12-favorites/index.ts'), 'FavoritesScreen'),
});

// Избранное S12, сегмент «Задачи» (5.3): сохранённые заявки; гостю — «Откройте в Telegram»
const savedJobs = createRoute({
  getParentRoute: () => rootRoute,
  path: SAVED_PATHS.jobs,
  component: screen(() => import('../features/jobs/s12-saved-jobs/index.ts'), 'SavedJobsScreen'),
});

// S49b после действия, отклонённого частичной санкцией: сервер ответил — сеть есть, экран своим
// чанком. Экраны S49 без сети (S49a, техработы) остаются в первом (app/StartupGate)
const restricted = createRoute({
  getParentRoute: () => rootRoute,
  path: RESTRICTED_PATH,
  component: screen(
    () => import('../features/service/s49-system/RestrictedRoute.tsx'),
    'RestrictedRoute',
  ),
});

export const routeTree = rootRoute.addChildren([
  home,
  jobs,
  myResponses,
  templates,
  myJobs,
  job,
  respond,
  manage,
  choice,
  deal,
  dispute,
  review,
  history,
  createWhat,
  createWhen,
  createBudget,
  createPreview,
  createDone,
  messages,
  chat,
  profile,
  settings,
  deleteAccount,
  becomeType,
  becomeAbout,
  becomeArea,
  cabinet,
  cabinetProfile,
  cabinetAvailability,
  cabinetPrices,
  cabinetNewPrice,
  cabinetPrice,
  cabinetPortfolio,
  cabinetWork,
  notifications,
  catalog,
  catalogResults,
  specialist,
  specialistServices,
  specialistWorks,
  specialistReviews,
  favorites,
  savedJobs,
  onboardingLanguage,
  onboardingIntent,
  onboardingRules,
  help,
  legal,
  restricted,
]);
