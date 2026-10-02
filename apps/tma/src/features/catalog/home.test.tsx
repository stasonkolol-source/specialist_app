// Главная S03 (DEVELOPMENT_PLAN 4.8) на MSW: заголовок и чип города, плитки разделов → выдача
// раздела, «Все услуги» → S04, подсказки при вводе → выдача категории, Enter → выдача по тексту,
// «Свободны сегодня рядом» и «Все» с точкой клиента после нажатия на чип, «Вещи» — заглушка S58.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { startApp } from '../../testing/app.tsx';
import { CATEGORY_IDS } from '../../testing/fixtures.ts';

const HOME = 'Найдём мастера рядом';

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

afterEach(() => setSession(null));

describe('S03 home', () => {
  it('shows the city, the sections and who is free today', async () => {
    startApp('/');

    expect(await screen.findByRole('heading', { name: HOME, level: 1 })).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Нови-Сад' })).toBeTruthy();
    const sections = within(screen.getByRole('region', { name: 'Что нужно сделать?' }));
    expect((await sections.findAllByRole('link')).map((tile) => tile.textContent?.trim())).toEqual([
      'Мастер на час',
      'Бьюти',
      'Уборка',
      'Переезды',
      'Репетиторы',
      'Все услуги',
    ]);
    const today = within(await screen.findByRole('region', { name: 'Свободны сегодня рядом' }));
    expect(today.getByText('Алексей Морозов')).toBeTruthy();
  });

  it('opens the results of a section and the whole catalog', async () => {
    const { app } = startApp('/');

    await click(await screen.findByRole('link', { name: /Уборка/ }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog/results'));
    expect(app.router.state.location.search).toEqual({ category: CATEGORY_IDS['cleaning'] });
    await act(async () => {
      app.router.history.back();
    });
    await click(await screen.findByRole('link', { name: /Все услуги/ }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog'));
  });

  it('suggests categories while typing and searches the text on Enter', async () => {
    const { app } = startApp('/');
    const field = await screen.findByRole('searchbox', { name: 'Поиск услуг и специалистов' });

    await act(async () => {
      fireEvent.change(field, { target: { value: 'элек' } });
    });
    const suggestions = within(await screen.findByRole('navigation', { name: 'Подсказки' }));
    await click(suggestions.getByRole('button', { name: /Электрика/ }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog/results'));
    expect(app.router.state.location.search).toEqual({ category: CATEGORY_IDS['electrical'] });

    await act(async () => {
      await app.router.navigate({ to: '/' });
    });
    const again = await screen.findByRole('searchbox', { name: 'Поиск услуг и специалистов' });
    await act(async () => {
      fireEvent.change(again, { target: { value: 'люстра' } });
      fireEvent.submit(again.closest('form') as HTMLFormElement);
    });
    await waitFor(() => expect(app.router.state.location.search).toEqual({ q: 'люстра' }));
  });

  it('finds the district by location and opens who is free today nearby', async () => {
    const { app } = startApp('/');

    await click(await screen.findByRole('button', { name: 'Нови-Сад' }));

    expect(await screen.findByRole('button', { name: 'Нови-Сад · Лиман' })).toBeTruthy();
    const today = within(screen.getByRole('region', { name: 'Свободны сегодня рядом' }));
    await click(today.getByRole('link', { name: 'Все' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog/results'));
    expect(app.router.state.location.search).toEqual({
      today: true,
      sort: 'distance',
      lat: 45.267,
      lon: 19.834,
    });
  });

  it('shows the goods stub in the second segment', async () => {
    startApp('/');

    await click(await screen.findByRole('radio', { name: 'Вещи' }));

    expect(await screen.findByRole('heading', { name: 'Вещи — скоро', level: 1 })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: HOME })).toBeNull();
  });
});
