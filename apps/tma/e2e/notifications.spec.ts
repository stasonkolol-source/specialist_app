// S42 уведомления (DEVELOPMENT_PLAN 4.9, API 2.3a): из профиля (S31), скриншоты × тема × язык,
// axe-core; «Прочитать все», переход по уведомлению и «Разрешить боту писать». Имена скриншотов
// начинаются с кода артборда: make design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';

import { ME, NOTIFICATIONS_NOW } from '../src/testing/fixtures.ts';
import { sentRequests } from './api.ts';
import { THEMES, expectNoAxeViolations, open, openProfile, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    profile: 'Профиль',
    row: /^Уведомления/,
    title: 'Уведомления',
    today: 'Сегодня',
    readAll: 'Прочитать все',
    allow: 'Разрешить боту писать',
    first: /Сделка подтверждена/,
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    profile: 'Profil',
    row: /^Obaveštenja/,
    title: 'Obaveštenja',
    today: 'Danas',
    readAll: 'Pročitaj sve',
    allow: 'Dozvoli botu da piše',
    first: /Dogovor je potvrđen/,
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S42 уведомления ${theme} ${l.locale}: из профиля, по дням, баннер бота`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(NOTIFICATIONS_NOW);
      const sent = sentRequests();
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        sent,
      });
      await openProfile(page, l.profile);
      await page.getByRole('link', { name: l.row }).click();

      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
      await expect(page.getByRole('region', { name: l.today })).toBeVisible();
      await expect(page.getByRole('button', { name: l.allow })).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S42-notifications-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
      // снимок вставляет стиль «без анимаций» — CSP приложения в WebKit его отклоняет и пишет в
      // консоль; дальше проверяем только то, что случилось после снимка
      watch.problems.length = 0;

      // разрешение боту: клиент Telegram спрашивает, backend записывает канал, баннер уходит
      await page.getByRole('button', { name: l.allow }).click();
      await expect(page.getByRole('button', { name: l.allow })).toBeHidden();
      expect(sent.writeAccess).toBe(1);

      await page.getByRole('button', { name: l.readAll }).click();
      await expect(page.getByRole('button', { name: l.readAll })).toBeHidden();
      expect(sent.read).toEqual([{ all: true }]);

      // deep link уведомления: у сделок экрана ещё нет — на Главную (таббар виден только там)
      await page.getByRole('link', { name: l.first }).click();
      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeHidden();
      await expect(page.getByRole('navigation', { name: /Разделы|Odeljci/ })).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
    });
  }
}
