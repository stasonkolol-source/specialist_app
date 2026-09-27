// Smoke каркаса на mock-платформе (DEVELOPMENT_PLAN 0.21a): провайдеры, маршруты, таббар,
// правило «таббар скрыт при MainButton», редирект неизвестного пути, язык из Telegram.
import type { ClientConfigOut } from '@sosed/api-client';
import { createMockPlatform } from '@sosed/platform';
import { createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { App } from './App.tsx';
import { assemble } from './bootstrap.ts';
import { useUpgradeStore } from './upgrade.ts';

const CONFIG: ClientConfigOut = {
  min_versions: { tma: '0.1.0' },
  flags: { 'goods.segment': false },
  legal_versions: {},
};

interface StartOptions {
  languageCode?: string;
  config?: ClientConfigOut;
  /** Ответ client-config вместо конфига: например, 426 от backend. */
  configResponse?: () => Response;
  version?: string;
  telegramVersion?: string;
}

function start(path = '/', options: StartOptions = {}) {
  const { languageCode = 'ru', config = CONFIG, version = '0.1.0', telegramVersion } = options;
  const { platform, telegram } = createMockPlatform({ languageCode, version: telegramVersion });
  const fetch = async (url: RequestInfo | URL) =>
    String(url) === '/api/v1/client-config'
      ? (options.configResponse?.() ?? new Response(JSON.stringify(config), { status: 200 }))
      : new Response(null, { status: 404 });
  const app = assemble(platform, {
    version,
    history: createMemoryHistory({ initialEntries: [path] }),
    fetch,
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
    start('/', { config: { ...CONFIG, flags: { 'goods.segment': true } } });
    const segment = await screen.findByRole('radiogroup', { name: 'Раздел' });
    await act(async () => {
      fireEvent.click(within(segment).getByRole('radio', { name: 'Вещи' }));
    });
    expect(screen.getByRole('heading', { name: 'Вещи — скоро' })).toBeTruthy();
  });

  it('hides the segment when the flag is off', async () => {
    start('/');
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
    start('/', {
      configResponse: () =>
        new Response(JSON.stringify(problem), {
          status: 426,
          headers: { 'Content-Type': 'application/problem+json' },
        }),
    });
    expect(await screen.findByRole('heading', { name: 'Вышла новая версия' })).toBeTruthy();
  });
});
