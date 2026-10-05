// Мастер «Стать специалистом» S32a–c (DEVELOPMENT_PLAN 2.9) целиком, на фейке backend кабинета:
// от «профиля нет» до «на проверке», только изменённое уходит на сервер, проверки полей, смена
// типа черновика, ввод между шагами, охрана шагов и ошибки сохранения.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { mainButton, pressBackButton, pressMainButton, startApp } from '../../testing/app.tsx';
import {
  CATEGORY_IDS,
  DISTRICT_IDS,
  FIRST_SERVICE,
  PROFILE_DRAFT,
  PROFILE_FILLED,
} from '../../testing/fixtures.ts';
import { profileHandlers, server } from '../../testing/msw.ts';
import { ProfileBackend } from '../../testing/profileBackend.ts';
import { useBecomeStore } from './shared/store.ts';

beforeEach(() => useBecomeStore.getState().reset());
afterEach(() => setSession(null));

function withBackend(backend: ProfileBackend): ProfileBackend {
  server.use(...profileHandlers(() => backend));
  return backend;
}

/** Изменяющие запросы к кабинету по порядку. */
const writes = (backend: ProfileBackend) =>
  backend.log.filter((entry) => !entry.request.startsWith('GET')).map((entry) => entry.request);

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

const type = (name: string, value: string) =>
  fireEvent.change(screen.getByRole('textbox', { name }), { target: { value } });

/** Шаг загрузил черновик и справочники: форма на экране, MainButton готова. */
const about = () => screen.findByRole('textbox', { name: 'Коротко о себе' });
const area = () => screen.findByRole('textbox', { name: 'Первая позиция прайса' });

/** S32a узнал, есть ли черновик: MainButton без загрузки. */
const typeReady = (telegram: Parameters<typeof mainButton>[0]) =>
  waitFor(() =>
    expect(mainButton(telegram)).toMatchObject({ text: 'Далее', is_progress_visible: false }),
  );

describe('S32a–c become a specialist', () => {
  it('walks from no profile to «on review»: type, about, districts and the first price', async () => {
    const backend = withBackend(new ProfileBackend());
    const { app, telegram } = startApp('/become/type?kind=pro');

    expect(await screen.findByRole('heading', { name: 'Как вы хотите работать?' })).toBeTruthy();
    expect(screen.getByRole('radio', { name: 'Специалист' }).getAttribute('aria-checked')).toBe(
      'true',
    );
    await typeReady(telegram);
    await pressMainButton(telegram);

    await about();
    expect(backend.profile).toMatchObject({ kind: 'pro', city_id: 1, status: 'draft' });
    await click(screen.getByRole('button', { name: 'Электрика' }));
    type('Коротко о себе', 'Электрик · люстры');
    expect(screen.getByText('Показывается под именем. 17 из 80')).toBeTruthy();
    await pressMainButton(telegram);

    await area();
    expect(backend.profile).toMatchObject({
      category_ids: [CATEGORY_IDS['electrical']],
      headline: 'Электрик · люстры',
      languages: ['ru'],
    });
    expect(screen.getByRole('heading', { name: 'Районы · Нови-Сад' })).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Лиман' }));
    type('Первая позиция прайса', 'Выезд и диагностика');
    fireEvent.change(screen.getByRole('textbox', { name: 'Цена в динарах' }), {
      target: { value: '2 000' },
    });
    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({ text: 'Отправить на проверку' }),
    );
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/profile'));
    expect(backend.profile).toMatchObject({
      status: 'pending_review',
      district_ids: [DISTRICT_IDS['Лиман']],
      work_modes: ['at_client'],
      travel_radius_km: 5,
    });
    expect(backend.services).toMatchObject([
      { title: 'Выезд и диагностика', price_type: 'fixed', price_min: { amount: 200_000 } },
    ]);
    expect(writes(backend)).toEqual([
      'POST /me/profile',
      'PUT /me/profile/categories',
      'PATCH /me/profile',
      'PUT /me/profile/areas',
      'PATCH /me/profile',
      'POST /me/profile/services',
      'POST /me/profile/submit',
    ]);
    expect(useBecomeStore.getState().headline).toBeNull();
  });

  it('marks what is missing on S32b and saves nothing', async () => {
    const backend = withBackend(new ProfileBackend(PROFILE_DRAFT));
    const { telegram } = startApp('/become/about');

    await about();
    await pressMainButton(telegram);

    expect(await screen.findByText('Выберите хотя бы одну категорию')).toBeTruthy();
    expect(screen.getByText('Напишите коротко о себе')).toBeTruthy();
    expect(
      screen.getByRole('textbox', { name: 'Коротко о себе' }).getAttribute('aria-invalid'),
    ).toBe('true');
    expect(writes(backend)).toEqual([]);
  });

  it('allows up to five categories and keeps chosen chips first, as on the artboard', async () => {
    withBackend(new ProfileBackend(PROFILE_FILLED, [FIRST_SERVICE]));
    startApp('/become/about');

    await about();
    const chips = () =>
      screen
        .getAllByRole('button')
        .filter(
          (button) => button.hasAttribute('aria-pressed') || button.hasAttribute('aria-expanded'),
        )
        .slice(0, 5)
        .map((button) => button.textContent);
    expect(chips()).toEqual([
      'Электрика',
      'Люстры и карнизы',
      'Сантехника',
      'Сборка мебели',
      'Другие категории',
    ]);

    await click(screen.getByRole('button', { name: 'Другие категории' }));
    expect(screen.getByRole('button', { name: 'Свернуть' }).getAttribute('aria-expanded')).toBe(
      'true',
    );
    for (const name of ['Сантехника', 'Маникюр', 'Уборка']) {
      await click(screen.getByRole('button', { name }));
    }
    await click(screen.getByRole('button', { name: 'Переезды' }));

    expect(screen.getByRole('button', { name: 'Переезды' }).getAttribute('aria-pressed')).toBe(
      'false',
    );
    expect(screen.getByRole('status').textContent).toBe('Можно выбрать до 5 категорий');
  });

  it('changes the type of the draft when the person goes back to S32a', async () => {
    const backend = withBackend(new ProfileBackend(PROFILE_DRAFT));
    const { telegram } = startApp('/become/type');

    await typeReady(telegram);
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: 'Специалист' }).getAttribute('aria-checked')).toBe(
        'true',
      ),
    );
    await click(screen.getByRole('radio', { name: /Подработка/ }));
    await pressMainButton(telegram);

    await about();
    expect(backend.profile).toMatchObject({ kind: 'casual', listed_in_catalog: false });
    expect(writes(backend)).toEqual(['PATCH /me/profile']);
    expect(backend.log.at(-1)?.body).toEqual({ kind: 'casual' });
  });

  it('keeps the input of a step while the person walks back and forth', async () => {
    withBackend(new ProfileBackend(PROFILE_FILLED, [FIRST_SERVICE]));
    const { telegram } = startApp('/become/area');

    await area();
    type('Первая позиция прайса', 'Замена розетки');
    await pressBackButton(telegram);
    await about();
    await pressMainButton(telegram);

    await area();
    expect(
      screen.getByRole<HTMLInputElement>('textbox', { name: 'Первая позиция прайса' }).value,
    ).toBe('Замена розетки');
  });

  it('lets a side job go without districts and a price, «at my place»', async () => {
    const backend = withBackend(
      new ProfileBackend({ ...PROFILE_FILLED, kind: 'casual', district_ids: [], work_modes: [] }),
    );
    const { app, telegram } = startApp('/become/area');

    await area();
    expect(
      screen.getByText('Для подработки — по желанию. Остальные позиции добавите в кабинете'),
    ).toBeTruthy();
    await click(screen.getByRole('radio', { name: 'У себя' }));
    expect(screen.queryByRole('radiogroup', { name: 'Радиус выезда' })).toBeNull();
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/profile'));
    expect(backend.profile).toMatchObject({
      status: 'pending_review',
      work_modes: ['at_own_place'],
    });
    expect(writes(backend)).toEqual(['PATCH /me/profile', 'POST /me/profile/submit']);
  });

  it('requires districts to travel and a price for a specialist', async () => {
    const backend = withBackend(new ProfileBackend({ ...PROFILE_FILLED, district_ids: [] }));
    const { telegram } = startApp('/become/area');

    await area();
    await pressMainButton(telegram);

    expect(await screen.findByText('Отметьте районы, куда выезжаете')).toBeTruthy();
    expect(screen.getByText('Назовите услугу')).toBeTruthy();
    expect(screen.getByText('Укажите цену в динарах')).toBeTruthy();
    expect(writes(backend)).toEqual([]);
  });

  it('edits the existing first price instead of adding a second one', async () => {
    const backend = withBackend(new ProfileBackend(PROFILE_FILLED, [FIRST_SERVICE]));
    const { app, telegram } = startApp('/become/area');

    await area();
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Цена в динарах' }).value).toBe(
      '2\u00a0000',
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Цена в динарах' }), {
      target: { value: '2500' },
    });
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/profile'));
    expect(writes(backend)).toEqual([
      `PATCH /me/profile/services/${FIRST_SERVICE.id}`,
      'POST /me/profile/submit',
    ]);
    expect(backend.services).toMatchObject([{ price_min: { amount: 250_000 } }]);
  });

  it('shows the server explanation when saving fails and keeps the input', async () => {
    withBackend(new ProfileBackend(PROFILE_DRAFT));
    server.use(
      http.put('*/api/v1/me/profile/categories', () =>
        HttpResponse.json(
          { type: 'x', title: 'x', status: 422, code: 'category_not_allowed', detail: 'Категория недоступна', trace_id: 't' },
          { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    ); // prettier-ignore
    const { telegram } = startApp('/become/about');

    await about();
    await click(screen.getByRole('button', { name: 'Электрика' }));
    type('Коротко о себе', 'Электрик');
    await pressMainButton(telegram);

    expect((await screen.findByRole('alert')).textContent).toBe('Категория недоступна');
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Коротко о себе' }).value).toBe(
      'Электрик',
    );
  });

  it('sends a step opened without a profile to S32a and a sent profile to S31', async () => {
    withBackend(new ProfileBackend());
    const first = startApp('/become/area');
    await waitFor(() => expect(first.app.router.state.location.pathname).toBe('/become/type'));
  });

  it('does not reopen the wizard for a profile on review', async () => {
    withBackend(
      new ProfileBackend({ ...PROFILE_FILLED, status: 'pending_review' }, [FIRST_SERVICE]),
    );
    const { app } = startApp('/become/about');

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/profile'));
  });
});
