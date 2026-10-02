// Свои заявки клиента S22 и S23 (DEVELOPMENT_PLAN 5.6) на фейке backend: вкладка «Заявки» клиенту
// открывает «Мои заявки» — люстра с «3 отклика — выберите исполнителя», уборка ждёт откликов,
// закрытая — в архиве, как на артборде; своя заявка — статус, места, отклики карточками.
// Скриншоты × тема × язык, axe-core. Имена скриншотов начинаются с кода артборда: make
// design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';

import { E2E_NOW, ME } from '../src/testing/fixtures.ts';
import { JobsBackend } from '../src/testing/jobsBackend.ts';
import { THEMES, expectNoAxeViolations, open, openTab, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Заявки',
    mine: 'Мои заявки',
    waiting: '3 отклика — выберите исполнителя',
    first: 'Алексей Морозов',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Zahtevi',
    mine: 'Moji zahtevi',
    waiting: '3 ponude — izaberite izvođača',
    first: 'Алексей Морозов',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S22 и S23 ${theme} ${l.locale}: мои заявки и своя заявка`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs: new JobsBackend().seedMine(),
      });
      const snap = async (name: string) => {
        expect(real(watch.problems)).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(name, { fullPage: true });
        await expectNoAxeViolations(page);
        // снимок вставляет стиль «без анимаций» — CSP приложения в WebKit его отклоняет и пишет
        // в консоль; дальше проверяем только то, что случилось после снимка
        watch.problems.length = 0;
      };

      await openTab(page, l.tab);
      await expect(page.getByRole('heading', { name: l.mine, level: 1 })).toBeVisible();
      await expect(page.getByText(l.waiting)).toBeVisible();
      await snap(`S22-my-jobs-${theme}-${l.locale}.png`);

      await page.getByRole('link', { name: /Повесить люстру/ }).click();
      await expect(page.getByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeVisible();
      await expect(page.getByText(l.first)).toBeVisible();
      await snap(`S23-manage-job-${theme}-${l.locale}.png`);
    });
  }
}
