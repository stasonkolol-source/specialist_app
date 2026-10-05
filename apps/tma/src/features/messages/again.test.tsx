// Сделка снова (DEVELOPMENT_PLAN 6.4, 6.2) на фейке backend: что в шапке S30 и в полосе под ней
// при каждом состоянии сделки. В шапке — всегда одно главное действие, коротко (она не
// прокручивается): нет сделки — «Договориться»; предложена, идёт или под спором — «Сделка» (S26);
// завершена или отменена в прямом диалоге — снова «Договориться» (шторка условий, «что делаем» —
// из прошлой сделки); клиенту в диалоге по отклику после завершённой — «Заказать снова» (прямой
// диалог с этим специалистом), после отмены — «К откликам». В полосе — сделка и второй строкой
// Telegram и «Поделиться контактом», без повтора кнопки шапки. Контакты открыты по
// `contacts_open` сервера: пара договорилась однажды — открыты и пока новое предложение ждёт
// ответа, и после отмены, и в другом диалоге с тем же мастером (ADR-0010, 2026-10-04);
// отклонённое предложение их не открывало.
import type { ConversationDealOut } from '@sosed/api-client';
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { startApp } from '../../testing/app.tsx';
import {
  CONVERSATION_IDS,
  ChatBackend,
  PAST_DEAL_ID,
  SPECIALIST_PROFILE_ID,
} from '../../testing/chatBackend.ts';
import { E2E_NOW } from '../../testing/fixtures.ts';
import { chatHandlers, server } from '../../testing/msw.ts';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(E2E_NOW) });
});
afterEach(() => {
  vi.useRealTimers();
  setSession(null);
});

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

function withChats(): ChatBackend {
  const backend = new ChatBackend().seed();
  server.use(...chatHandlers(() => backend));
  return backend;
}

/** Сделка диалога в нужном состоянии (`null` — сделки нет). */
function withDeal(chat: ChatBackend, id: string, status: ConversationDealOut['status'] | null) {
  const dialog = chat.dialogs.get(id);
  if (!dialog) throw new Error('fixtures');
  dialog.conversation = {
    ...dialog.conversation,
    deal: status ? { id: PAST_DEAL_ID, status, title: 'Повесить люстру' } : null,
  };
}

/** Шапка прямого диалога с Алексеем. */
const directHeader = () => screen.findByRole('banner', { name: 'Алексей Морозов' });

/** Подписи кнопок в шапке: «⋯» — без текста, её не считаем. */
const headerButtons = (header: HTMLElement) =>
  within(header)
    .getAllByRole('button')
    .map((button) => button.textContent)
    .filter(Boolean);

describe('S30 header by the deal', () => {
  it('offers to agree while there is no deal', async () => {
    withChats();
    startApp(`/messages/${CONVERSATION_IDS.direct}`);

    const header = await directHeader();
    // действие «предложить условия», а не статус «Договорились»
    expect(headerButtons(header)).toEqual(['Договориться']);
    expect(within(header).getByText('Сделки пока нет')).toBeTruthy();
  });

  it.each([
    ['proposed', 'Ждёт подтверждения', []],
    ['agreed', 'Договорились', ['Поделиться контактом']],
    ['disputed', 'Спор по сделке', []],
  ] as const)('leads to the %s deal from the header', async (status, label, actions) => {
    const chat = withChats();
    withDeal(chat, CONVERSATION_IDS.direct, status);
    startApp(`/messages/${CONVERSATION_IDS.direct}`);

    const header = await directHeader();
    expect(within(header).getByText(label)).toBeTruthy();
    // «Сделка» в шапке, как на артборде S54; в полосе — сделка без ссылки на неё же и контакты
    expect(headerButtons(header)).toEqual(['Сделка']);
    expect(screen.getByText('Сделка «Повесить люстру»')).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Открыть сделку' })).toBeNull();
    for (const action of actions) expect(screen.getByRole('button', { name: action })).toBeTruthy();
    expect(screen.queryAllByRole('button', { name: 'Поделиться контактом' })).toHaveLength(
      actions.length,
    );
  });

  it('agrees again after the completed deal and keeps the contacts at hand', async () => {
    const chat = withChats();
    chat.pastDeal(CONVERSATION_IDS.direct, 'completed');
    startApp(`/messages/${CONVERSATION_IDS.direct}`);

    const header = await directHeader();
    expect(within(header).getByText('Сделка завершена')).toBeTruthy();
    // снова договориться — в шапке, она не прокручивается; контакты — второй строкой полосы
    expect(headerButtons(header)).toEqual(['Договориться']);
    expect(screen.getAllByRole('button', { name: /Договориться/ })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Telegram: @aleksey_m' })).toBeTruthy();
    expect(screen.getByText('Прошлая сделка «Повесить люстру»')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Открыть сделку' }).getAttribute('href')).toContain(
      `/deals/${PAST_DEAL_ID}`,
    );
    await click(screen.getByRole('button', { name: 'Поделиться контактом' }));
    await click(
      within(await screen.findByRole('dialog', { name: 'Поделиться контактом' })).getByRole(
        'button',
        { name: 'Закрыть' },
      ),
    );

    await click(within(header).getByRole('button', { name: 'Договориться' }));
    const sheet = await screen.findByRole('dialog', { name: 'Договорились?' });
    // тот же маникюр — без набора: «что делаем» из прошлой сделки
    expect(
      (within(sheet).getByRole('textbox', { name: 'Что делаем' }) as HTMLInputElement).value,
    ).toBe('Повесить люстру');
    await click(within(sheet).getByRole('button', { name: 'Предложить' }));

    await waitFor(() => expect(chat.proposals).toEqual([{ title: 'Повесить люстру' }]));
    // в диалоге — новая сделка: ждёт подтверждения второй стороны, в шапке — «Сделка»
    await waitFor(() => expect(headerButtons(header)).toEqual(['Сделка']));
    expect(within(header).getByText('Ждёт подтверждения')).toBeTruthy();
    expect(screen.queryByText('Прошлая сделка «Повесить люстру»')).toBeNull();
    // договорились раньше — контакты не закрылись: второй строкой в полосе новой сделки
    expect(screen.getByText('Сделка «Повесить люстру»')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Telegram: @aleksey_m' })).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Поделиться контактом' }));
    expect(await screen.findByRole('dialog', { name: 'Поделиться контактом' })).toBeTruthy();
  });

  it('keeps the contacts open after the agreed deal was cancelled', async () => {
    const chat = withChats();
    chat.pastDeal(CONVERSATION_IDS.direct, 'cancelled');
    startApp(`/messages/${CONVERSATION_IDS.direct}`);

    const header = await directHeader();
    expect(within(header).getByText('Договорённость отменена')).toBeTruthy();
    // договаривались — контакты открыты: в полосе прошлой сделки, как после завершённой
    expect(headerButtons(header)).toEqual(['Договориться']);
    expect(screen.getByText('Прошлая сделка «Повесить люстру»')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Telegram: @aleksey_m' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Поделиться контактом' })).toBeTruthy();
  });

  it('shows the Telegram of a specialist they already agreed with in a new chat', async () => {
    const chat = withChats();
    const direct = chat.dialogs.get(CONVERSATION_IDS.direct);
    const job = chat.dialogs.get(CONVERSATION_IDS.job);
    if (!direct || !job) throw new Error('fixtures');
    // тот же мастер: по отклику договорились, прямой диалог с ним — без сделки
    job.conversation = { ...job.conversation, counterpart_id: direct.conversation.counterpart_id };
    chat.pastDeal(CONVERSATION_IDS.job, 'completed');
    direct.conversation = { ...direct.conversation, counterpart_telegram: '@aleksey_m' };
    startApp(`/messages/${CONVERSATION_IDS.direct}`);

    const header = await directHeader();
    expect(within(header).getByText('Сделки пока нет')).toBeTruthy();
    // сделки нет, контакты открыты: «Договориться» — в шапке, Telegram — в полосе «вы уже
    // договаривались»
    expect(headerButtons(header)).toEqual(['Договориться']);
    expect(screen.getByText('Вы уже договаривались — контакты открыты')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Договориться' })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Telegram: @aleksey_m' })).toBeTruthy();
    // делиться пока не по чему: сделки в этом диалоге нет
    expect(screen.queryByRole('button', { name: 'Поделиться контактом' })).toBeNull();
  });

  it('agrees again after a declined proposal with the contacts still closed', async () => {
    const chat = withChats();
    withDeal(chat, CONVERSATION_IDS.direct, 'cancelled');
    startApp(`/messages/${CONVERSATION_IDS.direct}`);

    const header = await directHeader();
    // не договаривались: делиться нечем, полосы отклонённого предложения нет
    expect(headerButtons(header)).toEqual(['Договориться']);
    expect(screen.queryByRole('button', { name: 'Поделиться контактом' })).toBeNull();
    expect(screen.queryByText(/сделка «Повесить люстру»/i)).toBeNull();
    // условия — та же шторка, «что делаем» — из отклонённого предложения
    await click(within(header).getByRole('button', { name: 'Договориться' }));
    const sheet = await screen.findByRole('dialog', { name: 'Договорились?' });
    expect(
      (within(sheet).getByRole('textbox', { name: 'Что делаем' }) as HTMLInputElement).value,
    ).toBe('Повесить люстру');
  });

  it('orders again from the response chat with a completed deal', async () => {
    const chat = withChats();
    chat.pastDeal(CONVERSATION_IDS.job, 'completed');
    const job = chat.dialogs.get(CONVERSATION_IDS.job);
    if (!job) throw new Error('fixtures');
    job.conversation = { ...job.conversation, counterpart_profile_id: SPECIALIST_PROFILE_ID };
    const { app } = startApp(`/messages/${CONVERSATION_IDS.job}`);

    const header = await screen.findByRole('banner', { name: 'Никола Петрович' });
    expect(headerButtons(header)).toEqual(['Заказать снова']);
    expect(screen.queryByRole('button', { name: 'К откликам' })).toBeNull();
    // «Поделиться контактом» — в полосе прошлой сделки
    expect(screen.getByRole('button', { name: 'Поделиться контактом' })).toBeTruthy();
    await click(within(header).getByRole('button', { name: 'Заказать снова' }));

    await waitFor(() => expect(chat.starts).toEqual([{ profile_id: SPECIALIST_PROFILE_ID }]));
    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(`/messages/${CONVERSATION_IDS.direct}`),
    );
    expect(headerButtons(await directHeader())).toEqual(['Договориться']);
  });

  it('still leads the client to the responses after the cancelled response deal', async () => {
    const chat = withChats();
    chat.pastDeal(CONVERSATION_IDS.job, 'cancelled');
    startApp(`/messages/${CONVERSATION_IDS.job}`);

    const header = await screen.findByRole('banner', { name: 'Никола Петрович' });
    // заявка снова открыта — «К откликам»; выбор отклика был договорённостью — контакты открыты
    expect(headerButtons(header)).toEqual(['К откликам']);
    expect(screen.queryByRole('button', { name: 'Заказать снова' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Поделиться контактом' })).toBeTruthy();
  });

  it('keeps sharing the contact for the performer after the completed deal', async () => {
    const chat = withChats();
    withDeal(chat, CONVERSATION_IDS.performer, 'completed');
    startApp(`/messages/${CONVERSATION_IDS.performer}`);

    const header = await screen.findByRole('banner', { name: 'Дмитрий Соколов' });
    // исполнителю снова отсюда нечего — «Сделка»; ссылки на неё в полосе нет
    expect(headerButtons(header)).toEqual(['Сделка']);
    expect(screen.getByText('Прошлая сделка «Повесить люстру»')).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Открыть сделку' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Поделиться контактом' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Заказать снова' })).toBeNull();
  });
});
