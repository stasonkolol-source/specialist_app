// Мастер «Создать заявку» S20a–d и итог S21 (DEVELOPMENT_PLAN 5.2) на фейке backend заявок: путь от
// пустого черновика до «на проверке», проверки шагов, один POST на черновик (повтор — с тем же
// ключом), черновик в DeviceStorage переживает перезапуск. S21 — «что дальше» одной строкой: где
// ждать откликов, что бот напишет (или «Разрешите боту писать» с запросом), до какого числа открыта
// заявка, и «Хотите быстрее? Пригласите специалистов»; сам переходит в «опубликована», когда
// автопроверка опубликовала заявку; мастер — одна запись истории: «Назад» после публикации не
// возвращает в его шаги; двойное «Опубликовать», 409 «запрос ещё идёт» и ключ, потраченный на
// другое тело, — одна заявка без ошибки; подсказка категории для длинного заголовка, ориентир цены
// с единицей, «Кто что увидит» одной строкой, подробности — под «Подробнее».
import { setSession } from '@sosed/api-client';
import { getCatalogListCategoriesMockHandler } from '@sosed/api-client/mocks';
import { DRAFT_STORAGE_KEY } from '@sosed/hooks';
import type { MockTelegram } from '@sosed/platform';
import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  backButtonVisible,
  mainButton,
  pressBackButton,
  pressMainButton,
  startApp,
} from '../../testing/app.tsx';
import { problem } from '../../testing/backend.ts';
import {
  CARD_PROFILE_ID,
  CATEGORY_IDS,
  DISTRICT_IDS,
  categoriesFor,
  suggestFor,
} from '../../testing/fixtures.ts';
import { NOTIFICATION_SETTINGS, WRITE_ACCESS } from '../../testing/fixtures.ts';
import { JobsBackend, createdJobId } from '../../testing/jobsBackend.ts';
import { jobsHandlers, server } from '../../testing/msw.ts';
import { useDraftStore } from './shared/draft.ts';

/** 2 октября 2026, 12:00 по Белграду: окно «18–21» ещё впереди. */
const NOON = new Date('2026-10-02T10:00:00Z');

beforeEach(() => {
  useDraftStore.setState({ draft: null, storage: null });
  vi.useFakeTimers({ toFake: ['Date'], now: NOON });
});
afterEach(async () => {
  // отложенная запись черновика прошлого теста не должна долететь до хранилища следующего: на
  // медленном раннере CI «Люстры» из сценария мастера оказывались черновиком теста цены
  await useDraftStore.getState().clear();
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
  // категория подобрана по тексту (/suggest); чип и есть «Изменить» (jsdom склеивает текст
  // скрытой подписи без пробела)
  await screen.findByRole('button', { name: /^Мастер на час → Люстры и карнизы ?Изменить$/ });
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
    // одно поле «Язык общения» — без заголовка «Детали» над ним
    expect(screen.queryByRole('heading', { name: 'Детали' })).toBeNull();
    type('Сумма', '5000');
    expect(screen.getByRole('textbox', { name: 'Сумма' })).toHaveProperty('value', '5 000');
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Проверьте заявку' })).toBeTruthy();
    // карточка — как в ленте исполнителя: район без города, «только что», мест ещё 0 из 5
    const card = screen.getByRole('article');
    expect(within(card).getByRole('heading', { name: 'Люстры', level: 2 })).toBeTruthy();
    expect(within(card).getByText(/^5\s000\sRSD$/u)).toBeTruthy();
    expect(within(card).getByText('Сегодня 18–21')).toBeTruthy();
    expect(within(card).getByText('Люстры и карнизы')).toBeTruthy();
    expect(within(card).getByText('Лиман')).toBeTruthy();
    expect(within(card).getByText('только что')).toBeTruthy();
    expect(within(card).getByText('откликов 0 из 5')).toBeTruthy();
    // кто что увидит — одной строкой, подробности — по «Подробнее»
    expect(screen.getByText('Адрес и контакты увидит только выбранный исполнитель')).toBeTruthy();
    expect(screen.queryByText(/^— точный адрес/)).toBeNull();
    await click(screen.getByRole('button', { name: 'Подробнее' }));
    expect(
      screen.getByText(
        '— точный адрес: Народног фронта 25, кв. 14; после договорённости — и ваш Telegram (его можно скрыть в настройках)',
      ),
    ).toBeTruthy();
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Заявка на проверке' })).toBeTruthy();
    // на проверке — сколько обычно ждать; бот писать не может — просим разрешить, без обещаний
    expect(
      screen.getByText(
        /^Обычно это несколько минут\. Разрешите боту писать — иначе об откликах узнаете, только открыв приложение\.$/u,
      ),
    ).toBeTruthy();
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
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Коротко о задаче' }));
    type('Коротко о задаче', 'Нужно что-то починить');
    await pressMainButton(telegram);
    // категорию не подобрали — нужна своя: подсказка красная (без серого), «Выбрать» в фокусе
    expect(app.router.state.location.pathname).toBe('/jobs/new');
    const hint = screen.getByText('Опишите задачу — подберём категорию, или выберите её сами');
    expect(hint.className.split(' ')).toContain('text-danger');
    expect(hint.className.split(' ')).not.toContain('text-text2');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Выбрать' }));
    await click(screen.getByRole('button', { name: 'Выбрать' }));
    await click(await screen.findByRole('button', { name: 'Мастер на час' }));
    await click(await screen.findByRole('button', { name: 'Электрика' }));
    expect(screen.getByText('Заявку увидят специалисты этой категории')).toBeTruthy();
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Когда и где?' })).toBeTruthy();
    await pressMainButton(telegram);
    expect(screen.getByText('Выберите, когда нужен исполнитель')).toBeTruthy();
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

describe('S20b «Определить по геолокации»', () => {
  /** S20b после S20a: поле «Где» и кнопка под ним. */
  async function openWhen(options: Parameters<typeof startApp>[1] = {}) {
    withJobs(new JobsBackend());
    const { telegram } = startApp('/jobs/new', options);
    await fillWhat(telegram);
    expect(await screen.findByRole('heading', { name: 'Когда и где?' })).toBeTruthy();
    return screen.findByRole('button', { name: 'Определить по геолокации' });
  }

  it('chooses the district of the device point; the list still changes it', async () => {
    await click(await openWhen());

    expect(await screen.findByText('Район определён: Лиман')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Где' }).textContent).toBe('Нови-Сад, Лиман');
    await click(screen.getByRole('button', { name: 'Где' }));
    await click(await screen.findByRole('button', { name: 'Грбавица' }));
    expect(screen.getByRole('button', { name: 'Где' }).textContent).toBe('Нови-Сад, Грбавица');
    expect(screen.queryByText('Район определён: Лиман')).toBeNull();
  });

  it('asks to choose from the list when location is denied', async () => {
    await click(await openWhen({ location: null }));

    expect(
      await screen.findByText('Не получилось определить район — выберите из списка'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Где' }).textContent).toBe('Нови-Сад');
  });

  it('asks to choose from the list when the point is outside the city', async () => {
    // Белград: backend отвечает 404 outside_city
    await click(await openWhen({ location: { latitude: 44.8125, longitude: 20.4573 } }));

    expect(
      await screen.findByText('Не получилось определить район — выберите из списка'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Где' }).textContent).toBe('Нови-Сад');
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
    expect(
      await screen.findByRole('button', { name: /^Мастер на час → Электрика ?Изменить$/ }),
    ).toBeTruthy();
    expect(screen.getByText('Заявку увидят специалисты этой категории')).toBeTruthy();
    // отдельной ссылки «Изменить» рядом с чипом нет
    expect(screen.queryByRole('button', { name: 'Изменить' })).toBeNull();
  });
});

describe('S21 published (UX_GUIDANCE №3)', () => {
  /** Опубликована сразу: «Отклики придут сюда…» — 2 октября, открыта неделю. */
  const PUBLISHED_LINE =
    /^Отклики придут сюда и в Telegram — бот напишет о первом же\. Заявка открыта до 9 октября\.$/u;

  async function publish(telegram: MockTelegram) {
    await fillWhat(telegram);
    await fillWhen(telegram);
    await screen.findByRole('heading', { name: 'Сколько готовы заплатить?' });
    await click(screen.getByRole('radio', { name: 'Договорная' }));
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Проверьте заявку' });
    await pressMainButton(telegram);
  }

  it('says where responses come, that the bot writes and until when the job is open', async () => {
    const jobs = withJobs(new JobsBackend());
    jobs.status = 'published';
    server.use(
      http.get('*/api/v1/me/notification-settings', () =>
        HttpResponse.json({ ...NOTIFICATION_SETTINGS, telegram: WRITE_ACCESS }),
      ),
    );
    const { telegram } = startApp('/jobs/new');
    await publish(telegram);

    expect(await screen.findByRole('heading', { name: 'Заявка опубликована' })).toBeTruthy();
    expect(await screen.findByText(PUBLISHED_LINE)).toBeTruthy();
    // одно необязательное действие: пригласить; «Поделиться» — на S23
    expect(
      await screen.findByRole('heading', { name: 'Хотите быстрее? Пригласите специалистов' }),
    ).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Поделиться в чат' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Присылать в Telegram' })).toBeNull();
    expect(screen.queryByText(/провер/)).toBeNull();
  });

  it('asks to let the bot write instead of promising it, then promises it', async () => {
    const jobs = withJobs(new JobsBackend());
    jobs.status = 'published';
    const { telegram } = startApp('/jobs/new');
    await publish(telegram);

    expect(await screen.findByRole('heading', { name: 'Заявка опубликована' })).toBeTruthy();
    expect(
      await screen.findByText(
        /^Разрешите боту писать — иначе об откликах узнаете, только открыв приложение\. Заявка открыта до 9 октября\.$/u,
      ),
    ).toBeTruthy();
    await click(await screen.findByRole('button', { name: 'Присылать в Telegram' }));

    expect(await screen.findByText(PUBLISHED_LINE)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Присылать в Telegram' })).toBeNull();
    expect(telegram.callsOf('web_app_request_write_access')).toHaveLength(1);
  });
});

describe('S08 «Заказать напрямую» — direct request', () => {
  it('goes through the wizard and sends the job to the specialist only', async () => {
    const jobs = withJobs(new JobsBackend());
    const { app, telegram } = startApp(`/specialists/${CARD_PROFILE_ID}`);

    await click(await screen.findByRole('button', { name: 'Заказать напрямую' }));

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

    expect(
      await screen.findByRole('heading', { name: 'Хотите быстрее? Пригласите специалистов' }),
    ).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('К заявке'));
    const [invite] = await screen.findAllByRole('button', { name: 'Пригласить' });
    if (!invite) throw new Error('no specialists to invite');
    await click(invite);

    await waitFor(() => expect(jobs.invites.get(createdJobId(1))).toHaveLength(1));
    expect(await screen.findByText('Приглашён')).toBeTruthy();
  });
});

/** Шаги S20b–c до «Проверьте заявку»: бюджет — договорной. */
async function toPreview(telegram: MockTelegram) {
  await fillWhat(telegram);
  await fillWhen(telegram);
  await screen.findByRole('heading', { name: 'Сколько готовы заплатить?' });
  await click(screen.getByRole('radio', { name: 'Договорная' }));
  await pressMainButton(telegram);
  await screen.findByRole('heading', { name: 'Проверьте заявку' });
}

describe('S21 while the job is on review (SMOKE-2)', () => {
  it('switches to «published» with invites once the auto-check published the job', async () => {
    const jobs = withJobs(new JobsBackend());
    jobs.autoModerate = true;
    const { telegram } = startApp('/jobs/new');
    await toPreview(telegram);

    await pressMainButton(telegram);

    // ответ POST — «на проверке»: так экран и открывается
    expect(await screen.findByRole('heading', { name: 'Заявка на проверке' })).toBeTruthy();
    // автопроверка уже опубликовала заявку — экран перечитал её сам
    expect(
      await screen.findByRole('heading', { name: 'Заявка опубликована' }, { timeout: 4_000 }),
    ).toBeTruthy();
    expect(
      await screen.findByRole('heading', { name: 'Хотите быстрее? Пригласите специалистов' }),
    ).toBeTruthy();
    // «Обычно проверка занимает несколько минут…» у опубликованной уже нет
    expect(screen.queryByText(/несколько минут/)).toBeNull();
  });
});

describe('history after publishing (OWN-2)', () => {
  /** «Мои заявки» → «+» → мастер до «Проверьте заявку». */
  async function fromMyJobs() {
    withJobs(new JobsBackend());
    const started = startApp('/jobs/mine');
    await click(await screen.findByRole('button', { name: 'Новая заявка' }));
    await toPreview(started.telegram);
    return started;
  }

  it('walks back through the steps without leaving history entries behind', async () => {
    const { app, telegram } = await fromMyJobs();

    await pressBackButton(telegram);
    expect(await screen.findByRole('heading', { name: 'Сколько готовы заплатить?' })).toBeTruthy();
    await pressBackButton(telegram);
    expect(await screen.findByRole('heading', { name: 'Когда и где?' })).toBeTruthy();
    await pressBackButton(telegram);
    expect(await what()).toBeTruthy();
    // с первого шага — туда, откуда мастер открыли
    await pressBackButton(telegram);
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/mine'));
  });

  it('leads Back on S21 to where the wizard was opened', async () => {
    const { app, telegram } = await fromMyJobs();
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Заявка на проверке' });
    await waitFor(() => expect(backButtonVisible(telegram)).toBe(true));

    await pressBackButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/mine'));
    expect(screen.queryByText(/^Шаг \d из 4/)).toBeNull();
  });

  it('leads Back on S23 opened from S21 to where the wizard was opened', async () => {
    const { app, telegram } = await fromMyJobs();
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Заявка на проверке' });
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('К заявке'));
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Люстры', level: 1 });

    await pressBackButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/mine'));
    expect(screen.queryByText(/^Шаг \d из 4/)).toBeNull();
  });
});

describe('S20d «Опубликовать» pressed twice (MU-1)', () => {
  it('sends one request for two presses before a re-render', async () => {
    const jobs = withJobs(new JobsBackend());
    const { telegram } = startApp('/jobs/new');
    await toPreview(telegram);

    await act(async () => {
      telegram.emit('main_button_pressed');
      telegram.emit('main_button_pressed');
    });

    expect(await screen.findByRole('heading', { name: 'Заявка на проверке' })).toBeTruthy();
    expect(jobs.posts).toHaveLength(1);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('waits out «the request is still running» and lands on S21 without an error', async () => {
    const jobs = withJobs(new JobsBackend());
    // второй запрос двойного тапа пришёл, пока первый с тем же ключом ещё выполнялся
    jobs.failNext = problem(409, 'idempotency_in_progress', {
      detail: 'Запрос уже выполняется. Повторите чуть позже.',
    });
    const { telegram } = startApp('/jobs/new');
    await toPreview(telegram);

    await pressMainButton(telegram);

    expect(
      await screen.findByRole('heading', { name: 'Заявка на проверке' }, { timeout: 3_000 }),
    ).toBeTruthy();
    expect(screen.queryByText('Запрос уже выполняется. Повторите чуть позже.')).toBeNull();
    expect(jobs.posts.map((post) => post.key)).toEqual([jobs.posts[0]?.key, jobs.posts[0]?.key]);
    expect(jobs.jobs.size).toBe(1);
  });

  it('publishes a changed draft with a new key instead of a stuck 422', async () => {
    const jobs = withJobs(new JobsBackend());
    const { telegram } = startApp('/jobs/new');
    await toPreview(telegram);
    // ключ черновика уже потрачен на прежнее тело: публикация «не удалась», черновик поправили
    const key = useDraftStore.getState().draft?.key ?? '';
    const earlier = jobs.create({ ...(jobs.posts[0]?.body ?? {}), title: 'Люстры' } as never, key);
    expect(earlier.status).toBe(201);

    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Заявка на проверке' })).toBeTruthy();
    expect(screen.queryByText(/Idempotency-Key/)).toBeNull();
    const [, reused, fresh] = jobs.posts;
    expect(reused?.key).toBe(key);
    expect(fresh?.key).not.toBe(key);
    expect(fresh?.body).toEqual(reused?.body);
    expect(jobs.jobs.size).toBe(2);
  });
});

describe('S20a category for a long title (UXM-1)', () => {
  it('asks /suggest with the first words, within what the server accepts', async () => {
    const asked: string[] = [];
    server.use(
      http.get('*/api/v1/suggest', ({ request }) => {
        const q = new URL(request.url).searchParams.get('q') ?? '';
        asked.push(q);
        // как backend: `q` длиннее 64 знаков — 422
        if (q.length > 64) {
          return HttpResponse.json(
            { title: 'validation_error', status: 422, code: 'validation_error', trace_id: null },
            { status: 422 },
          );
        }
        return HttpResponse.json(suggestFor('Люстры', request.headers.get('Accept-Language')));
      }),
    );
    withJobs(new JobsBackend());
    startApp('/jobs/new');
    await what();

    type(
      'Коротко о задаче',
      'Люстры в двух комнатах повесить и подключить, потолок бетонный, крюки есть, стремянки нет',
    );

    expect(
      await screen.findByRole('button', { name: /^Мастер на час → Люстры и карнизы ?Изменить$/ }),
    ).toBeTruthy();
    expect(asked.length).toBeGreaterThan(0);
    expect(asked.every((q) => q.length <= 64)).toBe(true);
  });
});

describe('S20c reference price (UXM-2)', () => {
  it('names the unit the range is in', async () => {
    server.use(
      getCatalogListCategoriesMockHandler(({ request }) =>
        categoriesFor(request.headers.get('Accept-Language')).map((section) => ({
          ...section,
          children: section.children.map((node) =>
            node.id === CATEGORY_IDS['chandeliers']
              ? {
                  ...node,
                  price_hint: {
                    min: { amount: 18_000, currency: 'RSD' as const },
                    max: { amount: 45_000, currency: 'RSD' as const },
                    unit: 'm2' as const,
                  },
                }
              : node,
          ),
        })),
      ),
    );
    withJobs(new JobsBackend());
    const { telegram } = startApp('/jobs/new');
    await fillWhat(telegram);
    await fillWhen(telegram);

    expect(
      await screen.findByText(
        /^Обычно «Люстры и карнизы» стоит 180–450\sRSD за м² — это справочный диапазон\.$/u,
      ),
    ).toBeTruthy();
  });
});

/** «Подробнее» под строкой «Адрес и контакты увидит только выбранный исполнитель». */
async function whoSees() {
  const more = screen.getByRole('button', { name: 'Подробнее' });
  expect(more.getAttribute('aria-expanded')).toBe('false');
  await click(more);
  expect(screen.getByRole('button', { name: 'Свернуть' }).getAttribute('aria-expanded')).toBe(
    'true',
  );
  return screen.getByRole('region', { name: 'Кто что увидит' });
}

describe('S20d «Кто что увидит» (MU-7)', () => {
  it('says the chosen performer gets the Telegram after the deal, the phone — nobody', async () => {
    withJobs(new JobsBackend());
    const { telegram } = startApp('/jobs/new');
    await toPreview(telegram);

    const card = await whoSees();
    expect(card.textContent).toContain(
      'Только выбранный — точный адрес: Народног фронта 25, кв. 14; после договорённости — и ваш Telegram (его можно скрыть в настройках)',
    );
    expect(card.textContent).toContain('Никто — ваш телефон, пока вы сами им не поделитесь');
    expect(card.textContent).toContain('Все исполнители');
    expect(card.textContent).toContain('До 5 откликов');
  });

  it('names the specialist of a direct request and drops the five responses', async () => {
    withJobs(new JobsBackend());
    const { telegram } = startApp(`/jobs/new?direct=${CARD_PROFILE_ID}`);
    expect(await screen.findByText(/^Прямой запрос: Алексей Морозов\./)).toBeTruthy();
    await toPreview(telegram);

    const card = await whoSees();
    expect(card.textContent).toContain('Только Алексей Морозов');
    expect(card.textContent).not.toContain('Все исполнители');
    expect(card.textContent).not.toContain('До 5 откликов');
  });
});
