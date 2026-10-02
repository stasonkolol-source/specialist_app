// Выбор исполнителя и сделка S24–S26 (DEVELOPMENT_PLAN 6.2) на фейке backend: своя заявка S23 →
// отклик Алексея S24 → шторка выбора S25 → сделка S26 («Договорились», исполнитель, адрес,
// таймлайн, памятка). Скриншоты × тема × язык, axe-core. Имена скриншотов начинаются с кода
// артборда: make design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';

import { E2E_NOW, ME } from '../src/testing/fixtures.ts';
import { JobsBackend } from '../src/testing/jobsBackend.ts';
import { THEMES, expectNoAxeViolations, open, openTab, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Заявки',
    offer: 'Предложение',
    choose: 'Выбрать исполнителем',
    confirm: 'Выбрать этого исполнителя?',
    status: 'Статус',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Zahtevi',
    offer: 'Ponuda',
    choose: 'Izaberi izvođača',
    confirm: 'Izabrati ovog izvođača?',
    status: 'Status',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S24–S26 ${theme} ${l.locale}: отклик, выбор, сделка`, async ({ page }) => {
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
        watch.problems.length = 0;
      };

      await openTab(page, l.tab);
      await page.getByRole('link', { name: /Повесить люстру/ }).click();
      await page.getByRole('link', { name: /^Алексей Морозов/ }).click();
      await expect(page.getByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeVisible();
      await expect(page.getByRole('region', { name: l.offer })).toBeVisible();
      await snap(`S24-response-${theme}-${l.locale}.png`);

      await page.getByRole('button', { name: l.choose }).click();
      await expect(page.getByRole('dialog', { name: l.confirm })).toBeVisible();
      await snap(`S25-confirm-choice-${theme}-${l.locale}.png`);
      // нижняя кнопка шторки — кнопка оболочки приложения поверх неё, не внутри диалога
      await page.getByRole('button', { name: l.choose }).click();
      await expect(page.getByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeVisible();
      await expect(page.getByRole('region', { name: l.status })).toBeVisible();
      await snap(`S26-deal-${theme}-${l.locale}.png`);
    });
  }
}
