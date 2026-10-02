// Карточка специалиста S08–S10 (DEVELOPMENT_PLAN 4.5) гостем: поиск на главной → выдача S05 →
// профиль S08 → «Весь прайс» S09 → «Назад» → работа → просмотрщик S10 на тёмном фоне. Ссылка
// `startapp=s_…` открывает S08 сразу; скрытый профиль — «Профиль недоступен». Скриншоты × тема ×
// язык, axe-core; часы браузера — E2E_NOW: «Сегодня до 20:00», как на макете S08.
import { encodeStartParam } from '@sosed/links';
import { expect, test } from '@playwright/test';

import { CARD_PROFILE_ID, E2E_NOW, HIDDEN_PROFILE_ID } from '../src/testing/fixtures.ts';
import { THEMES, expectNoAxeViolations, open, pressTelegram, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    query: 'электрик',
    prices: 'Весь прайс · 9',
    priceTitle: 'Прайс',
    work: 'Люстра, Лиман',
    position: '1 / 18',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    query: 'električar',
    prices: 'Ceo cenovnik · 9',
    priceTitle: 'Cenovnik',
    work: 'Люстра, Лиман',
    position: '1 / 18',
  },
] as const;

const NAME = 'Алексей Морозов';
const deepLink = (id: string) => encodeStartParam({ type: 'specialist', id });

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S08, S09 и S10 ${theme} ${l.locale}: карточка из выдачи`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`);
      /** Снимок экрана: до него — ни ошибок, ни неописанных запросов, после — axe-core. */
      const snap = async (name: string, fullPage = true) => {
        expect(real(watch.problems)).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(name, { fullPage });
        await expectNoAxeViolations(page);
        watch.problems.length = 0;
      };

      // главная → поиск → выдача S05 → карточка
      await page.getByRole('searchbox').fill(l.query);
      await page.getByRole('searchbox').press('Enter');
      await page.getByRole('link', { name: new RegExp(NAME) }).click();
      await expect(page.getByRole('heading', { name: NAME, level: 1 })).toBeVisible();
      await snap(`S08-profile-${theme}-${l.locale}.png`);

      await page.getByRole('link', { name: l.prices }).click();
      await expect(page.getByRole('heading', { name: l.priceTitle, level: 1 })).toBeVisible();
      await snap(`S09-prices-${theme}-${l.locale}.png`);

      await pressTelegram(page, 'back_button_pressed');
      await page.getByRole('link', { name: l.work }).click();
      await expect(page.getByText(l.position)).toBeVisible();
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
      // просмотрщик во весь экран: снимок экрана, как артборд 390×844
      await snap(`S10-portfolio-${theme}-${l.locale}.png`, false);

      await pressTelegram(page, 'back_button_pressed');
      await expect(page.getByRole('heading', { name: NAME, level: 1 })).toBeVisible();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    });
  }
}

test('deeplink-s: startapp=s_… открывает профиль S08, «Назад» — на главную', async ({ page }) => {
  const watch = await open(page, `theme=light&lang=ru&start=${deepLink(CARD_PROFILE_ID)}`);

  await expect(page.getByRole('heading', { name: NAME, level: 1 })).toBeVisible();
  await pressTelegram(page, 'back_button_pressed');
  await expect(page.getByRole('heading', { name: 'Главная', level: 1 })).toBeVisible();
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});

test('deeplink-s: скрытый профиль — «Профиль недоступен»', async ({ page }) => {
  const watch = await open(page, `theme=light&lang=ru&start=${deepLink(HIDDEN_PROFILE_ID)}`);

  await expect(page.getByRole('heading', { name: 'Профиль недоступен' })).toBeVisible();
  await expectNoAxeViolations(page);
  // 404 BFF — по контракту: профиль скрыт; браузер пишет его в консоль ошибкой
  expect(real(watch.problems, ['404'])).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});
