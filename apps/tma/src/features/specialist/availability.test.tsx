// «Доступен сегодня» и пауза (DEVELOPMENT_PLAN 2.10): переключатель на S33 и экран S38 на фейке
// backend кабинета. Время — по Белграду и подменено: варианты «до 18/20/22» зависят от часа.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { pressMainButton, startApp } from '../../testing/app.tsx';
import { FIRST_SERVICE, PROFILE_FILLED } from '../../testing/fixtures.ts';
import { profileHandlers, server } from '../../testing/msw.ts';
import { ProfileBackend } from '../../testing/profileBackend.ts';

afterEach(() => {
  setSession(null);
  vi.useRealTimers();
});

/** Сейчас — `hour`:`minute` 1 октября по Белграду (UTC+2); таймеры — настоящие. */
function at(hour: number, minute = 0) {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(Date.UTC(2026, 9, 1, hour - 2, minute)));
}

function withBackend(backend: ProfileBackend): ProfileBackend {
  server.use(...profileHandlers(() => backend));
  return backend;
}

const PUBLISHED = { ...PROFILE_FILLED, status: 'published' as const };
const writes = (backend: ProfileBackend) =>
  backend.log.filter((entry) => !entry.request.startsWith('GET'));

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

describe('S33 «available today» switch', () => {
  it('switches on «until 20:00» and off again', async () => {
    at(15);
    const backend = withBackend(new ProfileBackend(PUBLISHED, [FIRST_SERVICE]));
    startApp('/cabinet');

    const off = await screen.findByRole('switch', { name: 'Доступен сегодня' });
    expect(screen.getByRole('link', { name: /Доступность/ }).textContent).toContain('выключено');
    await click(off);

    const on = await screen.findByRole('switch', { name: 'Доступен сегодня до 20:00' });
    expect(on.getAttribute('aria-checked')).toBe('true');
    expect(screen.getByRole('link', { name: /Доступность/ }).textContent).toContain(
      'сегодня до 20:00',
    );
    await click(on);

    await screen.findByRole('switch', { name: 'Доступен сегодня' });
    expect(writes(backend)).toEqual([
      { request: 'PUT /me/profile/availability', body: { until: '20:00' } },
      { request: 'PUT /me/profile/availability', body: { until: null } },
    ]);
  });

  it('cannot be switched on after 22:00', async () => {
    at(22, 30);
    withBackend(new ProfileBackend(PUBLISHED, [FIRST_SERVICE]));
    startApp('/cabinet');

    const late = await screen.findByRole('switch', { name: 'Доступен сегодня' });
    expect(late.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('На сегодня уже поздно — включите завтра')).toBeTruthy();
  });
});

describe('S38 availability', () => {
  it('saves «until 22:00» and the pause, then returns to the cabinet', async () => {
    at(19);
    const backend = withBackend(new ProfileBackend(PUBLISHED, [FIRST_SERVICE]));
    const { app, telegram } = startApp('/cabinet/availability');

    const early = await screen.findByRole('button', { name: 'до 18:00' });
    expect(early.hasAttribute('disabled')).toBe(true);
    await click(screen.getByRole('button', { name: 'до 22:00' }));
    expect(screen.getByText('Клиенты видят «Сегодня до 22:00»')).toBeTruthy();
    await click(screen.getByRole('switch', { name: 'Пауза или отпуск' }));
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet'));
    expect(writes(backend).map((entry) => entry.request)).toEqual([
      'PUT /me/profile/availability',
      'POST /me/profile/hide',
    ]);
    expect(backend.profile?.status).toBe('hidden');
    expect(backend.profile?.available_until).toBe('2026-10-01T20:00:00.000Z');
  });

  it('offers the pause only to a published profile', async () => {
    at(15);
    withBackend(new ProfileBackend({ ...PROFILE_FILLED, status: 'pending_review' }));
    startApp('/cabinet/availability');

    const pause = await screen.findByRole('switch', { name: 'Пауза или отпуск' });
    expect(pause.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('Пауза — когда профиль опубликован')).toBeTruthy();
  });
});
