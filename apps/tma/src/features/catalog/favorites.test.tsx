// Отзывы S11 и избранное S12 (DEVELOPMENT_PLAN 4.6) на MSW: сводка рейтинга и отзывы, «Отзывов
// пока нет», сердечко на S05 и S08 — один список с S12, убрать из S12, пустой список, гость без
// сердечек, вход в S12 из профиля S31.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { pressBackButton, startApp } from '../../testing/app.tsx';
import { CARD_PROFILE_ID, cardsFor } from '../../testing/fixtures.ts';
import { FavoritesBackend } from '../../testing/favoritesBackend.ts';
import { favoritesHandlers, server } from '../../testing/msw.ts';

const PROFILE = `/specialists/${CARD_PROFILE_ID}`;
const [ALEXEY, MARIA] = cardsFor('ru').map((card) => card.profile_id);

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

/** Избранное с памятью на время теста. */
function savedFavorites(...ids: (string | undefined)[]) {
  const backend = new FavoritesBackend(ids.filter((id) => id !== undefined));
  server.use(...favoritesHandlers(() => backend));
  return backend;
}

afterEach(() => setSession(null));

describe('S11 reviews', () => {
  it('opens from the profile with the rating summary and deal reviews', async () => {
    const { app } = startApp(PROFILE);
    const reviews = within(await screen.findByRole('region', { name: 'Отзывы' }));
    expect(reviews.getByText('Ирина С.')).toBeTruthy();
    // на S08 вкладок нет — отзыв помечен, что он по сделке
    expect(reviews.getByText('Сделка в «Соседях»')).toBeTruthy();

    await click(reviews.getByRole('link', { name: 'Все 37' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe(`${PROFILE}/reviews`));
    // шапка — сразу из профиля S08 в кэше, сводка — когда придут отзывы
    expect(await screen.findByRole('heading', { name: 'Отзывы', level: 1 })).toBeTruthy();
    expect(screen.getByText('Алексей Морозов · Электрика')).toBeTruthy();
    expect(await screen.findByRole('img', { name: 'Средняя оценка 4,9 из 5' })).toBeTruthy();
    expect(screen.getByRole('progressbar', { name: '5 звёзд: 35' })).toBeTruthy();
    // критерий: подпись и среднее рядом
    expect(screen.getByText('Вовремя').nextSibling?.textContent).toBe('4,8');
    expect(screen.getByText('Общение').nextSibling?.textContent).toBe('5,0');
    const cards = screen.getAllByRole('article');
    expect(cards).toHaveLength(3);
    // под именем — звёзды с месяцем, услуга — своей строкой
    const pavel = within(cards[1] as HTMLElement);
    expect(pavel.getByText('Август')).toBeTruthy();
    expect(pavel.getByText('Электрика')).toBeTruthy();
    expect(
      within(cards[2] as HTMLElement).getByRole('img', { name: 'Оценка 4 из 5' }),
    ).toBeTruthy();
    // вкладка «По сделкам · 37» уже говорит, что отзывы по сделкам: метки на карточках нет
    expect(screen.queryByText('Сделка в «Соседях»')).toBeNull();
  });

  it('says a new specialist has no reviews yet', async () => {
    startApp(`/specialists/${MARIA}/reviews`);

    expect(await screen.findByRole('heading', { name: 'Отзывов пока нет' })).toBeTruthy();
    expect(screen.queryByRole('article')).toBeNull();
  });
});

describe('S12 favorites', () => {
  it('saves from the results with a heart and shows it in the list', async () => {
    const backend = savedFavorites();
    const { app } = startApp('/catalog/results');

    const heart = await screen.findByRole('button', { name: 'В избранное: Мария Ковалёва' });
    await click(heart);

    expect(
      await screen.findByRole('button', { name: 'Убрать из избранного: Мария Ковалёва' }),
    ).toBeTruthy();
    await waitFor(() => expect(backend.ids).toEqual([MARIA]));
    await act(async () => {
      await app.router.navigate({ to: '/favorites' });
    });
    expect(await screen.findByRole('heading', { name: 'Избранное', level: 1 })).toBeTruthy();
    expect(await screen.findByText('Мария Ковалёва')).toBeTruthy();
    expect(screen.queryByText('Алексей Морозов')).toBeNull();
  });

  it('keeps the profile heart and the list in step, and removes from the list at once', async () => {
    const backend = savedFavorites(MARIA);
    const { app } = startApp(PROFILE);
    await click(await screen.findByRole('button', { name: 'Добавить в избранное' }));
    expect(await screen.findByRole('button', { name: 'Убрать из избранного' })).toBeTruthy();
    await waitFor(() => expect(backend.ids).toEqual([ALEXEY, MARIA]));

    await act(async () => {
      await app.router.navigate({ to: '/favorites' });
    });
    const names = async () =>
      (await screen.findAllByRole('article')).map(
        (card) => within(card).getAllByText(/Морозов|Ковалёва/)[0]?.textContent,
      );
    expect(await names()).toEqual(['Алексей Морозов', 'Мария Ковалёва']);
    await click(screen.getByRole('button', { name: 'Убрать из избранного: Алексей Морозов' }));

    await waitFor(() => expect(screen.queryByText('Алексей Морозов')).toBeNull());
    await waitFor(() => expect(backend.ids).toEqual([MARIA]));
  });

  it('suggests finding someone when the list is empty', async () => {
    savedFavorites();
    const { app } = startApp('/favorites');

    expect(await screen.findByRole('heading', { name: 'Здесь будут ваши мастера' })).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Найти специалиста' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog'));
  });

  it('opens from the profile S31 and goes back there', async () => {
    savedFavorites(MARIA);
    const { app, telegram } = startApp('/profile');

    await click(await screen.findByRole('link', { name: 'Избранное' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/favorites'));
    expect(await screen.findByText('Мария Ковалёва')).toBeTruthy();
    await pressBackButton(telegram);
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/profile'));
  });

  it('shows no hearts to a guest', async () => {
    server.use(
      http.post('*/api/v1/auth/telegram', () =>
        HttpResponse.json(
          { type: 'x', title: 'Unauthorized', status: 401, code: 'not_authenticated' },
          { status: 401 },
        ),
      ),
    );
    startApp('/catalog/results');

    expect(await screen.findByText('Алексей Морозов')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /В избранное/ })).toBeNull();
  });
});
