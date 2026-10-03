// Карточка специалиста S08–S11 (DEVELOPMENT_PLAN 4.5, 7.3) на MSW, как BFF: профиль одним
// запросом, переход из выдачи и по ссылке `s_`, «Профиль недоступен» для скрытого, прайс по
// группам, просмотрщик работ на тёмном фоне со свайпом и миниатюрами, «Назад» закрывает его
// целиком; отзывы S11 с ответом специалиста и «Показать ещё».
import type { CardReviewOut, CardReviewsOut } from '@sosed/api-client';
import { encodeStartParam } from '@sosed/links';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { backButtonVisible, mainButton, pressBackButton, startApp } from '../../testing/app.tsx';
import { CARD_PROFILE_ID, CARD_WORKS, HIDDEN_PROFILE_ID } from '../../testing/fixtures.ts';
import { server } from '../../testing/msw.ts';

const PROFILE = `/specialists/${CARD_PROFILE_ID}`;

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

/** Пути запросов к API за время теста. */
function recordRequests() {
  const paths: string[] = [];
  const listener = ({ request }: { request: Request }) => {
    paths.push(new URL(request.url).pathname);
  };
  server.events.on('request:start', listener);
  return {
    paths,
    stop: () => server.events.removeListener('request:start', listener),
  };
}

afterEach(() => {
  server.events.removeAllListeners();
});

describe('S08 profile', () => {
  it('shows the card from one BFF request: header, badges, memo, prices, works, about', async () => {
    const requests = recordRequests();
    const { telegram } = startApp(PROFILE);

    expect(await screen.findByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeTruthy();
    expect(screen.getByText('Электрик · мелкий ремонт · люстры')).toBeTruthy();
    expect(screen.getByText('4,9')).toBeTruthy();
    expect(screen.getByText('37 отзывов')).toBeTruthy();
    expect(screen.getByText('Лиман')).toBeTruthy();
    expect(screen.getByText('Телефон подтверждён')).toBeTruthy();
    expect(screen.getByText(/^Сегодня до /)).toBeTruthy();
    expect(screen.getByText(/Не вносите предоплату незнакомым исполнителям/)).toBeTruthy();

    const prices = within(screen.getByRole('region', { name: 'Цены' }));
    expect(prices.getByText('Установка люстры')).toBeTruthy();
    expect(prices.getByText(/^от 2\s500\sRSD$/u)).toBeTruthy();
    expect(prices.getByRole('link', { name: 'Весь прайс · 9' })).toBeTruthy();
    const works = within(screen.getByRole('region', { name: 'Работы' }));
    expect(works.getByRole('link', { name: 'Все · 18' })).toBeTruthy();
    expect(works.getByRole('link', { name: 'Видео: Подсветка кухни' })).toBeTruthy();
    expect(works.getAllByRole('link')).toHaveLength(4);
    const about = within(screen.getByRole('region', { name: 'О себе' }));
    expect(about.getByText(/^Электрик, 12 лет опыта/)).toBeTruthy();
    expect(about.getByText('Русский, сербский')).toBeTruthy();
    expect(about.getByText('Выезд: Лиман, Грбавица, Центр, Нова Детелинара')).toBeTruthy();
    expect(about.getByText('Обычно отвечает за 15 минут')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Предложить заявку' })).toBeTruthy();

    // «Написать» (6.4) — диалог со специалистом
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Написать'));
    expect(requests.paths.filter((path) => path.startsWith('/api/v1/specialists'))).toEqual([
      `/api/v1${PROFILE}`,
    ]);
    requests.stop();
  });

  it('opens from a card in the results and goes back to them', async () => {
    const { app, telegram } = startApp('/catalog/results');

    await click(await screen.findByRole('link', { name: /Алексей Морозов/ }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe(PROFILE));
    expect(await screen.findByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeTruthy();
    await pressBackButton(telegram);
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog/results'));
  });

  it('opens from an `s_` link; Back leads home', async () => {
    const startParam = encodeStartParam({ type: 'specialist', id: CARD_PROFILE_ID });
    const { app, telegram } = startApp('/', { startParam });

    await waitFor(() => expect(app.router.state.location.pathname).toBe(PROFILE));
    expect(await screen.findByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeTruthy();
    expect(backButtonVisible(telegram)).toBe(true);
    await pressBackButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/'));
  });

  it('says the profile is unavailable when it is hidden and leads to other specialists', async () => {
    const { app } = startApp(`/specialists/${HIDDEN_PROFILE_ID}`);

    expect(await screen.findByRole('heading', { name: 'Профиль недоступен' })).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Найти другого специалиста' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog'));
  });
});

describe('S09 prices', () => {
  it('groups the whole price list by category with duration, unit and amount', async () => {
    const { app } = startApp(PROFILE);
    await click(await screen.findByRole('link', { name: 'Весь прайс · 9' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe(`${PROFILE}/services`));
    expect(await screen.findByRole('heading', { name: 'Прайс', level: 1 })).toBeTruthy();
    expect(screen.getByText('Алексей Морозов · 9 услуг')).toBeTruthy();
    expect(screen.getByText(/^Цены ориентировочные/)).toBeTruthy();
    const groups = screen.getAllByRole('region');
    expect(groups.map((group) => group.textContent)).toEqual([
      expect.stringMatching(/^Мастер на час/),
      expect.stringMatching(/^Люстры и карнизы/),
      expect.stringMatching(/^Электрика/),
    ]);
    const first = within(groups[0] as HTMLElement);
    expect(first.getByText('до 1 часа · за визит')).toBeTruthy();
    expect(first.getByText('за час')).toBeTruthy();
    expect(first.getByText('Мелкий ремонт')).toBeTruthy();
    expect(within(groups[2] as HTMLElement).getByText(/^от 400\sRSD$/u)).toBeTruthy();
  });
});

describe('S10 portfolio viewer', () => {
  it('opens the tapped work dark, swipes and jumps by thumbnails, Back closes it whole', async () => {
    const { app, telegram } = startApp(PROFILE);
    await click(await screen.findByRole('link', { name: 'Люстра, Лиман' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe(`${PROFILE}/portfolio`));
    expect(await screen.findByText('1 / 18')).toBeTruthy();
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(telegram.callsOf('web_app_setup_swipe_behavior').at(-1)).toEqual({
      allow_vertical_swipe: false,
    });
    expect(screen.queryByRole('button', { name: 'Предыдущая работа' })).toBeNull();

    // свайп влево — следующая работа; открытая работа — в адресе, история не растёт
    const photo = screen.getByRole('img', { name: 'Люстра, Лиман' });
    await act(async () => {
      fireEvent.pointerDown(photo, { clientX: 300, clientY: 200 });
      fireEvent.pointerUp(photo, { clientX: 120, clientY: 210 });
    });
    expect(await screen.findByText('2 / 18')).toBeTruthy();
    expect(app.router.state.location.search).toEqual({ work: CARD_WORKS[1]?.id });

    const thumbs = within(screen.getByRole('group', { name: 'Другие работы' }));
    expect(thumbs.getByRole('button', { name: 'Работа 2 из 18, открыта' })).toBeTruthy();
    await click(thumbs.getByRole('button', { name: 'Ещё 14 работ' }));
    expect(await screen.findByText('5 / 18')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Работа 5 из 18, открыта' })).toBeTruthy();

    await pressBackButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(PROFILE));
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(telegram.callsOf('web_app_setup_swipe_behavior').at(-1)).toEqual({
      allow_vertical_swipe: true,
    });
  });

  it('pages with the arrow buttons and the keyboard', async () => {
    startApp(`${PROFILE}/portfolio?work=${CARD_WORKS[3]?.id}`);

    expect(await screen.findByText('4 / 18')).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Предыдущая работа' }));
    expect(await screen.findByText('3 / 18')).toBeTruthy();
    await act(async () => {
      fireEvent.keyDown(window, { key: 'ArrowRight' });
    });
    expect(await screen.findByText('4 / 18')).toBeTruthy();
  });
});

describe('S11 reviews', () => {
  const review = (n: number, reply: CardReviewOut['reply'] = null): CardReviewOut => ({
    id: `0199ee00-0000-7000-8000-0000000001${String(n).padStart(2, '0')}`,
    kind: 'deal',
    author_name: `Клиент ${n}`,
    rating: 5,
    criteria: {},
    body: `Отзыв номер ${n}`,
    category: null,
    published_at: '2026-09-20T12:00:00Z',
    reply,
  });
  const summary: CardReviewsOut['summary'] = {
    rating: 4.9,
    count: 21,
    is_new: false,
    distribution: [0, 0, 0, 1, 20],
    criteria: {},
  };

  it('shows the specialist reply and loads more reviews', async () => {
    server.use(
      http.get(/\/api\/v1\/specialists\/[^/]+\/reviews$/, ({ request }) => {
        const more = new URL(request.url).searchParams.get('cursor') === 'p2';
        const page: CardReviewsOut = more
          ? { summary, items: [review(21)], next_cursor: null }
          : {
              summary,
              items: [
                review(1, { body: 'Спасибо, рад был помочь!', at: '2026-09-21T09:00:00Z' }),
                review(2),
              ],
              next_cursor: 'p2',
            };
        return HttpResponse.json(page);
      }),
    );
    startApp(`${PROFILE}/reviews`);

    const first = await screen.findByText('Отзыв номер 1');
    const card = first.closest('article') as HTMLElement;
    expect(within(card).getByText('Ответ специалиста')).toBeTruthy();
    expect(within(card).getByText('Спасибо, рад был помочь!')).toBeTruthy();
    expect(screen.queryByText('Отзыв номер 21')).toBeNull();
    await click(screen.getByRole('button', { name: 'Показать ещё' }));

    expect(await screen.findByText('Отзыв номер 21')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Показать ещё' })).toBeNull();
  });
});
