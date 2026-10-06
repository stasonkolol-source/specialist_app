// Свои заявки клиента S22 и S23 (DEVELOPMENT_PLAN 5.6) на фейке backend: «Мои заявки» разделами с
// «3 отклика — выберите исполнителя» и «2 новых», чипы-фильтры — от пяти заявок, итог словом с
// датой («Выполнена …», «В работе» без даты); своя заявка — строка статуса («Ждём откликов ·
// открыта до …»), район, бюджет, просмотры, места без «осталось N мест», отклики карточками
// («Откликнулся первым», «Подработка», рейтинг), откликов нет — «бот напишет» и одна кнопка
// «Пригласить специалистов»; выполненная — итог одной строкой и одно действие; закрыть с
// причиной, пригласить специалиста; ссылка на свою заявку ведёт владельца на S23; вкладка
// «Заявки» клиенту с заявками в ходу открывает «Мои заявки», остальным — «Ленту»; на Главной —
// «Мои активные заявки». «Изменить» —
// мастер с полями заявки и сохранение с If-Match; версию сдвинула автопроверка — правка уходит с
// новой, саму заявку правили в другом месте — мастер показывает её текущую версию. S23 сам уходит
// из «на проверке», шапка не отстаёт от откликов; «Назад» после правки — не в шаги мастера; новые
// отклики видны на сегменте «Мои заявки» и на карточке заявки.
import type { JobStatus } from '@sosed/api-client';
import { getViewsGetBadgesQueryKey, setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  mainButton,
  pressBackButton,
  pressMainButton,
  startApp,
  userBackend,
} from '../../testing/app.tsx';
import { ChatBackend } from '../../testing/chatBackend.ts';
import { E2E_NOW, ME, NOTIFICATION_SETTINGS, WRITE_ACCESS } from '../../testing/fixtures.ts';
import {
  JobsBackend,
  completedDealFixture,
  myJobsFixture,
  responseCardsFixture,
} from '../../testing/jobsBackend.ts';
import { chatHandlers, jobsHandlers, server } from '../../testing/msw.ts';
import { byAttention } from './s22-my-jobs/order.ts';
import { useDraftStore } from './shared/draft.ts';

const [CHANDELIER, CLEANING] = myJobsFixture();
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
    // три заявки — чипы-фильтры только занимали бы место
    expect(screen.queryByRole('group', { name: 'Статус заявок' })).toBeNull();

    await click(screen.getByRole('link', { name: /Повесить люстру/ }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
  });

  it('filters by status chips from five jobs on', async () => {
    const backend = withMine();
    for (const [index, title] of ['Собрать шкаф', 'Покрасить стену'].entries()) {
      const id = `0199dd30-0000-7000-8000-0000000001${index}0`;
      if (CLEANING) backend.jobs.set(id, { ...CLEANING, id, title, status: 'closed' });
    }
    startApp('/jobs/mine');

    const chips = await screen.findByRole('group', { name: 'Статус заявок' });
    await click(within(chips).getByRole('button', { name: 'Архив' }));
    expect(screen.queryByRole('link', { name: /Повесить люстру/ })).toBeNull();
    expect(screen.getByRole('link', { name: /Собрать шкаф/ })).toBeTruthy();
    await click(within(chips).getByRole('button', { name: 'Все' }));
    expect(screen.getByRole('link', { name: /Повесить люстру/ })).toBeTruthy();
  });

  it('names the outcome with its date: done on the day it closed, in work without a date', async () => {
    const backend = withMine();
    if (!CHANDELIER || !CLEANING) throw new Error('fixtures');
    backend.jobs.set(CHANDELIER.id, {
      ...CHANDELIER,
      status: 'completed',
      closed_at: '2026-10-04T15:00:00Z',
      close_reason: 'hired_here',
    });
    backend.jobs.set(CLEANING.id, { ...CLEANING, status: 'assigned' });
    startApp('/jobs/mine');

    const done = await screen.findByRole('link', { name: /Повесить люстру/ });
    expect(within(done).getByText('Выполнена 4 октября')).toBeTruthy();
    const work = screen.getByRole('link', { name: /Генеральная уборка/ });
    expect(within(work).getByText('В работе')).toBeTruthy();
    // у заявки в работе нет даты закрытия — раньше ей доставалась «Закрыта» со сроком истечения
    expect(within(work).queryByText(/Закрыта/)).toBeNull();
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
    expect(screen.getByText('3 отклика — выберите исполнителя')).toBeTruthy();
  });
});

describe('the jobs tab', () => {
  it('always opens the feed, even for a client with jobs going on and new responses', async () => {
    // решение владельца (2026-10-03, подтверждено 2026-10-06): вкладка «Заявки» — всегда «Лента»;
    // свои заявки — сегментом «Мои заявки», новые отклики видны точкой на нём и счётчиком вкладки
    withMine();
    const chat = new ChatBackend();
    chat.jobsBadge = 2;
    server.use(...chatHandlers(() => chat));
    const { app } = startApp('/');
    await screen.findByRole('region', { name: 'Мои активные заявки' });
    const tabs = screen.getByRole('navigation', { name: 'Разделы' });
    await waitFor(() =>
      expect(
        within(tabs)
          .getByRole('link', { name: /Заявки/ })
          .getAttribute('href'),
      ).toMatch(/\/jobs$/),
    );

    await click(within(tabs).getByRole('link', { name: /Заявки/ }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs'));
    const segments = await screen.findByRole('navigation', { name: 'Раздел заявок' });
    await click(within(segments).getByRole('link', { name: /Мои заявки/ }));
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
    // строка статуса: слово словаря и до какого числа открыта; «Опубликована N мин назад» — нет
    expect(screen.getByText('3 отклика — выберите исполнителя')).toBeTruthy();
    expect(screen.getByText('открыта до 12 октября')).toBeTruthy();
    expect(screen.queryByText(/^Опубликована/)).toBeNull();
    expect(
      await screen.findByText('Лиман. Точный адрес откроется выбранному исполнителю'),
    ).toBeTruthy();
    expect(screen.getByText(/^5\s000\sRSD · фикс, за работу$/u)).toBeTruthy();
    expect(screen.getByText('12 просмотров')).toBeTruthy();
    expect(screen.getByText('3 из 5')).toBeTruthy();
    // «осталось N мест» — язык исполнителя
    expect(screen.queryByText(/осталось/)).toBeNull();
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
    // «выберите исполнителя» уже в строке статуса, про адрес — у района: баннер их не повторяет
    expect(screen.queryByText(/^Выберите исполнителя/)).toBeNull();
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

  it('names a whole-city performer «Весь Нови-Сад», not the first district (QA SMOKE-6)', async () => {
    const backend = withMine();
    const [alexey] = responseCardsFixture();
    if (!alexey || !CHANDELIER) throw new Error('fixtures');
    backend.responseCards.set(CHANDELIER.id, [
      { ...alexey, performer: { ...alexey.performer, district: null, whole_city: true } },
    ]);
    startApp(MANAGE);

    const card = await screen.findByRole('link', { name: /^Алексей Морозов/ });
    // город — из справочника: пока он грузится, «Весь город»
    expect(await within(card).findByText(/^Весь\sНови-Сад$/u)).toBeTruthy();
    expect(within(card).queryByText('Лиман')).toBeNull();
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
    expect(await screen.findByText('Закрыта 5 октября')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    // итог вместо процесса: ни просмотров, ни мест, отклики свёрнуты
    expect(screen.queryByText('12 просмотров')).toBeNull();
    expect(screen.queryByText('3 из 5')).toBeNull();
    expect(screen.getByRole('button', { name: 'Отклики (3)' })).toBeTruthy();
    expect(screen.queryByRole('link', { name: /^Алексей Морозов/ })).toBeNull();
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

  it('waits for responses with one status line, one text and one button (№5)', async () => {
    const backend = withMine();
    server.use(
      http.get('*/api/v1/me/notification-settings', () =>
        HttpResponse.json({ ...NOTIFICATION_SETTINGS, telegram: WRITE_ACCESS }),
      ),
    );
    startApp(`/jobs/${CLEANING?.id ?? ''}/manage`);

    expect(await screen.findByText('Ждём откликов')).toBeTruthy();
    expect(screen.getByText('открыта до 12 октября')).toBeTruthy();
    expect(await screen.findByText('Откликов пока нет')).toBeTruthy();
    expect(
      await screen.findByText(
        'Бот напишет, как только кто-то откликнется. Чтобы ускорить — пригласите специалистов.',
      ),
    ).toBeTruthy();
    // «Исполнители рядом уже получили уведомление» — не обещаем; мест и «Пригласить» в шапке нет
    expect(screen.queryByText(/получили уведомление/)).toBeNull();
    expect(screen.queryByText('0 из 5')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Пригласить' })).toBeNull();

    await click(screen.getByRole('button', { name: 'Пригласить специалистов' }));
    const sheet = screen.getByRole('dialog', { name: 'Пригласите специалистов' });
    const [invite] = await within(sheet).findAllByRole('button', { name: 'Пригласить' });
    if (!invite) throw new Error('no specialists to invite');
    await click(invite);
    await waitFor(() => expect(backend.invites.get(CLEANING?.id ?? '')).toHaveLength(1));
  });

  it('does not promise the bot while it cannot write', async () => {
    withMine();
    startApp(`/jobs/${CLEANING?.id ?? ''}/manage`);

    expect(
      await screen.findByText('Отклики появятся здесь. Чтобы ускорить — пригласите специалистов.'),
    ).toBeTruthy();
  });

  it('says how long the review takes in the status line, without a banner', async () => {
    const backend = withMine();
    if (!CLEANING) throw new Error('fixtures');
    backend.jobs.set(CLEANING.id, { ...CLEANING, status: 'pending_moderation' });
    startApp(`/jobs/${CLEANING.id}/manage`);

    expect(await screen.findByText('На проверке')).toBeTruthy();
    expect(screen.getByText('обычно несколько минут')).toBeTruthy();
    expect(screen.queryByText(/^Заявка на проверке/)).toBeNull();
    expect(await screen.findByText('Откликов пока нет')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Пригласить специалистов' })).toBeNull();
  });

  it('shows a done job as its outcome in one line and one action (№13)', async () => {
    const backend = withMine();
    const [aleksey] = responseCardsFixture();
    if (!CHANDELIER || !aleksey) throw new Error('fixtures');
    const done = {
      ...CHANDELIER,
      status: 'completed' as const,
      closed_at: '2026-10-05T07:00:00Z',
      close_reason: 'hired_here' as const,
    };
    backend.jobs.set(done.id, done);
    const deal = completedDealFixture(done, aleksey);
    backend.deals.set(deal.id, deal);
    const { app } = startApp(MANAGE);

    expect(await screen.findByText('Выполнена 5 октября')).toBeTruthy();
    expect(await screen.findByText(/^Алексей Морозов · 3\s500\sRSD$/u)).toBeTruthy();
    // процесс спрятан: ни «когда», ни мест, ни просмотров, ни подсказки про адрес
    expect(screen.getByText('Лиман')).toBeTruthy();
    expect(screen.queryByText(/Точный адрес/)).toBeNull();
    expect(screen.queryByText('12 просмотров')).toBeNull();
    expect(screen.queryByText('3 из 5')).toBeNull();
    expect(screen.queryByText(/Работа выполнена/)).toBeNull();
    // отклики свёрнуты
    const responses = screen.getByRole('button', { name: 'Отклики (3)' });
    expect(screen.queryByRole('link', { name: /^Алексей Морозов/ })).toBeNull();
    await click(responses);
    expect(await screen.findByRole('link', { name: /^Алексей Морозов/ })).toBeTruthy();

    await click(screen.getByRole('button', { name: 'Оставить отзыв' }));
    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(`/deals/${deal.id}/review`),
    );
  });

  it('offers to order again once the review is left', async () => {
    const backend = withMine();
    const [aleksey] = responseCardsFixture();
    if (!CHANDELIER || !aleksey) throw new Error('fixtures');
    const done = { ...CHANDELIER, status: 'completed' as const, closed_at: '2026-10-05T07:00:00Z' };
    backend.jobs.set(done.id, done);
    const deal = completedDealFixture(done, aleksey);
    backend.deals.set(deal.id, {
      ...deal,
      review_until: null,
      my_review: { id: '0199df00-0000-7000-8000-000000000001', status: 'published', rating: 5 },
    });
    startApp(MANAGE);

    expect(await screen.findByRole('button', { name: 'Заказать снова' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Оставить отзыв' })).toBeNull();
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

  it('saves over a version moved by the auto-check: no false «changed elsewhere» (ADV-07)', async () => {
    const backend = withMine();
    const { app, telegram } = startApp(MANAGE);
    await toPreview(telegram);
    // пока правку вносили, автопроверка сдвинула версию — поля владельца те же
    backend.touch(CHANDELIER?.id ?? '', { moderation_note: null });

    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    expect(backend.updates.map((update) => update.ifMatch)).toEqual(['"1"', '"2"']);
    expect(screen.queryByText(/изменили в другом месте/)).toBeNull();
  });

  it('edits twice in a row while the auto-check publishes each edit (ADV-07)', async () => {
    const backend = withMine();
    backend.autoModerate = true;
    const { app, telegram } = startApp(MANAGE);

    await toPreview(telegram);
    await pressMainButton(telegram);
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    await toPreview(telegram);
    await pressMainButton(telegram);

    await waitFor(() => expect(backend.updates).toHaveLength(2));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    expect(screen.queryByRole('alert')).toBeNull();
    // вторая правка — с версией, которую уже сдвинула автопроверка первой
    const job = backend.jobs.get(CHANDELIER?.id ?? '');
    expect(job?.version).toBe(5);
  });

  it('shows the current version of a job edited elsewhere and saves the edit again', async () => {
    const backend = withMine();
    const { app, telegram } = startApp(MANAGE);
    await toPreview(telegram);
    // заявку поправили на другом устройстве
    backend.touch(CHANDELIER?.id ?? '', { title: 'Повесить две люстры' });

    await pressMainButton(telegram);

    expect(
      await screen.findByText(
        'Пока вы правили, заявку изменили в другом месте. Показываем её текущую версию — внесите правку ещё раз и сохраните.',
      ),
    ).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Повесить две люстры', level: 2 })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/jobs/new/preview');

    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    expect(backend.updates.at(-1)?.ifMatch).toBe('"2"');
    expect(backend.updates.at(-1)?.body.title).toBe('Повесить две люстры');
  });

  it('asks to reopen the job when its version keeps moving', async () => {
    const backend = withMine();
    const { app, telegram } = startApp(MANAGE);
    await toPreview(telegram);
    const id = CHANDELIER?.id ?? '';
    // версия уходит вперёд и до сохранения, и на каждое чтение: повторы правки кончаются
    backend.touch(id, {});
    server.use(
      http.get(`*/api/v1/jobs/${id}`, () => {
        backend.touch(id, {});
        return HttpResponse.json({ ...backend.jobs.get(id), version: 0 });
      }),
    );

    await pressMainButton(telegram);

    expect(
      await screen.findByText(
        'Заявку уже изменили в другом месте — откройте её заново и повторите правку.',
      ),
    ).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Открыть заявку' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
  });

  it('goes Back from S23 after saving to where S23 was opened, not into the steps', async () => {
    withMine();
    const { app, telegram } = startApp('/jobs/mine');
    await click(await screen.findByRole('link', { name: /Повесить люстру/ }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    await toPreview(telegram);
    await pressMainButton(telegram);
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));

    await pressBackButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/mine'));
  });
});

describe('S23 stays fresh', () => {
  it('leaves «on review» by itself once the auto-check published the edit (SMOKE-2)', async () => {
    const backend = withMine();
    backend.autoModerate = true;
    const { app, telegram } = startApp(MANAGE);
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });
    await click(screen.getByRole('button', { name: 'Изменить' }));
    for (let step = 0; step < 4; step += 1) await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    expect(
      await screen.findByText('3 отклика — выберите исполнителя', undefined, { timeout: 4_000 }),
    ).toBeTruthy();
    expect(screen.queryByText('На проверке')).toBeNull();
    expect(screen.getByRole('button', { name: 'Пригласить' })).toBeTruthy();
  });

  it('re-reads the job on open even from a fresh cache', async () => {
    const backend = withMine();
    const reads: string[] = [];
    const id = CHANDELIER?.id ?? '';
    server.use(
      http.get(`*/api/v1/jobs/${id}`, () => {
        reads.push(id);
        return HttpResponse.json(backend.jobs.get(id));
      }),
    );
    const { app } = startApp(MANAGE);
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });
    await waitFor(() => expect(reads).toHaveLength(1));
    void app.router.navigate({ to: '/jobs/mine' });
    await screen.findByRole('heading', { name: 'Активные', level: 2 });

    void app.router.navigate({ to: MANAGE });

    await waitFor(() => expect(reads).toHaveLength(2));
  });

  it('updates the header counters together with the polled responses (SMOKE-5)', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval'], now: new Date(E2E_NOW) });
    const backend = withMine();
    startApp(MANAGE);
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });
    expect(await screen.findByText('3 из 5')).toBeTruthy();
    // новый отклик, пока экран открыт: заявка и карточки на сервере уже с ним
    const id = CHANDELIER?.id ?? '';
    const [first] = responseCardsFixture();
    if (!first) throw new Error('fixtures');
    backend.responseCards.set(id, [
      ...(backend.responseCards.get(id) ?? []),
      { ...first, id: '0199dd50-0000-7000-8000-000000000099', is_new: true },
    ]);
    backend.touch(id, { responses_count: 4, views_count: 13 });

    await act(() => vi.advanceTimersByTimeAsync(15_000));

    expect(await screen.findByText('4 из 5')).toBeTruthy();
    expect(screen.getByText('13 просмотров')).toBeTruthy();
    expect(await screen.findAllByRole('link', { name: /^Алексей Морозов/ })).toHaveLength(2);
  });
});

describe('new responses on «Мои заявки» (OWN-3)', () => {
  it('shows the tab count on the segment and refreshes the job card', async () => {
    const backend = withMine();
    const chat = new ChatBackend();
    server.use(...chatHandlers(() => chat));
    const id = CHANDELIER?.id ?? '';
    // список — как до нового отклика: новых нет
    const job = backend.jobs.get(id);
    if (job) backend.jobs.set(id, { ...job, new_responses: 0 });
    const { app } = startApp('/jobs/mine');
    const chandelier = await screen.findByRole('link', { name: /Повесить люстру/ });
    expect(within(chandelier).queryByText(/новы/)).toBeNull();
    const segments = screen.getByRole('navigation', { name: 'Раздел заявок' });
    expect(within(segments).getByRole('link', { name: 'Мои заявки' })).toBeTruthy();

    // пришёл отклик: бейдж (опрос) знает о нём раньше списка
    const listed = backend.jobs.get(id);
    if (listed) backend.jobs.set(id, { ...listed, new_responses: 1 });
    chat.jobsBadge = 1;
    await act(async () => {
      await app.queryClient.refetchQueries({ queryKey: getViewsGetBadgesQueryKey() });
    });

    expect(
      await within(segments).findByRole('link', { name: 'Мои заявки, 1 новый отклик' }),
    ).toBeTruthy();
    expect(
      await within(screen.getByRole('link', { name: /Повесить люстру/ })).findByText('1 новый'),
    ).toBeTruthy();
  });

  it('clears the tab count once the job is opened, even when the list is behind', async () => {
    const backend = withMine();
    const id = CHANDELIER?.id ?? '';
    // список ещё не знает о новых откликах (заявку открыли по ссылке бота) — знают сами карточки
    const job = backend.jobs.get(id);
    if (job) backend.jobs.set(id, { ...job, new_responses: 0 });
    const chat = new ChatBackend();
    chat.jobsBadge = 2;
    let badgeReads = 0;
    // свой обработчик — первым: иначе бейджи отдаст обработчик переписки
    server.use(
      http.get('*/api/v1/me/badges', () => {
        badgeReads += 1;
        return HttpResponse.json({ jobs: chat.jobsBadge, messages: 0 });
      }),
      ...chatHandlers(() => chat),
    );
    startApp(MANAGE);

    // карточки пришли с новыми откликами — бейдж перечитан сразу, а не через минуту опроса
    expect(await screen.findByRole('link', { name: /^Алексей Морозов/ })).toBeTruthy();
    await waitFor(() => expect(badgeReads).toBe(2));
  });

  it('shows the count on the segment of the feed too', async () => {
    withMine();
    const chat = new ChatBackend();
    chat.jobsBadge = 2;
    server.use(...chatHandlers(() => chat));
    startApp('/jobs');

    const segments = await screen.findByRole('navigation', { name: 'Раздел заявок' });
    expect(
      await within(segments).findByRole('link', { name: 'Мои заявки, 2 новых отклика' }),
    ).toBeTruthy();
  });
});
