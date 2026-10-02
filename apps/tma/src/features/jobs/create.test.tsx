// Мастер «Создать заявку» S20a–d и итог S21 (DEVELOPMENT_PLAN 5.2) на фейке backend заявок: путь от
// пустого черновика до «на проверке», проверки шагов, один POST на черновик (повтор — с тем же
// ключом), черновик в DeviceStorage переживает перезапуск, запрос «Сообщать об откликах?».
import { setSession } from '@sosed/api-client';
import { DRAFT_STORAGE_KEY } from '@sosed/hooks';
import type { MockTelegram } from '@sosed/platform';
import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { problem } from '../../testing/backend.ts';
import { CARD_PROFILE_ID, CATEGORY_IDS, DISTRICT_IDS } from '../../testing/fixtures.ts';
import { JobsBackend } from '../../testing/jobsBackend.ts';
import { jobsHandlers, server } from '../../testing/msw.ts';
import { useDraftStore } from './shared/draft.ts';

/** 2 октября 2026, 12:00 по Белграду: окно «18–21» ещё впереди. */
const NOON = new Date('2026-10-02T10:00:00Z');

beforeEach(() => {
  useDraftStore.setState({ draft: null, storage: null });
  vi.useFakeTimers({ toFake: ['Date'], now: NOON });
});
afterEach(() => {
  vi.useRealTimers();
  setSession(null);
});

function withJobs(backend: JobsBackend): JobsBackend {
  server.use(...jobsHandlers(() => backend));
  return backend;
}

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

const type = (name: string, value: string) =>
  fireEvent.change(screen.getByRole('textbox', { name }), { target: { value } });

/** Последняя запись черновика в DeviceStorage. */
const savedDraft = (telegram: MockTelegram) =>
  telegram
    .callsOf('web_app_device_storage_save_key')
    .filter((call) => call?.key === DRAFT_STORAGE_KEY)
    .at(-1)?.value;

/** S20a готов: черновик поднят, форма на экране. */
const what = () => screen.findByRole('textbox', { name: 'Коротко о задаче' });

async function fillWhat(telegram: MockTelegram) {
  await what();
  type('Коротко о задаче', 'Люстры');
  // категория подобрана по тексту (/suggest)
  await screen.findByRole('button', { name: 'Мастер на час → Люстры и карнизы' });
  type('Подробности', 'Потолок бетонный, крюк есть.');
  await pressMainButton(telegram);
}

async function fillWhen(telegram: MockTelegram) {
  expect(await screen.findByRole('heading', { name: 'Когда и где?' })).toBeTruthy();
  await click(screen.getByRole('radio', { name: 'Сегодня' }));
  await click(screen.getByRole('button', { name: '18–21' }));
  await click(await screen.findByRole('button', { name: 'Где' }));
  await click(await screen.findByRole('button', { name: 'Лиман' }));
  type('Точный адрес', 'Народног фронта 25, кв. 14');
  await pressMainButton(telegram);
}

describe('S20a–d create a job', () => {
  it('walks from an empty draft to S21 «on review» with one POST /jobs', async () => {
    const jobs = withJobs(new JobsBackend());
    const { app, telegram } = startApp('/jobs/new');

    await fillWhat(telegram);
    await fillWhen(telegram);
    expect(await screen.findByRole('heading', { name: 'Сколько готовы заплатить?' })).toBeTruthy();
    type('Сумма', '5000');
    expect(screen.getByRole('textbox', { name: 'Сумма' })).toHaveProperty('value', '5 000');
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Проверьте заявку' })).toBeTruthy();
    expect(screen.getByText(/^5\s000\sRSD$/u)).toBeTruthy();
    expect(screen.getByText('Сегодня 18–21')).toBeTruthy();
    expect(screen.getByText('— точный адрес: Народног фронта 25, кв. 14')).toBeTruthy();
    expect(screen.getByText('Лиман, Нови-Сад')).toBeTruthy();
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Заявка на проверке' })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/jobs/new/done');
    expect(jobs.posts).toHaveLength(1);
    expect(jobs.posts[0]?.key).toMatch(/^[0-9a-f-]{36}$/);
    expect(jobs.posts[0]?.body).toEqual({
      title: 'Люстры',
      description: 'Потолок бетонный, крюк есть.',
      category_id: CATEGORY_IDS['chandeliers'],
      urgency: 'today',
      preferred_from: '2026-10-02T16:00:00.000Z',
      preferred_to: '2026-10-02T19:00:00.000Z',
      budget_type: 'fixed',
      budget_min: 500_000,
      budget_max: null,
      budget_unit: 'work',
      city_id: 1,
      district_id: DISTRICT_IDS['Лиман'],
      address_private: 'Народног фронта 25, кв. 14',
      languages: ['ru'],
      media_ids: [],
    });
    // черновик опубликован — его больше нет ни в памяти, ни в DeviceStorage
    expect(useDraftStore.getState().draft).toBeNull();
    await waitFor(() => expect(savedDraft(telegram)).toBeNull());
  });

  it('checks each step before going on', async () => {
    withJobs(new JobsBackend());
    const { app, telegram } = startApp('/jobs/new');
    await what();

    await pressMainButton(telegram);

    expect(screen.getByText('Напишите хотя бы 5 символов')).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/jobs/new');
    type('Коротко о задаче', 'Нужно что-то починить');
    await pressMainButton(telegram);
    // категорию не подобрали — нужна своя
    expect(app.router.state.location.pathname).toBe('/jobs/new');
    await click(screen.getByRole('button', { name: 'Выбрать' }));
    await click(await screen.findByRole('button', { name: 'Мастер на час' }));
    await click(await screen.findByRole('button', { name: 'Электрика' }));
    expect(screen.getByText('Заявку увидят мастера этой категории')).toBeTruthy();
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Когда и где?' })).toBeTruthy();
    await pressMainButton(telegram);
    expect(screen.getByText('Выберите, когда нужен мастер')).toBeTruthy();
    expect(screen.getByText('Выберите район')).toBeTruthy();
  });

  it('retries a failed publish with the same key: one job', async () => {
    const jobs = withJobs(new JobsBackend());
    jobs.failNext = problem(503, 'external_service_unavailable');
    const { telegram } = startApp('/jobs/new');
    await fillWhat(telegram);
    await fillWhen(telegram);
    await screen.findByRole('heading', { name: 'Сколько готовы заплатить?' });
    await click(screen.getByRole('radio', { name: 'Договорная' }));
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Проверьте заявку' });

    await pressMainButton(telegram);
    expect(await screen.findByRole('alert')).toBeTruthy();
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Заявка на проверке' })).toBeTruthy();
    expect(jobs.posts.map((post) => post.key)).toEqual([jobs.posts[0]?.key, jobs.posts[0]?.key]);
    expect(jobs.jobs.size).toBe(1);
    expect(jobs.posts[1]?.body).toMatchObject({ budget_type: 'negotiable', budget_min: null });
  });

  it('keeps the draft in DeviceStorage across a restart of the Mini App', async () => {
    withJobs(new JobsBackend());
    const first = startApp('/jobs/new');
    await what();
    type('Коротко о задаче', 'Собрать шкаф-купе');
    await waitFor(() => expect(savedDraft(first.telegram)).toContain('Собрать шкаф-купе'));
    const saved = String(savedDraft(first.telegram));
    cleanup();
    useDraftStore.setState({ draft: null, storage: null });

    startApp('/jobs/new', { deviceStorage: { [DRAFT_STORAGE_KEY]: saved } });

    expect(await what()).toHaveProperty('value', 'Собрать шкаф-купе');
  });
});

describe('ways into the wizard', () => {
  it('opens S20a from «Не хотите искать сами?» on the home screen', async () => {
    withJobs(new JobsBackend());
    const { app } = startApp('/');
    await screen.findByRole('heading', { name: 'Не хотите искать сами?' });

    await click(screen.getByRole('button', { name: 'Создать заявку' }));

    expect(await what()).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/jobs/new');
  });

  it('starts a new draft with the category and title of a price item', async () => {
    withJobs(new JobsBackend());
    const title = encodeURIComponent('Замена розетки');
    startApp(`/jobs/new?category=${CATEGORY_IDS['electrical']}&title=${title}`);

    expect(await what()).toHaveProperty('value', 'Замена розетки');
    expect(await screen.findByRole('button', { name: 'Мастер на час → Электрика' })).toBeTruthy();
    expect(screen.getByText('Заявку увидят мастера этой категории')).toBeTruthy();
  });
});

describe('S21 published', () => {
  it('asks to send responses to Telegram while the bot cannot write', async () => {
    const jobs = withJobs(new JobsBackend());
    jobs.status = 'published';
    const { telegram } = startApp('/jobs/new');
    await fillWhat(telegram);
    await fillWhen(telegram);
    await screen.findByRole('heading', { name: 'Сколько готовы заплатить?' });
    await click(screen.getByRole('radio', { name: 'Договорная' }));
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Проверьте заявку' });
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Заявка опубликована' })).toBeTruthy();
    await click(await screen.findByRole('button', { name: 'Присылать в Telegram' }));

    expect(await screen.findByText('Отклики придут в Telegram')).toBeTruthy();
    expect(telegram.callsOf('web_app_request_write_access')).toHaveLength(1);
  });
});

describe('S08 «Написать» — direct request', () => {
  it('goes through the wizard and sends the job to the specialist only', async () => {
    const jobs = withJobs(new JobsBackend());
    const { app, telegram } = startApp(`/specialists/${CARD_PROFILE_ID}`);
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Написать'));

    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/new'));
    expect(await screen.findByText(/^Прямой запрос: Алексей Морозов\./)).toBeTruthy();
    await fillWhat(telegram);
    await fillWhen(telegram);
    expect(await screen.findByRole('heading', { name: 'Сколько готовы заплатить?' })).toBeTruthy();
    type('Сумма', '5000');
    await pressMainButton(telegram);
    expect(await screen.findByRole('heading', { name: 'Проверьте заявку' })).toBeTruthy();
    expect(screen.getByText(/^Прямой запрос: Алексей Морозов\./)).toBeTruthy();
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Запрос отправлен' })).toBeTruthy();
    expect(jobs.posts).toHaveLength(1);
    expect(jobs.posts[0]?.directTo).toBe(CARD_PROFILE_ID);
    expect(jobs.posts[0]?.body.title).toBe('Люстры');
  });

  it('becomes a job for everyone with «Отправить всем исполнителям»', async () => {
    const jobs = withJobs(new JobsBackend());
    const { telegram } = startApp(`/jobs/new?direct=${CARD_PROFILE_ID}`);
    expect(await screen.findByText(/^Прямой запрос: Алексей Морозов\./)).toBeTruthy();

    await click(screen.getByRole('button', { name: 'Отправить всем исполнителям' }));

    await waitFor(() => expect(screen.queryByText(/^Прямой запрос/)).toBeNull());
    await fillWhat(telegram);
    await fillWhen(telegram);
    type('Сумма', '5000');
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Проверьте заявку' });
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Заявка на проверке' })).toBeTruthy();
    expect(jobs.posts[0]?.directTo ?? null).toBeNull();
  });
});

describe('S21 invite specialists', () => {
  it('offers specialists from the catalog when the job is published at once', async () => {
    const jobs = new JobsBackend();
    jobs.status = 'published';
    withJobs(jobs);
    const { telegram } = startApp('/jobs/new');
    await fillWhat(telegram);
    await fillWhen(telegram);
    type('Сумма', '5000');
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Проверьте заявку' });
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Пригласите специалистов' })).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('К заявке'));
    const [invite] = await screen.findAllByRole('button', { name: 'Пригласить' });
    if (!invite) throw new Error('no specialists to invite');
    await click(invite);

    await waitFor(() => expect(jobs.invites.get('job-1')).toHaveLength(1));
    expect(await screen.findByText('Приглашён')).toBeTruthy();
  });
});
