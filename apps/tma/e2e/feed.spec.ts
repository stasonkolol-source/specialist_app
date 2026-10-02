// Лента заявок S13–S15 (DEVELOPMENT_PLAN 5.3) на фейке backend: вкладка «Заявки» → «До 3 км» →
// шторка S14 с «Мастер на час» → «Показать 3 заявки» → лента S13, как на артборде (тёмная — D13)
// → заявка S15; сохранённые заявки — сегмент «Задачи» избранного S12. Скриншоты × тема × язык,
// axe-core. Часы браузера — E2E_NOW (10:00 по Белграду): окно «18–21» ещё сегодня. Ссылка
// `startapp=j_…` открывает S15 сразу. Имена скриншотов начинаются с кода артборда: make
// design-compare кладёт их рядом с эталоном.
import { encodeStartParam } from '@sosed/links';
import { expect, test } from '@playwright/test';

import { E2E_NOW, ME } from '../src/testing/fixtures.ts';
import { FEED_JOBS, JobsBackend } from '../src/testing/jobsBackend.ts';
import {
  THEMES,
  expectNoAxeViolations,
  open,
  openProfile,
  openTab,
  pressTelegram,
  real,
} from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Заявки',
    feed: 'Заявки рядом',
    near: 'До 3 км',
    filters: /^Фильтры/,
    sheet: 'Фильтры',
    handyman: 'Мастер на час',
    radius: 'Радиус от вас · Лиман',
    found: '3 заявки по фильтрам · новые сверху',
    job: 'Повесить люстру',
    client: 'В «Соседях» 3 месяца · 2 заявки',
    profile: 'Профиль',
    favorites: 'Избранное',
    savedJobs: 'Задачи · 2',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Zahtevi',
    feed: 'Zahtevi u blizini',
    near: 'Do 3 km',
    filters: /^Filteri/,
    sheet: 'Filteri',
    handyman: 'Majstor na sat',
    radius: 'Radijus od vas · Liman',
    found: '3 zahteva po filterima · najnoviji prvi',
    job: 'Повесить люстру',
    client: 'U aplikaciji „Sosedi“ 3 meseca · 2 zahteva',
    profile: 'Profil',
    favorites: 'Omiljeni',
    savedJobs: 'Zadaci · 2',
  },
] as const;

const LEAK = FEED_JOBS[0]?.card.id ?? '';
const CHANDELIER = FEED_JOBS[1]?.card.id ?? '';

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S13, S14 и S15 ${theme} ${l.locale}: лента с фильтрами и заявка`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs: new JobsBackend(),
      });
      /** Снимок экрана: до него — ни ошибок, ни неописанных запросов, после — axe-core. */
      const snap = async (name: string, fullPage = true) => {
        expect(real(watch.problems)).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(name, { fullPage });
        await expectNoAxeViolations(page);
        // снимок вставляет стиль «без анимаций» — CSP приложения в WebKit его отклоняет и пишет
        // в консоль; дальше проверяем только то, что случилось после снимка
        watch.problems.length = 0;
      };

      await openTab(page, l.tab);
      await expect(page.getByRole('heading', { name: l.feed, level: 1 })).toBeVisible();
      await page.getByRole('button', { name: l.near }).click();
      await expect(page.getByRole('button', { name: l.near, pressed: true })).toBeVisible();

      await page.getByRole('button', { name: l.filters }).click();
      const sheet = page.getByRole('dialog', { name: l.sheet });
      await expect(sheet.getByText(l.radius)).toBeVisible();
      await sheet.getByRole('button', { name: l.handyman }).click();
      await expect(sheet.getByRole('button', { name: l.handyman, pressed: true })).toBeVisible();
      // шторка закреплена на экране: снимок экрана, как артборд 390×844, а не всей страницы
      await snap(`S14-feed-filters-${theme}-${l.locale}.png`, false);

      await pressTelegram(page, 'main_button_pressed');
      await expect(sheet).toBeHidden();
      await expect(page.getByText(l.found)).toBeVisible();
      await expect(page.getByRole('heading', { name: l.job, level: 2 })).toBeVisible();
      await snap(`S13-feed-${theme}-${l.locale}.png`);

      await page.getByRole('link', { name: new RegExp(l.job) }).click();
      await expect(page.getByRole('heading', { name: l.job, level: 1 })).toBeVisible();
      await expect(page.getByText(l.client)).toBeVisible();
      await snap(`S15-job-${theme}-${l.locale}.png`);

      await pressTelegram(page, 'back_button_pressed');
      await expect(page.getByText(l.found)).toBeVisible();
    });
  }
}

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S12 ${theme} ${l.locale}: сохранённые заявки — сегмент «Задачи»`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const jobs = new JobsBackend();
      jobs.saved = [LEAK, CHANDELIER];
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs,
      });

      await openProfile(page, l.profile);
      await page.getByRole('link', { name: l.favorites }).click();
      await page.getByRole('link', { name: l.savedJobs }).click();
      await expect(page.getByRole('heading', { name: l.job, level: 2 })).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S12-favorites-jobs-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });
  }
}

test('deeplink-j: startapp=j_… открывает заявку S15, «Назад» — в ленту', async ({ page }) => {
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const start = encodeStartParam({ type: 'job', id: CHANDELIER });
  const watch = await open(page, `theme=light&lang=ru&start=${start}`, {
    jobs: new JobsBackend(),
  });

  await expect(page.getByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeVisible();
  await pressTelegram(page, 'back_button_pressed');
  await expect(page.getByRole('heading', { name: 'Заявки рядом', level: 1 })).toBeVisible();
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});
