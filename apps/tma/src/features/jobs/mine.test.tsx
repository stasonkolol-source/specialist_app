// Свои заявки клиента S22 и S23 (DEVELOPMENT_PLAN 5.6) на фейке backend: «Мои заявки» разделами с
// «3 отклика — выберите исполнителя» и «2 новых», чипы; своя заявка — статус, район, бюджет,
// просмотры, места, отклики карточками («Откликнулся первым», «Подработка», рейтинг), закрыть с
// причиной, пригласить специалиста; ссылка на свою заявку ведёт владельца на S23; вкладка
// «Заявки» и клиенту открывает «Ленту», «Мои заявки» — сегментом; на Главной — «Мои активные
// заявки». «Изменить» —
// мастер с полями заявки и сохранение с If-Match; чужая правка между ними — «откройте заново».
import type { JobStatus } from '@sosed/api-client';
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { http } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressMainButton, startApp, userBackend } from '../../testing/app.tsx';
import { E2E_NOW, ME } from '../../testing/fixtures.ts';
import { JobsBackend, myJobsFixture, responseCardsFixture } from '../../testing/jobsBackend.ts';
import { jobsHandlers, server } from '../../testing/msw.ts';
import { byAttention } from './s22-my-jobs/order.ts';
import { useDraftStore } from './shared/draft.ts';

const [CHANDELIER] = myJobsFixture();
const MANAGE = `/jobs/${CHANDELIER?.id ?? ''}/manage`;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(E2E_NOW) });
});
afterEach(() => {
  vi.useRealTimers();
  setSession(null);
});

function withMine(): JobsBackend {
  const backend = new JobsBackend().seedMine();
  server.use(...jobsHandlers(() => backend));
  return backend;
}

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

describe('S22 my jobs', () => {
  it('groups jobs and shows responses waiting for a choice', async () => {
    withMine();
    const { app } = startApp('/jobs/mine');

    const activeTitle = await screen.findByRole('heading', { name: 'Активные', level: 2 });
    const chandelier = screen.getByRole('link', { name: /Повесить люстру/ });
    expect(within(chandelier).getByText('3 отклика — выберите исполнителя')).toBeTruthy();
    expect(within(chandelier).getByText('2 новых')).toBeTruthy();
    expect(await within(chandelier).findByText('Лиман')).toBeTruthy();
    const cleaning = screen.getByRole('link', { name: /Генеральная уборка/ });
    expect(within(cleaning).getByText('Ждём откликов')).toBeTruthy();
    // ждёт выбора исполнителя — первой в группе (сервер отдал её второй)
    const active = activeTitle.closest('section');
    expect(active && within(active).getAllByRole('link')).toEqual([chandelier, cleaning]);
    expect(screen.getByRole('heading', { name: 'Архив', level: 2 })).toBeTruthy();
    const done = screen.getByRole('link', { name: /Уборка после ремонта/ });
    // статус закрытой — в дате, бейджем не повторяется
    expect(within(done).getByText('Закрыта 14 сентября')).toBeTruthy();
    expect(within(done).queryByText('Закрыта')).toBeNull();

    const chips = screen.getByRole('group', { name: 'Статус заявок' });
    await click(within(chips).getByRole('button', { name: 'Архив' }));
    expect(screen.queryByRole('link', { name: /Повесить люстру/ })).toBeNull();
    await click(within(chips).getByRole('button', { name: 'Все' }));

    await click(screen.getByRole('link', { name: /Повесить люстру/ }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
  });

  it('gives the Serbian closing date in the genitive: «Zatvoren 14. septembra»', async () => {
    withMine();
    userBackend({ ...ME, ui_locale: 'sr-Latn' });
    startApp('/jobs/mine', { languageCode: 'sr' });

    // Intl даёт «14. septembar»; дата в значении «когда» — в родительном падеже
    expect(await screen.findByText('Zatvoren 14. septembra')).toBeTruthy();
  });

  it('opens S23 at once from the list while the job itself reloads', async () => {
    withMine();
    const { app } = startApp('/jobs/mine');
    const link = await screen.findByRole('link', { name: /Повесить люстру/ });
    // заявка перечитывается долго — экран рисует её из списка «Мои заявки»
    server.use(http.get('*/api/v1/jobs/:jobId', () => new Promise<never>(() => undefined)));
    await click(link);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
    expect(screen.getByText('Приём откликов')).toBeTruthy();
  });

  it('is a segment of the jobs tab: the tab itself opens the feed, also for a client', async () => {
    withMine();
    const { app } = startApp('/');
    const tabs = await screen.findByRole('navigation', { name: 'Разделы' });

    await click(within(tabs).getByRole('link', { name: 'Заявки' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs'));
    const segments = await screen.findByRole('navigation', { name: 'Раздел заявок' });
    await click(within(segments).getByRole('link', { name: 'Мои заявки' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/mine'));
  });
});

describe('S22 order inside a group', () => {
  const job = (
    title: string,
    status: JobStatus,
    responses: number,
    fresh: number,
    publishedHoursAgo: number | null,
  ) => ({
    title,
    status,
    responses_count: responses,
    new_responses: fresh,
    published_at:
      publishedHoursAgo === null
        ? null
        : new Date(Date.parse(E2E_NOW) - publishedHoursAgo * 3_600_000).toISOString(),
    created_at: new Date(Date.parse(E2E_NOW) - 48 * 3_600_000).toISOString(),
  });

  it('puts jobs waiting for a choice first, then moderation, then «Ждём откликов»', () => {
    const jobs = [
      job('ждём, новая', 'published', 0, 0, 1),
      job('на проверке', 'pending_moderation', 0, 0, null),
      job('отклики без новых', 'published', 2, 0, 2),
      job('ждём, старая', 'published', 0, 0, 5),
      job('нужно исправить', 'rejected', 0, 0, null),
      job('новые отклики, старая', 'published', 3, 1, 6),
      job('новые отклики, новая', 'published', 1, 1, 3),
    ];
    expect([...jobs].sort(byAttention).map((item) => item.title)).toEqual([
      'новые отклики, новая',
      'новые отклики, старая',
      'отклики без новых',
      'на проверке',
      'нужно исправить',
      'ждём, новая',
      'ждём, старая',
    ]);
  });

  it('orders other groups by time only, newer first', () => {
    const jobs = [job('старая', 'closed', 3, 0, 30), job('новая', 'expired', 0, 0, 10)];
    expect([...jobs].sort(byAttention).map((item) => item.title)).toEqual(['новая', 'старая']);
  });
});

describe('S23 manage job', () => {
  it('shows the job, its views, slots and response cards', async () => {
    withMine();
    startApp(MANAGE);

    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
    expect(screen.getByText('Приём откликов')).toBeTruthy();
    expect(
      await screen.findByText('Лиман. Точный адрес откроется выбранному исполнителю'),
    ).toBeTruthy();
    expect(screen.getByText(/^5\s000\sRSD · фикс, за работу$/u)).toBeTruthy();
    expect(screen.getByText('12 просмотров')).toBeTruthy();
    expect(screen.getByText('3 из 5')).toBeTruthy();
    const first = await screen.findByRole('link', { name: /^Алексей Морозов/ });
    // рейтинг со звездой: число, отзывы рядом без «·», район
    expect(within(first).getByText('4,9')).toBeTruthy();
    expect(within(first).getByText('37 отзывов')).toBeTruthy();
    expect(within(first).getByText('Лиман')).toBeTruthy();
    expect(within(first).getByText('Откликнулся первым')).toBeTruthy();
    expect(within(first).getByText('Телефон подтверждён')).toBeTruthy();
    // непросмотренный отклик — точкой у имени, не бейджем «Новый» рядом с 37 отзывами; точка
    // держится за последнее слово имени, перенос её не отрывает
    const dot = within(first).getByRole('img', { name: 'Новый отклик' });
    expect(dot.parentElement?.textContent).toBe('Морозов ');
    expect(within(first).queryByText('Новый')).toBeNull();
    const casual = screen.getByRole('link', { name: /^Иван Гаврилов/ });
    expect(within(casual).getByText('Новый специалист')).toBeTruthy();
    expect(within(casual).getByText('Подработка')).toBeTruthy();
    const seen = screen.getByRole('link', { name: /^Никола Петрович/ });
    expect(within(seen).queryByRole('img', { name: 'Новый отклик' })).toBeNull();
    expect(
      screen.getByText('Выберите исполнителя — только ему откроется точный адрес.'),
    ).toBeTruthy();
    // «Поднять» — v1: кнопки с меткой версии нет
    expect(screen.queryByRole('button', { name: /Поднять/ })).toBeNull();
  });

  it('keeps at most two badges on a response card', async () => {
    const backend = withMine();
    const [, ivan] = responseCardsFixture();
    if (!ivan || !CHANDELIER) throw new Error('fixtures');
    // подработка, откликнулся первым и с телефоном — «Откликнулся первым» уступает фактам
    backend.responseCards.set(CHANDELIER.id, [
      { ...ivan, is_first: true, performer: { ...ivan.performer, phone_verified: true } },
    ]);
    startApp(MANAGE);

    const card = await screen.findByRole('link', { name: /^Иван Гаврилов/ });
    expect(within(card).getByText('Подработка')).toBeTruthy();
    expect(within(card).getByText('Телефон подтверждён')).toBeTruthy();
    expect(within(card).queryByText('Откликнулся первым')).toBeNull();
  });

  it('closes the job with a reason', async () => {
    const backend = withMine();
    startApp(MANAGE);
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });

    await click(screen.getByRole('button', { name: /Закрыть заявку/ }));
    const sheet = screen.getByRole('dialog', { name: 'Почему закрываете заявку?' });
    await click(within(sheet).getByRole('button', { name: 'Нашёлся в другом месте' }));

    await waitFor(() =>
      expect(backend.actions).toEqual([
        { jobId: CHANDELIER?.id, action: 'close', reason: 'hired_elsewhere' },
      ]),
    );
    expect(await screen.findByText('Закрыта')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('invites a specialist from the catalog', async () => {
    const backend = withMine();
    startApp(MANAGE);
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });

    await click(screen.getByRole('button', { name: 'Пригласить' }));
    const sheet = screen.getByRole('dialog', { name: 'Пригласите специалистов' });
    const [invite] = await within(sheet).findAllByRole('button', { name: 'Пригласить' });
    if (!invite) throw new Error('no specialists to invite');
    await click(invite);

    await waitFor(() => expect(backend.invites.get(CHANDELIER?.id ?? '')).toHaveLength(1));
    expect(await within(sheet).findByText('Приглашён')).toBeTruthy();
  });

  it('is where the owner lands from a link to the job', async () => {
    withMine();
    const { app } = startApp(`/jobs/${CHANDELIER?.id ?? ''}`);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
  });
});

describe('S03 my active jobs', () => {
  it('lists open jobs with their responses and leads to them', async () => {
    withMine();
    const { app } = startApp('/');

    const block = await screen.findByRole('region', { name: 'Мои активные заявки' });
    const row = within(block).getByRole('link', { name: /Повесить люстру/ });
    expect(within(row).getByText('3 отклика · 2 новых')).toBeTruthy();
    expect(within(block).getByText('Ждём откликов')).toBeTruthy();
    expect(within(block).queryByText('Уборка после ремонта')).toBeNull();

    await click(row);
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
  });
});

describe('S23 edit', () => {
  /** «Изменить» и шаги мастера до «Проверьте заявку». */
  async function toPreview(telegram: Parameters<typeof pressMainButton>[0]) {
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });
    await click(screen.getByRole('button', { name: 'Изменить' }));
    expect(await screen.findByText('Шаг 1 из 4. Правка заявки')).toBeTruthy();
    expect(screen.getByDisplayValue('Повесить люстру')).toBeTruthy();
    for (const step of ['Шаг 2 из 4. Правка заявки', 'Шаг 3 из 4. Правка заявки']) {
      await pressMainButton(telegram);
      expect(await screen.findByText(step)).toBeTruthy();
    }
    await pressMainButton(telegram);
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Сохранить изменения'));
  }

  it('saves the job with the version it was opened at', async () => {
    const backend = withMine();
    const { app, telegram } = startApp(MANAGE);

    await toPreview(telegram);
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    const [update] = backend.updates;
    expect(update?.ifMatch).toBe('"1"');
    expect(update?.body.title).toBe('Повесить люстру');
    expect(update?.body.urgency).toBe('today');
    expect(backend.jobs.get(CHANDELIER?.id ?? '')?.version).toBe(2);
    // правка закрыта: следующая начнётся с той версии, что видна на S23
    await waitFor(() => expect(useDraftStore.getState().editing).toBeNull());
  });

  it('asks to reopen the job changed elsewhere', async () => {
    const backend = withMine();
    const { app, telegram } = startApp(MANAGE);
    await toPreview(telegram);
    const id = CHANDELIER?.id ?? '';
    const job = backend.jobs.get(id);
    if (job) backend.jobs.set(id, { ...job, version: job.version + 1 });

    await pressMainButton(telegram);

    expect(
      await screen.findByText(
        'Заявку уже изменили в другом месте — откройте её заново и повторите правку.',
      ),
    ).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Открыть заявку' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
  });
});
