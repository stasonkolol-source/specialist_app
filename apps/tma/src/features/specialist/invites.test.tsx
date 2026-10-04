// «Отзывы до платформы» S55 (DEVELOPMENT_PLAN 7.6а) на фейке backend кабинета: строка «4 из 5» в
// S33, список со статусами, новая ссылка с «Кому» и отправкой в Telegram, «Отозвать» через
// шторку, все места заняты и неопубликованный профиль.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { FIRST_SERVICE, PROFILE_FILLED } from '../../testing/fixtures.ts';
import { InvitesBackend, inviteFixture, invitesFixture } from '../../testing/invitesBackend.ts';
import { profileHandlers, server } from '../../testing/msw.ts';
import { ProfileBackend } from '../../testing/profileBackend.ts';

afterEach(() => setSession(null));

const PUBLISHED = { ...PROFILE_FILLED, status: 'published' as const };

function withInvites(
  invites = new InvitesBackend(invitesFixture()),
  profile: typeof PROFILE_FILLED = PUBLISHED,
) {
  const backend = new ProfileBackend(profile, [FIRST_SERVICE], { invites });
  server.use(...profileHandlers(() => backend));
  return invites;
}

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

const row = async (name: string) =>
  (await screen.findByText(name, { selector: 'span' })).closest('li') as HTMLElement;

describe('S55 review invites', () => {
  it('opens from the cabinet row «4 из 5» and lists invites with their status', async () => {
    withInvites();
    const { app } = startApp('/cabinet');

    const entry = await screen.findByRole('link', { name: /Отзывы до платформы/ });
    await waitFor(() => expect(within(entry).getByText('4 из 5')).toBeTruthy());
    await click(entry);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet/review-invites'));
    expect(
      await screen.findByRole('heading', { name: 'Отзывы до платформы', level: 1 }),
    ).toBeTruthy();
    expect(screen.getByText('4 из 5 · осталось 1')).toBeTruthy();
    expect(within(await row('Ксения Д.')).getByText('Опубликован')).toBeTruthy();
    expect(within(await row('Татьяна М.')).getByText('На модерации')).toBeTruthy();
    const waiting = await row('Андрей В.');
    expect(within(waiting).getByText('Ждём отзыв')).toBeTruthy();
    // отозвать можно только ждущую отзыва ссылку
    expect(screen.getAllByRole('button', { name: /^Отозвать ссылку/ })).toHaveLength(1);
  });

  it('creates a link for «Кому» and sends it to a Telegram chat', async () => {
    const invites = withInvites(new InvitesBackend([]));
    const { telegram } = startApp('/cabinet/review-invites');

    expect(await screen.findByText(/Приглашений пока нет/)).toBeTruthy();
    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({ is_visible: true, text: 'Создать ссылку' }),
    );
    await pressMainButton(telegram);
    const sheet = await screen.findByRole('dialog', { name: 'Новая ссылка' });
    fireEvent.change(within(sheet).getByRole('textbox', { name: 'Кому' }), {
      target: { value: ' Андрей В. ' },
    });
    await pressMainButton(telegram);

    const ready = await screen.findByRole('dialog', { name: 'Ссылка готова' });
    const [invite] = invites.items;
    expect(invite).toMatchObject({ client_name: 'Андрей В.', status: 'waiting' });
    expect(within(ready).getByRole<HTMLInputElement>('textbox').value).toBe(
      invite?.url.replace('https://', ''),
    );
    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({ text: 'Отправить в Telegram' }),
    );
    await pressMainButton(telegram);
    await waitFor(() =>
      expect(telegram.callsOf('web_app_open_tg_link').at(-1)?.path_full).toContain(
        encodeURIComponent(invite?.url ?? ''),
      ),
    );
    await click(within(ready).getByRole('button', { name: 'Готово' }));

    expect(within(await row('Андрей В.')).getByText('Ждём отзыв')).toBeTruthy();
    expect(screen.getByText('1 из 5 · осталось 4')).toBeTruthy();
  });

  it('revokes an unused link after the confirmation sheet', async () => {
    const invites = withInvites();
    startApp('/cabinet/review-invites');

    await click(await screen.findByRole('button', { name: 'Отозвать ссылку: Андрей В.' }));
    const sheet = await screen.findByRole('dialog', { name: 'Отозвать ссылку?' });
    expect(invites.log).toEqual([]);
    await click(within(sheet).getByRole('button', { name: 'Отозвать' }));

    await waitFor(() => expect(screen.queryByText('Андрей В.')).toBeNull());
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(invites.log.map((entry) => entry.request)).toEqual([
      `DELETE /me/profile/review-invites/${invitesFixture()[0]?.token}`,
    ]);
    expect(screen.getByText('3 из 5 · осталось 2')).toBeTruthy();
  });

  it('explains that all five places are taken instead of the MainButton', async () => {
    const five = [
      ...invitesFixture(),
      inviteFixture(5, { status: 'waiting', created_at: '2026-10-01T10:00:00Z' }),
    ];
    withInvites(new InvitesBackend(five));
    const { telegram } = startApp('/cabinet/review-invites');

    expect(await screen.findByText(/Все 5 мест заняты/)).toBeTruthy();
    expect(screen.getByText('5 из 5 · осталось 0')).toBeTruthy();
    expect(mainButton(telegram)?.is_visible).not.toBe(true);
  });

  it('explains that an unpublished profile cannot invite yet', async () => {
    withInvites(new InvitesBackend([]), { ...PROFILE_FILLED, status: 'pending_review' });
    const { telegram } = startApp('/cabinet/review-invites');

    expect(await screen.findByText(/Профиль ещё не опубликован/)).toBeTruthy();
    expect(mainButton(telegram)?.is_visible).not.toBe(true);
  });
});
