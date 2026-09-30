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

import { ONBOARDING_PATHS, onboardingSearch } from '../features/onboarding/index.ts';
import { LEGAL_PATH, LegalScreen } from '../features/service/s48-legal/index.ts';
import { RESTRICTED_PATH, RestrictedRoute } from '../features/service/s49-system/index.ts';
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

const home = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: screen(() => import('../features/home/s03-home/index.ts'), 'HomeScreen'),
});

const jobs = createRoute({
  getParentRoute: () => rootRoute,
  path: '/jobs',
  component: screen(() => import('../features/jobs/s22-my-jobs/index.ts'), 'MyJobsScreen'),
});

// Создающее действие: без согласия с правилами — S02c (routes/guards.ts)
const createJob = createRoute({
  getParentRoute: () => rootRoute,
  path: '/jobs/new',
  beforeLoad: requireConsent,
  component: screen(() => import('../features/jobs/s20a-create-what/index.ts'), 'CreateJobScreen'),
});

const messages = createRoute({
  getParentRoute: () => rootRoute,
  path: '/messages',
  component: screen(() => import('../features/messages/s29-chats/index.ts'), 'ChatsScreen'),
});

const profile = createRoute({
  getParentRoute: () => rootRoute,
  path: '/profile',
  component: screen(() => import('../features/account/s31-account/index.ts'), 'AccountScreen'),
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

// S48 и S49b — в первом чанке, без lazy: экраны S49 рисуются и без сети (точка сборки
// импортирует их напрямую), а S49b открывает правила площадки у себя.
// Документ S48 — в пути, чтобы S02c, S31 и deep link открывали нужный.
const legal = createRoute({
  getParentRoute: () => rootRoute,
  path: LEGAL_PATH,
  component: LegalScreen,
});

// S49b после действия, отклонённого частичной санкцией
const restricted = createRoute({
  getParentRoute: () => rootRoute,
  path: RESTRICTED_PATH,
  component: RestrictedRoute,
});

export const routeTree = rootRoute.addChildren([
  home,
  jobs,
  createJob,
  messages,
  profile,
  notifications,
  onboardingLanguage,
  onboardingIntent,
  onboardingRules,
  legal,
  restricted,
]);
