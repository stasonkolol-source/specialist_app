// Кабинет специалиста S33 и правка профиля S34 (DEVELOPMENT_PLAN 2.10) на фейке backend кабинета:
// статус и полнота, продолжение черновика, правка только изменённого, районы, проверки полей.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../testing/app.tsx';
import {
  DISTRICT_IDS,
  FIRST_SERVICE,
  PROFILE_DRAFT,
  PROFILE_FILLED,
} from '../../testing/fixtures.ts';
import { profileHandlers, server } from '../../testing/msw.ts';
import { ProfileBackend } from '../../testing/profileBackend.ts';

afterEach(() => setSession(null));

function withBackend(backend: ProfileBackend): ProfileBackend {
  server.use(...profileHandlers(() => backend));
  return backend;
}

const writes = (backend: ProfileBackend) =>
  backend.log.filter((entry) => !entry.request.startsWith('GET'));

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

const PUBLISHED = { ...PROFILE_FILLED, status: 'published' as const };

describe('S33 cabinet', () => {
  it('shows the status, how complete the profile is and what to add first', async () => {
    withBackend(new ProfileBackend(PUBLISHED, [FIRST_SERVICE]));
    const { app } = startApp('/cabinet');

    expect(await screen.findByText('Профиль опубликован и виден в поиске')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Кабинет специалиста', level: 1 })).toBeTruthy();
    // без работ, фото профиля и описания позиции: 90 из 125 баллов «Специалиста»
    expect(screen.getByText('Профиль заполнен на 72%')).toBeTruthy();
    expect(
      screen.getByRole('progressbar', { name: 'Полнота профиля' }).getAttribute('aria-valuenow'),
    ).toBe('72');
    expect(screen.getByText('Добавьте ещё 3 работы в портфолио')).toBeTruthy();

    await click(screen.getByRole('link', { name: 'Профиль' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet/profile'));
  });

  it('continues a draft in the wizard with the MainButton', async () => {
    withBackend(new ProfileBackend({ ...PROFILE_FILLED, headline: null }, [FIRST_SERVICE]));
    const { app, telegram } = startApp('/cabinet');

    expect(await screen.findByText('Черновик, осталось несколько шагов')).toBeTruthy();
    expect(screen.getByText('Напишите коротко о себе')).toBeTruthy();
    // черновика в каталоге нет — смотреть клиентам нечего
    expect(screen.queryByRole('button', { name: 'Посмотреть как клиент' })).toBeNull();
    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({
        is_visible: true,
        text: 'Продолжить заполнение',
      }),
    );
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/become/about'));
  });

  it('shows a published profile as clients see it (S08)', async () => {
    withBackend(new ProfileBackend(PUBLISHED, [FIRST_SERVICE]));
    const { app } = startApp('/cabinet');

    await click(await screen.findByRole('button', { name: 'Посмотреть как клиент' }));

    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(`/specialists/${PUBLISHED.id}`),
    );
  });

  it('has no MainButton for a published profile', async () => {
    withBackend(new ProfileBackend(PUBLISHED, [FIRST_SERVICE]));
    const published = startApp('/cabinet');
    await screen.findByText('Профиль опубликован и виден в поиске');
    expect(mainButton(published.telegram)?.is_visible).not.toBe(true);
  });

  it('sends a person without a profile to S31', async () => {
    withBackend(new ProfileBackend());
    const { app } = startApp('/cabinet');

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/profile'));
  });
});

describe('S34 edit profile', () => {
  const name = () => screen.findByRole<HTMLInputElement>('textbox', { name: 'Имя' });

  it('saves only what changed and returns to the cabinet', async () => {
    const backend = withBackend(new ProfileBackend(PUBLISHED, [FIRST_SERVICE]));
    const { app, telegram } = startApp('/cabinet');
    await click(await screen.findByRole('link', { name: 'Профиль' }));

    fireEvent.change(await name(), { target: { value: 'Алексей Морозов' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'О себе' }), {
      target: { value: 'Электрик, 12 лет опыта, в Нови-Саде с 2022 года. Свой инструмент.' },
    });
    expect(screen.getByText('Изменения появятся в профиле после автопроверки')).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ text: 'Сохранить' }));
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet'));
    expect(writes(backend)).toEqual([
      {
        request: 'PATCH /me/profile',
        body: {
          display_name: 'Алексей Морозов',
          about: 'Электрик, 12 лет опыта, в Нови-Саде с 2022 года. Свой инструмент.',
        },
      },
    ]);
    expect(backend.profile?.display_name).toBe('Алексей Морозов');
  });

  it('changes districts from the folded field', async () => {
    const backend = withBackend(new ProfileBackend(PUBLISHED, [FIRST_SERVICE]));
    const { app, telegram } = startApp('/cabinet/profile');

    await name();
    const field = screen.getByRole('button', { name: 'Лиман, Грбавица, Центр и ещё 1' });
    expect(field.getAttribute('aria-expanded')).toBe('false');
    await click(field);
    await click(screen.getByRole('button', { name: 'Адице' }));
    await click(screen.getByRole('button', { name: 'Центр' }));
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet'));
    expect(writes(backend).map((entry) => entry.request)).toEqual(['PUT /me/profile/areas']);
    expect(backend.profile?.district_ids).toEqual([
      DISTRICT_IDS['Лиман'],
      DISTRICT_IDS['Грбавица'],
      DISTRICT_IDS['Нова Детелинара'],
      DISTRICT_IDS['Адице'],
    ]);
  });

  it('turns «Весь Нови-Сад» on: every district of the city is saved', async () => {
    const backend = withBackend(new ProfileBackend(PUBLISHED, [FIRST_SERVICE]));
    const { app, telegram } = startApp('/cabinet/profile');

    await name();
    await click(screen.getByRole('button', { name: 'Лиман, Грбавица, Центр и ещё 1' }));
    const whole = screen.getByRole('checkbox', { name: 'Весь Нови-Сад' });
    expect(whole.getAttribute('aria-checked')).toBe('false');
    await click(whole);
    // список свёрнут, поле говорит «весь город»
    expect(screen.queryByRole('button', { name: 'Адице' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Весь Нови-Сад' })).toBeTruthy();
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet'));
    expect(writes(backend).map((entry) => entry.request)).toEqual(['PUT /me/profile/areas']);
    expect(backend.profile?.district_ids.toSorted()).toEqual(
      Object.values(DISTRICT_IDS).toSorted(),
    );
  });

  it('shows «Весь Нови-Сад» when every district is chosen; off — the list as before', async () => {
    const all = Object.values(DISTRICT_IDS);
    const backend = withBackend(
      new ProfileBackend({ ...PUBLISHED, district_ids: all }, [FIRST_SERVICE]),
    );
    const { app, telegram } = startApp('/cabinet/profile');

    await name();
    await click(screen.getByRole('button', { name: 'Весь Нови-Сад' }));
    const whole = screen.getByRole('checkbox', { name: 'Весь Нови-Сад' });
    expect(whole.getAttribute('aria-checked')).toBe('true');
    await click(whole);
    await click(screen.getByRole('button', { name: 'Лиман' }));
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet'));
    expect(backend.profile?.district_ids).toEqual(all.filter((id) => id !== DISTRICT_IDS['Лиман']));
  });

  it('keeps the name and the headline required', async () => {
    const backend = withBackend(new ProfileBackend(PROFILE_DRAFT));
    const { telegram } = startApp('/cabinet/profile');

    fireEvent.change(await name(), { target: { value: '  ' } });
    await pressMainButton(telegram);

    expect(await screen.findByText('Укажите имя')).toBeTruthy();
    expect(screen.getByText('Напишите коротко о себе')).toBeTruthy();
    expect(screen.queryByText('Изменения появятся в профиле после автопроверки')).toBeNull();
    expect(writes(backend)).toEqual([]);
  });
});
