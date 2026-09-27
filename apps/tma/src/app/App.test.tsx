// Smoke каркаса на mock-платформе (DEVELOPMENT_PLAN 0.21a): провайдеры, маршруты, таббар,
// правило «таббар скрыт при MainButton», редирект неизвестного пути, язык из Telegram;
// ходячий скелет 0.22: вход по initData → язык с сервера, GET /me → имя на S31, смена языка.
import type { ClientConfigOut } from '@sosed/api-client';
import { setSession } from '@sosed/api-client';
import {
  getIdentityAuthenticateTelegramMockHandler,
  getSystemGetClientConfigMockHandler,
} from '@sosed/api-client/mocks';
import { createMockPlatform } from '@sosed/platform';
import { createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { CLIENT_CONFIG, ME } from '../testing/fixtures.ts';
import { API_ORIGIN, TOKENS, server } from '../testing/msw.ts';
import { App } from './App.tsx';
import { assemble } from './bootstrap.ts';
import { useUpgradeStore } from './upgrade.ts';

interface StartOptions {
  languageCode?: string;
  config?: ClientConfigOut;
  version?: string;
  telegramVersion?: string;
}

function start(path = '/', options: StartOptions = {}) {
  const { languageCode = 'ru', version = '0.1.0', telegramVersion, config } = options;
  if (config) server.use(getSystemGetClientConfigMockHandler(config));
  const { platform, telegram } = createMockPlatform({ languageCode, version: telegramVersion });
  const app = assemble(platform, {
    version,
    history: createMemoryHistory({ initialEntries: [path] }),
    baseUrl: API_ORIGIN,
  });
  render(<App {...app} />);
  return { app, telegram };
}

beforeEach(() => {
  useUpgradeStore.setState({ forced: null });
});

describe('Mini App skeleton', () => {
  it('renders home with the tab bar and signals ready to Telegram', async () => {
    const { telegram } = start('/');

    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    const nav = screen.getByRole('navigation', { name: 'Разделы' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((link) => link.textContent || link.getAttribute('aria-label'))).toEqual([
      'Главная',
      'Заявки',
      'Создать заявку',
      'Сообщения',
      'Профиль',
    ]);
    expect(within(nav).getByRole('link', { name: 'Главная' }).getAttribute('aria-current')).toBe(
      'page',
    );
    expect(telegram.callsOf('web_app_ready')).toHaveLength(1);
    expect(telegram.callsOf('web_app_expand')).toHaveLength(1);
  });

  it('navigates between tabs', async () => {
    start('/');
    const nav = await screen.findByRole('navigation', { name: 'Разделы' });

    await act(async () => {
      fireEvent.click(within(nav).getByRole('link', { name: 'Сообщения' }));
    });

    expect(await screen.findByRole('heading', { name: 'Сообщения' })).toBeTruthy();
    expect(within(nav).getByRole('link', { name: 'Сообщения' }).getAttribute('aria-current')).toBe(
      'page',
    );
  });

  it('hides the tab bar while the MainButton is shown', async () => {
    const { telegram } = start('/jobs/new');

    expect(await screen.findByRole('heading', { name: 'Создать заявку' })).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();
    const setup = telegram.callsOf('web_app_setup_main_button').at(-1);
    expect(setup).toMatchObject({ is_visible: true, text: 'Далее' });
    expect(telegram.callsOf('web_app_setup_back_button').at(-1)).toMatchObject({
      is_visible: true,
    });
  });

  it('redirects unknown paths to home', async () => {
    start('/no/such/screen');
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
  });

  it('takes the language from Telegram launch params', async () => {
    const { app } = start('/', { languageCode: 'sr' });
    expect(app.i18n.language).toBe('sr-Latn');
    expect(document.documentElement.lang).toBe('sr-Latn');
    expect(await screen.findByRole('heading', { name: app.i18n.t('nav.home') })).toBeTruthy();
  });
});

describe('client-config at startup', () => {
  it('shows the «Услуги / Вещи» segment only when goods.segment is on', async () => {
    start('/');
    const segment = await screen.findByRole('radiogroup', { name: 'Раздел' });
    await act(async () => {
      fireEvent.click(within(segment).getByRole('radio', { name: 'Вещи' }));
    });
    expect(screen.getByRole('heading', { name: 'Вещи — скоро' })).toBeTruthy();
  });

  it('hides the segment when the flag is off', async () => {
    start('/', { config: { ...CLIENT_CONFIG, flags: { 'goods.segment': false } } });
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(screen.queryByRole('radiogroup', { name: 'Раздел' })).toBeNull();
  });

  it('asks to update Telegram below the minimum Bot API', async () => {
    start('/', { telegramVersion: '6.0' });
    expect(await screen.findByRole('heading', { name: 'Обновите Telegram' })).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();
  });

  it('asks to reload an outdated Mini App bundle', async () => {
    start('/', { version: '0.0.9' });
    expect(await screen.findByRole('heading', { name: 'Вышла новая версия' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Перезагрузить' })).toBeTruthy();
  });

  it('switches to the update screen on 426 from the API', async () => {
    const problem = {
      type: 'x',
      title: 'Upgrade Required',
      status: 426,
      code: 'client_upgrade_required',
      trace_id: null,
      min_version: '9.0.0',
    };
    server.use(
      http.get('*/api/v1/client-config', () => HttpResponse.json(problem, { status: 426 })),
    );
    start('/');
    expect(await screen.findByRole('heading', { name: 'Вышла новая версия' })).toBeTruthy();
  });
});

describe('walking skeleton (0.22)', () => {
  afterEach(() => setSession(null));

  it('signs in by initData, shows the name from /me and switches <html lang>', async () => {
    // /me только с токеном из POST /auth/telegram: запрос раньше входа получит 401 и дождётся его
    server.use(
      http.get('*/api/v1/me', ({ request }) =>
        request.headers.get('Authorization') === `Bearer ${TOKENS.access_token}`
          ? HttpResponse.json(ME)
          : HttpResponse.json(
              { type: 'x', title: 'Unauthorized', status: 401, code: 'not_authenticated' },
              { status: 401 },
            ),
      ),
    );
    const { app } = start('/profile');
    void app.signIn(); // как main.tsx

    expect(await screen.findByRole('heading', { name: ME.display_name })).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Srpski (latinica)' }));
    });

    expect(await screen.findByRole('heading', { name: 'Profil', level: 1 })).toBeTruthy();
    expect(document.documentElement.lang).toBe('sr-Latn');
  });

  it('switches to the language saved on the server once signed in', async () => {
    const user = { ...ME, ui_locale: 'sr-Cyrl' as const };
    server.use(getIdentityAuthenticateTelegramMockHandler({ ...TOKENS, is_new: false, user }));
    const { app } = start('/', { languageCode: 'ru' });
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();

    await act(async () => {
      await app.signIn();
    });

    expect(app.i18n.language).toBe('sr-Cyrl');
    expect(document.documentElement.lang).toBe('sr-Cyrl');
    expect(await screen.findByRole('heading', { name: 'Почетна' })).toBeTruthy();
  });
});
