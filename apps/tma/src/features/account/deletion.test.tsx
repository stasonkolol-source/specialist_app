// Удаление аккаунта S45 и дата удаления на S31 (DEVELOPMENT_PLAN 2.12a) на /me с памятью:
// без галочки удалить нельзя, запрос → дата и «Отменить удаление», отмена с S45 и с S31,
// «Нужна пауза?» — только видимому клиентам специалисту.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { mainButton, pressMainButton, startApp, userBackend } from '../../testing/app.tsx';
import { DELETION_EXECUTE_AFTER, ME, PROFILE_FILLED } from '../../testing/fixtures.ts';
import { profileHandlers, server } from '../../testing/msw.ts';
import { ProfileBackend } from '../../testing/profileBackend.ts';

afterEach(() => setSession(null));

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

const SCHEDULED = 'Аккаунт удалится 8 октября';

describe('S45 delete account', () => {
  it('needs the confirmation, then schedules the deletion in 7 days', async () => {
    const backend = userBackend(ME);
    const { telegram } = startApp('/profile/delete');

    expect(
      await screen.findByRole('heading', { name: 'Удаление аккаунта', level: 1 }),
    ).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Удалится' }).textContent).toContain(
      'Телефон и способы входа',
    );
    expect(screen.getByRole('region', { name: 'Останется без вашего имени' })).toBeTruthy();
    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({ is_visible: true, text: 'Удалить аккаунт' }),
    );
    expect(String(mainButton(telegram)?.color).toLowerCase()).toBe('#c62828');

    await pressMainButton(telegram);
    expect(
      await screen.findByText('Отметьте, что понимаете: удалённый аккаунт не восстановить'),
    ).toBeTruthy();
    expect(backend.requests.deletion).toEqual([]);

    await click(screen.getByRole('checkbox', { name: /Понимаю/ }));
    await pressMainButton(telegram);

    expect(await screen.findByText(SCHEDULED)).toBeTruthy();
    expect(backend.requests.deletion).toEqual(['request']);
    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ text: 'Отменить удаление' }));
  });

  it('cancels a scheduled deletion and returns to the profile', async () => {
    const backend = userBackend({ ...ME, deletion_scheduled_at: DELETION_EXECUTE_AFTER });
    const { app, telegram } = startApp('/profile/delete');

    expect(await screen.findByText(SCHEDULED)).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ text: 'Отменить удаление' }));
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/profile'));
    expect(backend.requests.deletion).toEqual(['cancel']);
    expect(screen.queryByText(SCHEDULED)).toBeNull();
  });

  it('offers a pause only to a specialist visible to clients', async () => {
    userBackend(ME);
    const backend = new ProfileBackend({ ...PROFILE_FILLED, status: 'published' });
    server.use(...profileHandlers(() => backend));
    const { app } = startApp('/profile/delete');

    await click(
      await screen.findByRole('button', { name: 'Нужна пауза? Скрыть профиль из поиска' }),
    );

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet/availability'));
  });

  it('has no pause without a profile', async () => {
    userBackend(ME);
    startApp('/profile/delete');

    await screen.findByRole('heading', { name: 'Удаление аккаунта', level: 1 });
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Удалится' })).toBeTruthy());
    expect(screen.queryByRole('button', { name: /Нужна пауза/ })).toBeNull();
  });
});

describe('S31 account deletion', () => {
  it('shows the scheduled date and cancels in place', async () => {
    const backend = userBackend({ ...ME, deletion_scheduled_at: DELETION_EXECUTE_AFTER });
    startApp('/profile');

    expect(await screen.findByText(SCHEDULED)).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Отменить' }));

    await waitFor(() => expect(screen.queryByText(SCHEDULED)).toBeNull());
    expect(backend.requests.deletion).toEqual(['cancel']);
  });

  it('leads to S45 from «Удалить аккаунт»', async () => {
    userBackend(ME);
    const { app } = startApp('/profile');

    await click(await screen.findByRole('link', { name: 'Удалить аккаунт' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/profile/delete'));
  });
});
