// Подписки на заявки S18 и S19 (DEVELOPMENT_PLAN 5.7) на фейке backend: список как на артборде —
// название по категории, где и бюджет, «сразу» или «подборкой», «N заявок за неделю», тихие часы;
// переключатель и удаление; запрос «Присылать новые заявки в бот?» → requestWriteAccess; новая
// подписка с одним POST на тело формы, правка — PATCH; «Сохранить как подписку» из шторки S14 —
// форма с фильтрами ленты; «По моим подпискам» на S13 — лента `feed=alerts`.
import { setSession } from '@sosed/api-client';
import type { MockTelegram } from '@sosed/platform';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { CATEGORY_IDS, E2E_NOW } from '../../testing/fixtures.ts';
import { JobsBackend, alertsFixture } from '../../testing/jobsBackend.ts';
import { jobsHandlers, server } from '../../testing/msw.ts';

const HANDYMAN = CATEGORY_IDS['handyman'] ?? 0;
const CLEANING = CATEGORY_IDS['cleaning'] ?? 0;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(E2E_NOW) });
});
afterEach(() => {
  vi.useRealTimers();
  setSession(null);
});

function withJobs(backend = new JobsBackend()): JobsBackend {
  server.use(...jobsHandlers(() => backend));
  return backend;
}

function withAlerts(): JobsBackend {
  const jobs = new JobsBackend();
  jobs.alerts = alertsFixture();
  return withJobs(jobs);
}

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

const pressSecondary = (telegram: MockTelegram) =>
  act(async () => {
    telegram.emit('secondary_button_pressed');
  });

/** S18 загрузился: переключатель первой подписки на экране. */
const listed = () =>
  screen.findByRole('switch', { name: 'Присылать заявки по подписке «Мастер на час»' });

/** Карточка подписки S18 по названию. */
const card = (title: string) => screen.getByRole('region', { name: title }) as HTMLElement;

describe('S18 alerts', () => {
  it('lists alerts as on the artboard with the week stats and quiet hours', async () => {
    withAlerts();
    const { telegram } = startApp('/jobs/alerts');

    expect(
      await screen.findByRole('heading', { name: 'Подписки на заявки', level: 1 }),
    ).toBeTruthy();
    expect(await listed()).toBeTruthy();
    const handyman = card('Мастер на час');
    expect(within(handyman).getByText('Электрика, Сантехника, Сборка мебели…')).toBeTruthy();
    // где и бюджет — одной строкой с одной «·», язык — своей строкой
    expect(await within(handyman).findByText(/^Лиман, до 3 км · от 2\s000\sRSD$/u)).toBeTruthy();
    expect(within(handyman).getByText('Русский')).toBeTruthy();
    expect(within(handyman).getByText('Присылать сразу')).toBeTruthy();
    expect(within(handyman).getByText('8 заявок за неделю')).toBeTruthy();
    expect(
      within(handyman).getByRole('switch', { name: 'Присылать заявки по подписке «Мастер на час»' })
        .ariaChecked,
    ).toBe('true');

    const furniture = card('Сборка мебели');
    expect(within(furniture).getByText('Мастер на час')).toBeTruthy();
    expect(within(furniture).getByText('Весь город · любой бюджет')).toBeTruthy();
    expect(within(furniture).getByText('Русский')).toBeTruthy();
    expect(within(furniture).getByText('Подборкой раз в день, в 09:00')).toBeTruthy();
    expect(within(furniture).getByText('3 заявки за неделю')).toBeTruthy();
    expect(
      screen.getByText(/Тихие часы 22:00–08:00: ночью приходят только срочные заявки/),
    ).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Новая подписка'));
  });

  it('asks to send new jobs to the bot while it cannot write', async () => {
    withAlerts();
    const { telegram } = startApp('/jobs/alerts');

    expect(
      await screen.findByRole('heading', { name: 'Присылать новые заявки в бот?' }),
    ).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Присылать в Telegram' }));

    expect(await screen.findByText('Новые заявки придут в Telegram')).toBeTruthy();
    expect(telegram.callsOf('web_app_request_write_access')).toHaveLength(1);
  });

  it('turns an alert off at once and deletes one after a confirmation', async () => {
    const jobs = withAlerts();
    startApp('/jobs/alerts');
    await listed();

    await click(
      screen.getByRole('switch', { name: 'Присылать заявки по подписке «Мастер на час»' }),
    );
    // оптимистично, до ответа сервера; onMutate асинхронный (отмена запросов) — под нагрузкой CI
    // переключатель меняется на такт позже клика
    await waitFor(() =>
      expect(
        screen.getByRole('switch', { name: 'Присылать заявки по подписке «Мастер на час»' })
          .ariaChecked,
      ).toBe('false'),
    );
    await waitFor(() =>
      expect(jobs.alertWrites.at(-1)).toMatchObject({
        method: 'PATCH',
        body: { is_active: false },
      }),
    );

    await click(within(card('Сборка мебели')).getByRole('button', { name: 'Удалить' }));

    await waitFor(() => expect(screen.queryByText('Подборкой раз в день, в 09:00')).toBeNull());
    expect(jobs.alerts.map((alert) => alert.id)).toEqual([alertsFixture()[0]?.id]);
  });

  it('shows the empty state without alerts', async () => {
    withJobs();
    startApp('/jobs/alerts');

    expect(await screen.findByRole('heading', { name: 'Подписок пока нет' })).toBeTruthy();
  });
});

describe('S19 alert form', () => {
  it('creates an alert with one POST and returns to the list', async () => {
    const jobs = withJobs();
    const { telegram } = startApp('/jobs/alerts');
    await screen.findByRole('heading', { name: 'Подписок пока нет' });
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Новая подписка'));
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Новая подписка', level: 1 })).toBeTruthy();
    // без категорий не сохраняется
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Сохранить подписку'));
    await pressMainButton(telegram);
    expect(await screen.findByText('Выберите хотя бы одну категорию')).toBeTruthy();
    expect(jobs.alertWrites).toEqual([]);

    await click(await screen.findByRole('button', { name: 'Мастер на час' }));
    await click(screen.getByRole('button', { name: '3 км' }));
    expect(await screen.findByText('Радиус от вас · Лиман')).toBeTruthy();
    fireEvent.change(screen.getByRole('textbox', { name: 'Бюджет от' }), {
      target: { value: '2000' },
    });
    await click(screen.getByRole('radio', { name: 'Раз в день' }));
    await click(screen.getByRole('button', { name: /Язык общения/ }));
    await click(await screen.findByRole('button', { name: 'Русский' }));
    await pressMainButton(telegram);

    // подписка создана, а боту писать нельзя — контекстный запрос разрешения
    expect(
      await screen.findByRole('heading', { name: 'Присылать новые заявки в бот?' }),
    ).toBeTruthy();
    expect(await screen.findByText('Подборкой раз в день, в 09:00')).toBeTruthy();
    expect(jobs.alertWrites).toHaveLength(1);
    const [write] = jobs.alertWrites;
    expect(write?.key).toBeTruthy();
    expect(write?.body).toEqual({
      criteria: {
        category_ids: [HANDYMAN],
        city_id: 1,
        district_ids: [],
        // точка — с точностью ~100 м, как у ленты
        center: { lat: 45.267, lon: 19.834 },
        radius_km: 3,
        min_budget: 200_000,
        urgencies: [],
        languages: ['ru'],
      },
      delivery: 'digest',
    });
  });

  it('edits an alert with PATCH of the whole criteria', async () => {
    const jobs = withAlerts();
    const { telegram } = startApp('/jobs/alerts');
    await listed();

    await click(within(card('Мастер на час')).getByRole('button', { name: 'Изменить' }));
    expect(await screen.findByRole('heading', { name: 'Подписка', level: 1 })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Мастер на час', pressed: true })).toBeTruthy();
    expect((screen.getByRole('textbox', { name: 'Бюджет от' }) as HTMLInputElement).value).toMatch(
      /^2\s000$/u,
    );
    await click(screen.getByRole('button', { name: 'Уборка' }));
    await click(screen.getByRole('switch', { name: 'Только срочные' }));
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Сохранить подписку'));
    await pressMainButton(telegram);

    await waitFor(() => expect(jobs.alertWrites.at(-1)?.method).toBe('PATCH'));
    expect(jobs.alertWrites.at(-1)?.body).toMatchObject({
      criteria: {
        category_ids: [HANDYMAN, CLEANING],
        radius_km: 3,
        min_budget: 200_000,
        urgencies: ['asap'],
      },
      delivery: 'instant',
    });
    expect(await screen.findByText('Мастер на час и ещё 1')).toBeTruthy();
  });
});

describe('S14 «Сохранить как подписку» and S13 «По моим подпискам»', () => {
  it('opens the alert form with the feed filters', async () => {
    const jobs = withJobs();
    const { telegram, app } = startApp('/jobs');
    await screen.findByText('Течёт смеситель на кухне');

    await click(screen.getByRole('button', { name: /^Фильтры/ }));
    const sheet = await screen.findByRole('dialog', { name: 'Фильтры' });
    await click(within(sheet).getByRole('button', { name: 'Мастер на час' }));
    await waitFor(() =>
      expect(telegram.callsOf('web_app_setup_secondary_button').at(-1)).toMatchObject({
        is_visible: true,
        text: 'Сохранить как подписку',
      }),
    );
    await pressSecondary(telegram);

    expect(await screen.findByRole('heading', { name: 'Новая подписка', level: 1 })).toBeTruthy();
    expect(app.router.state.location.search).toMatchObject({
      categories: [HANDYMAN],
      from: 'feed',
    });
    expect(screen.getByRole('button', { name: 'Мастер на час', pressed: true })).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Сохранить подписку'));
    await pressMainButton(telegram);

    // из шторки — к списку подписок
    expect(
      await screen.findByRole('heading', { name: 'Подписки на заявки', level: 1 }),
    ).toBeTruthy();
    expect(jobs.alertWrites[0]?.body).toMatchObject({
      criteria: { category_ids: [HANDYMAN], center: null, radius_km: null },
      delivery: 'instant',
    });
  });

  it('shows the jobs of enabled alerts with feed=alerts', async () => {
    const jobs = withAlerts();
    const { app } = startApp('/jobs');
    await screen.findByText('Течёт смеситель на кухне');

    await click(screen.getByRole('button', { name: 'По моим подпискам', pressed: false }));

    await waitFor(() => expect(app.router.state.location.search).toEqual({ alerts: true }));
    await waitFor(() => expect(jobs.feedRequests.at(-1)?.get('feed')).toBe('alerts'));
    expect(await screen.findByText(/по подпискам, новые сверху$/)).toBeTruthy();

    await click(screen.getByRole('button', { name: 'Подписки на новые заявки' }));
    expect(
      await screen.findByRole('heading', { name: 'Подписки на заявки', level: 1 }),
    ).toBeTruthy();
  });

  it('offers to set up alerts when there are none', async () => {
    withJobs();
    startApp('/jobs?alerts=true');

    expect(await screen.findByRole('heading', { name: 'Подписок пока нет' })).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Настроить подписки' }));
    expect(
      await screen.findByRole('heading', { name: 'Подписки на заявки', level: 1 }),
    ).toBeTruthy();
  });
});
