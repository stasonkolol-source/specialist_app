// Портфолио S37, работа и фото профиля S34 (DEVELOPMENT_PLAN 2.11): из кабинета S33. Скриншоты ×
// тема × язык и axe-core — на портфолио артборда S37; загрузка — настоящим веб-транспортом (XHR,
// холст) в «хранилище» page.route: фото становится работой и фото профиля. Имена скриншотов
// начинаются с кода артборда: make design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';

import { FIRST_SERVICE, ME, PORTFOLIO, PROFILE_FILLED } from '../src/testing/fixtures.ts';
import { ProfileBackend } from '../src/testing/profileBackend.ts';
import { PHOTO_PNG } from './api.ts';
import {
  THEMES,
  expectNoAxeViolations,
  open,
  openProfile,
  pressTelegram,
  real,
} from './support.ts';

const PUBLISHED = { ...PROFILE_FILLED, status: 'published' as const };

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Профиль',
    card: /Кабинет специалиста/,
    portfolio: /^Портфолио/,
    count: '16 работ',
    workTitle: 'Работа',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Profil',
    card: /Kabinet stručnjaka/,
    portfolio: /^Portfolio/,
    count: '16 radova',
    workTitle: 'Rad',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S37 ${theme} ${l.locale}: портфолио и работа`, async ({ page }) => {
      const profile = new ProfileBackend(PUBLISHED, [FIRST_SERVICE], { works: PORTFOLIO });
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
      await page.getByRole('link', { name: l.portfolio }).click();

      await expect(page.getByText(l.count)).toBeVisible();
      await snap(`S37-portfolio-edit-${theme}-${l.locale}.png`);

      await page.getByRole('link', { name: 'Щиток', exact: true }).click();
      await expect(page.getByRole('heading', { name: l.workTitle, level: 1 })).toBeVisible();
      await snap(`S37-work-${theme}-${l.locale}.png`);
    });
  }
}

test('S37 и S34: фото уходит в хранилище и становится работой и фото профиля', async ({ page }) => {
  const profile = new ProfileBackend(PUBLISHED, [FIRST_SERVICE], { works: PORTFOLIO.slice(0, 1) });
  const watch = await open(page, 'theme=light&lang=ru', { signedIn: true, profile });
  await openProfile(page, 'Профиль');
  await page.getByRole('link', { name: /Кабинет специалиста/ }).click();
  await page.getByRole('link', { name: /^Портфолио/ }).click();
  await expect(page.getByText('1 работа')).toBeVisible();

  const works = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Фото или видео' }).click();
  await (await works).setFiles({ name: 'kitchen.png', mimeType: 'image/png', buffer: PHOTO_PNG });

  await expect(page.getByText('2 работы')).toBeVisible();
  await expect(page.getByRole('img', { name: 'Работа 2' })).toHaveAttribute('srcset', /\/cdn\//);
  expect(profile.works.map((work) => work.media?.status)).toEqual(['ready', 'ready']);

  await pressTelegram(page, 'back_button_pressed');
  await page.getByRole('link', { name: 'Профиль', exact: true }).click();
  const avatar = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Изменить фото' }).click();
  await (await avatar).setFiles({ name: 'me.png', mimeType: 'image/png', buffer: PHOTO_PNG });

  const photo = page.getByRole('region', { name: 'Фото профиля' });
  await expect(photo.getByText('Ваше фото')).toBeVisible();
  await expect(photo.getByRole('img')).toHaveAttribute('src', /\/cdn\/.+\/thumb\.webp$/);
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});
