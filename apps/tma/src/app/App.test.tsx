// Smoke каркаса на mock-платформе (DEVELOPMENT_PLAN 0.21a): провайдеры, маршруты, таббар,
// правило «таббар скрыт при MainButton», редирект неизвестного пути, язык из Telegram;
// ходячий скелет 0.22: вход по initData → язык с сервера, GET /me → имя на S31, смена языка;
// 1.5a: S48, S49 поверх приложения, ошибка рендера экрана и тема до первого экрана.
import type { ClientConfigOut } from '@sosed/api-client';
import { setSession } from '@sosed/api-client';
import {
  getIdentityAuthenticateTelegramMockHandler,
  getSystemGetClientConfigMockHandler,
} from '@sosed/api-client/mocks';
import type { ColorScheme } from '@sosed/platform';
import { createMockPlatform } from '@sosed/platform/mock';
import { createHashHistory, createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import type { FunctionComponent } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CLIENT_CONFIG, ME } from '../testing/fixtures.ts';
import { API_ORIGIN, TOKENS, server } from '../testing/msw.ts';
import { App } from './App.tsx';
import { assemble } from './bootstrap.ts';
import { CHROME } from './chrome.ts';
import { useSystemStore } from '../features/service/s49-system/index.ts';

/** Экран «Сообщения» падает при рендере, пока `broken.render`: ошибка любого экрана. */
const broken = vi.hoisted(() => ({ render: false }));
vi.mock('../features/messages/s29-chats/index.ts', async (importOriginal) => {
  const actual = await importOriginal<{ ChatsScreen: FunctionComponent }>();
  return {
    ...actual,
    ChatsScreen: () => {
      if (broken.render) throw new TypeError('screen render failed');
      return <actual.ChatsScreen />;
    },
  };
});

interface StartOptions {
  languageCode?: string;
  config?: ClientConfigOut;
  version?: string;
  telegramVersion?: string;
  colorScheme?: ColorScheme;
  /** Hash history, как в Telegram (app/router.ts), вместо memory. */
  hash?: boolean;
}

function start(path = '/', options: StartOptions = {}) {
  const { languageCode = 'ru', version = '0.1.0', telegramVersion, colorScheme, config } = options;
  if (config) server.use(getSystemGetClientConfigMockHandler(config));
  const { platform, telegram } = createMockPlatform({
    languageCode,
    version: telegramVersion,
    colorScheme,
  });
  const app = assemble(platform, {
    version,
    history: options.hash ? createHashHistory() : createMemoryHistory({ initialEntries: [path] }),
    baseUrl: API_ORIGIN,
  });
  render(<App {...app} />);
  return { app, telegram };
}

beforeEach(() => {
  useSystemStore.setState({ appWide: null, restriction: null });
  broken.render = false;
});

/** MainButton в Telegram нативная (в DOM её нет): показывалась ли она хоть раз. */
const mainButtonShown = (telegram: ReturnType<typeof start>['telegram']) =>
  telegram.callsOf('web_app_setup_main_button').some((params) => params?.is_visible === true);

describe('Mini App skeleton', () => {
  it('renders home with the tab bar and signals ready to Telegram', async () => {
    const { telegram } = start('/');

    expect(await screen.findByRole('heading', { name: 'Найдём мастера рядом' })).toBeTruthy();
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

  // В Telegram history — hash: href вкладки там «/#/profile», а не путь маршрута. Переход по
  // href вёл на главную, и вкладки казались некликабельными
  it('navigates between tabs with the hash history of Telegram', async () => {
    try {
      start('/', { hash: true });
      const nav = await screen.findByRole('navigation', { name: 'Разделы' });
      expect(within(nav).getByRole('link', { name: 'Профиль' }).getAttribute('href')).toBe(
        '/#/profile',
      );

      await act(async () => {
        fireEvent.click(within(nav).getByRole('link', { name: 'Профиль' }));
      });

      expect(await screen.findByRole('heading', { name: 'Профиль' })).toBeTruthy();
      expect(window.location.hash).toBe('#/profile');
      await act(async () => {
        fireEvent.click(within(nav).getByRole('link', { name: 'Сообщения' }));
      });
      expect(await screen.findByRole('heading', { name: 'Сообщения' })).toBeTruthy();
      expect(window.location.hash).toBe('#/messages');
    } finally {
      window.history.replaceState(null, '', '/');
    }
  });

  it('hides the tab bar while the MainButton is shown', async () => {
    const { telegram } = start('/jobs/new');

    expect(await screen.findByRole('heading', { name: 'Что нужно сделать?' })).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();
    const setup = telegram.callsOf('web_app_setup_main_button').at(-1);
    expect(setup).toMatchObject({ is_visible: true, text: 'Далее' });
    // открыт сразу, без истории: в шапке Telegram — «Закрыть», как на артборде S20a
    expect(telegram.callsOf('web_app_setup_back_button').at(-1)?.is_visible ?? false).toBe(false);
  });

  it('redirects unknown paths to home', async () => {
    start('/no/such/screen');
    expect(await screen.findByRole('heading', { name: 'Найдём мастера рядом' })).toBeTruthy();
  });

  it('takes the language from Telegram launch params', async () => {
    // гость (initData не принят): языка с сервера нет — остаётся язык клиента Telegram
    server.use(http.post('*/api/v1/auth/telegram', () => problem(401, 'invalid_init_data')));
    const { app } = start('/', { languageCode: 'sr' });
    expect(app.i18n.language).toBe('sr-Latn');
    expect(document.documentElement.lang).toBe('sr-Latn');
    expect(
      await screen.findByRole('heading', { name: 'Pronaći ćemo majstora u blizini' }),
    ).toBeTruthy();
  });
});

describe('client-config at startup', () => {
  it('shows the «Услуги / Вещи» segment only when goods.segment is on', async () => {
    start('/');
    const segment = await screen.findByRole('radiogroup', { name: 'Раздел' });
    await act(async () => {
      fireEvent.click(within(segment).getByRole('radio', { name: /^Вещи/ }));
    });
    expect(screen.getByRole('heading', { name: 'Вещи — скоро' })).toBeTruthy();
  });

  it('hides the segment when the flag is off', async () => {
    start('/', { config: { ...CLIENT_CONFIG, flags: { 'goods.segment': false } } });
    expect(await screen.findByRole('heading', { name: 'Найдём мастера рядом' })).toBeTruthy();
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

    // язык — в настройках S43 (4.9): строка «Язык» профиля ведёт туда
    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: /^Язык/ }));
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole('radio', { name: 'Srpski (latinica)' }));
    });

    expect(await screen.findByRole('heading', { name: 'Podešavanja', level: 1 })).toBeTruthy();
    expect(document.documentElement.lang).toBe('sr-Latn');
  });

  it('switches to the language saved on the server once signed in', async () => {
    const user = { ...ME, ui_locale: 'sr-Cyrl' as const };
    server.use(getIdentityAuthenticateTelegramMockHandler({ ...TOKENS, is_new: false, user }));
    const { app } = start('/', { languageCode: 'ru' });

    // вход при запуске (S01) — до первого экрана: главная сразу на сохранённом языке, без мигания ru
    expect(
      await screen.findByRole('heading', { name: 'Пронаћи ћемо мајстора у близини' }),
    ).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Найдём мастера рядом' })).toBeNull();
    expect(app.i18n.language).toBe('sr-Cyrl');
    expect(document.documentElement.lang).toBe('sr-Cyrl');
    expect(
      await screen.findByRole('heading', { name: 'Пронаћи ћемо мајстора у близини' }),
    ).toBeTruthy();
  });
});

const problem = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  HttpResponse.json(
    { type: 'x', title: code, status, code, trace_id: 'test', ...extra },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  );

/** /me только с токеном из POST /auth/telegram — как backend. */
const meWithToken = http.get('*/api/v1/me', ({ request }) =>
  request.headers.get('Authorization') === `Bearer ${TOKENS.access_token}`
    ? HttpResponse.json(ME)
    : problem(401, 'not_authenticated'),
);

// 3 октября 18:00 по Белграду
const UNTIL = '2026-10-03T16:00:00Z';

describe('S48 legal documents (1.5a)', () => {
  it('opens a document by path, without the tab bar and with «Back»', async () => {
    const { app, telegram } = start('/legal/terms');

    expect(await screen.findByRole('heading', { name: 'Правила площадки', level: 1 })).toBeTruthy();
    expect(await screen.findByText('Редакция от 27 сентября 2026')).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();
    expect(telegram.callsOf('web_app_setup_back_button').at(-1)).toMatchObject({
      is_visible: true,
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Конфиденциальность' }));
    });
    expect(
      await screen.findByRole('heading', { name: 'Политика конфиденциальности', level: 1 }),
    ).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/legal/privacy');

    // открыли по ссылке, истории нет — «Назад» ведёт в профиль, откуда S48 открывают
    await act(async () => {
      telegram.emit('back_button_pressed');
    });
    expect(await screen.findByRole('heading', { name: 'Профиль', level: 1 })).toBeTruthy();
  });

  it('redirects an unknown document to the rules', async () => {
    const { app } = start('/legal/nope');
    expect(await screen.findByRole('heading', { name: 'Правила площадки', level: 1 })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/legal/terms');
  });
});

describe('S49 system states (1.5a)', () => {
  afterEach(() => setSession(null));

  it('shows maintenance by the client-config flag and retries', async () => {
    let maintenance = true;
    server.use(
      http.get('*/api/v1/client-config', () =>
        HttpResponse.json({
          ...CLIENT_CONFIG,
          flags: { ...CLIENT_CONFIG.flags, 'platform.maintenance': maintenance },
        }),
      ),
    );
    start('/');

    expect(await screen.findByRole('heading', { name: 'Технические работы' })).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();

    maintenance = false;
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });
    expect(await screen.findByRole('heading', { name: 'Найдём мастера рядом' })).toBeTruthy();
  });

  it('switches to maintenance on 503 maintenance from any request', async () => {
    server.use(http.patch('*/api/v1/me', () => problem(503, 'maintenance')));
    start('/settings');
    const language = await screen.findByRole('radio', { name: 'Srpski (latinica)' });

    await act(async () => {
      fireEvent.click(language);
    });

    expect(await screen.findByRole('heading', { name: 'Технические работы' })).toBeTruthy();
  });

  it('switches to maintenance when sign-in at launch meets 503', async () => {
    server.use(http.post('*/api/v1/auth/telegram', () => problem(503, 'maintenance')));
    start('/');
    expect(await screen.findByRole('heading', { name: 'Технические работы' })).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();
  });

  it('shows S49a when client-config cannot be reached at startup', async () => {
    let online = false;
    server.use(
      http.get('*/api/v1/client-config', () =>
        online ? HttpResponse.json(CLIENT_CONFIG) : HttpResponse.error(),
      ),
    );
    start('/');

    // после двух повторов запроса
    expect(
      await screen.findByRole('heading', { name: 'Нет соединения' }, { timeout: 5000 }),
    ).toBeTruthy();
    online = true;
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });
    expect(await screen.findByRole('heading', { name: 'Найдём мастера рядом' })).toBeTruthy();
  }, 10_000);

  it('closes the app with S49b when sign-in is refused by an account suspension', async () => {
    server.use(
      http.post('*/api/v1/auth/telegram', () =>
        problem(403, 'restricted', { restriction: 'suspended', until: UNTIL }),
      ),
    );
    const { app, telegram } = start('/');
    await act(async () => {
      await app.signIn();
    });

    expect(
      await screen.findByRole('heading', { name: 'Аккаунт приостановлен до 3 октября' }),
    ).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();
    // «Обжаловать» (2.5b) — только при частичной санкции: вход закрыт, сессии для запроса нет
    expect(screen.queryByRole('button', { name: 'Обжаловать' })).toBeNull();
    expect(mainButtonShown(telegram)).toBe(false);
  });

  it('starts loading the S49b texts with the restriction, not after its screen chunk', async () => {
    server.use(
      http.post('*/api/v1/auth/telegram', () =>
        problem(403, 'restricted', { restriction: 'banned', until: null }),
      ),
    );
    // без рендера: неймспейс service не запросят ни экран S49b, ни фоновая догрузка оболочки
    const app = assemble(createMockPlatform({ languageCode: 'ru' }).platform, {
      version: '0.1.0',
      history: createMemoryHistory({ initialEntries: ['/'] }),
      baseUrl: API_ORIGIN,
    });
    const load = vi.spyOn(app.i18n, 'loadNamespaces');

    await app.signIn();

    expect(load).toHaveBeenCalledWith('service');
    await waitFor(() => expect(app.i18n.hasLoadedNamespace('service')).toBe(true));
    expect(app.i18n.getFixedT('ru', 'service')('restricted.title', { kind: 'banned' })).toBe(
      'Аккаунт заблокирован',
    );
  });

  it('opens S49b when an action is refused by a partial restriction', async () => {
    server.use(
      meWithToken,
      http.patch('*/api/v1/me', () =>
        problem(403, 'restricted', { restriction: 'responding_blocked', until: UNTIL }),
      ),
    );
    const { app, telegram } = start('/settings');
    void app.signIn();
    const language = await screen.findByRole('radio', { name: 'Srpski (latinica)' });

    await act(async () => {
      fireEvent.click(language);
    });

    expect(
      await screen.findByRole('heading', { name: 'Аккаунт ограничен до 3 октября', level: 1 }),
    ).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/restricted');
    expect(screen.getByRole('alert').textContent).toBe(
      'До 3 октября, 18:00 нельзя откликаться на заявки',
    );
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();

    await act(async () => {
      telegram.emit('back_button_pressed');
    });
    expect(await screen.findByRole('heading', { name: 'Настройки', level: 1 })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/settings');
  });
});

describe('render errors and theme (1.5a)', () => {
  it('shows S49 «Что-то пошло не так» when a screen throws and recovers on «Повторить»', async () => {
    broken.render = true;
    start('/messages');

    // экран ошибки приложения, а не запасной экран роутера («Something went wrong!»)
    expect(
      await screen.findByRole('heading', { name: 'Что-то пошло не так', level: 1 }),
    ).toBeTruthy();
    expect(screen.queryByText(/Something went wrong/)).toBeNull();

    broken.render = false;
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });
    expect(await screen.findByRole('heading', { name: 'Сообщения', level: 1 })).toBeTruthy();
    expect(screen.getByRole('navigation', { name: 'Разделы' })).toBeTruthy();
  });

  it('applies the theme before the first frame and signals ready only after it', async () => {
    document.documentElement.dataset.theme = 'light';
    const { platform, telegram } = createMockPlatform({ colorScheme: 'dark' });
    const app = assemble(platform, {
      version: '0.1.0',
      history: createMemoryHistory({ initialEntries: ['/'] }),
      baseUrl: API_ORIGIN,
    });

    // до рендера: тема и цвета клиента уже стоят, а ready() нет — Telegram держит свою заглушку
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(telegram.callsOf('web_app_set_background_color').at(-1)).toEqual({
      color: CHROME.dark.background,
    });
    expect(telegram.callsOf('web_app_ready')).toHaveLength(0);

    render(<App {...app} />);
    await waitFor(() => expect(telegram.callsOf('web_app_ready')).toHaveLength(1));
  });

  it('applies the dark theme and Telegram colors before a startup S49 screen', async () => {
    const { telegram } = start('/', {
      colorScheme: 'dark',
      config: { ...CLIENT_CONFIG, flags: { ...CLIENT_CONFIG.flags, 'platform.maintenance': true } },
    });

    // оболочки маршрутов нет — тему ставит точка сборки
    expect(await screen.findByRole('heading', { name: 'Технические работы' })).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(telegram.callsOf('web_app_set_header_color').at(-1)).toEqual({
      color: CHROME.dark.header,
    });
    expect(telegram.callsOf('web_app_set_background_color').at(-1)).toEqual({
      color: CHROME.dark.background,
    });
  });
});
