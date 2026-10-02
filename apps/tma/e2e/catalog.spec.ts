// Каталог S04–S06 (DEVELOPMENT_PLAN 4.4) гостем, без входа: S03 «Все услуги» → S04, раздел
// раскрывается → услуга → выдача S05 → «Фильтры» → шторка S06. Скриншоты × тема × язык, axe-core.
// Часы браузера — E2E_NOW: «Сегодня до 20:00», как на макете S05. Имена скриншотов начинаются
// с кода артборда: make design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';

import { E2E_NOW } from '../src/testing/fixtures.ts';
import { THEMES, expectNoAxeViolations, open, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    all: 'Все услуги',
    group: /Мастер на час/,
    leaf: /Электрика/,
    card: 'Алексей Морозов',
    filters: /^Фильтры/,
    sheet: 'Фильтры',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    all: 'Sve usluge',
    group: /Majstor na sat/,
    leaf: /Elektrika/,
    card: 'Алексей Морозов',
    filters: /^Filteri/,
    sheet: 'Filteri',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S04, S05 и S06 ${theme} ${l.locale}: каталог гостю`, async ({ page }) => {
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

      await page.getByRole('link', { name: l.all }).click();
      await expect(page.getByRole('heading', { name: l.all, level: 1 })).toBeVisible();
      await page.getByRole('button', { name: l.group }).click();
      await expect(page.getByRole('link', { name: l.leaf })).toBeVisible();
      await snap(`S04-categories-${theme}-${l.locale}.png`);

      await page.getByRole('link', { name: l.leaf }).click();
      await expect(page.getByText(l.card)).toBeVisible();
      await snap(`S05-results-${theme}-${l.locale}.png`);

      await page.getByRole('button', { name: l.filters }).click();
      await expect(page.getByRole('dialog', { name: l.sheet })).toBeVisible();
      // шторка закреплена на экране: снимок экрана, как артборд 390×844, а не всей страницы
      await snap(`S06-filters-${theme}-${l.locale}.png`, false);
    });
  }
}
