// Договорённость и контакты (DEVELOPMENT_PLAN 6.5) на фейках backend: S53 — «… предлагает
// договориться», условия, срок, «Подтвердить» и «Отклонить»; в сделке после договорённости —
// Telegram второй стороны и «Поделиться контактом» (в чат сделки, шторка открыта); S54 в чате —
// галочками Telegram и/или телефон из подписанного ответа Telegram; S43 — «Мой Telegram».
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { ChatBackend, CONVERSATION_IDS } from '../../testing/chatBackend.ts';
import { E2E_NOW } from '../../testing/fixtures.ts';
import {
  JobsBackend,
  dealCardFixture,
  myJobsFixture,
  proposedDealFixture,
  responseCardsFixture,
} from '../../testing/jobsBackend.ts';
import { chatHandlers, jobsHandlers, server } from '../../testing/msw.ts';

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

function withJobs(): JobsBackend {
  const backend = new JobsBackend().seedMine();
  server.use(...jobsHandlers(() => backend));
  return backend;
}

function withChats(): ChatBackend {
  const backend = new ChatBackend().seed();
  server.use(...chatHandlers(() => backend));
  return backend;
}

describe('S53 proposal', () => {
  it('shows the terms and the deadline and confirms the deal', async () => {
    const jobs = withJobs();
    const deal = proposedDealFixture(CONVERSATION_IDS.direct);
    jobs.deals.set(deal.id, deal);
    jobs.dealRole = 'performer';
    const { telegram } = startApp(`/deals/${deal.id}`);

    expect(
      await screen.findByRole('heading', { name: 'Елена К. предлагает договориться', level: 1 }),
    ).toBeTruthy();
    const terms = screen.getByRole('region', { name: 'Повесить люстру' });
    expect(within(terms).getByText('Что')).toBeTruthy();
    // район, а не город, — как на артборде
    expect(within(terms).getByText('Лиман')).toBeTruthy();
    expect(within(terms).getByText(/3\s500\sRSD/u)).toBeTruthy();
    expect(screen.getByText(/Если не ответить за 72 часа, договорённость отменится/)).toBeTruthy();

    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Подтвердить'));
    await pressMainButton(telegram);

    await waitFor(() => expect(jobs.decisions).toEqual([{ id: deal.id, action: 'confirm' }]));
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: 'Елена К. предлагает договориться' }),
      ).toBeNull(),
    );
    expect(screen.getAllByText('Договорились').length).toBeGreaterThan(0);
  });

  it('declines the proposal', async () => {
    const jobs = withJobs();
    const deal = proposedDealFixture(CONVERSATION_IDS.direct);
    jobs.deals.set(deal.id, deal);
    jobs.dealRole = 'performer';
    const { telegram } = startApp(`/deals/${deal.id}`);

    // «Отклонить» — SecondaryButton под MainButton, как на артборде: нативная, в DOM её нет
    await waitFor(() =>
      expect(telegram.callsOf('web_app_setup_secondary_button').at(-1)).toMatchObject({
        is_visible: true,
        text: 'Отклонить',
        position: 'bottom',
      }),
    );
    expect(screen.queryByRole('button', { name: 'Отклонить' })).toBeNull();
    await act(async () => {
      telegram.emit('secondary_button_pressed');
    });

    await waitFor(() => expect(jobs.decisions).toEqual([{ id: deal.id, action: 'decline' }]));
    expect(await screen.findByText('Отменена')).toBeTruthy();
  });
});

describe('S53 from the chat', () => {
  it('leads from the chat to the deal', async () => {
    withJobs();
    withChats();
    const { app } = startApp(`/messages/${CONVERSATION_IDS.performer}`);

    expect(await screen.findByText(/Сделка «Собрать шкаф PAX»/)).toBeTruthy();
    await click(screen.getByRole('link', { name: 'Открыть сделку' }));

    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(
        '/deals/01a0e003-0000-7000-8000-000000000001',
      ),
    );
  });

  it('offers the terms once the proposal is sent', async () => {
    withChats();
    startApp(`/messages/${CONVERSATION_IDS.direct}`);

    const header = await screen.findByRole('banner', { name: 'Алексей Морозов' });
    expect(screen.queryByRole('link', { name: 'Посмотреть условия' })).toBeNull();
    await click(within(header).getByRole('button', { name: 'Договориться' }));
    const sheet = await screen.findByRole('dialog', { name: 'Договорились?' });
    fireEvent.change(within(sheet).getByRole('textbox', { name: 'Что делаем' }), {
      target: { value: 'Повесить люстру' },
    });
    await click(within(sheet).getByRole('button', { name: 'Предложить' }));

    expect(await screen.findByRole('link', { name: 'Посмотреть условия' })).toBeTruthy();
  });
});

describe('contacts after the deal', () => {
  it('opens the Telegram of the other side and shares a contact from the deal', async () => {
    const jobs = withJobs();
    const chat = withChats();
    const [job] = myJobsFixture();
    const [card] = responseCardsFixture();
    if (!job || !card) throw new Error('fixtures');
    const deal = dealCardFixture(job, card, 'client');
    jobs.deals.set(deal.id, deal);
    const { app, telegram } = startApp(`/deals/${deal.id}`);

    const contacts = await screen.findByRole('region', { name: 'Контакты' });
    await click(within(contacts).getByRole('button', { name: /Telegram: @aleksey_m/ }));
    expect(
      telegram
        .callsOf('web_app_open_tg_link')
        .some((p) => String(p?.path_full).includes('aleksey_m')),
    ).toBe(true);

    await click(within(contacts).getByRole('button', { name: /Поделиться контактом/ }));
    await waitFor(() => expect(chat.starts).toEqual([{ response_id: card.id }]));
    await waitFor(() => expect(app.router.state.location.pathname).toMatch(/^\/messages\/[^/]+$/));
    expect(app.router.state.location.search).toEqual({ share: true });
  });

  it('shares Telegram and then the phone in the chat after the deal', async () => {
    const chat = withChats();
    const { telegram } = startApp(`/messages/${CONVERSATION_IDS.performer}`);

    // «Поделиться контактом» — второй строкой полосы сделки, шапка — без кнопок
    const header = await screen.findByRole('banner', { name: 'Дмитрий Соколов' });
    expect(within(header).queryByRole('button', { name: 'Поделиться контактом' })).toBeNull();
    await click(screen.getByRole('button', { name: 'Поделиться контактом' }));
    let sheet = await screen.findByRole('dialog', { name: 'Поделиться контактом' });
    expect(within(sheet).getByText('@elena_k')).toBeTruthy();
    await click(within(sheet).getByRole('button', { name: 'Поделиться' }));

    await waitFor(() => expect(chat.shares[0]?.contact_type).toBe('telegram'));
    expect(chat.shares[0]?.init_data).toContain('elena_k');
    expect(await screen.findByText('Telegram: @elena_k')).toBeTruthy();

    // галочки, как на артборде: телефон вместо Telegram
    await click(screen.getByRole('button', { name: 'Поделиться контактом' }));
    sheet = await screen.findByRole('dialog', { name: 'Поделиться контактом' });
    await click(within(sheet).getByRole('checkbox', { name: 'Имя пользователя Telegram' }));
    await click(within(sheet).getByRole('checkbox', { name: 'Номер телефона' }));
    await click(within(sheet).getByRole('button', { name: 'Поделиться' }));

    await waitFor(() => expect(chat.shares[1]?.contact_type).toBe('phone'));
    expect(chat.shares).toHaveLength(2);
    expect(chat.shares[1]?.contact).toContain('hash=');
    expect(telegram.callsOf('web_app_request_phone')).toHaveLength(1);
    expect(await screen.findByText('Телефон: +381641234567')).toBeTruthy();
  });

  it('shares both contacts at once', async () => {
    const chat = withChats();
    const { telegram } = startApp(`/messages/${CONVERSATION_IDS.performer}`);

    await screen.findByRole('banner', { name: 'Дмитрий Соколов' });
    await click(screen.getByRole('button', { name: 'Поделиться контактом' }));
    const sheet = await screen.findByRole('dialog', { name: 'Поделиться контактом' });
    const username = within(sheet).getByRole('checkbox', { name: 'Имя пользователя Telegram' });
    expect(username.getAttribute('aria-checked')).toBe('true');
    await click(within(sheet).getByRole('checkbox', { name: 'Номер телефона' }));
    await click(within(sheet).getByRole('button', { name: 'Поделиться' }));

    await waitFor(() =>
      expect(chat.shares.map((s) => s.contact_type)).toEqual(['telegram', 'phone']),
    );
    expect(telegram.callsOf('web_app_request_phone')).toHaveLength(1);
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Поделиться контактом' })).toBeNull(),
    );
  });

  it('opens the share sheet at once when asked from the deal', async () => {
    withChats();
    startApp(`/messages/${CONVERSATION_IDS.performer}?share=true`);

    expect(await screen.findByRole('dialog', { name: 'Поделиться контактом' })).toBeTruthy();
  });
});

describe('S43 privacy', () => {
  it('turns showing my Telegram off', async () => {
    startApp('/settings');

    const toggle = await screen.findByRole('switch', { name: 'Мой Telegram' });
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));
    await click(toggle);

    await waitFor(() =>
      expect(
        screen.getByRole('switch', { name: 'Мой Telegram' }).getAttribute('aria-checked'),
      ).toBe('false'),
    );
  });
});
