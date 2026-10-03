// S47 Помощь (DEVELOPMENT_PLAN 4.9) в приложении целиком на mock-платформе: правила безопасных
// сделок, вопросы-раскрывашки с поиском, правила площадки S48, MainButton «Написать в поддержку»
// по контакту из client-config (Q25) и неактивная «Поддержка — скоро» без него (K23).
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../../testing/app.tsx';
import { CLIENT_CONFIG } from '../../../testing/fixtures.ts';
import { server } from '../../../testing/msw.ts';

afterEach(() => setSession(null));

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

const question = (name: string) => screen.getByRole('button', { name });

describe('S47 help', () => {
  it('shows the safety rules and answers, the first one open', async () => {
    startApp('/help');

    expect(await screen.findByRole('heading', { name: 'Помощь', level: 1 })).toBeTruthy();
    const safety = screen.getByRole('region', { name: 'Безопасные сделки' });
    expect(
      within(safety)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual(['Не вносите предоплату незнакомым', 'Не переходите по ссылкам «для оплаты»']);
    const faq = screen.getByRole('region', { name: 'Частые вопросы' });
    expect(
      within(faq)
        .getAllByRole('button')
        .map((button) => button.textContent),
    ).toEqual([
      'Почему откликов не больше 5?',
      'Когда откроются контакты?',
      'Как оставить отзыв?',
      'Сколько стоят «Соседи»?',
    ]);
    expect(question('Почему откликов не больше 5?').getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText(/Так клиент не тонет в сообщениях/)).toBeTruthy();

    await click(question('Сколько стоят «Соседи»?'));
    expect(question('Сколько стоят «Соседи»?').getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText(/«Соседи» деньги не принимают/)).toBeTruthy();
    await click(question('Почему откликов не больше 5?'));
    expect(question('Почему откликов не больше 5?').getAttribute('aria-expanded')).toBe('false');
  });

  it('finds questions by words of the question or the answer', async () => {
    startApp('/help');
    const search = await screen.findByRole('searchbox', { name: 'Поиск по вопросам' });

    fireEvent.change(search, { target: { value: 'ДОГОВОРИЛИСЬ телефоны' } });

    const faq = screen.getByRole('region', { name: 'Частые вопросы' });
    expect(
      within(faq)
        .getAllByRole('button')
        .map((button) => button.textContent),
    ).toEqual(['Когда откроются контакты?']);
    // найденное раскрыто: ответ — то, что ищут
    expect(question('Когда откроются контакты?').getAttribute('aria-expanded')).toBe('true');

    fireEvent.change(search, { target: { value: 'кешбэк' } });
    expect(within(faq).queryAllByRole('button')).toEqual([]);
    expect(screen.getByRole('status').textContent).toBe(
      'Такого вопроса нет. Напишите в поддержку — ответим',
    );
  });

  it('opens the platform rules S48', async () => {
    const { app } = startApp('/help');
    const rules = await screen.findByRole('link', { name: /Правила площадки/ });
    expect(rules.getAttribute('href')).toBe('/legal/terms');

    await click(rules);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/legal/terms'));
  });

  it('is «Поддержка — скоро», inactive, until the support contact is set', async () => {
    const { telegram } = startApp('/help');
    await screen.findByRole('heading', { name: 'Помощь', level: 1 });

    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({
        is_visible: true,
        is_active: false,
        text: 'Поддержка — скоро',
      }),
    );
    await pressMainButton(telegram);
    expect(telegram.callsOf('web_app_open_tg_link')).toEqual([]);
  });

  it('writes to support — the same account as /help in the bot', async () => {
    server.use(
      http.get('*/api/v1/client-config', () =>
        HttpResponse.json({ ...CLIENT_CONFIG, support_username: 'sosedi_support' }),
      ),
    );
    const { telegram } = startApp('/help');
    await screen.findByRole('heading', { name: 'Помощь', level: 1 });

    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({
        is_visible: true,
        is_active: true,
        text: 'Написать в поддержку',
      }),
    );
    await pressMainButton(telegram);
    expect(telegram.callsOf('web_app_open_tg_link')).toEqual([{ path_full: '/sosedi_support' }]);
  });
});
