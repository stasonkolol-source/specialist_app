// Прайс S35 и позиция S36 (DEVELOPMENT_PLAN 2.11): из кабинета S33, скриншоты × тема × язык,
// axe-core. Прайс — как на артборде S35. Имена скриншотов начинаются с кода артборда: make
// design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';

import { ME, PRICE_LIST, PROFILE_FILLED } from '../src/testing/fixtures.ts';
import { ProfileBackend } from '../src/testing/profileBackend.ts';
import { THEMES, expectNoAxeViolations, open, openProfile, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Профиль',
    card: /Кабинет специалиста/,
    prices: /^Прайс/,
    title: 'Прайс-лист',
    item: /Установка люстры/,
    itemTitle: 'Позиция прайса',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Profil',
    card: /Kabinet stručnjaka/,
    prices: /^Cenovnik/,
    title: 'Cenovnik',
    item: /Установка люстры/,
    itemTitle: 'Stavka cenovnika',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S35 и S36 ${theme} ${l.locale}: прайс и позиция`, async ({ page }) => {
      const profile = new ProfileBackend({ ...PROFILE_FILLED, status: 'published' }, PRICE_LIST);
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        profile,
      });
      /** Снимок экрана: до него — ни ошибок, ни неописанных запросов, после — axe-core. */
      const snap = async (name: string) => {
        expect(real(watch.problems)).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(name, { fullPage: true });
        await expectNoAxeViolations(page);
        // снимок вставляет стиль «без анимаций» — CSP приложения в WebKit его отклоняет и пишет
        // в консоль; дальше проверяем только то, что случилось после снимка
        watch.problems.length = 0;
      };
      await openProfile(page, l.tab);
      await page.getByRole('link', { name: l.card }).click();
      await page.getByRole('link', { name: l.prices }).click();

      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
      await snap(`S35-price-list-${theme}-${l.locale}.png`);

      await page.getByRole('link', { name: l.item }).click();
      await expect(page.getByRole('heading', { name: l.itemTitle, level: 1 })).toBeVisible();
      await snap(`S36-price-item-${theme}-${l.locale}.png`);
    });
  }
}
