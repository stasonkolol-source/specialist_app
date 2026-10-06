// Спор по сделке S52 (DEVELOPMENT_PLAN 6.1c, 6.2) на фейке backend: SecondaryButton «Есть
// проблема» S26 ведёт на S52; форма — что случилось, описание и фото (media `dispute`), «Отправить»
// после выбора и текста; спор сразу на экране — «Ждём ответа», а S26 — «на паузе» и «Спор по
// сделке». Вторая сторона видит сообщение, срок и отвечает; открывший отзывает спор — сделка снова
// идёт. Решение поддержки — с причиной; спор по сделке не в работе не открыть.
import type { DealCardDisputeOut, DealCardOut } from '@sosed/api-client';
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressMainButton, startApp, userBackend } from '../../testing/app.tsx';
import { E2E_NOW, ME } from '../../testing/fixtures.ts';
import {
  JobsBackend,
  dealCardFixture,
  myJobsFixture,
  responseCardsFixture,
} from '../../testing/jobsBackend.ts';
import { jobsHandlers, profileHandlers, server } from '../../testing/msw.ts';
import { ProfileBackend } from '../../testing/profileBackend.ts';

// в jsdom нет холста и XHR в хранилище: файл «доходит» в хранилище сразу
const transport = vi.hoisted(() => ({
  put: vi.fn(async () => ({ status: 200, etag: '"e"' as string | null })),
}));
vi.mock('./shared/uploads.ts', () => ({ mediaTransport: transport }));

const [CHANDELIER] = myJobsFixture();
const [ALEKSEY] = responseCardsFixture();
const NO_SHOW = 'Договорились на 19:00. В 19:40 мастера всё ещё нет.';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(E2E_NOW) });
});
afterEach(() => {
  vi.useRealTimers();
  setSession(null);
});

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

/** Идущая сделка клиента с Алексеем; фото — в памяти фейка media. */
function withDeal(patch: Partial<DealCardOut> = {}) {
  if (!CHANDELIER || !ALEKSEY) throw new Error('fixtures');
  const backend = new JobsBackend().seedMine();
  const profile = new ProfileBackend();
  backend.media = profile.media;
  const deal = { ...dealCardFixture(CHANDELIER, ALEKSEY, 'client'), ...patch };
  backend.deals.set(deal.id, deal);
  server.use(...jobsHandlers(() => backend), ...profileHandlers(() => profile));
  return { backend, deal };
}

/** Спор клиента «Не пришёл»: ждёт ответа исполнителя до послезавтра. */
function openedDispute(dealId: string, patch: Partial<DealCardDisputeOut> = {}) {
  return {
    id: '0199df00-0000-7000-8000-0000000000d1',
    deal_id: dealId,
    deal_status: 'disputed',
    status: 'open',
    kind: 'no_show',
    opened_by_me: true,
    description: NO_SHOW,
    photos: [],
    respond_by: new Date(Date.parse(E2E_NOW) + 48 * 60 * 60 * 1000).toISOString(),
    response: null,
    response_photos: [],
    responded_at: null,
    unanswered_at: null,
    withdrawn_at: null,
    outcome: null,
    reason_code: null,
    resolved_at: null,
    created_at: E2E_NOW,
    ...patch,
  } satisfies DealCardDisputeOut;
}

/** Выбор файлов в системном диалоге: change у скрытого input[type=file]. */
async function choose(files: File[]) {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error('нет выбора файлов');
  await act(async () => {
    fireEvent.change(input, { target: { files } });
  });
}

describe('S26 «Есть проблема»', () => {
  it('opens S52 from the «Есть проблема» row of an agreed deal', async () => {
    const { deal } = withDeal();
    const { app, telegram } = startApp(`/deals/${deal.id}`);
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });
    // строкой внизу, рядом с «Отменить сделку», а не нативной кнопкой с первой минуты (№2)
    const problem = await screen.findByRole('button', { name: 'Есть проблема' });
    expect(telegram.callsOf('web_app_setup_secondary_button').at(-1)?.is_visible ?? false).toBe(
      false,
    );

    await act(async () => {
      fireEvent.click(problem);
    });

    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(`/deals/${deal.id}/dispute`),
    );
    expect(
      await screen.findByRole('heading', { name: 'Проблема со сделкой', level: 1 }),
    ).toBeTruthy();
  });
});

describe('S52 dispute', () => {
  it('sends the problem with a photo and shows that it waits for the answer', async () => {
    const { backend, deal } = withDeal();
    const { app, telegram } = startApp(`/deals/${deal.id}/dispute`);

    expect(
      await screen.findByRole('heading', { name: 'Проблема со сделкой', level: 1 }),
    ).toBeTruthy();
    expect(screen.getByText(/^Повесить люстру · Алексей Морозов · /)).toBeTruthy();
    expect(
      screen.getByText(
        'Алексей Морозов получит уведомление и 48 часов на ответ. Поддержка подключится, если не договоритесь.',
      ),
    ).toBeTruthy();
    const kinds = screen.getByRole('radiogroup', { name: 'Что случилось?' });
    expect(
      within(kinds)
        .getAllByRole('radio')
        .map((radio) => radio.textContent),
    ).toEqual([
      'Не пришёл',
      'Сделал плохо или не то',
      'Взял предоплату или просит больше',
      'Грубость или угрозы',
      'Другое',
    ]);
    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ text: 'Отправить' }));
    expect(mainButton(telegram)?.is_active).toBe(false);

    await click(within(kinds).getByRole('radio', { name: 'Не пришёл' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Опишите, что произошло' }), {
      target: { value: `  ${NO_SHOW}  ` },
    });
    await choose([new File(['jpeg'], 'door.jpg', { type: 'image/jpeg' })]);
    await waitFor(() => expect(mainButton(telegram)?.is_active).toBe(true));
    await pressMainButton(telegram);

    expect(await screen.findByText('Ждём ответа')).toBeTruthy();
    expect(backend.decisions).toEqual([{ id: deal.id, action: 'dispute', reason: 'no_show' }]);
    const mine = screen.getByRole('region', { name: 'Ваше сообщение' });
    expect(within(mine).getByText('Не пришёл')).toBeTruthy();
    expect(within(mine).getByText(NO_SHOW)).toBeTruthy();
    expect(within(mine).getByRole('img', { name: 'Фото 1' })).toBeTruthy();
    expect(screen.getByText(/^Алексей Морозов может ответить до /)).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)?.is_visible).toBe(false));
    // сделка — на паузе, а строка ведёт к спору
    await act(async () => {
      void app.router.navigate({ to: `/deals/${deal.id}` });
    });
    expect(await screen.findByText(/^Открыт спор: сделка на паузе/)).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Спор по сделке' })).toBeTruthy();
  });

  it('lets the other side answer once before the deadline', async () => {
    const { backend, deal } = withDeal({ status: 'disputed' });
    backend.deals.set(deal.id, { ...deal, dispute: openedDispute(deal.id) });
    backend.dealRole = 'performer';
    const { telegram } = startApp(`/deals/${deal.id}/dispute`);

    const theirs = await screen.findByRole('region', { name: 'Сообщение второй стороны' });
    expect(within(theirs).getByText(NO_SHOW)).toBeTruthy();
    expect(screen.getByText('Нужен ваш ответ')).toBeTruthy();
    expect(
      screen.getByText(/^Ответьте до .* — иначе поддержка решит без вашего ответа\.$/),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Отозвать спор/ })).toBeNull();
    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ text: 'Ответить' }));
    expect(mainButton(telegram)?.is_active).toBe(false);

    fireEvent.change(screen.getByRole('textbox', { name: 'Ваш ответ' }), {
      target: { value: 'Пробки на мосту, был в 20:10' },
    });
    await waitFor(() => expect(mainButton(telegram)?.is_active).toBe(true));
    await pressMainButton(telegram);

    expect(await screen.findByText('Есть ответ')).toBeTruthy();
    const answer = screen.getByRole('region', { name: 'Ваш ответ' });
    expect(within(answer).getByText('Пробки на мосту, был в 20:10')).toBeTruthy();
    expect(
      screen.getByText('Поддержка рассмотрит спор и сообщит решение обеим сторонам.'),
    ).toBeTruthy();
    expect(backend.decisions).toEqual([{ id: deal.id, action: 'respond' }]);
    await waitFor(() => expect(mainButton(telegram)?.is_visible).toBe(false));
  });

  it('gives Serbian dates with the month in the genitive', async () => {
    const { backend, deal } = withDeal({ status: 'disputed' });
    // спор открыт позавчера — дата словами, а не «danas»
    const opened = openedDispute(deal.id, { created_at: '2026-10-03T08:00:00Z' });
    backend.deals.set(deal.id, { ...deal, dispute: opened });
    backend.dealRole = 'performer';
    userBackend({ ...ME, ui_locale: 'sr-Latn' });
    startApp(`/deals/${deal.id}/dispute`, { languageCode: 'sr' });

    // срок — через 48 ч: Intl даёт «7. oktobar», после «do» нужен родительный падеж
    expect(
      await screen.findByText(
        'Odgovorite do 7. oktobra u 10:00 — u suprotnom će podrška odlučiti bez vašeg odgovora.',
      ),
    ).toBeTruthy();
    expect(screen.getByText('poslato 3. oktobra u 10:00')).toBeTruthy();
  });

  it('withdraws the dispute after a confirmation and the deal goes on', async () => {
    const { backend, deal } = withDeal({ status: 'disputed' });
    backend.deals.set(deal.id, { ...deal, dispute: openedDispute(deal.id) });
    const { app } = startApp(`/deals/${deal.id}/dispute`);

    await click(await screen.findByRole('button', { name: /Отозвать спор/ }));
    const sheet = await screen.findByRole('dialog', { name: 'Отозвать спор?' });
    await click(within(sheet).getByRole('button', { name: 'Отозвать' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe(`/deals/${deal.id}`));
    expect(backend.decisions).toEqual([{ id: deal.id, action: 'withdraw' }]);
    expect(backend.deals.get(deal.id)?.status).toBe('agreed');
    expect((await screen.findAllByText('Договорились')).length).toBeGreaterThan(0);
  });

  it('keeps the dispute with «Не отзывать»', async () => {
    const { backend, deal } = withDeal({ status: 'disputed' });
    backend.deals.set(deal.id, { ...deal, dispute: openedDispute(deal.id) });
    startApp(`/deals/${deal.id}/dispute`);

    await click(await screen.findByRole('button', { name: /Отозвать спор/ }));
    const sheet = await screen.findByRole('dialog', { name: 'Отозвать спор?' });
    // не «Отменить»: рядом с «Отозвать» было непонятно, что отменяется
    expect(within(sheet).queryByRole('button', { name: 'Отменить' })).toBeNull();
    await click(within(sheet).getByRole('button', { name: 'Не отзывать' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(backend.decisions).toEqual([]);
    expect(screen.getByRole('button', { name: /Отозвать спор/ })).toBeTruthy();
  });

  it('shows the decision of support with its reason', async () => {
    const { backend, deal } = withDeal({ status: 'cancelled', cancel_reason: 'dispute' });
    const resolved = openedDispute(deal.id, {
      status: 'resolved',
      deal_status: 'cancelled',
      outcome: 'cancelled',
      reason_code: 'no_show',
      resolved_at: E2E_NOW,
    });
    backend.deals.set(deal.id, { ...deal, dispute: resolved });
    const { app } = startApp(`/deals/${deal.id}/dispute`);

    expect(await screen.findByText('Решение принято')).toBeTruthy();
    expect(
      screen.getByText(
        'Поддержка рассмотрела спор и отменила сделку. Причина: встреча не состоялась.',
      ),
    ).toBeTruthy();
    await click(screen.getByRole('button', { name: 'К сделке' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(`/deals/${deal.id}`));
    expect(await screen.findByText('Сделку отменила поддержка по итогам спора.')).toBeTruthy();
  });

  it('explains that a dispute needs a deal in progress', async () => {
    const { deal } = withDeal({ status: 'completed' });
    const { telegram } = startApp(`/deals/${deal.id}/dispute`);

    expect(
      await screen.findByRole('heading', {
        name: 'Спор можно открыть только по текущей сделке',
        level: 1,
      }),
    ).toBeTruthy();
    expect(screen.queryByRole('radiogroup')).toBeNull();
    expect(mainButton(telegram)?.is_visible ?? false).toBe(false);
  });
});
