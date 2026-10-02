// Лента заявок S13–S15 (DEVELOPMENT_PLAN 5.3) на фейке backend: новые сверху со счётчиком,
// быстрые чипы и шторка фильтров меняют адрес, «Показать N» считает черновик, «Показать ещё»
// грузит следующую страницу; заявка — места, описание, «Где» с расстоянием от точки ленты, блок
// заказчика; «Не интересно» убирает её из ленты; сердечко сохраняет её в «Задачи» S12; ссылка `j_`
// открывает S15; блок «Ищете подработку?» на Главной. Часы — E2E_NOW (10:00 по Белграду): окно
// «18–21» ещё сегодня.
import { setSession } from '@sosed/api-client';
import { encodeStartParam } from '@sosed/links';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
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
import { CATEGORY_IDS, E2E_NOW } from '../../testing/fixtures.ts';
import type { FeedFixture } from '../../testing/jobsBackend.ts';
import { FEED_JOBS, JobsBackend } from '../../testing/jobsBackend.ts';
import { jobsHandlers, server } from '../../testing/msw.ts';

const [LEAK, CHANDELIER] = FEED_JOBS as [FeedFixture, FeedFixture, ...FeedFixture[]];
const CHANDELIER_PATH = `/jobs/${CHANDELIER.card.id}`;

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

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

/** Заголовки карточек ленты по порядку. */
const titles = () =>
  screen.queryAllByRole('heading', { level: 2 }).map((heading) => heading.textContent);

const asGuest = () =>
  server.use(
    http.post('*/api/v1/auth/telegram', () =>
      HttpResponse.json(
        { type: 'x', title: 'Unauthorized', status: 401, code: 'not_authenticated' },
        { status: 401 },
      ),
    ),
  );

describe('S13 feed', () => {
  it('lists city jobs newest first with the count, budget, time badge and slots', async () => {
    withJobs();
    startApp('/jobs');

    expect(await screen.findByText('Течёт смеситель на кухне')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Заявки рядом', level: 1 })).toBeTruthy();
    expect(titles()).toEqual([
      'Течёт смеситель на кухне',
      'Повесить люстру',
      'Собрать шкаф PAX, 2 м',
      'Генеральная уборка, 2-комн. квартира',
      'Помочь с переездом: 1-комн., 3 этаж без лифта',
      'Маникюр с покрытием на дому',
    ]);
    expect(await screen.findByText('6 заявок · новые сверху')).toBeTruthy();
    const leak = screen.getByRole('link', { name: /Течёт смеситель/ });
    expect(within(leak).getByText('Договорная')).toBeTruthy();
    expect(within(leak).getByText('Срочно')).toBeTruthy();
    expect(within(leak).getByText('Сантехника')).toBeTruthy();
    expect(within(leak).getByText('5 мин назад')).toBeTruthy();
    expect(within(leak).getByText('откликов 4 из 5')).toBeTruthy();
    // без точки зрителя расстояния нет — только район
    expect(within(leak).getByText('Центр')).toBeTruthy();
    const chandelier = screen.getByRole('link', { name: /Повесить люстру/ });
    expect(within(chandelier).getByText(/^5\s000\sRSD$/u)).toBeTruthy();
    expect(within(chandelier).getByText('Сегодня 18–21')).toBeTruthy();
    expect(within(chandelier).getAllByRole('img', { name: /Фото/ })).toHaveLength(2);
    const segments = screen.getByRole('navigation', { name: 'Раздел заявок' });
    expect(within(segments).getByRole('link', { name: 'Лента' }).ariaCurrent).toBe('page');
    expect(screen.getByRole('navigation', { name: 'Разделы' })).toBeTruthy();
  });

  it('filters with the quick chips through the address', async () => {
    const jobs = withJobs();
    const { app } = startApp('/jobs');
    await screen.findByText('Течёт смеситель на кухне');

    await click(screen.getByRole('button', { name: 'Срочные', pressed: false }));

    await waitFor(() => expect(app.router.state.location.search).toEqual({ urgent: true }));
    await waitFor(() => expect(titles()).toEqual(['Течёт смеситель на кухне']));
    expect(jobs.feedRequests.at(-1)?.getAll('urgency')).toEqual(['asap']);
    expect(await screen.findByText('1 заявка по фильтрам · новые сверху')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Фильтры\s*1/ })).toBeTruthy();

    await click(screen.getByRole('button', { name: 'До 3 км', pressed: false }));

    await waitFor(() =>
      expect(app.router.state.location.search).toMatchObject({
        urgent: true,
        near: 3,
        lat: 45.267,
        lon: 19.834,
      }),
    );
    await screen.findByText('Центр, ≈ 2 км');
    expect(jobs.feedRequests.at(-1)?.get('radius_km')).toBe('3');
  });

  it('offers to reset filters when nothing matches', async () => {
    withJobs();
    const { app } = startApp('/jobs?photos=true&urgent=true');

    expect(
      await screen.findByRole('heading', { name: 'По этим фильтрам заявок нет' }),
    ).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Сбросить фильтры' }));

    await waitFor(() => expect(app.router.state.location.search).toEqual({}));
    expect(await screen.findByText('Маникюр с покрытием на дому')).toBeTruthy();
  });

  it('loads the next page with «Show more»', async () => {
    const many = Array.from({ length: 25 }, (_, index): FeedFixture => {
      const source = FEED_JOBS[index % FEED_JOBS.length] ?? LEAK;
      const id = `0199dd00-0000-7000-8000-${String(100 + index).padStart(12, '0')}`;
      return { ...source, card: { ...source.card, id, title: `Заявка ${index + 1}` } };
    });
    const jobs = withJobs(new JobsBackend(many));
    startApp('/jobs');

    await waitFor(() => expect(titles().length).toBeGreaterThan(0));
    await click(await screen.findByRole('button', { name: 'Показать ещё' }));

    // список виртуальный: в DOM — карточки у экрана, поэтому проверяем страницы
    await waitFor(() => expect(jobs.feedRequests).toHaveLength(2));
    expect(jobs.feedRequests[0]?.get('limit')).toBe('20');
    expect(jobs.feedRequests[1]?.get('cursor')).toBe('c20');
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Показать ещё' })).toBeNull());
    expect(titles().length).toBeLessThan(25);
  });
});

describe('S14 filters', () => {
  it('counts the draft on the MainButton and applies it to the address', async () => {
    const jobs = withJobs();
    const { app, telegram } = startApp('/jobs');
    await screen.findByText('Течёт смеситель на кухне');

    await click(screen.getByRole('button', { name: 'Фильтры' }));
    const sheet = await screen.findByRole('dialog', { name: 'Фильтры' });
    await click(within(sheet).getByRole('button', { name: 'Мастер на час' }));
    await click(within(sheet).getByRole('radio', { name: 'Сегодня' }));

    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Показать 2 заявки'));
    await click(within(sheet).getByRole('button', { name: /Бюджет от/ }));
    await click(await screen.findByRole('button', { name: /от 5\s000\sRSD/u }));
    expect(within(sheet).getByRole('button', { name: /Бюджет от.*от 5\s000\sRSD/u })).toBeTruthy();
    await pressMainButton(telegram);

    await waitFor(() =>
      expect(app.router.state.location.search).toEqual({
        categories: [CATEGORY_IDS.handyman],
        when: 'today',
        budget: 5000,
      }),
    );
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(titles()).toEqual(['Повесить люстру']));
    const request = jobs.feedRequests.at(-1);
    expect(request?.getAll('category')).toEqual([String(CATEGORY_IDS.handyman)]);
    expect(request?.getAll('urgency')).toEqual(['asap', 'today']);
    expect(request?.get('budget_from')).toBe('500000');
    expect(screen.getByRole('button', { name: 'Мастер на час', pressed: true })).toBeTruthy();
  });

  it('closes with Back without applying the draft', async () => {
    withJobs();
    const { app, telegram } = startApp('/jobs');
    await screen.findByText('Течёт смеситель на кухне');
    await click(screen.getByRole('button', { name: 'Фильтры' }));
    const sheet = await screen.findByRole('dialog', { name: 'Фильтры' });
    await click(within(sheet).getByRole('button', { name: 'Только с фото' }));

    await pressBackButton(telegram);

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(app.router.state.location.search).toEqual({});
  });

  it('asks for the location for a radius and names the nearest district', async () => {
    withJobs();
    const { telegram } = startApp('/jobs');
    await screen.findByText('Течёт смеситель на кухне');
    await click(screen.getByRole('button', { name: 'Фильтры' }));
    const sheet = await screen.findByRole('dialog', { name: 'Фильтры' });
    expect(within(sheet).getByText('Радиус')).toBeTruthy();

    await click(within(sheet).getByRole('button', { name: '1 км' }));

    expect(await within(sheet).findByText('Радиус от вас · Лиман')).toBeTruthy();
    expect(within(sheet).getByRole('button', { name: '1 км', pressed: true })).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Заявок нет'));
    expect(mainButton(telegram)?.is_active).toBe(false);
  });
});

describe('S15 job', () => {
  it('shows the job: slots, description, place, client', async () => {
    withJobs();
    const { telegram } = startApp(CHANDELIER_PATH);

    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
    expect(screen.getByText('Сегодня 18:00–21:00')).toBeTruthy();
    expect(await screen.findByText('Люстры и карнизы')).toBeTruthy();
    expect(screen.getByText(/^5\s000\sRSD$/u)).toBeTruthy();
    expect(screen.getByText('за всю работу')).toBeTruthy();
    expect(screen.getByText('15 мин назад')).toBeTruthy();
    expect(screen.getByText('Откликов 3 из 5')).toBeTruthy();
    expect(screen.getByText('Осталось 2 места')).toBeTruthy();
    expect(screen.getByText(/Стремянки у меня нет/)).toBeTruthy();
    expect(screen.getByText('Язык общения: русский')).toBeTruthy();
    expect(
      await screen.findByRole('img', { name: 'Примерный район на карте: Лиман' }),
    ).toBeTruthy();
    expect(screen.getByText('Точный адрес увидит только выбранный исполнитель')).toBeTruthy();
    const client = screen.getByRole('region', { name: 'Заказчик' });
    expect(within(client).getByText('Елена К.')).toBeTruthy();
    expect(within(client).getByText('В «Соседях» 3 месяца · 2 заявки')).toBeTruthy();
    expect(within(client).getByText('Телефон подтверждён')).toBeTruthy();
    expect(screen.getAllByRole('img', { name: /Фото \d из 2/ })).toHaveLength(2);
    // отклик — с формой 5.5: главной кнопки пока нет
    expect(mainButton(telegram)?.is_visible ?? false).toBe(false);
    expect(backButtonVisible(telegram)).toBe(true);
  });

  it('opens from the feed with the distance from the feed point', async () => {
    withJobs();
    const { app } = startApp('/jobs?near=3&lat=45.2671&lon=19.8335');
    const card = await screen.findByRole('link', { name: /Повесить люстру/ });

    await click(card);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(CHANDELIER_PATH));
    expect(app.router.state.location.search).toEqual({ lat: 45.267, lon: 19.834 });
    expect(await screen.findByText(/^Лиман, ≈ \d,\d км от вас$/u)).toBeTruthy();
  });

  it('hides the job with «Not interested» and returns to the feed without it', async () => {
    const jobs = withJobs();
    const { app } = startApp('/jobs');
    await click(await screen.findByRole('link', { name: /Повесить люстру/ }));
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });

    await click(await screen.findByRole('button', { name: 'Не интересно' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs'));
    expect(jobs.hidden).toEqual(new Set([CHANDELIER.card.id]));
    await screen.findByText('Течёт смеситель на кухне');
    await waitFor(() => expect(screen.queryByText('Повесить люстру')).toBeNull());
  });

  it('says when hiding failed and stays on the job', async () => {
    const jobs = withJobs();
    jobs.failNextHide = problem(500, 'internal_error');
    const { app } = startApp(CHANDELIER_PATH);

    await click(await screen.findByRole('button', { name: 'Не интересно' }));

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('Не получилось скрыть заявку. Повторите.')).toBeTruthy();
    expect(app.router.state.location.pathname).toBe(CHANDELIER_PATH);
  });

  it('has no «Not interested» and no heart for a guest', async () => {
    asGuest();
    withJobs();
    startApp(CHANDELIER_PATH);

    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
    expect(await screen.findByText('Елена К.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Не интересно' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Сохранить заявку' })).toBeNull();
  });

  it('saves the job with the heart: it shows under «Jobs» in S12', async () => {
    const jobs = withJobs();
    const { app } = startApp(CHANDELIER_PATH);

    await click(await screen.findByRole('button', { name: 'Сохранить заявку', pressed: false }));

    expect(await screen.findByRole('button', { name: 'Убрать из сохранённых' })).toBeTruthy();
    await waitFor(() => expect(jobs.saved).toEqual([CHANDELIER.card.id]));
    await act(async () => {
      await app.router.navigate({ to: '/favorites/jobs' });
    });
    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 2 })).toBeTruthy();
    const segments = screen.getByRole('navigation', { name: 'Что показать' });
    expect(within(segments).getByRole('link', { name: 'Задачи · 1' }).ariaCurrent).toBe('page');
    expect(within(segments).getByRole('link', { name: 'Мастера · 0' })).toBeTruthy();
  });

  it('says when the saved list is full and keeps the heart off', async () => {
    const jobs = withJobs();
    jobs.saved = Array.from({ length: 100 }, (_, index) => `saved-${index}`);
    startApp(CHANDELIER_PATH);

    await click(await screen.findByRole('button', { name: 'Сохранить заявку', pressed: false }));

    expect(
      await screen.findByText('Сохранено уже 100 заявок — уберите ненужные, чтобы сохранить новую'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Сохранить заявку', pressed: false })).toBeTruthy();
  });

  it('says the job is unavailable for an unknown id and a broken address', async () => {
    withJobs();
    const { app } = startApp('/jobs/0199dd00-0000-7000-8000-000000000999');

    expect(await screen.findByRole('heading', { name: 'Заявка недоступна' })).toBeTruthy();
    await click(screen.getByRole('button', { name: 'К ленте заявок' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs'));
  });

  it('opens from a `j_` link; Back leads to the feed', async () => {
    withJobs();
    const startParam = encodeStartParam({ type: 'job', id: CHANDELIER.card.id });
    const { app, telegram } = startApp('/', { startParam });

    await waitFor(() => expect(app.router.state.location.pathname).toBe(CHANDELIER_PATH));
    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
    await pressBackButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs'));
  });
});

describe('Jobs tab segments and the home block', () => {
  it('switches segments in place; «My responses» and «My jobs» come later', async () => {
    withJobs();
    const { app } = startApp('/jobs');
    const segments = await screen.findByRole('navigation', { name: 'Раздел заявок' });

    await click(within(segments).getByRole('link', { name: 'Мои заявки' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/mine'));
    expect(await screen.findByRole('heading', { name: 'Мои заявки', level: 1 })).toBeTruthy();
    expect(screen.getByRole('navigation', { name: 'Разделы' })).toBeTruthy();
  });

  it('shows «Looking for side jobs?» with new jobs of the day on Home', async () => {
    withJobs();
    const { app } = startApp('/');

    const block = await screen.findByRole('link', { name: /Ищете подработку\?/ });
    expect(within(block).getByText('5 новых задач рядом')).toBeTruthy();
    await click(block);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs'));
  });

  it('has no side-job block on Home without new jobs', async () => {
    withJobs(new JobsBackend([]));
    startApp('/');

    expect(await screen.findByRole('heading', { name: 'Найдём мастера рядом' })).toBeTruthy();
    await screen.findByRole('heading', { name: 'Что нужно сделать?' });
    expect(screen.queryByText('Ищете подработку?')).toBeNull();
  });
});

describe('S12 saved jobs', () => {
  it('switches «Masters» to «Jobs»; nothing saved — a hint and the way to the feed', async () => {
    withJobs();
    const { app } = startApp('/favorites');
    const segments = await screen.findByRole('navigation', { name: 'Что показать' });

    await click(await within(segments).findByRole('link', { name: 'Задачи · 0' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/favorites/jobs'));
    expect(
      await screen.findByRole('heading', { name: 'Здесь будут сохранённые заявки' }),
    ).toBeTruthy();
    await click(screen.getByRole('button', { name: 'К ленте заявок' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs'));
  });
});
