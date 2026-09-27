// S31-заглушка (DEVELOPMENT_PLAN 0.22): имя из GET /me, язык из ui_locale и его смена через
// PATCH /me, ошибки API и состояние «вне Telegram». API — MSW из orval с фикстурами SPEC §4.
import type { MeUpdateIn } from '@sosed/api-client';
import { configureApiClient, setSession } from '@sosed/api-client';
import type { Locale } from '@sosed/i18n';
import { I18nextProvider, createI18n, currentLocale } from '@sosed/i18n';
import type { Platform } from '@sosed/platform';
import { PlatformProvider, createBrowserPlatform, createMockPlatform } from '@sosed/platform';
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
import { afterEach, describe, expect, it, onTestFinished, vi } from 'vitest';

import { ME } from '../../../testing/fixtures.ts';
import { API_ORIGIN, TOKENS, server } from '../../../testing/msw.ts';
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
  return createRouter({
    routeTree: root.addChildren([profile, legal]),
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
  const i18n = createI18n({ locale, appName: 'Сосед' });
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

const checked = (name: string) => screen.getByRole('radio', { name }).getAttribute('aria-checked');

afterEach(() => setSession(null));

describe('S31 profile stub', () => {
  it('shows the name and the internal id from GET /me', async () => {
    const auth: (string | null)[] = [];
    server.use(
      http.get(ME_PATH, ({ request }) => {
        auth.push(request.headers.get('Authorization'));
        return HttpResponse.json(ME);
      }),
    );
    await renderScreen();

    expect(await screen.findByRole('heading', { name: 'Елена К.', level: 2 })).toBeTruthy();
    expect(screen.getByText(`ID: ${ME.id}`)).toBeTruthy();
    expect(auth).toEqual([`Bearer ${TOKENS.access_token}`]);
    expect(checked('Русский')).toBe('true');
  });

  it('announces loading until /me answers', async () => {
    await renderScreen();
    // live region читает содержимое: текст внутри, а не в aria-label
    expect(screen.getByRole('status').textContent).toBe('Загружаем профиль');
    expect(await screen.findByRole('heading', { name: 'Елена К.' })).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('saves the language with PATCH /me and keeps its answer as /me', async () => {
    let body: unknown = null;
    let ifMatch: string | null = null;
    const languages: (string | null)[] = [];
    server.use(
      http.get(ME_PATH, ({ request }) => {
        languages.push(request.headers.get('Accept-Language'));
        return HttpResponse.json(ME);
      }),
      http.patch(ME_PATH, async ({ request }) => {
        body = await request.json();
        ifMatch = request.headers.get('If-Match');
        return HttpResponse.json({ ...ME, ui_locale: 'sr-Latn' });
      }),
    );
    const { i18n } = await renderScreen();
    await screen.findByRole('heading', { name: 'Елена К.' });

    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Srpski (latinica)' }));
    });

    expect(await screen.findByRole('heading', { name: 'Profil', level: 1 })).toBeTruthy();
    expect(body).toEqual({ ui_locale: 'sr-Latn' });
    // ETag из GET /me mutator не отдаёт — If-Match пока не отправляем
    expect(ifMatch).toBeNull();
    expect(i18n.language).toBe('sr-Latn');
    expect(checked('Srpski (latinica)')).toBe('true');
    // ответ PATCH — тот же MeOut: /me не перечитывается
    await act(async () => undefined);
    expect(languages).toEqual(['ru']);
  });

  it('follows the language saved on the server and does not save it again', async () => {
    const patches: MeUpdateIn[] = [];
    server.use(
      http.get(ME_PATH, () => HttpResponse.json({ ...ME, ui_locale: 'sr-Cyrl' })),
      http.patch(ME_PATH, async ({ request }) => {
        const body = (await request.json()) as MeUpdateIn;
        patches.push(body);
        return HttpResponse.json({ ...ME, ...body });
      }),
    );
    // язык Telegram — ru, на сервере выбран sr-Cyrl
    const { i18n } = await renderScreen({ locale: 'ru' });

    expect(await screen.findByRole('heading', { name: 'Профил', level: 1 })).toBeTruthy();
    expect(i18n.language).toBe('sr-Cyrl');
    expect(checked('Српски (ћирилица)')).toBe('true');
    expect(checked('Русский')).toBe('false');

    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Српски (ћирилица)' }));
    });
    expect(patches).toEqual([]);

    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Русский' }));
    });
    expect(await screen.findByRole('heading', { name: 'Профиль', level: 1 })).toBeTruthy();
    expect(patches).toEqual([{ ui_locale: 'ru' }]);
    expect(i18n.language).toBe('ru');
    expect(checked('Русский')).toBe('true');
  });

  it('keeps the current language when the server has en, which MVP does not offer', async () => {
    const patch = vi.fn(() => HttpResponse.json(ME));
    server.use(
      http.get(ME_PATH, () => HttpResponse.json({ ...ME, ui_locale: 'en' })),
      http.patch(ME_PATH, patch),
    );
    const { i18n } = await renderScreen({ locale: 'sr-Latn' });
    await screen.findByRole('heading', { name: 'Елена К.' });

    expect(i18n.language).toBe('sr-Latn');
    expect(checked('Srpski (latinica)')).toBe('true');

    // на сервере en: выбор отмеченного языка сохраняется
    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Srpski (latinica)' }));
    });
    await waitFor(() => expect(patch).toHaveBeenCalledOnce());
  });

  it('does not call the API when the saved language is chosen again', async () => {
    const patch = vi.fn(() => HttpResponse.json(ME));
    server.use(http.patch(ME_PATH, patch));
    await renderScreen();
    await screen.findByRole('heading', { name: 'Елена К.' });

    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Русский' }));
    });

    expect(patch).not.toHaveBeenCalled();
  });

  // 412 сюда не попадает: If-Match клиент не шлёт, а без него сервер версию не сверяет
  it.each([
    ['500', () => problem(500, 'internal_error')],
    ['a network error', () => HttpResponse.error()],
  ])(
    'keeps the language and shows an error at once when PATCH /me fails with %s',
    async (_, fail) => {
      // /me после ошибки перечитывается, но ответа нет: экран не должен его ждать
      let release = () => undefined as void;
      const hold = new Promise<void>((resolve) => {
        release = resolve;
      });
      onTestFinished(() => release());
      let gets = 0;
      const patch = vi.fn(fail);
      server.use(
        http.get(ME_PATH, async () => {
          gets += 1;
          if (gets > 1) await hold;
          return HttpResponse.json(ME);
        }),
        http.patch(ME_PATH, patch),
      );
      const { i18n } = await renderScreen();
      await screen.findByRole('heading', { name: 'Елена К.' });

      await act(async () => {
        fireEvent.click(screen.getByRole('radio', { name: 'Српски (ћирилица)' }));
      });

      await waitFor(() =>
        expect(screen.getByRole('alert').textContent).toBe(
          'Не получилось сменить язык. Попробуйте ещё раз',
        ),
      );
      expect(gets).toBe(2);
      expect(i18n.language).toBe('ru');
      expect(checked('Русский')).toBe('true');
      expect(checked('Српски (ћирилица)')).toBe('false');

      // следующий выбор не отбрасывается, пока /me перечитывается
      await act(async () => {
        fireEvent.click(screen.getByRole('radio', { name: 'Srpski (latinica)' }));
      });
      await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    },
  );

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
