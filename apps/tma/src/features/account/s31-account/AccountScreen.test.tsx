// S31 (DEVELOPMENT_PLAN 2.9): имя и город из GET /me, вход в кабинет специалиста, строки в
// настройки S43 и помощь S47 (4.9; смена языка — в тестах S43), ошибки API и состояние «вне
// Telegram». API — MSW из orval с фикстурами SPEC §4, кабинет — фейк backend
// testing/profileBackend.ts.
import { configureApiClient, setSession } from '@sosed/api-client';
import type { Locale } from '@sosed/i18n';
import { I18nextProvider, createI18n, currentLocale } from '@sosed/i18n';
import type { Platform } from '@sosed/platform';
import { PlatformProvider, createBrowserPlatform } from '@sosed/platform';
import { createMockPlatform } from '@sosed/platform/mock';
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
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FIRST_SERVICE, ME, PROFILE_FILLED } from '../../../testing/fixtures.ts';
import { API_ORIGIN, TOKENS, profileHandlers, server } from '../../../testing/msw.ts';
import { ProfileBackend } from '../../../testing/profileBackend.ts';
import { AccountScreen } from './AccountScreen.tsx';

const ME_PATH = '*/api/v1/me';

const problem = (status: number, code: string) =>
  HttpResponse.json(
    { type: 'about:blank', title: code, status, code, trace_id: 'test' },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  );

interface RenderOptions {
  platform?: Platform;
  /** Сессия уже есть — вход по initData прошёл. */
  signedIn?: boolean;
  /** Повторный вход после 401: по умолчанию не удаётся. */
  onReauth?: () => Promise<boolean>;
  locale?: Locale;
}

/** Профиль и S48 в памяти: строка «Правила площадки» ведёт по маршруту приложения. */
function createTestRouter() {
  const root = createRootRoute();
  const profile = createRoute({ getParentRoute: () => root, path: '/', component: AccountScreen });
  const legal = createRoute({
    getParentRoute: () => root,
    path: '/legal/$document',
    component: () => <h1>S48</h1>,
  });
  const notifications = createRoute({
    getParentRoute: () => root,
    path: '/notifications',
    component: () => <h1>S42</h1>,
  });
  const become = createRoute({
    getParentRoute: () => root,
    path: '/become/$step',
    component: () => <h1>S32</h1>,
  });
  const cabinet = createRoute({
    getParentRoute: () => root,
    path: '/cabinet',
    component: () => <h1>S33</h1>,
  });
  const settings = createRoute({
    getParentRoute: () => root,
    path: '/settings',
    component: () => <h1>S43</h1>,
  });
  const help = createRoute({
    getParentRoute: () => root,
    path: '/help',
    component: () => <h1>S47</h1>,
  });
  return createRouter({
    routeTree: root.addChildren([profile, legal, notifications, become, cabinet, settings, help]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  });
}

async function renderScreen(options: RenderOptions = {}) {
  const {
    platform = createMockPlatform().platform,
    signedIn = true,
    onReauth = async () => false,
    locale = 'ru',
  } = options;
  const i18n = createI18n({ locale, appName: 'Соседи' });
  configureApiClient({ baseUrl: API_ORIGIN, locale: () => currentLocale(i18n), onReauth });
  setSession(
    signedIn ? { accessToken: TOKENS.access_token, refreshToken: TOKENS.refresh_token } : null,
  );
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
  return { i18n, router, queryClient };
}

afterEach(() => setSession(null));

describe('S31 notifications row', () => {
  it('shows the unread count and opens S42', async () => {
    const { router } = await renderScreen();
    const row = await screen.findByRole('link', { name: /Уведомления/ });

    await waitFor(() => expect(row.textContent).toContain('2 непрочитанных'));
    expect(row.getAttribute('href')).toBe('/notifications');
    await act(async () => {
      fireEvent.click(row);
    });
    expect(await screen.findByRole('heading', { name: 'S42' })).toBeTruthy();
    expect(router.state.location.pathname).toBe('/notifications');
  });

  it('has no counter when everything is read', async () => {
    server.use(
      http.get('*/api/v1/me/notifications', () =>
        HttpResponse.json({ items: [], next_cursor: null, unread_count: 0 }),
      ),
    );
    await renderScreen();
    const row = await screen.findByRole('link', { name: /Уведомления/ });
    await screen.findByRole('heading', { name: 'Елена К.' });

    expect(row.textContent).toBe('Уведомления');
  });
});

describe('S31 specialist entry', () => {
  const withProfile = (backend: ProfileBackend) => server.use(...profileHandlers(() => backend));

  it('offers to become a specialist or find side jobs when there is no profile', async () => {
    const { router } = await renderScreen();
    const pro = await screen.findByRole('link', { name: /Стать специалистом/ });

    expect(pro.textContent).toContain('Профиль в каталоге, заявки рядом');
    expect(screen.getByRole('link', { name: /Найти подработку/ }).getAttribute('href')).toBe(
      '/become/type?kind=casual',
    );
    await act(async () => {
      fireEvent.click(pro);
    });
    expect(await screen.findByRole('heading', { name: 'S32' })).toBeTruthy();
    expect(router.state.location.href).toBe('/become/type?kind=pro');
  });

  it('continues a draft at the step where something is missing', async () => {
    withProfile(new ProfileBackend({ ...PROFILE_FILLED, headline: null }, [FIRST_SERVICE]));
    const { router } = await renderScreen();
    const cabinet = await screen.findByRole('link', { name: /Кабинет специалиста/ });

    expect(cabinet.textContent).toContain('Черновик');
    expect(cabinet.getAttribute('href')).toBe('/become/about');
    await act(async () => {
      fireEvent.click(cabinet);
    });
    expect(router.state.location.pathname).toBe('/become/about');
  });

  it('opens the cabinet S33 for a profile on review', async () => {
    withProfile(
      new ProfileBackend({ ...PROFILE_FILLED, status: 'pending_review' }, [FIRST_SERVICE]),
    );
    const { router } = await renderScreen();
    const cabinet = await screen.findByRole('link', { name: /Кабинет специалиста/ });

    expect(cabinet.textContent).toContain('На проверке');
    expect(cabinet.textContent).toContain('Проверка обычно занимает до 30 минут');
    expect(cabinet.getAttribute('href')).toBe('/cabinet');
    expect(screen.queryByRole('link', { name: /Стать специалистом/ })).toBeNull();
    await act(async () => {
      fireEvent.click(cabinet);
    });
    expect(router.state.location.pathname).toBe('/cabinet');
  });

  it('marks a draft returned by moderation and names a side-job profile as such', async () => {
    withProfile(
      new ProfileBackend({
        ...PROFILE_FILLED,
        kind: 'casual',
        rejection_reason: 'contacts_in_text',
      }),
    );
    await renderScreen();
    const cabinet = await screen.findByRole('link', { name: /Профиль подработки/ });

    expect(cabinet.textContent).toContain('Нужны правки');
    expect(cabinet.getAttribute('href')).toBe('/become/area');
  });
});

describe('S31 profile', () => {
  it('shows the name and the home city from GET /me', async () => {
    const auth: (string | null)[] = [];
    server.use(
      http.get(ME_PATH, ({ request }) => {
        auth.push(request.headers.get('Authorization'));
        return HttpResponse.json(ME);
      }),
    );
    await renderScreen();

    expect(await screen.findByRole('heading', { name: 'Елена К.', level: 2 })).toBeTruthy();
    expect(await screen.findByText('Нови-Сад')).toBeTruthy();
    expect(auth).toEqual([`Bearer ${TOKENS.access_token}`]);
  });

  it('announces loading until /me answers', async () => {
    await renderScreen();
    // live region читает содержимое: текст внутри, а не в aria-label
    expect(screen.getByRole('status').textContent).toBe('Загружаем профиль');
    expect(await screen.findByRole('heading', { name: 'Елена К.' })).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('opens settings S43 from «Язык» with the current language and from «Настройки»', async () => {
    const { router } = await renderScreen({ locale: 'sr-Latn' });
    const app = await screen.findByRole('navigation', { name: 'Aplikacija' });
    const language = within(app).getByRole('link', { name: /^Jezik/ });
    expect(language.textContent).toBe('JezikSrpski');
    expect(language.getAttribute('href')).toBe('/settings');
    expect(within(app).getByRole('link', { name: 'Podešavanja' }).getAttribute('href')).toBe(
      '/settings',
    );

    await act(async () => {
      fireEvent.click(language);
    });

    expect(router.state.location.pathname).toBe('/settings');
    expect(await screen.findByRole('heading', { name: 'S43' })).toBeTruthy();
  });

  it('has no language list and no account deletion: both moved to settings S43', async () => {
    await renderScreen();
    await screen.findByRole('heading', { name: 'Елена К.' });

    expect(screen.queryByRole('radiogroup')).toBeNull();
    expect(screen.queryByRole('link', { name: 'Удалить аккаунт' })).toBeNull();
  });

  it('shows an error with retry when GET /me fails', async () => {
    server.use(http.get(ME_PATH, () => problem(500, 'internal_error'), { once: true }));
    await renderScreen();

    expect(await screen.findByRole('heading', { name: 'Что-то пошло не так' })).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });

    expect(await screen.findByRole('heading', { name: 'Елена К.' })).toBeTruthy();
  });

  it('asks to open the app in Telegram when sign-in by initData fails', async () => {
    server.use(
      http.get(ME_PATH, ({ request }) =>
        request.headers.has('Authorization')
          ? HttpResponse.json(ME)
          : problem(401, 'not_authenticated'),
      ),
    );
    const onReauth = vi.fn(async () => false);
    await renderScreen({ signedIn: false, onReauth });

    expect(await screen.findByRole('heading', { name: 'Откройте в Telegram' })).toBeTruthy();
    expect(onReauth).toHaveBeenCalledOnce();
    expect(screen.queryByRole('heading', { name: 'Что-то пошло не так' })).toBeNull();
  });

  it('shows the name once a pending sign-in completes', async () => {
    server.use(
      http.get(ME_PATH, ({ request }) =>
        request.headers.get('Authorization') === `Bearer ${TOKENS.access_token}`
          ? HttpResponse.json(ME)
          : problem(401, 'not_authenticated'),
      ),
    );
    // как createAuth в app/session.ts: обмен initData кладёт токены в память api-client
    const onReauth = async () => {
      setSession({ accessToken: TOKENS.access_token, refreshToken: TOKENS.refresh_token });
      return true;
    };
    await renderScreen({ signedIn: false, onReauth });

    expect(await screen.findByRole('heading', { name: 'Елена К.' })).toBeTruthy();
  });

  it('opens help (S47) from the support group', async () => {
    const { router } = await renderScreen();
    const support = await screen.findByRole('navigation', { name: 'Поддержка' });
    const help = within(support).getByRole('link', { name: 'Помощь' });
    expect(help.getAttribute('href')).toBe('/help');

    await act(async () => {
      fireEvent.click(help);
    });

    expect(router.state.location.pathname).toBe('/help');
    expect(await screen.findByRole('heading', { name: 'S47' })).toBeTruthy();
  });

  it('opens the platform rules (S48) from the support group', async () => {
    const { router } = await renderScreen();
    const support = await screen.findByRole('navigation', { name: 'Поддержка' });
    const rules = within(support).getByRole('link', { name: 'Правила площадки' });
    expect(rules.getAttribute('href')).toBe('/legal/terms');

    await act(async () => {
      fireEvent.click(rules);
    });

    expect(router.state.location.pathname).toBe('/legal/terms');
    expect(await screen.findByRole('heading', { name: 'S48' })).toBeTruthy();
  });

  it('shows S49a «Нет соединения» with retry when /me cannot be reached', async () => {
    server.use(http.get(ME_PATH, () => HttpResponse.error(), { once: true }));
    await renderScreen();

    expect(await screen.findByRole('heading', { name: 'Нет соединения', level: 2 })).toBeTruthy();
    expect(screen.getByText('Проверьте интернет и попробуйте ещё раз')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Что-то пошло не так' })).toBeNull();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });

    expect(await screen.findByRole('heading', { name: 'Елена К.' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Нет соединения' })).toBeNull();
  });

  it('keeps the saved profile under S49a when the network drops on refresh', async () => {
    const { queryClient } = await renderScreen();
    await screen.findByRole('heading', { name: 'Елена К.' });
    server.use(http.get(ME_PATH, () => HttpResponse.error()));

    await act(async () => {
      await queryClient.refetchQueries();
    });

    expect(await screen.findByRole('heading', { name: 'Нет соединения', level: 2 })).toBeTruthy();
    expect(screen.getByText('Показываем сохранённое — обновим, когда сеть появится')).toBeTruthy();
    const saved = screen.getByRole('region', { name: /^Сохранено в \d{2}:\d{2}$/ });
    expect(within(saved).getByRole('heading', { name: 'Елена К.' })).toBeTruthy();
  });

  it('outside Telegram shows the same state without calling the API', async () => {
    const getMe = vi.fn(() => HttpResponse.json(ME));
    server.use(http.get(ME_PATH, getMe));
    await renderScreen({ platform: createBrowserPlatform(), signedIn: false });

    expect(screen.getByRole('heading', { name: 'Откройте в Telegram' })).toBeTruthy();
    await act(async () => undefined);
    expect(getMe).not.toHaveBeenCalled();
  });
});
