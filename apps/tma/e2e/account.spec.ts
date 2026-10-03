// Удаление аккаунта S45 (DEVELOPMENT_PLAN 2.12a): из настроек S43 (4.9), скриншоты × тема × язык и
// axe-core — у опубликованного специалиста, как на артборде (с «Нужна пауза?»); запрос и отмена —
// дата удаления на S31 и «Отменить». Имена скриншотов начинаются с кода артборда:
// make design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';

import { ME, PROFILE_FILLED } from '../src/testing/fixtures.ts';
import { ProfileBackend } from '../src/testing/profileBackend.ts';
import {
  THEMES,
  expectNoAxeViolations,
  open,
  openProfile,
  pressTelegram,
  real,
} from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Профиль',
    settings: 'Настройки',
    row: 'Удалить аккаунт',
    title: 'Удаление аккаунта',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Profil',
    settings: 'Podešavanja',
    row: 'Obriši nalog',
    title: 'Brisanje naloga',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S45 ${theme} ${l.locale}: что удалится и что останется`, async ({ page }) => {
      const profile = new ProfileBackend({ ...PROFILE_FILLED, status: 'published' });
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        profile,
      });
      await openProfile(page, l.tab);
      await page.getByRole('link', { name: l.settings, exact: true }).click();
      await page.getByRole('link', { name: l.row }).click();

      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S45-delete-account-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });
  }
}

test('S45 и S31: удаление через 7 дней и отмена из профиля', async ({ page }) => {
  const watch = await open(page, 'theme=light&lang=ru', { signedIn: true });
  await openProfile(page);
  await page.getByRole('link', { name: 'Настройки', exact: true }).click();
  await page.getByRole('link', { name: 'Удалить аккаунт' }).click();
  await expect(page.getByRole('heading', { name: 'Удаление аккаунта', level: 1 })).toBeVisible();

  await page.getByRole('checkbox', { name: /Понимаю/ }).click();
  const request = page.waitForRequest(
    (r) => r.method() === 'POST' && r.url().endsWith('/api/v1/me/deletion'),
  );
  await pressTelegram(page, 'main_button_pressed');
  await request;
  await expect(page.getByText('Аккаунт удалится 8 октября')).toBeVisible();

  // назад: S45 → настройки S43 → профиль S31
  await pressTelegram(page, 'back_button_pressed');
  await expect(page.getByRole('heading', { name: 'Настройки', level: 1 })).toBeVisible();
  await pressTelegram(page, 'back_button_pressed');
  const banner = page.getByRole('status').filter({ hasText: 'Аккаунт удалится 8 октября' });
  await expect(banner).toBeVisible();
  await banner.getByRole('button', { name: 'Отменить' }).click();
  await expect(banner).toBeHidden();
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});
