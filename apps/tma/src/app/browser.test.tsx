// Браузерная оболочка (DEVELOPMENT_PLAN 8.1): тот же SPA вне Telegram — веб-ссылка на карточку,
// «Продолжить в браузере», своя кнопка «Назад» и MainButton в контенте; экраны, которых в браузере
// нет, — «Открыть в Telegram»; «Как удалить аккаунт» без входа.
import { createBrowserPlatform } from '@sosed/platform';
import { uuidToBase62 } from '@sosed/links';
import { createMemoryHistory } from '@tanstack/react-router';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CARD_PROFILE_ID } from '../testing/fixtures.ts';
import { API_ORIGIN } from '../testing/msw.ts';
import { App } from './App.tsx';
import { assemble } from './bootstrap.ts';

function start(path: string) {
  const app = assemble(createBrowserPlatform(), {
    version: '0.1.0',
    history: createMemoryHistory({ initialEntries: [path] }),
    languages: ['ru'],
    baseUrl: API_ORIGIN,
  });
  render(<App {...app} />);
  return app;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('браузерная оболочка', () => {
  it('/s/<id>: «Продолжить в браузере» — S08 гостем, «Назад» — обратно', async () => {
    start(`/s/${uuidToBase62(CARD_PROFILE_ID)}`);

    expect(await screen.findByRole('heading', { name: 'Профиль специалиста' })).toBeTruthy();
    // без бота в сборке ссылки на Telegram нет — объяснение вместо неё
    expect(screen.getByText(/Ссылка на Telegram появится/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Назад' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Продолжить в браузере' }));

    expect(await screen.findByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeTruthy();
    // MainButton — в контенте, гостю без сердечка и жалобы; «Предложить заявку» — тот же мастер
    // заявки, которого в браузере нет: одна кнопка
    expect(screen.getByRole('button', { name: 'Написать' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Предложить заявку' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Поделиться профилем' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /избранное/i })).toBeNull();
    expect(screen.queryByText('Пожаловаться на профиль')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
    expect(await screen.findByRole('heading', { name: 'Профиль специалиста' })).toBeTruthy();
  });

  it('«Написать» гостем — «Открыть в Telegram»: мастера заявки в браузере нет', async () => {
    start(`/specialists/${CARD_PROFILE_ID}`);

    expect(await screen.findByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Написать' }));

    expect(await screen.findByRole('heading', { name: '«Соседи» живут в Telegram' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Продолжить в браузере' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
    expect(await screen.findByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeTruthy();
  });

  it('с ботом в сборке «Написать в Telegram» сразу ведёт на этот профиль в Mini App', async () => {
    vi.stubEnv('VITE_TELEGRAM_BOT', 'sosed_bot');
    start(`/specialists/${CARD_PROFILE_ID}`);

    expect(await screen.findByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Написать в Telegram' }).getAttribute('href')).toBe(
      `https://t.me/sosed_bot?startapp=s_${uuidToBase62(CARD_PROFILE_ID)}`,
    );
    // без промежуточной страницы: ни «Написать», ни «Предложить заявку»
    expect(screen.queryByRole('button', { name: 'Написать' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Предложить заявку' })).toBeNull();
  });

  it('главная и битая ссылка — «Открыть в Telegram»', async () => {
    start('/s/broken');
    expect(await screen.findByRole('heading', { name: '«Соседи» живут в Telegram' })).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();
  });

  it('«Как удалить аккаунт» — инструкция без входа', async () => {
    start('/delete-account');

    expect(
      await screen.findByRole('heading', { name: 'Как удалить аккаунт', level: 1 }),
    ).toBeTruthy();
    expect(screen.getByText('Отправьте боту «Соседей» команду /settings.')).toBeTruthy();
    expect(screen.getByText('Профиль, фото, прайс и портфолио')).toBeTruthy();
  });
});
