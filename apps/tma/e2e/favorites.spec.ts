// Отзывы S11 и избранное S12 (DEVELOPMENT_PLAN 4.6): профиль S08 → «Все 37» → сводка рейтинга и
// отзывы, на третий — ответ специалиста (7.3), как на артборде; вошедший: профиль S31 → «Избранное» → три мастера, как на артборде, сердечко убирает
// из списка. Скриншоты × тема × язык, axe-core; часы браузера — E2E_NOW: «Сегодня до 20:00».
import { encodeStartParam } from '@sosed/links';
import { expect, test } from '@playwright/test';

import {
  CARD_PROFILE_ID,
  E2E_AVAILABLE_UNTIL,
  E2E_NOW,
  ME,
  cardsFor,
} from '../src/testing/fixtures.ts';
import { FavoritesBackend } from '../src/testing/favoritesBackend.ts';
import { THEMES, expectNoAxeViolations, open, openProfile, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    all: 'Все 37',
    reviews: 'Отзывы',
    reply: 'Ответ специалиста',
    favorites: 'Избранное',
    profile: 'Профиль',
    remove: 'Убрать из избранного: Ольга Власова',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    all: 'Svi 37',
    reviews: 'Utisci',
    reply: 'Odgovor stručnjaka',
    favorites: 'Omiljeni',
    profile: 'Profil',
    remove: 'Ukloni iz omiljenih: Ольга Власова',
  },
] as const;

/** Мастера артборда S12: Алексей Морозов, Мария Ковалёва, Ольга Власова. */
const SAVED = [0, 1, 3].map((index) => cardsFor('ru')[index]?.profile_id ?? '');

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S11 ${theme} ${l.locale}: отзывы о специалисте`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const start = encodeStartParam({ type: 'specialist', id: CARD_PROFILE_ID });
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${start}`);

      await page.getByRole('link', { name: l.all }).click();
      await expect(page.getByRole('heading', { name: l.reviews, level: 1 })).toBeVisible();
      await expect(page.getByRole('article')).toHaveCount(3);
      await expect(page.getByRole('article').nth(2).getByText(l.reply)).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S11-reviews-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });

    test(`S12 ${theme} ${l.locale}: избранное из профиля`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const favorites = new FavoritesBackend(SAVED, E2E_AVAILABLE_UNTIL);
      // язык интерфейса вошедшего — из /me
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        favorites,
      });

      await openProfile(page, l.profile);
      await page.getByRole('link', { name: l.favorites }).click();
      await expect(page.getByRole('heading', { name: l.favorites, level: 1 })).toBeVisible();
      await expect(page.getByRole('article')).toHaveCount(3);
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S12-favorites-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);

      await page.getByRole('button', { name: l.remove }).click();
      await expect(page.getByRole('article')).toHaveCount(2);
      expect(favorites.ids).toEqual([SAVED[0], SAVED[1]]);
    });
  }
}
