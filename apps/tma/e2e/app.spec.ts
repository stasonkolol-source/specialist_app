// Каркас Mini App в браузерах проектов (DEVELOPMENT_PLAN 0.21b): скриншоты экранов × тема × язык,
// axe-core, CSP собранного приложения, без внешней сети и неописанных запросов к API.
// Имена скриншотов начинаются с кода артборда — make design-compare кладёт их рядом с эталоном.
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

import { mockApi } from './api.ts';

const THEMES = ['light', 'dark'] as const;
const LOCALES = [
  { locale: 'ru', telegram: 'ru', home: 'Главная', create: 'Создать заявку', goods: 'Вещи' },
  { locale: 'sr-Latn', telegram: 'sr', home: 'Početna', create: 'Novi zahtev', goods: 'Stvari' },
] as const;

interface Watch {
  problems: string[];
  unexpectedApi: string[];
}

/** Открыть приложение на mock-платформе и собирать всё, что не должно случиться. */
async function open(page: Page, query: string): Promise<Watch> {
  const watch: Watch = { problems: [], unexpectedApi: [] };
  page.on('request', (request) => {
    if (!request.url().startsWith('http://127.0.0.1'))
      watch.problems.push(`network ${request.url()}`);
  });
  page.on('console', (message) => {
    if (message.type() === 'error') watch.problems.push(`console ${message.text()}`);
  });
  page.on('pageerror', (error) => watch.problems.push(`page ${error.message}`));
  await mockApi(page, watch.unexpectedApi);
  await page.goto(`/?platform=mock&${query}`);
  await page.evaluate(() => document.fonts.ready);
  return watch;
}

/** Ответ 401 на синтетический initData — ожидаемая ошибка консоли браузера, не приложения. */
const real = (problems: string[]) =>
  problems.filter((p) => !p.includes('401') && !p.includes('Unauthorized'));

async function expectNoAxeViolations(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
}

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

test('таббар переключает разделы', async ({ page }) => {
  await open(page, 'theme=light&lang=ru');
  const tabs = page.getByRole('navigation', { name: 'Разделы' });
  for (const name of ['Заявки', 'Сообщения', 'Профиль', 'Главная']) {
    await tabs.getByRole('link', { name }).click();
    await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible();
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
  await expect(page.getByRole('heading', { name: 'Почетна' })).toBeVisible();
  expect(real(watch.problems)).toEqual([]);
});

test('CSP собранного приложения строгая и не мешает работе', async ({ page }) => {
  const response = await page.goto('/?platform=mock');
  const csp = response?.headers()['content-security-policy'] ?? '';
  expect(csp).toContain("script-src 'self';");
  expect(csp).toContain('frame-ancestors https://web.telegram.org');
  expect(csp).not.toContain('unsafe');
});
