// S31-заглушка (DEVELOPMENT_PLAN 0.22): имя из GET /me, смена языка через PATCH /me, ошибки API
// и состояние «вне Telegram». API — MSW из orval с фикстурами SPEC §4.
import { configureApiClient, setSession } from '@sosed/api-client';
import type { Locale } from '@sosed/i18n';
import { I18nextProvider, createI18n, currentLocale } from '@sosed/i18n';
import type { Platform } from '@sosed/platform';
import { PlatformProvider, createBrowserPlatform, createMockPlatform } from '@sosed/platform';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';

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

function renderScreen(options: RenderOptions = {}) {
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
  render(
    <PlatformProvider platform={platform}>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <AccountScreen />
        </QueryClientProvider>
      </I18nextProvider>
    </PlatformProvider>,
  );
  return { i18n };
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
    renderScreen();

    expect(await screen.findByRole('heading', { name: 'Елена К.', level: 2 })).toBeTruthy();
    expect(screen.getByText(`ID: ${ME.id}`)).toBeTruthy();
    expect(auth).toEqual([`Bearer ${TOKENS.access_token}`]);
    expect(checked('Русский')).toBe('true');
  });

  it('shows a loading state until /me answers', async () => {
    renderScreen();
    expect(screen.getByRole('status', { name: 'Загружаем профиль' })).toBeTruthy();
    expect(await screen.findByRole('heading', { name: 'Елена К.' })).toBeTruthy();
  });

  it('saves the language with PATCH /me, switches the app and reloads /me', async () => {
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
    const { i18n } = renderScreen();
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
    // /me перечитан уже на новом языке
    await waitFor(() => expect(languages).toEqual(['ru', 'sr-Latn']));
  });

  it('does not call the API when the current language is chosen again', async () => {
    const patch = vi.fn(() => HttpResponse.json(ME));
    server.use(http.patch(ME_PATH, patch));
    renderScreen();
    await screen.findByRole('heading', { name: 'Елена К.' });

    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Русский' }));
    });

    expect(patch).not.toHaveBeenCalled();
  });

  it.each([
    [412, 'stale_version'],
    [500, 'internal_error'],
  ])('keeps the language and shows an error when PATCH /me fails with %i', async (status, code) => {
    server.use(http.patch(ME_PATH, () => problem(status, code)));
    const { i18n } = renderScreen();
    await screen.findByRole('heading', { name: 'Елена К.' });

    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Српски (ћирилица)' }));
    });

    expect((await screen.findByRole('alert')).textContent).toBe(
      'Не получилось сменить язык. Попробуйте ещё раз',
    );
    expect(i18n.language).toBe('ru');
    expect(checked('Русский')).toBe('true');
    expect(checked('Српски (ћирилица)')).toBe('false');
  });

  it('shows an error with retry when GET /me fails', async () => {
    server.use(http.get(ME_PATH, () => problem(500, 'internal_error'), { once: true }));
    renderScreen();

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
    renderScreen({ signedIn: false, onReauth });

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
    renderScreen({ signedIn: false, onReauth });

    expect(await screen.findByRole('heading', { name: 'Елена К.' })).toBeTruthy();
  });

  it('outside Telegram shows the same state without calling the API', async () => {
    const getMe = vi.fn(() => HttpResponse.json(ME));
    server.use(http.get(ME_PATH, getMe));
    renderScreen({ platform: createBrowserPlatform(), signedIn: false });

    expect(screen.getByRole('heading', { name: 'Откройте в Telegram' })).toBeTruthy();
    await act(async () => undefined);
    expect(getMe).not.toHaveBeenCalled();
  });
});
