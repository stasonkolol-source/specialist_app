// Браузерная оболочка (DEVELOPMENT_PLAN 8.1): тот же SPA вне Telegram — веб-ссылка на карточку с
// превью того, кого прислали, «Посмотреть в браузере», своя кнопка «Назад» и MainButton в контенте;
// экраны, которых в браузере нет, и главная — лендинг с «Открыть в Telegram»; «Как удалить аккаунт»
// без входа; подвал с документами.
import { createBrowserPlatform } from '@sosed/platform';
import { uuidToBase62 } from '@sosed/links';
import { createMemoryHistory } from '@tanstack/react-router';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CARD_PROFILE_ID, E2E_NOW, HIDDEN_PROFILE_ID } from '../testing/fixtures.ts';
import { FEED_JOBS } from '../testing/jobsBackend.ts';
import { API_ORIGIN } from '../testing/msw.ts';
import { App } from './App.tsx';
import { assemble } from './bootstrap.ts';

const NAME = 'Алексей Морозов';

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

beforeEach(() => {
  // «сегодня 18:00–21:00» у заявки — по часам фикстур
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(E2E_NOW) });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe('браузерная оболочка', () => {
  it('/s/<id>: превью специалиста, «Посмотреть в браузере» — S08 гостем, «Назад» — обратно', async () => {
    start(`/s/${uuidToBase62(CARD_PROFILE_ID)}`);

    // кого прислали — тем же запросом, что S08
    expect(await screen.findByRole('heading', { name: NAME, level: 1 })).toBeTruthy();
    expect(screen.getByText('Электрик · мелкий ремонт · люстры')).toBeTruthy();
    expect(screen.getByText('4,9')).toBeTruthy();
    expect(screen.getByText('37 отзывов')).toBeTruthy();
    expect(screen.getByText('Лиман')).toBeTruthy();
    expect(screen.getByText('Телефон подтверждён')).toBeTruthy();
    expect(
      screen.getByText(
        'Написать мастеру и договориться можно в Telegram — в мини-приложении «Соседи».',
      ),
    ).toBeTruthy();
    // без бота в сборке ссылки на Telegram нет — объяснение вместо неё
    expect(screen.getByText(/Ссылка на Telegram появится/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Назад' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Посмотреть в браузере' }));

    expect(await screen.findByRole('button', { name: 'Написать' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: NAME, level: 1 })).toBeTruthy();
    // MainButton — в контенте, гостю без сердечка и жалобы; «Предложить заявку» — тот же мастер
    // заявки, которого в браузере нет: одна кнопка
    expect(screen.queryByRole('button', { name: 'Заказать напрямую' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Поделиться профилем' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /избранное/i })).toBeNull();
    expect(screen.queryByText('Пожаловаться на профиль')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
    expect(await screen.findByRole('button', { name: 'Посмотреть в браузере' })).toBeTruthy();
  });

  it('/s/<id> скрытого профиля — общий вариант без данных', async () => {
    start(`/s/${uuidToBase62(HIDDEN_PROFILE_ID)}`);

    expect(await screen.findByRole('heading', { name: 'Профиль специалиста' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Посмотреть в браузере' })).toBeTruthy();
  });

  it('/j/<id>: превью заявки — бюджет и срок, район и места', async () => {
    const job = FEED_JOBS[1]?.card;
    start(`/j/${uuidToBase62(job?.id ?? '')}`);

    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
    expect(screen.getByText('5 000 RSD · сегодня 18:00–21:00')).toBeTruthy();
    expect(await screen.findByText('Лиман · откликов 3 из 5')).toBeTruthy();
    expect(screen.getAllByRole('img', { name: /^Фото \d из 2$/ })).toHaveLength(2);
    expect(
      screen.getByText(
        'Откликнуться и написать клиенту можно в Telegram — в мини-приложении «Соседи».',
      ),
    ).toBeTruthy();
  });

  it('«Написать» гостем — лендинг со строкой «только в Telegram»', async () => {
    start(`/specialists/${CARD_PROFILE_ID}`);

    expect(await screen.findByRole('heading', { name: NAME, level: 1 })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Написать' }));

    expect(await screen.findByRole('heading', { name: 'Соседи', level: 1 })).toBeTruthy();
    expect(screen.getByText('Эта страница открывается только в Telegram.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Посмотреть в браузере' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
    expect(await screen.findByRole('heading', { name: NAME, level: 1 })).toBeTruthy();
  });

  it('с ботом в сборке «Написать в Telegram» сразу ведёт на этот профиль в Mini App', async () => {
    vi.stubEnv('VITE_TELEGRAM_BOT', 'sosed_bot');
    start(`/specialists/${CARD_PROFILE_ID}`);

    expect(await screen.findByRole('heading', { name: NAME, level: 1 })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Написать в Telegram' }).getAttribute('href')).toBe(
      `https://t.me/sosed_bot?startapp=s_${uuidToBase62(CARD_PROFILE_ID)}`,
    );
    // без промежуточной страницы: ни «Написать», ни «Предложить заявку»
    expect(screen.queryByRole('button', { name: 'Написать' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Заказать напрямую' })).toBeNull();
  });

  it('главная — лендинг: знак, правила площадки и подвал с документами', async () => {
    start('/');

    // h1 «Соседи» есть и у экрана запуска S01 — ждём слоган лендинга
    expect(
      await screen.findByText('Мастера рядом, на вашем языке. Нови-Сад, в Telegram.'),
    ).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Соседи', level: 1 })).toBeTruthy();
    expect(screen.queryByText('Эта страница открывается только в Telegram.')).toBeNull();
    const rules = screen.getByRole('list', { name: 'Правила площадки' });
    expect(
      within(rules)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual([
      'Отзывы — только по реальным сделкам.',
      'Контакты — после договорённости.',
      'Оплата — напрямую исполнителю, после работы.',
    ]);
    const footer = screen.getByRole('navigation', { name: 'Документы' });
    expect(
      within(footer)
        .getAllByRole('link')
        .map((link) => [link.textContent, link.getAttribute('href')]),
    ).toEqual([
      ['Правила площадки', '/legal/terms'],
      ['Конфиденциальность', '/legal/privacy'],
      ['Как удалить аккаунт', '/delete-account'],
    ]);
    // таббара в браузере нет
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();

    fireEvent.click(within(footer).getByRole('link', { name: 'Как удалить аккаунт' }));
    expect(
      await screen.findByRole('heading', { name: 'Как удалить аккаунт', level: 1 }),
    ).toBeTruthy();
  });

  it('битая ссылка — лендинг без строки о закрытом экране', async () => {
    start('/s/broken');
    expect(
      await screen.findByText('Мастера рядом, на вашем языке. Нови-Сад, в Telegram.'),
    ).toBeTruthy();
    expect(screen.queryByText('Эта страница открывается только в Telegram.')).toBeNull();
  });

  it('«Как удалить аккаунт» — инструкция без входа; без поддержки нет и фразы о ней', async () => {
    start('/delete-account');

    expect(
      await screen.findByRole('heading', { name: 'Как удалить аккаунт', level: 1 }),
    ).toBeTruthy();
    expect(screen.getByText('Отправьте боту «Соседей» команду /settings.')).toBeTruthy();
    expect(screen.getByText('Профиль, фото, прайс и портфолио')).toBeTruthy();
    // support_username в client-config фикстур не задан: ни кнопки, ни «Напишите в поддержку»
    expect(screen.queryByText(/Напишите в поддержку/)).toBeNull();
    // в подвале — документы, ссылки на саму страницу нет
    const footer = screen.getByRole('navigation', { name: 'Документы' });
    expect(within(footer).queryByRole('link', { name: 'Как удалить аккаунт' })).toBeNull();
    expect(within(footer).getByRole('link', { name: 'Правила площадки' })).toBeTruthy();
  });
});
