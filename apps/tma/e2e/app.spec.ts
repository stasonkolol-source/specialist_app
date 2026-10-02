// Каркас Mini App в браузерах проектов (DEVELOPMENT_PLAN 0.21b): скриншоты экранов × тема × язык,
// axe-core, CSP собранного приложения, без внешней сети и неописанных запросов к API.
// Имена скриншотов начинаются с кода артборда — make design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';

import { ME } from '../src/testing/fixtures.ts';
import { THEMES, expectNoAxeViolations, open, openProfile, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    home: 'Найдём мастера рядом',
    create: 'Создать заявку',
    goods: 'Вещи',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    home: 'Pronaći ćemo majstora u blizini',
    create: 'Novi zahtev',
    goods: 'Stvari',
  },
] as const;

for (const theme of THEMES) {
  for (const { locale, telegram, home, goods } of LOCALES) {
    test(`S03 главная ${theme} ${locale}`, async ({ page }) => {
      const watch = await open(page, `theme=${theme}&lang=${telegram}`);

      await expect(page.getByRole('heading', { name: home })).toBeVisible();
      await expect(page.getByRole('radio', { name: goods })).toBeVisible();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.locator('html')).toHaveAttribute('lang', locale);
      // до скриншота и axe: они сами вставляют стили и скрипты, которые строгая CSP отклоняет
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S03-home-${theme}-${locale}.png`, { fullPage: true });
      await expectNoAxeViolations(page);
    });
  }

  test(`S20a создание ${theme}: MainButton скрывает таббар`, async ({ page }) => {
    const watch = await open(page, `theme=${theme}&lang=ru`);
    const tabs = page.getByRole('navigation', { name: 'Разделы' });

    await tabs.getByRole('link', { name: 'Создать заявку' }).click();

    await expect(page.getByRole('heading', { name: 'Создать заявку' })).toBeVisible();
    await expect(tabs).toBeHidden();
    expect(real(watch.problems)).toEqual([]);
    await expect(page).toHaveScreenshot(`S20a-create-${theme}-ru.png`, { fullPage: true });
    await expectNoAxeViolations(page);
  });
}

for (const theme of THEMES) {
  test(`S31 профиль ${theme}: имя и город из /me, вход «Стать специалистом»`, async ({ page }) => {
    const watch = await open(page, `theme=${theme}&lang=ru`, { signedIn: true });
    await openProfile(page);

    await expect(page.getByRole('heading', { name: ME.display_name })).toBeVisible();
    await expect(page.getByText('Нови-Сад')).toBeVisible();
    await expect(page.getByRole('link', { name: /Стать специалистом/ })).toBeVisible();
    expect(real(watch.problems)).toEqual([]);
    expect(watch.unexpectedApi).toEqual([]);
    await expect(page).toHaveScreenshot(`S31-account-${theme}-ru.png`, { fullPage: true });
    await expectNoAxeViolations(page);
  });
}

test('S31: язык пишется в PATCH /me и сразу меняет интерфейс', async ({ page }) => {
  const watch = await open(page, 'theme=light&lang=ru', { signedIn: true });
  await openProfile(page);
  await expect(page.getByRole('heading', { name: ME.display_name })).toBeVisible();
  const patch = page.waitForRequest(
    (r) => r.method() === 'PATCH' && r.url().endsWith('/api/v1/me'),
  );

  await page.getByRole('radio', { name: 'Srpski (latinica)' }).click();

  expect((await patch).postDataJSON()).toEqual({ ui_locale: 'sr-Latn' });
  await expect(page.getByRole('heading', { name: 'Profil', level: 1 })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'sr-Latn');
  await expect(page.getByRole('radio', { name: 'Srpski (latinica)' })).toHaveAttribute(
    'aria-checked',
    'true',
  );
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});

test('S31 без входа: «Откройте в Telegram» вместо ошибки', async ({ page }) => {
  const watch = await open(page, 'theme=light&lang=ru');
  await openProfile(page);

  await expect(page.getByRole('heading', { name: 'Откройте в Telegram' })).toBeVisible();
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
  await expectNoAxeViolations(page);
});

test('таббар переключает разделы', async ({ page }) => {
  await open(page, 'theme=light&lang=ru');
  const tabs = page.getByRole('navigation', { name: 'Разделы' });
  // вкладка → заголовок её экрана; у Главной — свой, как на артборде S03
  const screens = [
    ['Заявки', 'Заявки'],
    ['Сообщения', 'Сообщения'],
    ['Профиль', 'Профиль'],
    ['Главная', 'Найдём мастера рядом'],
  ] as const;
  for (const [name, heading] of screens) {
    await tabs.getByRole('link', { name }).click();
    await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible();
    await expect(tabs.getByRole('link', { name })).toHaveAttribute('aria-current', 'page');
  }
});

test('«Вещи» на главной — заглушка S58', async ({ page }) => {
  await open(page, 'theme=light&lang=ru');
  await page.getByRole('radio', { name: 'Вещи' }).click();
  await expect(page.getByRole('heading', { name: 'Вещи — скоро' })).toBeVisible();
});

test('sr-Cyrl: smoke — выбранный язык остаётся кириллицей', async ({ page }) => {
  const watch = await open(page, 'theme=light&lang=sr&locale=sr-Cyrl');
  await expect(page.locator('html')).toHaveAttribute('lang', 'sr-Cyrl');
  await expect(
    page.getByRole('heading', { name: 'Пронаћи ћемо мајстора у близини' }),
  ).toBeVisible();
  expect(real(watch.problems)).toEqual([]);
});

test('CSP собранного приложения строгая и не мешает работе', async ({ page }) => {
  const response = await page.goto('/?platform=mock');
  const csp = response?.headers()['content-security-policy'] ?? '';
  expect(csp).toContain("script-src 'self';");
  expect(csp).toContain('frame-ancestors https://web.telegram.org');
  expect(csp).not.toContain('unsafe');
});
