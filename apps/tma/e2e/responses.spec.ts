// Отклики S15–S17 и шаблоны S57 (DEVELOPMENT_PLAN 5.5) на фейке backend: заявка S15 → MainButton
// «Откликнуться · осталось 2 места» → форма S16 с основным шаблоном → «Отправить отклик» → «Мои
// отклики» S17 с «клиент увидит его после проверки»; «Мои отклики» как на артборде (выбран, ждёт
// решения, не выбран) → шаблоны S57. Скриншоты × тема × язык, axe-core. Имена скриншотов
// начинаются с кода артборда: make design-compare кладёт их рядом с эталоном.
import type { Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

import { E2E_NOW, ME } from '../src/testing/fixtures.ts';
import {
  FEED_JOBS,
  JobsBackend,
  myResponsesFixture,
  templatesFixture,
} from '../src/testing/jobsBackend.ts';
import type { Watch } from './support.ts';
import { THEMES, expectNoAxeViolations, open, openTab, pressTelegram, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Заявки',
    segment: 'Мои отклики',
    job: 'Повесить люстру',
    caption: 'Отклик на заявку',
    sent: 'Отклик отправлен — клиент увидит его после проверки',
    waiting: 'Ждёт решения клиента',
    templates: 'Шаблоны откликов',
    primary: 'Основной',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Zahtevi',
    segment: 'Moje ponude',
    job: 'Повесить люстру',
    caption: 'Ponuda za zahtev',
    sent: 'Ponuda je poslata — naručilac će je videti posle provere',
    waiting: 'Čeka odluku naručioca',
    templates: 'Šabloni ponuda',
    primary: 'Glavni',
  },
] as const;

const CHANDELIER = FEED_JOBS.find((item) => item.card.title === 'Повесить люстру')?.card.id ?? '';

/** Снимок экрана: до него — ни ошибок, ни неописанных запросов, после — axe-core. */
async function snap(page: Page, watch: Watch, name: string) {
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
  await expect(page).toHaveScreenshot(name, { fullPage: true });
  await expectNoAxeViolations(page);
  // снимок вставляет стиль «без анимаций» — CSP приложения в WebKit его отклоняет и пишет в
  // консоль; дальше проверяем только то, что случилось после снимка
  watch.problems.length = 0;
}

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S16 ${theme} ${l.locale}: отклик из основного шаблона`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const jobs = new JobsBackend();
      jobs.templates = templatesFixture();
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs,
      });

      await openTab(page, l.tab);
      await page.getByRole('link', { name: new RegExp(l.job) }).click();
      await expect(page.getByRole('heading', { name: l.job, level: 1 })).toBeVisible();
      await pressTelegram(page, 'main_button_pressed');
      await expect(page.getByText(l.caption)).toBeVisible();
      await expect(page.getByRole('heading', { name: l.job, level: 1 })).toBeVisible();
      await snap(page, watch, `S16-respond-${theme}-${l.locale}.png`);

      await pressTelegram(page, 'main_button_pressed');
      await expect(page.getByText(l.sent)).toBeVisible();
      await expect(page.getByText(l.waiting)).toBeVisible();
      expect(jobs.responsePosts.map((post) => post.jobId)).toEqual([CHANDELIER]);
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
    });

    test(`S17 и S57 ${theme} ${l.locale}: мои отклики и шаблоны`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const jobs = new JobsBackend();
      jobs.responses = myResponsesFixture();
      jobs.respondedToday = 3;
      jobs.templates = templatesFixture();
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs,
      });

      await openTab(page, l.tab);
      await page.getByRole('link', { name: l.segment }).click();
      await expect(page.getByText(l.waiting)).toBeVisible();
      await snap(page, watch, `S17-my-responses-${theme}-${l.locale}.png`);

      await page.getByRole('button', { name: l.templates }).click();
      await expect(page.getByRole('heading', { name: l.templates, level: 1 })).toBeVisible();
      await expect(page.getByText(l.primary, { exact: true })).toBeVisible();
      await snap(page, watch, `S57-templates-${theme}-${l.locale}.png`);
    });
  }
}
