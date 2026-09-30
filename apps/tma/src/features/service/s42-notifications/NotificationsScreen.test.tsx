// S42 (DEVELOPMENT_PLAN 4.9): лента из GET /me/notifications по дням, отметка «не прочитано»,
// «Прочитать все», переход по deep link уведомления, баннер «бот не может писать», состояния.
import { configureApiClient, setSession } from '@sosed/api-client';
import type { Locale } from '@sosed/i18n';
import { I18nextProvider, createI18n, currentLocale } from '@sosed/i18n';
import { encodeStartParam } from '@sosed/links';
import type { MockOptions } from '@sosed/platform';
import { PlatformProvider, createMockPlatform } from '@sosed/platform';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  NOTIFICATIONS_NOW,
  NOTIFICATION_SETTINGS,
  WRITE_ACCESS,
  notificationsFor,
} from '../../../testing/fixtures.ts';
import { API_ORIGIN, TOKENS, server } from '../../../testing/msw.ts';
import { NotificationsScreen } from './NotificationsScreen.tsx';

const LIST = '*/api/v1/me/notifications';
const READ = '*/api/v1/me/notifications/read';
const SETTINGS = '*/api/v1/me/notification-settings';

const HOME = encodeStartParam({ type: 'home' });
const TERMS = encodeStartParam({ type: 'legal', document: 'terms' });

/** Deep link → адрес: как routes/startapp.ts, но явно — тест не зависит от таблицы маршрутов. */
const targetOf = (link: string) => (link === HOME ? '/' : link === TERMS ? '/legal/terms' : null);

function createTestRouter() {
  const root = createRootRoute();
  const route = (path: string, name: string) =>
    createRoute({ getParentRoute: () => root, path, component: () => <h1>{name}</h1> });
  const notifications = createRoute({
    getParentRoute: () => root,
    path: '/notifications',
    component: () => <NotificationsScreen targetOf={targetOf} />,
  });
  return createRouter({
    routeTree: root.addChildren([
      notifications,
      route('/', 'Главная'),
      route('/profile', 'Профиль'),
      route('/legal/$document', 'S48'),
    ]),
    history: createMemoryHistory({ initialEntries: ['/notifications'] }),
  });
}

async function renderScreen({
  locale = 'ru',
  platform: platformOptions = {},
}: { locale?: Locale; platform?: MockOptions } = {}) {
  const { platform, telegram } = createMockPlatform(platformOptions);
  const i18n = createI18n({ locale, appName: 'Соседи' });
  configureApiClient({
    baseUrl: API_ORIGIN,
    locale: () => currentLocale(i18n),
    onReauth: async () => false,
  });
  setSession({ accessToken: TOKENS.access_token, refreshToken: TOKENS.refresh_token });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createTestRouter();
  await router.load();
  render(
    <PlatformProvider platform={platform}>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </I18nextProvider>
    </PlatformProvider>,
  );
  return { router, telegram };
}

/** Строки одного дня: заголовок секции → её строки (текст без лишних пробелов). */
const day = (name: string) =>
  within(screen.getByRole('region', { name }))
    .getAllByText((_, element) => element?.classList.contains('font-semibold') ?? false)
    .map((element) => element.textContent);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: NOTIFICATIONS_NOW });
});

afterEach(() => {
  vi.useRealTimers();
  setSession(null);
});

describe('S42 notifications', () => {
  it('groups the feed by day, marks unread and shows minutes for fresh ones', async () => {
    await renderScreen();

    expect(await screen.findByRole('heading', { name: 'Уведомления', level: 1 })).toBeTruthy();
    await screen.findByRole('region', { name: 'Сегодня' });
    expect(day('Сегодня')).toEqual([
      'Сделка подтверждена',
      'Новое сообщение',
      'Новый отклик',
      'Заявка прошла проверку',
    ]);
    expect(day('Вчера')).toEqual(['Как прошла уборка?', 'Проверка уведомлений']);
    expect(screen.getAllByRole('img', { name: 'Не прочитано' })).toHaveLength(2);
    const deal = screen.getByRole('link', { name: /Сделка подтверждена/ });
    expect(deal.textContent).toContain('2 мин');
    expect(screen.getByRole('link', { name: /Как прошла уборка/ }).textContent).toContain('18:40');
    // без deep link — не ссылка
    expect(screen.queryByRole('link', { name: /Проверка уведомлений/ })).toBeNull();
    expect(screen.getByText('Проверка уведомлений')).toBeTruthy();
  });

  it('marks everything read at once and hides the button', async () => {
    let body: unknown = null;
    server.use(
      http.post(READ, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ unread_count: 0 });
      }),
    );
    await renderScreen();
    await screen.findByRole('link', { name: /Сделка подтверждена/ });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Прочитать все' }));
    });

    await waitFor(() => expect(screen.queryAllByRole('img', { name: 'Не прочитано' })).toEqual([]));
    expect(screen.queryByRole('button', { name: 'Прочитать все' })).toBeNull();
    await waitFor(() => expect(body).toEqual({ all: true }));
  });

  it('opens the notification target and marks it read', async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post(READ, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({ unread_count: 1 });
      }),
    );
    const { router } = await renderScreen();
    const deal = await screen.findByRole('link', { name: /Сделка подтверждена/ });
    expect(deal.getAttribute('href')).toBe('/');

    await act(async () => {
      fireEvent.click(deal);
    });

    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(router.state.location.pathname).toBe('/');
    const [first] = notificationsFor('ru').items;
    await waitFor(() => expect(bodies).toEqual([{ ids: [first?.id] }]));
  });

  it('does not mark an already read notification again', async () => {
    const read = vi.fn(() => HttpResponse.json({ unread_count: 2 }));
    server.use(http.post(READ, read));
    await renderScreen();
    const decision = await screen.findByRole('link', { name: /Заявка прошла проверку/ });

    await act(async () => {
      fireEvent.click(decision);
    });

    expect(await screen.findByRole('heading', { name: 'S48' })).toBeTruthy();
    expect(read).not.toHaveBeenCalled();
  });

  it('texts come in the language of the request', async () => {
    const languages: (string | null)[] = [];
    server.use(
      http.get(LIST, ({ request }) => {
        languages.push(request.headers.get('Accept-Language'));
        return HttpResponse.json(notificationsFor(request.headers.get('Accept-Language')));
      }),
    );
    await renderScreen({ locale: 'sr-Latn' });

    expect(await screen.findByRole('heading', { name: 'Obaveštenja', level: 1 })).toBeTruthy();
    await screen.findByRole('region', { name: 'Danas' });
    expect(day('Danas')[0]).toBe('Dogovor je potvrđen');
    expect(screen.getByRole('button', { name: 'Pročitaj sve' })).toBeTruthy();
    expect(languages).toEqual(['sr-Latn']);
  });

  it('asks Telegram for write access when the bot cannot write', async () => {
    let granted = 0;
    server.use(
      http.post('*/api/v1/me/telegram/write-access', () => {
        granted += 1;
        return HttpResponse.json(WRITE_ACCESS);
      }),
    );
    const { telegram } = await renderScreen();
    const allow = await screen.findByRole('button', { name: 'Разрешить боту писать' });
    expect(
      screen.getByText('Бот не может писать вам — отклики и сообщения видны только здесь.'),
    ).toBeTruthy();

    await act(async () => {
      fireEvent.click(allow);
    });

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Разрешить боту писать' })).toBeNull(),
    );
    expect(telegram.callsOf('web_app_request_write_access')).toHaveLength(1);
    expect(granted).toBe(1);
  });

  it('keeps the banner and explains when the user declines', async () => {
    await renderScreen({ platform: { writeAccess: false } });
    const allow = await screen.findByRole('button', { name: 'Разрешить боту писать' });

    await act(async () => {
      fireEvent.click(allow);
    });

    expect((await screen.findByRole('alert')).textContent).toContain('Нажмите «Старт»');
    expect(screen.getByRole('button', { name: 'Разрешить боту писать' })).toBeTruthy();
  });

  it('shows no banner when the bot can write', async () => {
    server.use(
      http.get(SETTINGS, () =>
        HttpResponse.json({ ...NOTIFICATION_SETTINGS, telegram: WRITE_ACCESS }),
      ),
    );
    await renderScreen();
    await screen.findByRole('link', { name: /Сделка подтверждена/ });

    expect(screen.queryByText(/Бот не может писать/)).toBeNull();
  });

  it('shows an empty state without notifications', async () => {
    server.use(
      http.get(LIST, () => HttpResponse.json({ items: [], next_cursor: null, unread_count: 0 })),
    );
    await renderScreen();

    expect(await screen.findByRole('heading', { name: 'Пока уведомлений нет' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Прочитать все' })).toBeNull();
  });

  it('loads the next page by cursor', async () => {
    const [first, second] = notificationsFor('ru').items;
    server.use(
      http.get(LIST, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor');
        return HttpResponse.json(
          cursor === 'c1'
            ? { items: [second], next_cursor: null, unread_count: 1 }
            : { items: [first], next_cursor: 'c1', unread_count: 1 },
        );
      }),
    );
    await renderScreen();
    const more = await screen.findByRole('button', { name: 'Показать ещё' });

    await act(async () => {
      fireEvent.click(more);
    });

    expect(await screen.findByRole('link', { name: /Новое сообщение/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Показать ещё' })).toBeNull();
  });

  it('shows «no connection» with retry when the feed cannot load', async () => {
    server.use(http.get(LIST, () => HttpResponse.error(), { once: true }));
    await renderScreen();

    expect(await screen.findByRole('heading', { name: 'Нет соединения' })).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });
    expect(await screen.findByRole('link', { name: /Сделка подтверждена/ })).toBeTruthy();
  });
});
