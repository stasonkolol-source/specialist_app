// Кабинет специалиста S33 и правка профиля S34 (DEVELOPMENT_PLAN 2.10): из карточки на S31,
// скриншоты × тема × язык, axe-core. Имена скриншотов начинаются с кода артборда: make
// design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';

import { FIRST_SERVICE, ME, PROFILE_FILLED } from '../src/testing/fixtures.ts';
import { ProfileBackend } from '../src/testing/profileBackend.ts';
import { THEMES, expectNoAxeViolations, open, openProfile, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Профиль',
    card: /Кабинет специалиста/,
    title: 'Кабинет специалиста',
    published: 'Профиль опубликован · виден в поиске',
    row: 'Профиль',
    edit: 'Редактирование профиля',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Profil',
    card: /Kabinet stručnjaka/,
    title: 'Kabinet stručnjaka',
    published: 'Profil je objavljen · vidljiv u pretrazi',
    row: 'Profil',
    edit: 'Izmena profila',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S33 и S34 ${theme} ${l.locale}: кабинет и правка профиля`, async ({ page }) => {
      const profile = new ProfileBackend({ ...PROFILE_FILLED, status: 'published' }, [
        FIRST_SERVICE,
      ]);
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

      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
      await expect(page.getByText(l.published)).toBeVisible();
      await snap(`S33-cabinet-${theme}-${l.locale}.png`);

      await page.getByRole('link', { name: l.row, exact: true }).click();
      await expect(page.getByRole('heading', { name: l.edit, level: 1 })).toBeVisible();
      await snap(`S34-edit-profile-${theme}-${l.locale}.png`);
    });
  }
}
