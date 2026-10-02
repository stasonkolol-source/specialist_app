// Каталог S04–S06 (DEVELOPMENT_PLAN 4.4) на MSW, как backend 4.2: дерево с числом специалистов,
// выдача с карточками, «Возможно, вы имели в виду», пустая выдача, шторка фильтров с «Показать N»,
// фильтры в адресе переживают «Назад», гость видит каталог без входа.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { mainButton, pressBackButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { CATEGORY_IDS, NOBODY_QUERY, TYPO_QUERY } from '../../testing/fixtures.ts';
import { server } from '../../testing/msw.ts';

afterEach(() => setSession(null));

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

describe('S04 categories', () => {
  it('shows the tree with specialist counts and opens a subcategory in the results', async () => {
    const { app } = startApp('/catalog');

    expect(await screen.findByRole('heading', { name: 'Все услуги', level: 1 })).toBeTruthy();
    const handyman = await screen.findByRole('button', { name: /Мастер на час/ });
    expect(handyman.getAttribute('aria-expanded')).toBe('false');
    expect(await within(handyman).findByLabelText('12 специалистов')).toBeTruthy();

    await click(handyman);

    expect(handyman.getAttribute('aria-expanded')).toBe('true');
    const electrical = screen.getByRole('link', { name: /Электрика/ });
    expect(within(electrical).getByLabelText('5 специалистов')).toBeTruthy();
    await click(electrical);
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog/results'));
    expect(app.router.state.location.search).toEqual({ category: CATEGORY_IDS['electrical'] });
  });
});

describe('S05 results', () => {
  it('shows ready cards: rating, place and languages, facts and price', async () => {
    startApp('/catalog/results');

    const first = (await screen.findByText('Алексей Морозов')).closest('article');
    expect(first).toBeTruthy();
    const card = within(first as HTMLElement);
    expect(card.getByText('4,9')).toBeTruthy();
    expect(card.getByText('(37)')).toBeTruthy();
    expect(card.getByText(/^Лиман, ≈\s1,5\sкм$/u)).toBeTruthy();
    expect(card.getByText('ru, sr')).toBeTruthy();
    expect(card.getByText(/^Сегодня до /)).toBeTruthy();
    expect(card.getByText('Телефон подтверждён')).toBeTruthy();
    expect(card.getByText(/^от 2\s000\sRSD$/u)).toBeTruthy();
    const newcomer = (await screen.findByText('Иван Гаврилов')).closest('article');
    expect(within(newcomer as HTMLElement).getByText('Новый специалист')).toBeTruthy();
    expect(await screen.findByText('9 специалистов')).toBeTruthy();
  });

  it('shows the corrected word for a misspelled query', async () => {
    startApp(`/catalog/results?q=${TYPO_QUERY}`);

    expect(await screen.findByText('Возможно, вы имели в виду «Električar»')).toBeTruthy();
  });

  it('suggests relaxing filters when nothing is found and resets them', async () => {
    const { app } = startApp(`/catalog/results?q=${encodeURIComponent(NOBODY_QUERY)}&today=true`);

    expect(await screen.findByRole('heading', { name: 'Никого не нашли' })).toBeTruthy();
    expect(screen.getByText('Ослабьте фильтры — например, уберите район или цену')).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Сбросить фильтры' }));

    await waitFor(() => expect(app.router.state.location.search).toEqual({ q: NOBODY_QUERY }));
  });

  it('keeps filters in the address: they survive going back', async () => {
    const { app } = startApp('/catalog/results?today=true');
    expect(await screen.findByText('Алексей Морозов')).toBeTruthy();

    await act(async () => {
      await app.router.navigate({ to: '/catalog' });
    });
    await act(async () => {
      app.router.history.back();
    });

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/catalog/results'));
    expect(app.router.state.location.search).toEqual({ today: true });
    expect(screen.getByRole('button', { name: 'Свободен сегодня', pressed: true })).toBeTruthy();
  });

  it('works for a guest without signing in', async () => {
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
  });
});

describe('S06 filters', () => {
  it('counts on the MainButton and applies the draft to the address', async () => {
    const { app, telegram } = startApp('/catalog/results');
    await screen.findByText('Алексей Морозов');

    await click(screen.getByRole('button', { name: /Фильтры/ }));

    const sheet = screen.getByRole('dialog', { name: 'Фильтры' });
    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({ text: 'Показать 9 специалистов' }),
    );
    await click(within(sheet).getByRole('button', { name: 'Сербский' }));
    // счёт ждёт, пока человек перестанет нажимать (400 мс), и спрашивает сервер
    await waitFor(
      () => expect(mainButton(telegram)).toMatchObject({ text: 'Показать 3 специалиста' }),
      { timeout: 3000 },
    );
    await pressMainButton(telegram);

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(app.router.state.location.search).toEqual({ langs: ['sr'] });
    expect(await screen.findByText('3 специалиста')).toBeTruthy();
  });

  it('closes on Back without applying the draft', async () => {
    const { app, telegram } = startApp('/catalog/results');
    await screen.findByText('Алексей Морозов');
    await click(screen.getByRole('button', { name: /Фильтры/ }));
    await click(screen.getByRole('switch', { name: 'Свободен сегодня' }));

    await pressBackButton(telegram);

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(app.router.state.location.pathname).toBe('/catalog/results');
    expect(app.router.state.location.search).toEqual({});
  });

  it('picks a category in the second view of the sheet', async () => {
    const { app, telegram } = startApp('/catalog/results');
    await screen.findByText('Алексей Морозов');
    await click(screen.getByRole('button', { name: /Фильтры/ }));

    await click(screen.getByRole('button', { name: /Категория/ }));
    await click(screen.getByRole('button', { name: 'Уборка' }));
    expect(screen.getByRole('button', { name: /Категория/ }).textContent).toContain('Уборка');
    await pressMainButton(telegram);

    await waitFor(() =>
      expect(app.router.state.location.search).toEqual({ category: CATEGORY_IDS['cleaning'] }),
    );
  });
});
