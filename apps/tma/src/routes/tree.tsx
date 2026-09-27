// Маршруты TanStack Router: связывают URL и экран, логики нет (ADR-0020 §13).
// Экраны грузятся отдельными чанками (code splitting по маршрутам), оболочка — в первом.
import { Navigate, createRootRoute, createRoute, lazyRouteComponent } from '@tanstack/react-router';

import { AppShell } from '../features/shell/index.ts';

export const rootRoute = createRootRoute({
  component: AppShell,
  // Неизвестный путь (устаревшая ссылка, опечатка) — на главную, а не пустой экран
  notFoundComponent: () => <Navigate to="/" replace />,
});

const home = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: lazyRouteComponent(() => import('../features/home/s03-home/index.ts'), 'HomeScreen'),
});

const jobs = createRoute({
  getParentRoute: () => rootRoute,
  path: '/jobs',
  component: lazyRouteComponent(
    () => import('../features/jobs/s22-my-jobs/index.ts'),
    'MyJobsScreen',
  ),
});

const createJob = createRoute({
  getParentRoute: () => rootRoute,
  path: '/jobs/new',
  component: lazyRouteComponent(
    () => import('../features/jobs/s20a-create-what/index.ts'),
    'CreateJobScreen',
  ),
});

const messages = createRoute({
  getParentRoute: () => rootRoute,
  path: '/messages',
  component: lazyRouteComponent(
    () => import('../features/messages/s29-chats/index.ts'),
    'ChatsScreen',
  ),
});

const profile = createRoute({
  getParentRoute: () => rootRoute,
  path: '/profile',
  component: lazyRouteComponent(
    () => import('../features/account/s31-account/index.ts'),
    'AccountScreen',
  ),
});

// Спайк 0.24 — только dev-сервер: в сборке ветка `false ? … : []` и её чанк выпадают
const devRoutes = import.meta.env.DEV
  ? [
      createRoute({
        getParentRoute: () => rootRoute,
        path: '/__spike/upload',
        component: lazyRouteComponent(
          () => import('../features/spike/upload/UploadSpikeScreen.tsx'),
          'UploadSpikeScreen',
        ),
      }),
    ]
  : [];

export const routeTree = rootRoute.addChildren([
  home,
  jobs,
  createJob,
  messages,
  profile,
  ...devRoutes,
]);
