// Запуск и онбординг (DEVELOPMENT_PLAN 1.5b): скриншоты S01, S02a–c × тема × язык, axe-core, путь
// нового пользователя целиком, вернувшийся пользователь, новая редакция правил, deep link. Имена
// скриншотов начинаются с кода артборда: make design-compare кладёт их рядом с эталоном.
// MainButton и BackButton — нативные кнопки клиента Telegram (в DOM их нет): нажимаем событием
// клиента, их тексты и видимость проверяют unit-тесты (src/app/onboarding.test.tsx).
import type { Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

import type { MeOut } from '@sosed/api-client';

import {
  CLIENT_CONFIG,
  ME,
  NEW_USER,
  OUTDATED_CONSENTS_USER,
  citiesFor,
} from '../src/testing/fixtures.ts';
import { json, sentRequests } from './api.ts';
import { THEMES, expectNoAxeViolations, open, pressTelegram, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    app: 'Соседи',
    signingIn: 'Входим через Telegram…',
    language: 'Язык и город',
    novisad: 'Нови-Сад',
    intent: 'Что вы хотите?',
    rules: 'Правила площадки',
    accept: 'Мне есть 18 лет, я принимаю правила площадки',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    app: 'Sosedi',
    signingIn: 'Prijavljujemo vas preko Telegram-a…',
    language: 'Jezik i grad',
    novisad: 'Novi Sad',
    intent: 'Šta želite?',
    rules: 'Pravila platforme',
    accept: 'Imam 18 godina i prihvatam pravila platforme',
  },
] as const;

const TABS = /Разделы|Odeljci/;

/** Пользователь на языке теста: язык из ui_locale применяется при входе. */
const on = (me: MeOut, locale: MeOut['ui_locale']): MeOut => ({ ...me, ui_locale: locale });

const main = (page: Page) => pressTelegram(page, 'main_button_pressed');

for (const theme of THEMES) {
  for (const l of LOCALES) {
    const query = `theme=${theme}&lang=${l.telegram}`;

    test(`S01 запуск ${theme} ${l.locale}: вордмарк, скелетон, «Входим через Telegram…»`, async ({
      page,
    }) => {
      // client-config отвечает, когда отпустим: экран запуска держится
      let release: () => void = () => undefined;
      const held = new Promise<void>((resolve) => {
        release = resolve;
      });
      const watch = await open(page, query, {
        signedIn: true,
        me: on(ME, l.locale),
        handlers: {
          'GET /api/v1/client-config': async (route) => {
            await held;
            await route.fulfill(json(CLIENT_CONFIG));
          },
        },
      });

      await expect(page.getByRole('heading', { name: l.app, level: 1 })).toBeVisible();
      await expect(page.getByRole('status')).toHaveText(l.signingIn);
      await expect(page.getByRole('navigation', { name: TABS })).toHaveCount(0);
      expect(real(watch.problems)).toEqual([]);
      await expect(page).toHaveScreenshot(`S01-launch-${theme}-${l.locale}.png`);
      await expectNoAxeViolations(page);

      release();
      await expect(page.getByRole('navigation', { name: TABS })).toBeVisible();
    });

    test(`S02a язык и город ${theme} ${l.locale}`, async ({ page }) => {
      const watch = await open(page, query, { signedIn: true, me: on(NEW_USER, l.locale) });

      await expect(page.getByRole('heading', { name: l.language, level: 1 })).toBeVisible();
      await expect(page.getByRole('radio', { name: l.novisad })).toHaveAttribute(
        'aria-checked',
        'true',
      );
      await expect(page.getByRole('radio', { name: 'English' })).toBeDisabled();
      await expect(page.getByRole('navigation', { name: TABS })).toHaveCount(0);
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S02a-language-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });

    test(`S02b намерение ${theme} ${l.locale}`, async ({ page }) => {
      const watch = await open(page, query, {
        signedIn: true,
        me: on({ ...NEW_USER, home_city_id: 1 }, l.locale),
      });

      await expect(page.getByRole('heading', { name: l.intent, level: 1 })).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S02b-intent-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });

    test(`S02c правила ${theme} ${l.locale}`, async ({ page }) => {
      const watch = await open(page, query, {
        signedIn: true,
        me: on({ ...NEW_USER, home_city_id: 1, intent: 'client' }, l.locale),
      });

      await expect(page.getByRole('heading', { name: l.rules, level: 1 })).toBeVisible();
      // как на артборде: галочка отмечена, уведомления включены
      await page.getByRole('checkbox', { name: l.accept }).click();
      await expect(page.getByRole('checkbox', { name: l.accept })).toHaveAttribute(
        'aria-checked',
        'true',
      );
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S02c-rules-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });
  }
}

test('новый пользователь: S01 → S02a → S02b → S02c → главная', async ({ page }) => {
  const sent = sentRequests();
  const watch = await open(page, 'theme=light&lang=ru', { signedIn: true, me: NEW_USER, sent });

  // S02a: смена языка перерисовывает экран сразу, без перезагрузки
  await expect(page.getByRole('heading', { name: 'Язык и город', level: 1 })).toBeVisible();
  await page.getByRole('radio', { name: 'Srpski · latinica' }).click();
  await expect(page.getByRole('heading', { name: 'Jezik i grad', level: 1 })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'sr-Latn');
  await expect(page.getByRole('radio', { name: 'Novi Sad' })).toBeVisible();
  await page.getByRole('radio', { name: 'Русский' }).click();
  await expect(page.getByRole('heading', { name: 'Язык и город', level: 1 })).toBeVisible();
  await expect(page.getByRole('radio', { name: 'Нови-Сад' })).toBeVisible();
  await main(page);

  // S02b
  await expect(page.getByRole('heading', { name: 'Что вы хотите?', level: 1 })).toBeVisible();
  expect(sent.patch).toEqual([{ ui_locale: 'ru', home_city_id: 1 }]);
  await page.getByRole('radio', { name: 'Я специалист' }).click();
  await main(page);

  // S02c: без галочки не пускает
  await expect(page.getByRole('heading', { name: 'Правила площадки', level: 1 })).toBeVisible();
  expect(sent.patch.at(-1)).toEqual({ intent: 'pro' });
  await main(page);
  await expect(page.getByRole('alert')).toHaveText('Отметьте галочку: без неё начать нельзя');
  expect(sent.consents).toEqual([]);
  await page.getByRole('checkbox', { name: /Мне есть 18 лет/ }).click();
  await main(page);

  await expect(page.getByRole('heading', { name: 'Найдём мастера рядом', level: 1 })).toBeVisible();
  await expect(page.getByRole('navigation', { name: TABS })).toBeVisible();
  expect(sent.consents).toEqual([{ terms_version: 'draft-1', privacy_version: 'draft-1' }]);
  expect(sent.writeAccess).toBe(1);
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});

test('S01 вернувшийся пользователь сразу попадает на главную', async ({ page }) => {
  const sent = sentRequests();
  const watch = await open(page, 'theme=light&lang=ru', { signedIn: true, me: ME, sent });

  await expect(page.getByRole('heading', { name: 'Найдём мастера рядом', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Язык и город' })).toHaveCount(0);
  expect(sent.patch).toEqual([]);
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});

test('S02c новая редакция правил: вернувшийся видит только её', async ({ page }) => {
  const sent = sentRequests();
  const watch = await open(page, 'theme=light&lang=ru', {
    signedIn: true,
    me: OUTDATED_CONSENTS_USER,
    sent,
  });

  await expect(page.getByRole('heading', { name: 'Правила площадки', level: 1 })).toBeVisible();
  await page.getByRole('checkbox', { name: /Мне есть 18 лет/ }).click();
  await main(page);

  await expect(page.getByRole('heading', { name: 'Найдём мастера рядом', level: 1 })).toBeVisible();
  expect(sent.patch).toEqual([]);
  expect(sent.consents).toHaveLength(1);
  expect(real(watch.problems)).toEqual([]);
});

test('S01 deep link на экран следующих шагов открывает главную', async ({ page }) => {
  // `g_` — раздел «Вещи», он после MVP: экрана нет (у `d_` экран S26 есть с 6.2)
  const watch = await open(page, 'theme=light&lang=ru&start=g_02y9UKmeRG6vSNbdsEYkkR', {
    signedIn: true,
    me: ME,
  });
  await expect(page.getByRole('heading', { name: 'Найдём мастера рядом', level: 1 })).toBeVisible();
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});

test('S02a без сети: города не загрузились — «Повторить»', async ({ page }) => {
  let online = false;
  const watch = await open(page, 'theme=light&lang=ru', {
    signedIn: true,
    me: NEW_USER,
    handlers: {
      'GET /api/v1/cities': (route) =>
        online ? route.fulfill(json(citiesFor('ru'))) : route.abort('internetdisconnected'),
    },
  });

  await expect(page.getByRole('alert')).toHaveText(
    'Нет соединения. Проверьте интернет и попробуйте ещё раз.',
    { timeout: 10_000 },
  );
  online = true;
  await page.getByRole('button', { name: 'Повторить' }).click();
  await expect(page.getByRole('radio', { name: 'Нови-Сад' })).toBeVisible();
  expect(real(watch.problems, ['ERR_INTERNET_DISCONNECTED'])).toEqual([]);
  await expectNoAxeViolations(page);
});
