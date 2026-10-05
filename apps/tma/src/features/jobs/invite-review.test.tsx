// «Отзыв до платформы» S56 (DEVELOPMENT_PLAN 7.6а) на фейке backend: по ссылке `ri_` — кто просит
// отзыв, звёзды с подписью, «Что делал специалист», текст и галочка «Подтверждаю…»; без галочки отзыв
// не уходит; после отправки — «Спасибо». Недействительная ссылка — нейтральный экран, своя ссылка
// — объяснение, второй отзыв о том же специалисте — «Вы уже оставили отзыв».
import { setSession } from '@sosed/api-client';
import { encodeStartParam } from '@sosed/links';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { InvitesBackend, invitesFixture } from '../../testing/invitesBackend.ts';
import { invitesHandlers, server } from '../../testing/msw.ts';

afterEach(() => setSession(null));

/** Ссылка Андрею из артборда S55 — ждёт отзыва. */
const WAITING = invitesFixture()[0];

function withInvites(options: ConstructorParameters<typeof InvitesBackend>[1] = {}) {
  const backend = new InvitesBackend(invitesFixture(), options);
  server.use(...invitesHandlers(() => backend));
  return backend;
}

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

describe('S56 invite review', () => {
  it('leaves a review by the `ri_` link after confirming the work', async () => {
    const backend = withInvites();
    if (!WAITING) throw new Error('fixtures');
    const { app, telegram } = startApp('/', {
      startParam: encodeStartParam({ type: 'review_invite', id: WAITING.token }),
    });

    expect(
      await screen.findByRole('heading', { name: 'Отзыв о прошлой работе', level: 1 }),
    ).toBeTruthy();
    expect(app.router.state.location.pathname).toBe(`/review-invites/${WAITING.token}`);
    expect(screen.getByText('Алексей Морозов')).toBeTruthy();
    expect(screen.getByText('Электрик · мелкий ремонт · люстры')).toBeTruthy();
    expect(screen.getByText(/^Алексей просит рассказать о работе/)).toBeTruthy();
    // MainButton — после оценки
    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({ text: 'Отправить отзыв', is_active: false }),
    );
    await click(screen.getByRole('radio', { name: '5 звёзд' }));
    expect(screen.getByText('Отлично')).toBeTruthy();
    fireEvent.change(screen.getByRole('textbox', { name: 'Что делал специалист' }), {
      target: { value: 'Проводка в ванной и светильники' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Отзыв' }), {
      target: { value: 'Всё сделал за день, объяснил, что и зачем.' },
    });
    await waitFor(() => expect(mainButton(telegram)?.is_active).toBe(true));

    // без галочки «Подтверждаю…» отзыв не уходит
    await pressMainButton(telegram);
    expect(
      await screen.findByText('Отметьте, что этот специалист делал для вас работу'),
    ).toBeTruthy();
    expect(backend.reviews.size).toBe(0);
    await click(
      screen.getByRole('checkbox', {
        name: 'Подтверждаю: Алексей действительно делал(а) для меня эту работу',
      }),
    );
    await pressMainButton(telegram);

    expect(
      await screen.findByRole('heading', { name: 'Спасибо! Отзыв появится после проверки' }),
    ).toBeTruthy();
    expect(backend.reviews.get(WAITING.token)).toEqual({
      rating: 5,
      work_title: 'Проводка в ванной и светильники',
      body: 'Всё сделал за день, объяснил, что и зачем.',
      confirmed: true,
    });
  });

  it('shows one neutral screen for a revoked, expired, used or unknown link', async () => {
    withInvites();
    // использованная ссылка (отзыв Ксении уже опубликован) — та же 404, что и несуществующая
    startApp(`/review-invites/${invitesFixture()[2]?.token}`);

    expect(
      await screen.findByRole('heading', { name: 'Ссылка недействительна', level: 1 }),
    ).toBeTruthy();
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('explains to the specialist that the link is for a past client', async () => {
    withInvites({ own: true });
    const { telegram } = startApp(`/review-invites/${WAITING?.token}`);

    expect(await screen.findByRole('heading', { name: 'Это ваша ссылка', level: 1 })).toBeTruthy();
    expect(mainButton(telegram)?.is_visible).not.toBe(true);
  });

  it('explains that a review about this specialist was already left', async () => {
    withInvites({ reviewed: true });
    const { telegram } = startApp(`/review-invites/${WAITING?.token}`);

    await click(await screen.findByRole('radio', { name: '4 звезды' }));
    await click(screen.getByRole('checkbox', { name: /^Подтверждаю/ }));
    await pressMainButton(telegram);

    expect(
      await screen.findByRole('heading', { name: 'Вы уже оставили отзыв', level: 1 }),
    ).toBeTruthy();
  });
});
