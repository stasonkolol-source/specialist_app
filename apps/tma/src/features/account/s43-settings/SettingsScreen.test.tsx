// S43 Настройки (DEVELOPMENT_PLAN 4.9) в приложении целиком на mock-платформе и MSW: язык (PATCH
// /me, без перезагрузки; тесты перенесены с S31), город в шторке, уведомления «группа × канал» и
// тихие часы (PUT /me/notification-settings, нажатие видно сразу), переключатель «Запуск раздела
// «Вещи»» у подписанных (7.5), экспорт данных через поддержку и «скоро» без контакта, версия.
import type {
  CityOut,
  MeUpdateIn,
  NotificationSettingsIn,
  NotificationSettingsOut,
} from '@sosed/api-client';
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, describe, expect, it, onTestFinished, vi } from 'vitest';

import { startApp, userBackend } from '../../../testing/app.tsx';
import { CLIENT_CONFIG, ME, NOTIFICATION_SETTINGS, citiesFor } from '../../../testing/fixtures.ts';
import { server } from '../../../testing/msw.ts';

afterEach(() => setSession(null));

const ME_PATH = '*/api/v1/me';
const SETTINGS_PATH = '*/api/v1/me/notification-settings';

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

const problem = (status: number, code: string) =>
  HttpResponse.json(
    { type: 'about:blank', title: code, status, code, trace_id: 'test' },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  );

const checked = (role: 'radio' | 'checkbox' | 'switch', name: string) =>
  screen.getByRole(role, { name }).getAttribute('aria-checked');

/** Настройки уведомлений с памятью: PUT заменяет их, как backend; `fail` — ответ ошибкой. */
function notificationBackend({ fail = false, initial = NOTIFICATION_SETTINGS } = {}) {
  let settings = initial;
  const puts: NotificationSettingsIn[] = [];
  server.use(
    http.get(SETTINGS_PATH, () => HttpResponse.json(settings)),
    http.put(SETTINGS_PATH, async ({ request }) => {
      const body = (await request.json()) as NotificationSettingsIn;
      puts.push(body);
      if (fail) return problem(500, 'internal_error');
      settings = {
        ...settings,
        groups: settings.groups.map((row) => ({
          ...row,
          ...body.groups.find((sent) => sent.group === row.group),
        })),
        quiet_hours: { ...settings.quiet_hours, enabled: body.quiet_hours.enabled },
      } satisfies NotificationSettingsOut;
      return HttpResponse.json(settings);
    }),
  );
  return { puts };
}

describe('S43 language', () => {
  it('saves the language with PATCH /me and keeps its answer as /me', async () => {
    const backend = userBackend(ME);
    const gets: (string | null)[] = [];
    server.use(
      http.get(ME_PATH, ({ request }) => {
        gets.push(request.headers.get('Accept-Language'));
        return HttpResponse.json(backend.user);
      }),
    );
    const { app } = startApp('/settings');
    await screen.findByRole('heading', { name: 'Настройки', level: 1 });
    expect(screen.getByText('English — скоро')).toBeTruthy();
    expect(checked('radio', 'Русский')).toBe('true');
    const before = gets.length;

    await click(screen.getByRole('radio', { name: 'Srpski (latinica)' }));

    expect(await screen.findByRole('heading', { name: 'Podešavanja', level: 1 })).toBeTruthy();
    expect(backend.requests.patch).toEqual([{ ui_locale: 'sr-Latn' }]);
    expect(app.i18n.language).toBe('sr-Latn');
    expect(document.documentElement.lang).toBe('sr-Latn');
    expect(checked('radio', 'Srpski (latinica)')).toBe('true');
    // ответ PATCH — тот же MeOut: /me не перечитывается
    await act(async () => undefined);
    expect(gets.length).toBe(before);
  });

  it('follows the language saved on the server and does not save it again', async () => {
    const backend = userBackend({ ...ME, ui_locale: 'sr-Cyrl' });
    // язык Telegram — ru, на сервере выбран sr-Cyrl
    const { app } = startApp('/settings', { languageCode: 'ru' });

    expect(await screen.findByRole('heading', { name: 'Подешавања', level: 1 })).toBeTruthy();
    expect(app.i18n.language).toBe('sr-Cyrl');
    expect(checked('radio', 'Српски (ћирилица)')).toBe('true');

    await click(screen.getByRole('radio', { name: 'Српски (ћирилица)' }));
    expect(backend.requests.patch).toEqual([]);

    await click(screen.getByRole('radio', { name: 'Русский' }));
    expect(await screen.findByRole('heading', { name: 'Настройки', level: 1 })).toBeTruthy();
    expect(backend.requests.patch).toEqual([{ ui_locale: 'ru' }]);
    expect(checked('radio', 'Русский')).toBe('true');
  });

  it('keeps the current language when the server has en, which MVP does not offer', async () => {
    const backend = userBackend({ ...ME, ui_locale: 'en' });
    const { app } = startApp('/settings', { languageCode: 'sr' });
    await screen.findByRole('heading', { name: 'Podešavanja', level: 1 });

    expect(app.i18n.language).toBe('sr-Latn');
    expect(checked('radio', 'Srpski (latinica)')).toBe('true');

    // на сервере en: выбор отмеченного языка сохраняется
    await click(screen.getByRole('radio', { name: 'Srpski (latinica)' }));
    await waitFor(() => expect(backend.requests.patch).toEqual([{ ui_locale: 'sr-Latn' }]));
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
      userBackend(ME);
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
      const { app } = startApp('/settings');
      await screen.findByRole('radio', { name: 'Русский' });

      await click(screen.getByRole('radio', { name: 'Српски (ћирилица)' }));

      await waitFor(() =>
        expect(screen.getByRole('alert').textContent).toBe(
          'Не получилось сменить язык. Попробуйте ещё раз.',
        ),
      );
      expect(app.i18n.language).toBe('ru');
      expect(checked('radio', 'Русский')).toBe('true');

      // следующий выбор не отбрасывается, пока /me перечитывается
      await click(screen.getByRole('radio', { name: 'Srpski (latinica)' }));
      await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    },
  );
});

describe('S43 city', () => {
  it('changes the city in a sheet; cities that are not open yet are «скоро»', async () => {
    const twoCities: CityOut[] = citiesFor('ru').map((city) => ({ ...city, status: 'active' }));
    const backend = userBackend(ME);
    server.use(http.get('*/api/v1/cities', () => HttpResponse.json(twoCities)));
    startApp('/settings');
    const row = await screen.findByRole('button', { name: /^Город/ });
    await waitFor(() => expect(row.textContent).toContain('Нови-Сад'));

    await click(row);
    const sheet = screen.getByRole('dialog', { name: 'Ваш город' });
    await click(within(sheet).getByRole('radio', { name: 'Белград' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(backend.requests.patch).toEqual([{ home_city_id: 2 } satisfies MeUpdateIn]);
    expect(screen.getByRole('button', { name: /^Город/ }).textContent).toContain('Белград');
  });

  it('shows a city that is not open yet as «скоро», not selectable', async () => {
    userBackend(ME);
    startApp('/settings');
    await click(await screen.findByRole('button', { name: /^Город/ }));

    const sheet = screen.getByRole('dialog', { name: 'Ваш город' });
    const belgrade = within(sheet).getByRole('radio', { name: 'Белград' }) as HTMLButtonElement;
    expect(belgrade.disabled).toBe(true);
    expect(belgrade.textContent).toContain('скоро');
    expect(
      within(sheet).getByRole('radio', { name: 'Нови-Сад' }).getAttribute('aria-checked'),
    ).toBe('true');
  });
});

describe('S43 notifications', () => {
  it('shows groups × channels without the service group and quiet hours', async () => {
    userBackend(ME);
    notificationBackend();
    startApp('/settings');

    const section = await screen.findByRole('region', { name: 'Уведомления' });
    await within(section).findByRole('checkbox', { name: 'Сообщения — в боте' });
    const boxes = within(section).getAllByRole('checkbox');
    expect(boxes.map((box) => box.getAttribute('aria-label'))).toEqual([
      'Заявки по подпискам — в боте',
      'Заявки по подпискам — в приложении',
      'Отклики и выбор — в боте',
      'Отклики и выбор — в приложении',
      'Сообщения — в боте',
      'Сообщения — в приложении',
      'Сделки, споры, отзывы — в боте',
      'Сделки, споры, отзывы — в приложении',
      'Новости «Соседей» — в боте',
      'Новости «Соседей» — в приложении',
    ]);
    expect(checked('checkbox', 'Новости «Соседей» — в боте')).toBe('false');
    expect(checked('switch', 'Тихие часы 22:00–08:00')).toBe('true');
    expect(
      within(section).getByText('Ночью придут только сообщения и срочные заявки'),
    ).toBeTruthy();
  });

  it('shows a tap at once and saves the whole settings', async () => {
    userBackend(ME);
    const backend = notificationBackend();
    startApp('/settings');
    const messages = await screen.findByRole('checkbox', { name: 'Сообщения — в боте' });

    await click(messages);

    await waitFor(() => expect(checked('checkbox', 'Сообщения — в боте')).toBe('false'));
    await waitFor(() => expect(backend.puts).toHaveLength(1));
    expect(backend.puts[0]).toEqual({
      groups: [
        { group: 'job_matches', telegram: true, in_app: true },
        { group: 'responses', telegram: true, in_app: true },
        { group: 'messages', telegram: false, in_app: true },
        { group: 'deals', telegram: true, in_app: true },
        { group: 'marketing', telegram: false, in_app: false },
        { group: 'goods_launch', telegram: false, in_app: false },
      ],
      quiet_hours: { enabled: true, start: '22:00:00', end: '08:00:00' },
      digest_hour: 9,
    });

    await click(screen.getByRole('switch', { name: 'Тихие часы 22:00–08:00' }));
    await waitFor(() => expect(backend.puts).toHaveLength(2));
    expect(backend.puts[1]?.quiet_hours.enabled).toBe(false);
    expect(backend.puts[1]?.groups[2]).toEqual({
      group: 'messages',
      telegram: false,
      in_app: true,
    });
    expect(checked('switch', 'Тихие часы 22:00–08:00')).toBe('false');
  });

  it('returns the mark and says it was not saved when the server fails', async () => {
    userBackend(ME);
    notificationBackend({ fail: true });
    startApp('/settings');

    await click(await screen.findByRole('checkbox', { name: 'Новости «Соседей» — в приложении' }));

    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toBe(
        'Не получилось сохранить. Попробуйте ещё раз.',
      ),
    );
    expect(checked('checkbox', 'Новости «Соседей» — в приложении')).toBe('false');
  });

  it('has no «Вещи» launch switch for those who did not subscribe on S58', async () => {
    userBackend(ME);
    notificationBackend();
    startApp('/settings');

    await screen.findByRole('checkbox', { name: 'Сообщения — в боте' });
    expect(screen.queryByRole('switch', { name: 'Запуск раздела «Вещи»' })).toBeNull();
  });

  it('unsubscribes from the «Вещи» launch with one switch and keeps the row', async () => {
    userBackend(ME);
    const backend = notificationBackend({
      initial: {
        ...NOTIFICATION_SETTINGS,
        groups: NOTIFICATION_SETTINGS.groups.map((row) =>
          row.group === 'goods_launch' ? { ...row, telegram: true, in_app: true } : row,
        ),
      },
    });
    startApp('/settings');
    const launch = await screen.findByRole('switch', { name: 'Запуск раздела «Вещи»' });
    expect(launch.getAttribute('aria-checked')).toBe('true');
    expect(screen.getByText('Бот напишет один раз, когда раздел откроется')).toBeTruthy();

    await click(launch);

    await waitFor(() => expect(backend.puts).toHaveLength(1));
    expect(backend.puts[0]?.groups).toContainEqual({
      group: 'goods_launch',
      telegram: false,
      in_app: false,
    });
    // выключил по ошибке — включит обратно: строка не пропадает
    expect(checked('switch', 'Запуск раздела «Вещи»')).toBe('false');
  });
});

describe('S43 data export and version', () => {
  it('is «скоро» until the support contact is set', async () => {
    userBackend(ME);
    startApp('/settings');

    const exportRow = await screen.findByText('Экспорт моих данных');
    expect(exportRow.closest('button')).toBeNull();
    expect(screen.getByText('скоро')).toBeTruthy();
    // «Запрос в поддержку» обещал бы действие, которое «скоро» отменяет
    expect(screen.queryByText('Запрос в поддержку')).toBeNull();
    expect(screen.getByText('Соседи · версия 0.0.0-test')).toBeTruthy();
  });

  it('opens the chat with support — the same account as /help in the bot', async () => {
    userBackend(ME);
    server.use(
      http.get('*/api/v1/client-config', () =>
        HttpResponse.json({ ...CLIENT_CONFIG, support_username: 'sosedi_support' }),
      ),
    );
    const { telegram } = startApp('/settings');

    const exportRow = await screen.findByRole('button', { name: /Экспорт моих данных/ });
    expect(exportRow.textContent).toContain('Запрос в поддержку');
    await click(exportRow);

    expect(telegram.callsOf('web_app_open_tg_link')).toEqual([{ path_full: '/sosedi_support' }]);
  });
});
