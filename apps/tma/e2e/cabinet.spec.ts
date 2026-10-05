// Кабинет специалиста S33, доступность S38 и правка профиля S34 (DEVELOPMENT_PLAN 2.10): из
// карточки на S31, скриншоты × тема × язык, axe-core. Время в браузере — 15:00 по Белграду:
// варианты «до 18/20/22» и подписи зависят от часа. Имена скриншотов начинаются с кода артборда:
// make design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';

import { FIRST_SERVICE, ME, PROFILE_FILLED } from '../src/testing/fixtures.ts';
import { ProfileBackend } from '../src/testing/profileBackend.ts';
import {
  THEMES,
  expectNoAxeViolations,
  open,
  openProfile,
  pressTelegram,
  real,
} from './support.ts';

/** 15:00 по Белграду 1 октября: все варианты «доступен сегодня» ещё впереди. */
const AFTERNOON = new Date('2026-10-01T15:00:00+02:00');

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Профиль',
    card: /Кабинет специалиста/,
    title: 'Кабинет специалиста',
    published: 'Профиль опубликован и виден в поиске',
    row: 'Профиль',
    edit: 'Редактирование профиля',
    areas: /^Лиман,\sГрбавица,\sЦентр\sи\sещё\s1$/,
    wholeCity: /^Весь\sНови-Сад/,
    availability: /Доступность/,
    availabilityTitle: 'Доступность',
    today: 'Доступен сегодня',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Profil',
    card: /Kabinet stručnjaka/,
    title: 'Kabinet stručnjaka',
    published: 'Profil je objavljen i vidljiv u pretrazi',
    row: 'Profil',
    edit: 'Izmena profila',
    areas: /^Liman,\sGrbavica,\sCentar\si\sjoš\s1$/,
    wholeCity: /^Ceo\sNovi\sSad/,
    availability: /Dostupnost/,
    availabilityTitle: 'Dostupnost',
    today: 'Dostupan danas',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S33, S38 и S34 ${theme} ${l.locale}: кабинет, доступность и правка`, async ({ page }) => {
      await page.clock.setFixedTime(AFTERNOON);
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

      // S38 как на артборде: «Доступен сегодня» включён, выбрано «до 20:00»
      await page.getByRole('link', { name: l.availability }).click();
      await expect(
        page.getByRole('heading', { name: l.availabilityTitle, level: 1 }),
      ).toBeVisible();
      await page.getByRole('switch', { name: l.today }).click();
      await snap(`S38-availability-${theme}-${l.locale}.png`);
      await pressTelegram(page, 'back_button_pressed');

      await page.getByRole('link', { name: l.row, exact: true }).click();
      await expect(page.getByRole('heading', { name: l.edit, level: 1 })).toBeVisible();
      // районы раскрыты: сверху «Весь Нови-Сад» (у профиля отмечены не все — выключен), под ним список
      await page.getByRole('button', { name: l.areas }).click();
      await expect(page.getByRole('checkbox', { name: l.wholeCity })).toHaveAttribute(
        'aria-checked',
        'false',
      );
      await snap(`S34-edit-profile-${theme}-${l.locale}.png`);
    });
  }
}
