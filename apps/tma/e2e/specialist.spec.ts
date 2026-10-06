// Мастер «Стать специалистом» S32a–c и вход с S31 (DEVELOPMENT_PLAN 2.9): путь от «профиля нет» до
// кабинета S33 «на проверке» на фейке backend кабинета, скриншоты каждого шага × тема × язык (поля заполнены,
// как на артбордах), axe-core. Имена скриншотов начинаются с кода артборда: make design-compare
// кладёт их рядом с эталоном. MainButton и BackButton — нативные кнопки клиента Telegram (в DOM
// их нет): нажимаем событием клиента, их тексты проверяют unit-тесты (become.test.tsx).
import type { Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

import { ME } from '../src/testing/fixtures.ts';
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
    profile: 'Профиль',
    become: /Стать специалистом/,
    type: 'Как вы хотите работать?',
    about: 'Чем вы занимаетесь?',
    categories: ['Электрика', 'Люстры и карнизы'],
    headline: 'Коротко о себе',
    aboutField: 'О себе',
    serbian: 'Сербский',
    area: 'Где и почём работаете',
    wholeCity: /^Весь\sНови-Сад/,
    service: 'Первая позиция прайса',
    price: 'Цена в динарах',
    sent: /Профиль\sна\sпроверке,\sобычно\sдо\s30\sминут\s—\sбот\sнапишет/,
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    profile: 'Profil',
    become: /Postanite stručnjak/,
    type: 'Kako želite da radite?',
    about: 'Čime se bavite?',
    categories: ['Elektrika', 'Lusteri i garnišne'],
    headline: 'Ukratko o sebi',
    aboutField: 'O sebi',
    serbian: 'Srpski',
    area: 'Gde i po kojoj ceni radite',
    wholeCity: /^Ceo\sNovi\sSad/,
    service: 'Prva stavka cenovnika',
    price: 'Cena u dinarima',
    sent: /Profil\sje\sna\sproveri,\sobično\sdo\s30\sminuta\s—\sbot/,
  },
] as const;

const main = (page: Page) => pressTelegram(page, 'main_button_pressed');

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S31 → S32a–c ${theme} ${l.locale}: профиль специалиста уходит на проверку`, async ({
      page,
    }) => {
      const profile = new ProfileBackend();
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        profile,
      });
      /** Снимок шага: до него — ни ошибок, ни неописанных запросов, после — axe-core. */
      const snap = async (name: string) => {
        expect(real(watch.problems)).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(name, { fullPage: true });
        await expectNoAxeViolations(page);
        // снимок вставляет стиль «без анимаций» — CSP приложения в WebKit его отклоняет и пишет
        // в консоль; дальше проверяем только то, что случилось после снимка
        watch.problems.length = 0;
      };
      await openProfile(page, l.profile);
      await page.getByRole('link', { name: l.become }).click();

      // S32a: «Специалист» отмечен — S31 открыл мастер с этим типом
      await expect(page.getByRole('heading', { name: l.type, level: 1 })).toBeVisible();
      await expect(page.getByRole('radio').first()).toHaveAttribute('aria-checked', 'true');
      await snap(`S32a-become-type-${theme}-${l.locale}.png`);
      await main(page);

      // S32b: заполняем, как на артборде
      const headline = page.getByRole('textbox', { name: l.headline });
      await expect(headline).toBeVisible();
      for (const name of l.categories) await page.getByRole('button', { name }).click();
      await headline.fill('Электрик · мелкий ремонт · люстры');
      await page
        .getByRole('textbox', { name: l.aboutField, exact: true })
        .fill(
          'Электрик, 12 лет опыта, в Нови-Саде с 2022 года. Свой инструмент и стремянка до 3 м.',
        );
      await page.getByRole('button', { name: l.serbian, exact: true }).click();
      await expect(page.getByRole('heading', { name: l.about, level: 1 })).toBeVisible();
      await snap(`S32b-become-about-${theme}-${l.locale}.png`);
      await main(page);

      // S32c: «Весь Нови-Сад», «Выезжаю» и «до 5 км» по умолчанию, первая позиция прайса.
      // Районы прокликивать не нужно (решение владельца 2026-10-05): уходят все районы города
      const service = page.getByRole('textbox', { name: l.service });
      await expect(service).toBeVisible();
      await expect(page.getByRole('checkbox', { name: l.wholeCity })).toHaveAttribute(
        'aria-checked',
        'true',
      );
      await service.fill('Выезд и диагностика');
      await page.getByRole('textbox', { name: l.price }).fill('2000');
      await expect(page.getByRole('heading', { name: l.area, level: 1 })).toBeVisible();
      await snap(`S32c-become-area-prices-${theme}-${l.locale}.png`);
      await main(page);

      // итог — кабинет S33: срок, «бот напишет» и одно действие на время ожидания (UX №7)
      await expect(page.getByText(l.sent)).toBeVisible();
      expect(profile.profile?.status).toBe('pending_review');
      expect(profile.profile?.district_ids).toHaveLength(8);
      expect(profile.services).toHaveLength(1);
      await snap(`S33-cabinet-review-${theme}-${l.locale}.png`);
    });
  }
}
