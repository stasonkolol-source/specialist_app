// Сообщения S29 и диалог S30 (DEVELOPMENT_PLAN 6.4) на фейке backend: список с именами, заявкой,
// сделкой, «Вы: …», коротким временем и непрочитанными, вкладки по роли; диалог — шапка, памятка о
// предоплате, подписи дней, маска контакта словами с подсказкой, отметка прочитанного,
// оптимистичная отправка и повтор неотправленного, новое от собеседника при опросе, «Договориться»
// шторкой условий, клиенту по отклику — «К откликам»; «Написать» на S08 открывает диалог; deep
// link `c_`; бейдж «Сообщения N» в таббаре.
import { encodeStartParam } from '@sosed/links';
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { http } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { problem } from '../../testing/backend.ts';
import { ChatBackend, CONVERSATION_IDS } from '../../testing/chatBackend.ts';
import { CARD_PROFILE_ID, E2E_NOW } from '../../testing/fixtures.ts';
import { chatHandlers, server } from '../../testing/msw.ts';

const DIRECT = `/messages/${CONVERSATION_IDS.direct}`;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(E2E_NOW) });
});
afterEach(() => {
  vi.useRealTimers();
  setSession(null);
});

function withChats(): ChatBackend {
  const backend = new ChatBackend().seed();
  server.use(...chatHandlers(() => backend));
  return backend;
}

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

describe('S29 chats', () => {
  it('lists dialogs with the counterpart, context, deal, last message and unread', async () => {
    withChats();
    const { app } = startApp('/messages');

    const direct = await screen.findByRole('link', { name: /Алексей Морозов/ });
    expect(within(direct).getByText('Из профиля специалиста')).toBeTruthy();
    expect(within(direct).getByText(/Позвоните мне/)).toBeTruthy();
    // скрытый сервером телефон — словами, как в диалоге
    expect(within(direct).getByText('контакт скрыт')).toBeTruthy();
    expect(within(direct).getByText('2 непрочитанных')).toBeTruthy();
    // время как в Telegram: за последнюю неделю — день недели (сейчас понедельник, 5 октября)
    expect(within(direct).getByText('пт')).toBeTruthy();
    const job = screen.getByRole('link', { name: /Никола Петрович/ });
    expect(within(job).getByText('Заявка: Повесить люстру')).toBeTruthy();
    // отклик — плашкой рядом с заявкой, текст отклика — без приписки
    expect(within(job).getByText('Отклик')).toBeTruthy();
    expect(within(job).getByText('Mogu danas posle 18h')).toBeTruthy();
    const mine = screen.getByRole('link', { name: /Дмитрий Соколов/ });
    expect(within(mine).getByText('Договорились')).toBeTruthy();
    expect(within(mine).getByText('Вы: Спасибо, тогда до четверга!')).toBeTruthy();
    expect(within(mine).getByText('чт')).toBeTruthy();
    expect(screen.getByText('Телефоны и ссылки видны только после договорённости')).toBeTruthy();

    const tabs = screen.getByRole('radiogroup', { name: 'Сообщения' });
    await click(within(tabs).getByRole('radio', { name: 'Я исполнитель' }));
    await waitFor(() => expect(screen.queryByRole('link', { name: /Алексей Морозов/ })).toBeNull());
    expect(screen.getByRole('link', { name: /Дмитрий Соколов/ })).toBeTruthy();
    await click(within(tabs).getByRole('radio', { name: 'Все' }));

    await click(await screen.findByRole('link', { name: /Алексей Морозов/ }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(DIRECT));
  });

  it('opens a dialog with its header from the list while messages load', async () => {
    withChats();
    startApp('/messages');
    const direct = await screen.findByRole('link', { name: /Алексей Морозов/ });
    // сообщения отвечают долго: собеседник и сделка — из списка, пузыри — скелетоном
    server.use(
      http.get(
        `*/api/v1/conversations/${CONVERSATION_IDS.direct}/messages`,
        () => new Promise<never>(() => undefined),
      ),
    );
    await click(direct);

    expect(await screen.findByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeTruthy();
    // сделки нет — и строки о ней нет, без «Сделки пока нет» (UX_GUIDANCE №8)
    expect(screen.queryByText('Сделки пока нет')).toBeNull();
    expect(screen.getByRole('img', { name: 'Алексей Морозов' })).toBeTruthy();
    // кнопки шапки и поле ввода — только по ответу диалога
    expect(screen.queryByRole('button', { name: 'Договориться' })).toBeNull();
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('shows the unread count on the Messages tab', async () => {
    withChats();
    startApp('/messages');

    const tabs = await screen.findByRole('navigation', { name: 'Разделы' });
    // два от Алексея и отклик Николы
    expect(await within(tabs).findByLabelText('3 непрочитанных сообщения')).toBeTruthy();
  });

  it('says there is nothing yet without dialogs', async () => {
    startApp('/messages');

    expect(await screen.findByRole('heading', { name: 'Сообщений пока нет' })).toBeTruthy();
  });
});

describe('S30 chat', () => {
  it('shows the counterpart, the safety note, masked contacts and marks new as read', async () => {
    const backend = withChats();
    startApp(DIRECT);

    const header = await screen.findByRole('banner', { name: 'Алексей Морозов' });
    expect(within(header).queryByText('Сделки пока нет')).toBeNull();
    expect(within(header).getByRole('link', { name: /Алексей Морозов/ })).toBeTruthy();
    expect(screen.getByText(/Не вносите предоплату незнакомым исполнителям/)).toBeTruthy();
    // день — подписью над первым сообщением, а не в строке о начале диалога
    expect(screen.getByText('Диалог из профиля специалиста')).toBeTruthy();
    const day = screen.getByText('2 октября');
    expect(day.getAttribute('dateTime')).toBe('2026-10-02');
    expect(screen.getAllByText(/октября/)).toHaveLength(1);
    // «•••» сервера — плашкой «контакт скрыт»; диктору — до каких пор
    expect(screen.queryByText('•••')).toBeNull();
    expect(screen.getByText('контакт скрыт')).toBeTruthy();
    expect(screen.getByText('Контакт скрыт до договорённости')).toBeTruthy();
    expect(
      screen.getByText('Контакты откроются после договорённости — так безопаснее'),
    ).toBeTruthy();
    await waitFor(() => expect(backend.reads).toHaveLength(1));
  });

  it('sends at once, repeats a failed send with the same key and polls new messages', async () => {
    const backend = withChats();
    const { app } = startApp(DIRECT);
    const field = await screen.findByLabelText('Сообщение');

    backend.failNext = problem(500, 'internal');
    fireEvent.change(field, { target: { value: 'Буду ждать в 19:00' } });
    await click(screen.getByRole('button', { name: 'Отправить' }));
    const failed = await screen.findByRole('button', { name: /Буду ждать в 19:00/ });
    // переписка — от 2 октября, сегодня 5-е: новое — под подписью «Сегодня»
    expect(screen.getByText('Сегодня')).toBeTruthy();
    expect(within(failed).getByText('Не отправлено — нажмите, чтобы повторить')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBeTruthy();

    await click(failed);
    await waitFor(() => expect(backend.sent).toHaveLength(1));
    await waitFor(() =>
      expect(screen.queryByText('Не отправлено — нажмите, чтобы повторить')).toBeNull(),
    );
    expect(screen.getByText('Буду ждать в 19:00')).toBeTruthy();

    backend.incoming(CONVERSATION_IDS.direct, 'Хорошо, до встречи!');
    await act(async () => {
      await app.queryClient.invalidateQueries();
    });
    expect(await screen.findByText('Хорошо, до встречи!')).toBeTruthy();
  });

  it('proposes a deal in a direct dialog', async () => {
    const backend = withChats();
    startApp(DIRECT);

    await click(await screen.findByRole('button', { name: 'Договориться' }));
    const sheet = await screen.findByRole('dialog', { name: 'Договорились?' });
    const propose = within(sheet).getByRole('button', { name: 'Предложить' });
    expect((propose as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(sheet).getByLabelText('Что делаем'), {
      target: { value: 'Повесить люстру' },
    });
    fireEvent.change(within(sheet).getByLabelText('Цена, RSD'), { target: { value: '3500' } });
    await click(propose);

    await waitFor(() =>
      expect(backend.proposals).toEqual([
        { title: 'Повесить люстру', price_type: 'fixed', price_amount: 350_000 },
      ]),
    );
    const header = await screen.findByRole('banner', { name: 'Алексей Морозов' });
    await waitFor(() => expect(within(header).getByText('Ждёт подтверждения')).toBeTruthy());
    expect(within(header).queryByRole('button', { name: 'Договориться' })).toBeNull();
    // одна строка от сервера: кто и до когда отвечает, как узнать о решении (UX_GUIDANCE №14)
    expect(
      await screen.findByText(
        /^Условия отправлены\. Алексей Морозов может подтвердить до\s8\sоктября/u,
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/ждём подтверждения/)).toBeNull();
  });

  it('tells the client of an empty dialog what to write and how the answer comes (№8)', async () => {
    const backend = withChats();
    const dialog = backend.dialogs.get(CONVERSATION_IDS.direct);
    if (!dialog) throw new Error('fixtures');
    dialog.messages = [];
    startApp(DIRECT);

    expect(
      await screen.findByText(/^Опишите задачу: что, где и\sкогда\. Алексей Морозов получит/u),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Договориться' })).toBeTruthy();
  });

  it('leads the client of a response dialog to the responses', async () => {
    withChats();
    const { app } = startApp(`/messages/${CONVERSATION_IDS.job}`);

    expect(await screen.findByText('Отклик на заявку')).toBeTruthy();
    expect(screen.getByText(/Цена: 3\s500\sRSD/u)).toBeTruthy();
    expect(screen.getByText('Когда: Сегодня, 19:00')).toBeTruthy();
    await click(screen.getByRole('button', { name: 'К откликам' }));

    await waitFor(() =>
      expect(app.router.state.location.pathname).toMatch(/^\/jobs\/[^/]+\/manage$/),
    );
  });

  it('opens from a `c_` link', async () => {
    withChats();
    const startParam = encodeStartParam({ type: 'chat', id: CONVERSATION_IDS.direct });
    const first = startApp('/', { startParam });
    await waitFor(() => expect(first.app.router.state.location.pathname).toBe(DIRECT));
    expect(await screen.findByRole('banner', { name: 'Алексей Морозов' })).toBeTruthy();
  });

  it('starts a dialog from «Написать» on S08', async () => {
    const backend = withChats();
    const { app, telegram } = startApp(`/specialists/${CARD_PROFILE_ID}`);

    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Написать'));
    await pressMainButton(telegram);

    await waitFor(() => expect(backend.starts).toEqual([{ profile_id: CARD_PROFILE_ID }]));
    await waitFor(() => expect(app.router.state.location.pathname).toMatch(/^\/messages\/[^/]+$/));
  });
});
