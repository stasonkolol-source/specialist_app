// Прайс S35 и позиция S36 (DEVELOPMENT_PLAN 2.11) на фейке backend кабинета: группы по категориям
// профиля, «…» — порядок и «скрыть», новая позиция, правка только изменённого, удаление.
import type { ServiceOut } from '@sosed/api-client';
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { CATEGORY_IDS, PROFILE_FILLED } from '../../testing/fixtures.ts';
import { profileHandlers, server } from '../../testing/msw.ts';
import { ProfileBackend } from '../../testing/profileBackend.ts';

afterEach(() => setSession(null));

const ELECTRICAL = CATEGORY_IDS['electrical'] ?? 0;
const CHANDELIERS = CATEGORY_IDS['chandeliers'] ?? 0;

const item = (
  id: string,
  title: string,
  position: number,
  extra: Partial<ServiceOut> = {},
): ServiceOut => ({
  id: `0199bb00-0000-7000-8000-00000000030${id}`,
  title,
  description: null,
  category_id: ELECTRICAL,
  price_type: 'fixed',
  price_min: { amount: 200_000, currency: 'RSD' },
  price_max: null,
  unit: null,
  duration_min: null,
  position,
  is_active: true,
  ...extra,
});

/** Прайс артборда S35: электрика и люстры с карнизами. */
const PRICE_LIST = [
  item('1', 'Выезд и диагностика', 0),
  item('2', 'Мастер на час', 1, { price_type: 'hourly', unit: 'hour' }),
  item('3', 'Установка люстры', 2, {
    category_id: CHANDELIERS,
    price_type: 'from',
    price_min: { amount: 250_000, currency: 'RSD' },
    duration_min: 120,
  }),
  item('4', 'Бра или светильник', 3, {
    category_id: CHANDELIERS,
    price_min: { amount: 120_000, currency: 'RSD' },
    is_active: false,
  }),
];

const PUBLISHED = { ...PROFILE_FILLED, status: 'published' as const };

function withBackend(services: ServiceOut[] = PRICE_LIST): ProfileBackend {
  const backend = new ProfileBackend(PUBLISHED, services);
  server.use(...profileHandlers(() => backend));
  return backend;
}

const writes = (backend: ProfileBackend) =>
  backend.log.filter((entry) => !entry.request.startsWith('GET'));

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

describe('S35 price list', () => {
  it('groups items by the profile categories with their price kind and duration', async () => {
    withBackend();
    const { app, telegram } = startApp('/cabinet/prices');

    const electrical = await screen.findByRole('region', { name: 'Электрика' });
    expect(screen.getByText('4 позиции · порядок — в меню «…»')).toBeTruthy();
    expect(within(electrical).getByRole('link', { name: /Мастер на час/ }).textContent).toContain(
      'за час',
    );
    const chandeliers = screen.getByRole('region', { name: 'Люстры и карнизы' });
    expect(within(chandeliers).getByText('от · 1–2 часа')).toBeTruthy();
    // разряды и валюта — через неразрывные пробелы Intl
    expect(within(chandeliers).getByText(/^от 2\s500\sRSD$/u)).toBeTruthy();
    expect(within(chandeliers).getByText('Скрыта')).toBeTruthy();

    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ text: 'Добавить позицию' }));
    await pressMainButton(telegram);
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet/prices/new'));
  });

  it('moves an item down within its group from the «…» menu', async () => {
    const backend = withBackend();
    startApp('/cabinet/prices', { popupAnswer: 'down' });

    await click(await screen.findByRole('button', { name: 'Действия: Выезд и диагностика' }));

    await waitFor(() => expect(writes(backend)).toHaveLength(1));
    expect(writes(backend)[0]).toEqual({
      request: 'PUT /me/profile/services/order',
      body: {
        service_ids: [PRICE_LIST[1]?.id, PRICE_LIST[0]?.id, PRICE_LIST[2]?.id, PRICE_LIST[3]?.id],
      },
    });
  });

  it('hides an item from the «…» menu', async () => {
    const backend = withBackend();
    startApp('/cabinet/prices', { popupAnswer: 'toggle' });

    await click(await screen.findByRole('button', { name: 'Действия: Мастер на час' }));

    await waitFor(() =>
      expect(screen.getByRole('link', { name: /Мастер на час/ }).textContent).toContain('Скрыта'),
    );
    expect(writes(backend)).toEqual([
      { request: `PATCH /me/profile/services/${PRICE_LIST[1]?.id}`, body: { is_active: false } },
    ]);
  });
});

describe('S36 price item', () => {
  const name = () => screen.findByRole<HTMLInputElement>('textbox', { name: 'Название' });

  it('adds an item with group, «from» price, duration and description', async () => {
    const backend = withBackend([]);
    const { app, telegram } = startApp('/cabinet/prices/new');

    fireEvent.change(await name(), { target: { value: 'Установка карниза' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Группа' }), {
      target: { value: String(CHANDELIERS) },
    });
    await click(screen.getByRole('radio', { name: 'От' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Цена в динарах' }), {
      target: { value: '1500' },
    });
    fireEvent.change(screen.getByRole('combobox', { name: 'Длительность' }), {
      target: { value: '60' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Описание' }), {
      target: { value: 'Сверлим, крепим, вешаем' },
    });
    await pressMainButton(telegram);

    await waitFor(() => expect(writes(backend)).toHaveLength(1));
    expect(writes(backend)[0]).toEqual({
      request: 'POST /me/profile/services',
      body: {
        title: 'Установка карниза',
        price_type: 'from',
        price_min: 150_000,
        category_id: CHANDELIERS,
        duration_min: 60,
        description: 'Сверлим, крепим, вешаем',
      },
    });
    await waitFor(() => expect(app.router.state.location.pathname).not.toBe('/cabinet/prices/new'));
  });

  it('saves only what changed and clears a removed description', async () => {
    const backend = withBackend([
      item('1', 'Выезд и диагностика', 0, { description: 'Приеду, найду причину' }),
    ]);
    const { telegram } = startApp(`/cabinet/prices/${PRICE_LIST[0]?.id}`);

    await name();
    fireEvent.change(screen.getByRole('textbox', { name: 'Цена в динарах' }), {
      target: { value: '2500' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Описание' }), { target: { value: '' } });
    await pressMainButton(telegram);

    await waitFor(() => expect(writes(backend)).toHaveLength(1));
    expect(writes(backend)[0]?.body).toEqual({ price_min: 250_000, clear: ['description'] });
  });

  it('deletes an item after confirmation', async () => {
    const backend = withBackend();
    const { app } = startApp(`/cabinet/prices/${PRICE_LIST[0]?.id}`, { popupAnswer: 'ok' });

    await name();
    await click(screen.getByRole('button', { name: 'Удалить позицию' }));

    await waitFor(() =>
      expect(writes(backend)).toEqual([
        { request: `DELETE /me/profile/services/${PRICE_LIST[0]?.id}`, body: undefined },
      ]),
    );
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet/prices'));
    expect(backend.services).toHaveLength(3);
  });

  it('requires a title and a price', async () => {
    const backend = withBackend([]);
    const { telegram } = startApp('/cabinet/prices/new');

    await name();
    await pressMainButton(telegram);

    expect(await screen.findByText('Назовите услугу')).toBeTruthy();
    expect(screen.getByText('Укажите цену')).toBeTruthy();
    expect(writes(backend)).toEqual([]);
  });
});
