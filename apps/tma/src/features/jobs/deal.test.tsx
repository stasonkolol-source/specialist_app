// Выбор исполнителя и сделка (DEVELOPMENT_PLAN 6.2) на фейке backend: карточка отклика S23 ведёт
// на S24 — мини-профиль, предложение, «Ваш бюджет»; «Отклонить» освобождает место; MainButton
// «Выбрать исполнителем» открывает S25 — что изменится сразу, и подтверждение создаёт сделку и
// ведёт на S26: статус, вторая сторона, адрес, таймлайн и памятка. «Работа выполнена» — отметка
// стороны, вторая завершает сделку; отмена — причиной из шторки. Ссылка `d_` открывает сделку,
// S23 «в работе» и S17 выбранного — «Открыть сделку». SecondaryButton «Написать» на S24 начинает
// диалог по отклику (6.4). Завершённая сделка клиента — «Заказать снова»: прямой диалог с этим
// специалистом.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { E2E_NOW } from '../../testing/fixtures.ts';
import {
  JobsBackend,
  completedDealFixture,
  dealCardFixture,
  myJobsFixture,
  responseCardsFixture,
} from '../../testing/jobsBackend.ts';
import { ChatBackend } from '../../testing/chatBackend.ts';
import { chatHandlers, jobsHandlers, server } from '../../testing/msw.ts';

const [CHANDELIER] = myJobsFixture();
const JOB_ID = CHANDELIER?.id ?? '';
const [ALEKSEY] = responseCardsFixture();
const MANAGE = `/jobs/${JOB_ID}/manage`;
const CHOICE = `/jobs/${JOB_ID}/responses/${ALEKSEY?.id ?? ''}`;

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

/** Сделка с Алексеем уже идёт: заявка «в работе». */
function withDeal(backend: JobsBackend) {
  if (!CHANDELIER || !ALEKSEY) throw new Error('fixtures');
  const deal = dealCardFixture(CHANDELIER, ALEKSEY, 'client');
  backend.deals.set(deal.id, deal);
  backend.jobs.set(JOB_ID, { ...CHANDELIER, status: 'assigned', responses_count: 0 });
  backend.responseCards.set(
    JOB_ID,
    responseCardsFixture().map((card) => ({
      ...card,
      status: card.id === ALEKSEY.id ? 'accepted' : 'not_selected',
    })),
  );
  return deal;
}

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

describe('S24 response and S25 choice', () => {
  it('leads from a response card to the offer and chooses the performer', async () => {
    const backend = withMine();
    const { app, telegram } = startApp(MANAGE);

    await click(await screen.findByRole('link', { name: /^Алексей Морозов/ }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(CHOICE));
    expect(await screen.findByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeTruthy();
    expect(screen.getByText('4,9')).toBeTruthy();
    expect(screen.getByText('37 отзывов')).toBeTruthy();
    const offer = screen.getByRole('region', { name: 'Предложение' });
    expect(within(offer).getByText('Цена за работу')).toBeTruthy();
    expect(within(offer).getByText('сегодня в 19:00')).toBeTruthy();
    // бюджет и «Отклонить» — нижней строкой карточки предложения
    expect(within(offer).getByText(/^Ваш бюджет — 5\s000\sRSD$/u)).toBeTruthy();
    expect(within(offer).getByRole('button', { name: 'Отклонить' })).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Выбрать исполнителем'));

    await pressMainButton(telegram);
    const sheet = await screen.findByRole('dialog', { name: 'Выбрать этого исполнителя?' });
    const changes = within(sheet).getByRole('region', { name: 'Что изменится сразу' });
    expect(
      within(changes).getByText('Исполнителю откроется точный адрес — в карточке сделки'),
    ).toBeTruthy();
    expect(
      within(sheet).getByText(
        'Остальные откликнувшиеся получат уведомление, что выбран другой исполнитель',
      ),
    ).toBeTruthy();
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toMatch(/^\/deals\//));
    expect(backend.decisions).toEqual([{ id: ALEKSEY?.id, action: 'accept' }]);
    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
    expect(screen.getAllByText('Договорились')).toHaveLength(2); // статус и шаг таймлайна
  });

  it('writes to the performer from the response with the secondary button', async () => {
    withMine();
    const chat = new ChatBackend();
    server.use(...chatHandlers(() => chat));
    const { app, telegram } = startApp(CHOICE);
    await screen.findByRole('heading', { name: 'Алексей Морозов', level: 1 });
    await waitFor(() =>
      expect(telegram.callsOf('web_app_setup_secondary_button').at(-1)?.text).toBe('Написать'),
    );

    await act(async () => {
      telegram.emit('secondary_button_pressed');
    });

    await waitFor(() => expect(chat.starts).toEqual([{ response_id: ALEKSEY?.id }]));
    await waitFor(() => expect(app.router.state.location.pathname).toMatch(/^\/messages\/.+$/));
  });

  it('declines a response after a confirmation and goes back to the job', async () => {
    const backend = withMine();
    const { app, telegram } = startApp(CHOICE, { popupAnswer: 'ok' });

    await click(await screen.findByRole('button', { name: 'Отклонить' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    expect(telegram.callsOf('web_app_open_popup').at(-1)?.message).toBe(
      'Отклонить этот отклик? Место освободится, вернуть отклик не получится.',
    );
    expect(backend.decisions).toEqual([{ id: ALEKSEY?.id, action: 'decline' }]);
  });

  it('keeps the response when the decline is not confirmed', async () => {
    const backend = withMine();
    const { app, telegram } = startApp(CHOICE, { popupAnswer: 'cancel' });

    await click(await screen.findByRole('button', { name: 'Отклонить' }));

    await waitFor(() => expect(telegram.callsOf('web_app_open_popup')).toHaveLength(1));
    expect(backend.decisions).toEqual([]);
    expect(app.router.state.location.pathname).toBe(CHOICE);
    expect(screen.getByRole('button', { name: 'Отклонить' })).toBeTruthy();
  });

  it('shows a decided response in words and the deal of the chosen one', async () => {
    const backend = withMine();
    const deal = withDeal(backend);
    const { app, telegram } = startApp(CHOICE);

    expect(await screen.findByText('Вы выбрали этого исполнителя')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Отклонить' })).toBeNull();
    await waitFor(() => expect(mainButton(telegram)?.is_visible).toBe(false));

    await click(await screen.findByRole('button', { name: 'Открыть сделку' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(`/deals/${deal.id}`));
  });
});

describe('S26 deal', () => {
  it('shows terms, the performer, the address and the steps', async () => {
    const backend = withMine();
    const deal = withDeal(backend);
    const { telegram } = startApp(`/deals/${deal.id}`);

    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
    expect(screen.getAllByText('Договорились')).toHaveLength(2); // статус и шаг таймлайна
    expect(screen.getByText('Алексей Морозов')).toBeTruthy();
    const performer = screen.getByRole('link', { name: /^Алексей Морозов/ });
    expect(within(performer).getByText('4,9')).toBeTruthy();
    expect(within(performer).getByText('37 отзывов')).toBeTruthy();
    expect(within(performer).getByText('исполнитель')).toBeTruthy();
    expect(screen.getByText('бул. Цара Лазара, 56, кв. 12')).toBeTruthy();
    expect(screen.getByText('Лиман · адрес видите только вы и Алексей Морозов')).toBeTruthy();
    const steps = screen.getByRole('region', { name: 'Статус' });
    expect(within(steps).getByText('Отклик на заявку')).toBeTruthy();
    expect(within(steps).getByText('Выбран исполнителем')).toBeTruthy();
    expect(within(steps).getByText('Работа выполнена')).toBeTruthy();
    expect(screen.getByText(/Не вносите предоплату незнакомым исполнителям/)).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Работа выполнена'));
  });

  it('marks the work done, then the other side completes it', async () => {
    const backend = withMine();
    const deal = withDeal(backend);
    const { telegram } = startApp(`/deals/${deal.id}`);
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Работа выполнена'));

    await pressMainButton(telegram);

    expect(await screen.findByText(/^Вы отметили «Работа выполнена»/)).toBeTruthy();
    expect(backend.decisions).toEqual([{ id: deal.id, action: 'complete' }]);
    await waitFor(() => expect(mainButton(telegram)?.is_visible).toBe(false));
  });

  it('cancels with a reason', async () => {
    const backend = withMine();
    const deal = withDeal(backend);
    startApp(`/deals/${deal.id}`);

    await click(await screen.findByRole('button', { name: /Отменить сделку/ }));
    const sheet = await screen.findByRole('dialog', { name: 'Почему отменяете?' });
    await click(within(sheet).getByRole('button', { name: 'планы изменились' }));

    expect(await screen.findByText('Вы отменили сделку: планы изменились.')).toBeTruthy();
    expect(backend.decisions).toEqual([{ id: deal.id, action: 'cancel', reason: 'plans_changed' }]);
  });

  it('is shown to the chosen performer with the client', async () => {
    const backend = withMine();
    const deal = withDeal(backend);
    backend.dealRole = 'performer';
    startApp(`/deals/${deal.id}`);

    expect(await screen.findByText('Елена К.')).toBeTruthy();
    expect(screen.getByText('клиент')).toBeTruthy();
    expect(screen.queryByText(/Не вносите предоплату/)).toBeNull();
  });

  it('opens from the job in work', async () => {
    const backend = withMine();
    const deal = withDeal(backend);
    const { app } = startApp(MANAGE);

    expect(await screen.findByText('Исполнитель выбран')).toBeTruthy();
    await click(await screen.findByRole('button', { name: 'Открыть сделку' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe(`/deals/${deal.id}`));
  });
});

describe('S26 order again', () => {
  /** Завершённая сделка с Алексеем: отзыв ещё можно оставить. */
  function withCompleted(backend: JobsBackend) {
    if (!CHANDELIER || !ALEKSEY) throw new Error('fixtures');
    const deal = completedDealFixture(CHANDELIER, ALEKSEY);
    backend.deals.set(deal.id, deal);
    return deal;
  }

  it('opens the direct chat with the specialist from the completed deal', async () => {
    const deal = withCompleted(withMine());
    const chat = new ChatBackend();
    server.use(...chatHandlers(() => chat));
    const { app } = startApp(`/deals/${deal.id}`);

    await click(await screen.findByRole('button', { name: 'Заказать снова' }));

    await waitFor(() =>
      expect(chat.starts).toEqual([{ profile_id: ALEKSEY?.performer.profile_id }]),
    );
    await waitFor(() => expect(app.router.state.location.pathname).toMatch(/^\/messages\/.+$/));
  });

  it('is not offered before the deal is completed', async () => {
    const deal = withDeal(withMine());
    startApp(`/deals/${deal.id}`);

    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });
    expect(screen.queryByRole('button', { name: 'Заказать снова' })).toBeNull();
  });

  it('is not offered to the performer', async () => {
    const backend = withMine();
    const deal = withCompleted(backend);
    backend.dealRole = 'performer';
    startApp(`/deals/${deal.id}`);

    expect(await screen.findByText('Елена К.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Заказать снова' })).toBeNull();
  });
});
