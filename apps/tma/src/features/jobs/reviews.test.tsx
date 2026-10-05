// Отзывы в Mini App (DEVELOPMENT_PLAN 7.3) на фейке backend: завершённая сделка S26 — шаг «Отзыв»,
// «Отзыв можно оставить до …» и MainButton «Оставить отзыв»; S27 — звёзды с подписью, «Что
// понравилось?», текст, «Опубликовать отзыв» — отзыв ждёт проверки, сделка показывает его статус;
// второй раз — «Вы уже оставили отзыв». S28 — сделки «Активные» / «Завершённые» с отзывом или
// «Оставить отзыв»; отзывы «Обо мне» с ответом из шторки; строка «Сделки и отзывы» в S31.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressMainButton, startApp, userBackend } from '../../testing/app.tsx';
import { E2E_NOW, ME } from '../../testing/fixtures.ts';
import {
  JobsBackend,
  completedDealFixture,
  dealCardFixture,
  myJobsFixture,
  receivedReviewFixture,
  responseCardsFixture,
} from '../../testing/jobsBackend.ts';
import { jobsHandlers, server } from '../../testing/msw.ts';

const [CHANDELIER] = myJobsFixture();
const [ALEKSEY] = responseCardsFixture();

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

function withCompleted() {
  if (!CHANDELIER || !ALEKSEY) throw new Error('fixtures');
  const backend = new JobsBackend().seedMine();
  const deal = completedDealFixture(CHANDELIER, ALEKSEY);
  backend.deals.set(deal.id, deal);
  server.use(...jobsHandlers(() => backend));
  return { backend, deal };
}

describe('S26 and S27 review', () => {
  it('leaves a review from the completed deal and shows it waits for the check', async () => {
    const { backend, deal } = withCompleted();
    const { app, telegram } = startApp(`/deals/${deal.id}`);

    expect(await screen.findByText(/^Отзыв можно оставить до/)).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Оставить отзыв'));
    await pressMainButton(telegram);
    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(`/deals/${deal.id}/review`),
    );

    expect(await screen.findByRole('heading', { name: 'Как всё прошло?', level: 1 })).toBeTruthy();
    expect(screen.getByText('Алексей Морозов')).toBeTruthy();
    // фото к отзыву — v1: строка «скоро», без плитки, похожей на загрузку
    expect(screen.getByText('Фото к отзыву — скоро')).toBeTruthy();
    expect(screen.queryByText('Фото')).toBeNull();
    await waitFor(() => expect(mainButton(telegram)?.is_active).toBe(false));
    await click(screen.getByRole('radio', { name: '4 звезды' }));
    expect(screen.getByText('Хорошо')).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Качество' }));
    await click(screen.getByRole('button', { name: 'Пунктуальность' }));
    await click(screen.getByRole('button', { name: 'Пунктуальность' })); // передумал
    fireEvent.change(screen.getByRole('textbox', { name: 'Отзыв' }), {
      target: { value: '  Повесил аккуратно  ' },
    });
    await waitFor(() => expect(mainButton(telegram)?.is_active).toBe(true));
    await pressMainButton(telegram);

    await waitFor(() =>
      expect(backend.reviews.get(deal.id)).toMatchObject({
        rating: 4,
        criteria: { quality: 4 },
        body: 'Повесил аккуратно',
      }),
    );
    expect(await screen.findByText('Спасибо! Отзыв появится после проверки.')).toBeTruthy();
    await click(screen.getByRole('button', { name: 'К сделке' }));
    expect(await screen.findByText('Ваш отзыв на проверке')).toBeTruthy();
  });

  it('speaks Serbian: dates in the genitive, «Naruči ponovo» as in the chat', async () => {
    const { deal } = withCompleted();
    userBackend({ ...ME, ui_locale: 'sr-Latn' });
    startApp(`/deals/${deal.id}`, { languageCode: 'sr' });

    // Intl даёт «19. oktobar»; после «do» и в значении «когда» нужен родительный падеж
    expect(await screen.findByText('Utisak možete ostaviti do 19. oktobra')).toBeTruthy();
    expect(screen.getByText('Dogovor je završen 5. oktobra. Hvala!')).toBeTruthy();
    // «Заказать снова» — как в шапке диалога S30: коротко, на «ты»
    expect(screen.getByRole('button', { name: 'Naruči ponovo' })).toBeTruthy();
  });

  it('explains that the review is already left', async () => {
    const { backend, deal } = withCompleted();
    backend.deals.set(deal.id, {
      ...deal,
      my_review: { id: 'r1', status: 'published', rating: 5 },
      review_until: null,
    });
    startApp(`/deals/${deal.id}/review`);

    expect(
      await screen.findByRole('heading', { name: 'Вы уже оставили отзыв по этой сделке.' }),
    ).toBeTruthy();
  });

  it('does not offer a review before the work is done', async () => {
    if (!CHANDELIER || !ALEKSEY) throw new Error('fixtures');
    const backend = new JobsBackend().seedMine();
    const deal = dealCardFixture(CHANDELIER, ALEKSEY, 'client');
    backend.deals.set(deal.id, deal);
    server.use(...jobsHandlers(() => backend));
    startApp(`/deals/${deal.id}/review`);

    expect(
      await screen.findByRole('heading', {
        name: 'Отзыв можно оставить, когда работа будет выполнена.',
      }),
    ).toBeTruthy();
  });
});

describe('S28 deals and reviews', () => {
  it('groups deals and leads to a review from a finished one', async () => {
    const { backend, deal } = withCompleted();
    if (!CHANDELIER || !ALEKSEY) throw new Error('fixtures');
    const active = dealCardFixture(
      CHANDELIER,
      { ...ALEKSEY, id: `${ALEKSEY.id.slice(0, -1)}9` },
      'client',
    );
    backend.deals.set(active.id, active);
    const { app } = startApp('/profile');

    await click(await screen.findByRole('link', { name: 'Сделки и отзывы' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/deals'));
    const finished = await screen.findByRole('heading', { name: 'Завершённые' });
    expect(screen.getByRole('heading', { name: 'Активные' })).toBeTruthy();
    const card = within(finished.parentElement as HTMLElement).getByRole('article', {
      name: 'Повесить люстру',
    });
    expect(within(card).getByText('Отзыва пока нет')).toBeTruthy();
    // имя и дата — отдельными частями строки: при переносе «·» не повисает после имени
    expect(within(card).getByText('Алексей Морозов')).toBeTruthy();
    await click(within(card).getByRole('button', { name: 'Оставить отзыв' }));

    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(`/deals/${deal.id}/review`),
    );
  });

  it('answers a review about me once', async () => {
    const { backend } = withCompleted();
    backend.received.push(receivedReviewFixture());
    startApp('/deals?tab=reviews');

    const review = await screen.findByRole('article', { name: 'Елена К.' });
    expect(within(review).getByText('Всё собрал быстро и аккуратно')).toBeTruthy();
    await click(within(review).getByRole('button', { name: 'Ответить' }));
    const sheet = await screen.findByRole('dialog', { name: 'Ответ на отзыв' });
    fireEvent.change(within(sheet).getByRole('textbox', { name: 'Ответ на отзыв' }), {
      target: { value: 'Спасибо!' },
    });
    await click(within(sheet).getByRole('button', { name: 'Отправить ответ' }));

    await waitFor(() =>
      expect(backend.replies).toEqual([{ reviewId: receivedReviewFixture().id, body: 'Спасибо!' }]),
    );
    const answered = await screen.findByRole('article', { name: 'Елена К.' });
    expect(await within(answered).findByText(/Ответ на проверке/)).toBeTruthy();
    expect(within(answered).queryByRole('button', { name: 'Ответить' })).toBeNull();
  });
});
