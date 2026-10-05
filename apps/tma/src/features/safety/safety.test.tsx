// Жалобы S46 и блокировки S44 (DEVELOPMENT_PLAN 4.7) на фейках backend: шторка жалобы с профиля
// S08 (причины профиля, подробности, «Также заблокировать», «Жалоба отправлена»), с отзыва S11, с
// заявки S15 и из меню чата S30 (собеседник с диалогом); MainButton экрана спрятана, пока шторка
// открыта; «Заблокировать» на S08 — после подтверждения, «Разблокировать» — сразу; в S30 блокировка
// закрывает композер; лимит жалоб — текстом сервера; S44 — список, «Разблокировать», пусто; S43 —
// число заблокированных и переход в S44.
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressBackButton, startApp } from '../../testing/app.tsx';
import { ChatBackend, CONVERSATION_IDS } from '../../testing/chatBackend.ts';
import { CARD_PROFILE_ID, E2E_NOW, userIdOf } from '../../testing/fixtures.ts';
import { FEED_JOBS, JobsBackend } from '../../testing/jobsBackend.ts';
import { chatHandlers, jobsHandlers, safetyHandlers, server } from '../../testing/msw.ts';
import { ARTBOARD_BLOCKS, SafetyBackend } from '../../testing/safetyBackend.ts';

const PROFILE = `/specialists/${CARD_PROFILE_ID}`;
const ALEXEY = userIdOf(CARD_PROFILE_ID);
const DIRECT = `/messages/${CONVERSATION_IDS.direct}`;

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

function withSafety(backend = new SafetyBackend()): SafetyBackend {
  server.use(...safetyHandlers(() => backend));
  return backend;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(E2E_NOW) });
});
afterEach(() => {
  vi.useRealTimers();
  setSession(null);
});

describe('S46 report', () => {
  it('reports a profile with a reason and details, blocks too and says it was sent', async () => {
    const safety = withSafety();
    const { telegram } = startApp(PROFILE);
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Написать'));

    await click(await screen.findByRole('button', { name: 'Пожаловаться на профиль' }));

    const sheet = within(await screen.findByRole('dialog', { name: 'Пожаловаться на профиль' }));
    await waitFor(() => expect(mainButton(telegram)?.is_visible).toBe(false));
    const reasons = sheet.getAllByRole('radio').map((radio) => radio.textContent);
    expect(reasons).toEqual([
      'Мошенничество или просит предоплату',
      'Фейковые отзывы или чужие фото',
      'Оскорбления или угрозы',
      'Запрещённые услуги',
      'Другое',
    ]);
    const send = sheet.getByRole('button', { name: 'Отправить жалобу' });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    await click(sheet.getByRole('radio', { name: 'Мошенничество или просит предоплату' }));
    expect(
      sheet.getByText(
        'Жалобы на мошенничество модератор рассматривает в течение 2 часов, с 08:00 до 23:00.',
      ),
    ).toBeTruthy();
    fireEvent.change(sheet.getByLabelText('Подробности'), {
      target: { value: 'Попросил перевести 2 000 RSD на карту до приезда' },
    });
    await click(sheet.getByRole('checkbox', { name: 'Также заблокировать специалиста' }));
    await click(send);

    const done = within(await screen.findByRole('dialog', { name: 'Жалоба отправлена' }));
    expect(
      done.getByText('Модератор проверит её в течение 2 часов, с 08:00 до 23:00.'),
    ).toBeTruthy();
    expect(done.getByText(/Этот человек больше не сможет писать вам/)).toBeTruthy();
    expect(safety.reports).toEqual([
      {
        target_type: 'profile',
        target_id: CARD_PROFILE_ID,
        reason: 'fraud',
        comment: 'Попросил перевести 2 000 RSD на карту до приезда',
        conversation_id: null,
      },
    ]);
    expect(safety.blocks.map((user) => [user.user_id, user.display_name])).toEqual([
      [ALEXEY, 'Алексей М.'],
    ]);

    await click(done.getByRole('button', { name: 'Готово' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    // заблокирован: «Написать» и «Предложить заявку» нет, вместо «Заблокировать» — «Разблокировать»
    expect(await screen.findByText(/Вы заблокировали этого специалиста/)).toBeTruthy();
    expect(mainButton(telegram)?.is_visible).toBe(false);
    expect(screen.queryByRole('button', { name: 'Предложить заявку' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Разблокировать' })).toBeTruthy();
  });

  it('closes with Back and gives the MainButton back to the screen', async () => {
    withSafety();
    const { telegram } = startApp(PROFILE);
    await click(await screen.findByRole('button', { name: 'Пожаловаться на профиль' }));
    await screen.findByRole('dialog', { name: 'Пожаловаться на профиль' });

    await act(async () => {
      await pressBackButton(telegram);
    });

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(mainButton(telegram)?.is_visible).toBe(true));
    expect(screen.getByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeTruthy();
  });

  it('reports a review from its «⋯» with review reasons', async () => {
    const safety = withSafety();
    startApp(`${PROFILE}/reviews`);

    await click(await screen.findByRole('button', { name: 'Пожаловаться на отзыв: Ирина С.' }));
    const sheet = within(await screen.findByRole('dialog', { name: 'Пожаловаться на отзыв' }));
    expect(sheet.queryByRole('checkbox')).toBeNull(); // отзыв не блокируют из шторки
    await click(sheet.getByRole('radio', { name: 'Оскорбления' }));
    expect(
      sheet.getByText(
        /Жалобы на угрозы и запрещённые услуги модератор рассматривает в течение часа/,
      ),
    ).toBeTruthy();
    await click(sheet.getByRole('button', { name: 'Отправить жалобу' }));

    expect(
      await screen.findByText('Модератор проверит её в течение часа, с 08:00 до 23:00.'),
    ).toBeTruthy();
    expect(safety.reports.map((report) => [report.target_type, report.reason])).toEqual([
      ['review', 'offensive'],
    ]);
  });

  it('reports a job from S15 next to «Not interested»', async () => {
    const safety = withSafety();
    server.use(...jobsHandlers(() => new JobsBackend()));
    const job = FEED_JOBS[0];
    const { telegram } = startApp(`/jobs/${job?.card.id}`);
    await waitFor(() => expect(mainButton(telegram)?.is_visible).toBe(true));

    await click(await screen.findByRole('button', { name: 'Пожаловаться' }));

    const sheet = within(await screen.findByRole('dialog', { name: 'Пожаловаться на заявку' }));
    await waitFor(() => expect(mainButton(telegram)?.is_visible).toBe(false));
    await click(sheet.getByRole('radio', { name: 'Спам или реклама' }));
    await click(sheet.getByRole('button', { name: 'Отправить жалобу' }));
    await screen.findByRole('dialog', { name: 'Жалоба отправлена' });
    expect(safety.reports.map((report) => [report.target_type, report.target_id])).toEqual([
      ['job', job?.card.id],
    ]);
  });

  it('shows the server text when the daily limit is reached', async () => {
    const safety = withSafety();
    safety.reports = Array.from({ length: 20 }, (_, n) => ({
      target_type: 'user' as const,
      target_id: `01a0e700-0000-7000-8000-${String(n).padStart(12, '0')}`,
      reason: 'spam' as const,
    }));
    startApp(PROFILE);
    await click(await screen.findByRole('button', { name: 'Пожаловаться на профиль' }));
    const sheet = within(await screen.findByRole('dialog', { name: 'Пожаловаться на профиль' }));

    await click(sheet.getByRole('radio', { name: 'Другое' }));
    await click(sheet.getByRole('button', { name: 'Отправить жалобу' }));

    expect(
      await sheet.findByText(
        'Слишком много жалоб за сутки. Попробуйте завтра или напишите в поддержку.',
      ),
    ).toBeTruthy();
  });
});

describe('blocking', () => {
  it('blocks from S08 after confirming and unblocks at once', async () => {
    const safety = withSafety();
    startApp(PROFILE, { popupAnswer: 'ok' });

    await click(await screen.findByRole('button', { name: 'Заблокировать' }));

    expect(await screen.findByRole('button', { name: 'Разблокировать' })).toBeTruthy();
    await waitFor(() => expect(safety.blocks.map((user) => user.user_id)).toEqual([ALEXEY]));
    await click(screen.getByRole('button', { name: 'Разблокировать' }));
    expect(await screen.findByRole('button', { name: 'Заблокировать' })).toBeTruthy();
    await waitFor(() => expect(safety.blocks).toEqual([]));
  });

  it('does not block when the confirmation is declined', async () => {
    const safety = withSafety();
    startApp(PROFILE, { popupAnswer: 'cancel' });

    await click(await screen.findByRole('button', { name: 'Заблокировать' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Заблокировать' })).toBeTruthy());
    expect(safety.blocks).toEqual([]);
  });

  it('S30: reports the counterpart with the conversation from the «⋯» menu', async () => {
    const safety = withSafety();
    const chat = new ChatBackend().seed();
    chat.safety = safety;
    server.use(...chatHandlers(() => chat));
    startApp(DIRECT, { popupAnswer: 'report' });

    await click(
      await screen.findByRole('button', { name: 'Меню диалога: пожаловаться или заблокировать' }),
    );

    const sheet = within(
      await screen.findByRole('dialog', { name: 'Пожаловаться на собеседника' }),
    );
    await click(sheet.getByRole('radio', { name: 'Не пришёл или пропал' }));
    await click(sheet.getByRole('button', { name: 'Отправить жалобу' }));
    await screen.findByRole('dialog', { name: 'Жалоба отправлена' });
    expect(safety.reports).toEqual([
      expect.objectContaining({
        target_type: 'user',
        reason: 'no_show',
        conversation_id: CONVERSATION_IDS.direct,
      }),
    ]);
  });

  it('S30: blocking from the menu closes the composer, unblocking opens it again', async () => {
    const safety = withSafety();
    const chat = new ChatBackend().seed();
    chat.safety = safety;
    server.use(...chatHandlers(() => chat));
    startApp(DIRECT, { popupAnswer: ['block', 'ok'] });
    expect(await screen.findByRole('textbox', { name: 'Сообщение' })).toBeTruthy();

    await click(
      screen.getByRole('button', { name: 'Меню диалога: пожаловаться или заблокировать' }),
    );

    expect(
      await screen.findByText('Вы заблокировали собеседника. Переписка — только для чтения.'),
    ).toBeTruthy();
    expect(screen.queryByRole('textbox', { name: 'Сообщение' })).toBeNull();
    expect(safety.blocks).toHaveLength(1);
    await click(screen.getByRole('button', { name: 'Разблокировать' }));
    expect(await screen.findByRole('textbox', { name: 'Сообщение' })).toBeTruthy();
    expect(safety.blocks).toEqual([]);
  });

  it('S30: says the counterpart is unavailable when they blocked me', async () => {
    const safety = withSafety();
    const chat = new ChatBackend().seed();
    chat.safety = safety;
    const counterpart = (
      await chat.handle('GET', new URL(`http://localhost/api/v1/conversations`), undefined)
    )?.body as { items: { id: string; counterpart_id: string }[] };
    const direct = counterpart.items.find((item) => item.id === CONVERSATION_IDS.direct);
    safety.blockedMe.add(direct?.counterpart_id ?? '');
    server.use(...chatHandlers(() => chat));
    startApp(DIRECT);

    expect(await screen.findByText('Собеседник недоступен: написать ему нельзя.')).toBeTruthy();
    expect(screen.queryByRole('textbox', { name: 'Сообщение' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Разблокировать' })).toBeNull();
  });
});

describe('S44 blocked', () => {
  it('opens from settings with the count, lists and unblocks', async () => {
    const safety = withSafety(new SafetyBackend(ARTBOARD_BLOCKS));
    const { app } = startApp('/settings');

    const row = await screen.findByRole('link', { name: /^Заблокированные/ });
    await waitFor(() => expect(row.textContent).toContain('2'));
    await click(row);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/settings/blocked'));
    const list = within(await screen.findByRole('list', { name: 'Заблокированные пользователи' }));
    expect(screen.getByText(/^Они не могут писать вам/)).toBeTruthy();
    expect(list.getByText('Олег Р.')).toBeTruthy();
    expect(list.getByText('С 14 сентября')).toBeTruthy();
    expect(list.getByText('Марина Т.')).toBeTruthy();

    await click(list.getByRole('button', { name: 'Разблокировать: Олег Р.' }));

    await waitFor(() => expect(screen.queryByText('Олег Р.')).toBeNull());
    await waitFor(() =>
      expect(safety.blocks.map((user) => user.display_name)).toEqual(['Марина Т.']),
    );
  });

  it('says nobody is blocked yet', async () => {
    withSafety();
    startApp('/settings/blocked');

    expect(await screen.findByRole('heading', { name: 'Вы никого не заблокировали' })).toBeTruthy();
    // вступление «Они не могут…» не к кому отнести — его нет, пустое состояние говорит то же
    expect(screen.queryByText(/^Они не могут писать вам/)).toBeNull();
    expect(
      screen.getByRole('heading', { name: 'Как пожаловаться или заблокировать' }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        'В профиле специалиста — строки «Пожаловаться» и «Заблокировать» внизу, в чате — меню «⋯» справа вверху.',
      ),
    ).toBeTruthy();
  });
});
