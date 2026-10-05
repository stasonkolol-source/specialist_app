// Главная S03 (DEVELOPMENT_PLAN 4.8) на MSW: заголовок и чип города, плитки разделов → выдача
// раздела, «Все услуги» → S04, подсказки при вводе → выдача категории, Enter → выдача по тексту,
// «Свободны сегодня рядом» и «Все» с точкой клиента после нажатия на чип; «Вещи» — S58 (7.5):
// «Сообщить о запуске» сначала просит разрешить боту писать, потом включает группу `goods_launch`.
// Место под «Мои активные заявки» до ответа /me/jobs — только под столько строк, сколько было в
// прошлый раз: плитки разделов не прыгают ни у клиента без заявок, ни у клиента с ними.
import type { JobOut, NotificationSettingsIn, NotificationSettingsOut } from '@sosed/api-client';
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { startApp } from '../../testing/app.tsx';
import {
  CATEGORY_IDS,
  ME,
  NOTIFICATION_SETTINGS,
  WRITE_ACCESS,
  categoriesFor,
} from '../../testing/fixtures.ts';
import { myJobsFixture } from '../../testing/jobsBackend.ts';
import { server } from '../../testing/msw.ts';
import { rememberRows, rememberedRows } from './s03-home/activeJobs.ts';

const HOME = 'Найдём мастера рядом';

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

afterEach(() => setSession(null));

describe('S03 home', () => {
  it('shows the city, the sections and who is free today', async () => {
    startApp('/');

    expect(await screen.findByRole('heading', { name: HOME, level: 1 })).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Нови-Сад' })).toBeTruthy();
    const sections = within(screen.getByRole('region', { name: 'Что нужно сделать?' }));
    expect((await sections.findAllByRole('link')).map((tile) => tile.textContent?.trim())).toEqual([
      'Мастер на час',
      'Бьюти',
      'Уборка',
      'Переезды',
      'Репетиторы',
      'Все услуги',
    ]);
    const today = within(await screen.findByRole('region', { name: 'Свободны сегодня рядом' }));
    expect(today.getByText('Алексей Морозов')).toBeTruthy();
    // как на артборде S03: «37 отзывов» словом, а не «(37)» выдачи; языки — словами
    expect(today.getByText('37 отзывов')).toBeTruthy();
    expect(today.getByText('рус., серб.')).toBeTruthy();
  });

  it('a guest with refused initData signs in once and does not ask /me for the city', async () => {
    const calls: string[] = [];
    const refused = (code: string) => HttpResponse.json({ status: 401, code }, { status: 401 });
    server.use(
      http.post('*/api/v1/auth/telegram', () => {
        calls.push('auth');
        return refused('init_data_expired');
      }),
      http.get('*/api/v1/me', () => {
        calls.push('me');
        return refused('not_authenticated');
      }),
    );
    startApp('/');

    expect(await screen.findByRole('button', { name: 'Нови-Сад' })).toBeTruthy();
    expect(await screen.findByRole('region', { name: 'Свободны сегодня рядом' })).toBeTruthy();
    // гостю /me не нужен, и 401 не запускает второй вход по тому же initData
    expect(calls).toEqual(['auth']);
  });

  it('keeps the tile grid while the sections load: no lone «All services»', async () => {
    let answer: () => void = () => undefined;
    const answered = new Promise<void>((resolve) => {
      answer = resolve;
    });
    server.use(
      http.get('*/api/v1/categories', async ({ request }) => {
        await answered;
        return HttpResponse.json(categoriesFor(request.headers.get('Accept-Language')));
      }),
    );
    startApp('/');

    const region = await screen.findByRole('region', { name: 'Что нужно сделать?' });
    // пять плиток-скелетонов в сетке и «Все услуги» — та же геометрия, что после ответа
    expect(region.querySelectorAll('.grid > [aria-hidden="true"]')).toHaveLength(5);
    expect(
      within(region)
        .getAllByRole('link')
        .map((tile) => tile.textContent?.trim()),
    ).toEqual(['Все услуги']);

    answer();
    expect(await within(region).findByRole('link', { name: /Уборка/ })).toBeTruthy();
    expect(region.querySelectorAll('.grid > [aria-hidden="true"]')).toHaveLength(0);
  });

  it('opens the results of a section and the whole catalog', async () => {
    const { app } = startApp('/');

    await click(await screen.findByRole('link', { name: /Уборка/ }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog/results'));
    expect(app.router.state.location.search).toEqual({ category: CATEGORY_IDS['cleaning'] });
    await act(async () => {
      app.router.history.back();
    });
    await click(await screen.findByRole('link', { name: /Все услуги/ }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog'));
  });

  it('suggests categories while typing and searches the text on Enter', async () => {
    const { app } = startApp('/');
    const field = await screen.findByRole('searchbox', { name: 'Поиск услуг и специалистов' });

    await act(async () => {
      fireEvent.change(field, { target: { value: 'элек' } });
    });
    const suggestions = within(await screen.findByRole('navigation', { name: 'Подсказки' }));
    await click(suggestions.getByRole('button', { name: /Электрика/ }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog/results'));
    expect(app.router.state.location.search).toEqual({ category: CATEGORY_IDS['electrical'] });

    await act(async () => {
      await app.router.navigate({ to: '/' });
    });
    const again = await screen.findByRole('searchbox', { name: 'Поиск услуг и специалистов' });
    await act(async () => {
      fireEvent.change(again, { target: { value: 'люстра' } });
      fireEvent.submit(again.closest('form') as HTMLFormElement);
    });
    await waitFor(() => expect(app.router.state.location.search).toEqual({ q: 'люстра' }));
  });

  it('finds the district by location and opens who is free today nearby', async () => {
    const { app } = startApp('/');

    await click(await screen.findByRole('button', { name: 'Нови-Сад' }));

    expect(await screen.findByRole('button', { name: 'Нови-Сад · Лиман' })).toBeTruthy();
    const today = within(screen.getByRole('region', { name: 'Свободны сегодня рядом' }));
    await click(today.getByRole('link', { name: 'Все' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog/results'));
    expect(app.router.state.location.search).toEqual({
      today: true,
      sort: 'distance',
      lat: 45.24,
      lon: 19.835,
    });
  });

  it('shows S58 in the second segment and leads movers to a new job', async () => {
    const { app } = startApp('/');

    await click(await screen.findByRole('radio', { name: /^Вещи/ }));

    expect(await screen.findByRole('heading', { name: 'Вещи — скоро', level: 1 })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: HOME })).toBeNull();
    const features = within(await screen.findByRole('region', { name: 'Что здесь будет' }));
    expect(features.getAllByRole('listitem')).toHaveLength(4);
    // шаблона «Уезжаю» нет (Q23): переезд — обычный мастер заявки S20a
    await click(screen.getByRole('link', { name: /Переезжаете\?/ }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/new'));
  });
});

/** Настройки уведомлений с памятью, как backend: разрешение боту писать попадает в `telegram`. */
function settingsBackend() {
  let settings: NotificationSettingsOut = NOTIFICATION_SETTINGS;
  const puts: NotificationSettingsIn[] = [];
  let writeAccess = 0;
  server.use(
    http.get('*/api/v1/me/notification-settings', () => HttpResponse.json(settings)),
    http.post('*/api/v1/me/telegram/write-access', () => {
      writeAccess += 1;
      settings = { ...settings, telegram: WRITE_ACCESS };
      return HttpResponse.json(WRITE_ACCESS);
    }),
    http.put('*/api/v1/me/notification-settings', async ({ request }) => {
      const body = (await request.json()) as NotificationSettingsIn;
      puts.push(body);
      settings = {
        ...settings,
        groups: settings.groups.map((row) => ({
          ...row,
          ...body.groups.find((sent) => sent.group === row.group),
        })),
      };
      return HttpResponse.json(settings);
    }),
  );
  return { puts, writeAccess: () => writeAccess };
}

const goodsLaunch = (body: NotificationSettingsIn | undefined) =>
  body?.groups.find((row) => row.group === 'goods_launch');

describe('S03 my active jobs: the place before the list arrives', () => {
  afterEach(() => rememberRows(ME.id, 0));

  /** /me/jobs отвечает, когда тест разрешит: до этого видно, держит ли Главная место под блок. */
  function holdMyJobs(items: JobOut[]): () => Promise<void> {
    let release: () => void = () => undefined;
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get('*/api/v1/me/jobs', async () => {
        await released;
        return HttpResponse.json({ items });
      }),
    );
    return () =>
      act(async () => {
        release();
      });
  }

  /** Что прямо над разделами: блок своих заявок, его скелетон или раздел с заголовком и поиском. */
  const aboveSections = () =>
    screen.getByRole('region', { name: 'Что нужно сделать?' }).previousElementSibling;
  /** Строки скелетона — по строке RowsSkeleton (ui-web). */
  const skeletonRows = (element: Element | null | undefined) =>
    element?.querySelectorAll('.min-h-13').length ?? 0;

  it('keeps no place for a client without active jobs last time: the tiles do not jump up', async () => {
    const release = holdMyJobs([]);
    startApp('/');

    await screen.findByRole('heading', { name: HOME, level: 1 });
    await waitFor(() => expect(aboveSections()?.querySelector('h1')).toBeTruthy());
    expect(skeletonRows(aboveSections())).toBe(0);

    await release();
    await waitFor(() =>
      expect(screen.queryByRole('region', { name: 'Мои активные заявки' })).toBeNull(),
    );
    expect(aboveSections()?.querySelector('h1')).toBeTruthy();
  });

  it('holds as many rows as last time, then remembers the new count for the next launch', async () => {
    rememberRows(ME.id, 2);
    const [chandelier] = myJobsFixture();
    const release = holdMyJobs(chandelier ? [chandelier] : []);
    startApp('/');

    await screen.findByRole('heading', { name: HOME, level: 1 });
    expect(aboveSections()?.getAttribute('aria-hidden')).toBe('true');
    expect(skeletonRows(aboveSections())).toBe(2);

    await release();
    const block = await screen.findByRole('region', { name: 'Мои активные заявки' });
    expect(aboveSections()).toBe(block);
    await waitFor(() => expect(rememberedRows(ME.id)).toBe(1));
  });

  it('keeps the hint per user: another account on the device holds no place', async () => {
    rememberRows('someone-else', 3);
    const release = holdMyJobs([]);
    startApp('/');

    await screen.findByRole('heading', { name: HOME, level: 1 });
    expect(skeletonRows(aboveSections())).toBe(0);
    await release();
  });
});

describe('S58 goods soon', () => {
  it('asks the bot permission first, then subscribes to the launch', async () => {
    const backend = settingsBackend();
    startApp('/');
    await click(await screen.findByRole('radio', { name: /^Вещи/ }));

    await click(await screen.findByRole('button', { name: 'Сообщить о запуске' }));

    expect(
      await screen.findByText('Готово! Бот напишет, когда раздел «Вещи» откроется.'),
    ).toBeTruthy();
    expect(backend.writeAccess()).toBe(1);
    expect(backend.puts).toHaveLength(1);
    expect(goodsLaunch(backend.puts[0])).toEqual({
      group: 'goods_launch',
      telegram: true,
      in_app: true,
    });
    expect(screen.queryByRole('button', { name: 'Сообщить о запуске' })).toBeNull();
  });

  it('subscribes even when the bot may not write, and promises the app instead', async () => {
    const backend = settingsBackend();
    startApp('/', { writeAccess: false });
    await click(await screen.findByRole('radio', { name: /^Вещи/ }));

    await click(await screen.findByRole('button', { name: 'Сообщить о запуске' }));

    expect(
      await screen.findByText(
        'Готово! Сообщим в уведомлениях приложения, когда раздел «Вещи» откроется.',
      ),
    ).toBeTruthy();
    expect(backend.writeAccess()).toBe(0);
    expect(goodsLaunch(backend.puts[0])?.telegram).toBe(true);
  });

  it('shows «Готово!» to those already subscribed', async () => {
    server.use(
      http.get('*/api/v1/me/notification-settings', () =>
        HttpResponse.json({
          ...NOTIFICATION_SETTINGS,
          telegram: WRITE_ACCESS,
          groups: NOTIFICATION_SETTINGS.groups.map((row) =>
            row.group === 'goods_launch' ? { ...row, telegram: true, in_app: true } : row,
          ),
        } satisfies NotificationSettingsOut),
      ),
    );
    startApp('/');
    await click(await screen.findByRole('radio', { name: /^Вещи/ }));

    expect(
      await screen.findByText('Готово! Бот напишет, когда раздел «Вещи» откроется.'),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Сообщить о запуске' })).toBeNull();
  });

  it('keeps the button and says so when the subscription is not saved', async () => {
    settingsBackend();
    server.use(
      http.put('*/api/v1/me/notification-settings', () =>
        HttpResponse.json(
          { type: 'about:blank', title: 'x', status: 500, code: 'internal_error', trace_id: 't' },
          { status: 500, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    );
    startApp('/');
    await click(await screen.findByRole('radio', { name: /^Вещи/ }));

    await click(await screen.findByRole('button', { name: 'Сообщить о запуске' }));

    expect((await screen.findByRole('alert')).textContent).toBe(
      'Не получилось подписаться. Попробуйте ещё раз.',
    );
    expect(screen.getByRole('button', { name: 'Сообщить о запуске' })).toBeTruthy();
  });
});
