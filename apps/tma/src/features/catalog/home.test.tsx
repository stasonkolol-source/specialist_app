// Главная S03 (DEVELOPMENT_PLAN 4.8) на MSW: заголовок и чип города, плитки разделов → выдача
// раздела, «Все услуги» → S04, подсказки при вводе → выдача категории, Enter → выдача по тексту,
// «Свободны сегодня рядом» и «Все» с точкой клиента после нажатия на чип; «Вещи» — S58 (7.5):
// «Сообщить о запуске» сначала просит разрешить боту писать, потом включает группу `goods_launch`.
import type { NotificationSettingsIn, NotificationSettingsOut } from '@sosed/api-client';
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { startApp } from '../../testing/app.tsx';
import {
  CATEGORY_IDS,
  NOTIFICATION_SETTINGS,
  WRITE_ACCESS,
  categoriesFor,
} from '../../testing/fixtures.ts';
import { server } from '../../testing/msw.ts';

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
      lat: 45.267,
      lon: 19.834,
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
