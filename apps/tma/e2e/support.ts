// Общее для e2e Mini App: открыть приложение на mock-платформе, собрать то, чего быть не должно
// (внешняя сеть, ошибки консоли, неописанные запросы к API), и проверить axe-core.
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

import type { MockApiOptions } from './api.ts';
import { mockApi } from './api.ts';

export const THEMES = ['light', 'dark'] as const;

/** Ответы API, где 404 — по контракту, а не ошибка: «профиля исполнителя ещё нет» (2.8a). Браузер
 *  всё равно пишет такой ответ в консоль ошибкой — её не считаем. */
const EXPECTED_NOT_FOUND = ['/api/v1/me/profile'];

export interface Watch {
  problems: string[];
  unexpectedApi: string[];
}

/** Открыть приложение на mock-платформе и собирать всё, что не должно случиться. */
export async function open(page: Page, query: string, api: MockApiOptions = {}): Promise<Watch> {
  const watch: Watch = { problems: [], unexpectedApi: [] };
  page.on('request', (request) => {
    const url = request.url();
    // blob: — превью выбранного файла в памяти браузера: WebKit сообщает о нём как о запросе
    if (!url.startsWith('http://127.0.0.1') && !url.startsWith('blob:http://127.0.0.1')) {
      watch.problems.push(`network ${url}`);
    }
  });
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const { pathname } = new URL(message.location().url || 'about:blank');
    if (message.text().includes('404') && EXPECTED_NOT_FOUND.includes(pathname)) return;
    watch.problems.push(`console ${message.text()}`);
  });
  page.on('pageerror', (error) => watch.problems.push(`page ${error.message}`));
  await mockApi(page, watch.unexpectedApi, api);
  await page.goto(`/?platform=mock&${query}`);
  await page.evaluate(() => document.fonts.ready);
  return watch;
}

/** Ответ 401 на синтетический initData — ожидаемая ошибка консоли браузера, не приложения.
 *  `expected` — ещё статусы и сетевые ошибки, которые сценарий вызывает сам (403, 503, обрыв). */
export const real = (problems: string[], expected: readonly string[] = []) =>
  problems.filter(
    (p) =>
      !p.includes('401') &&
      !p.includes('Unauthorized') &&
      !expected.some((allowed) => p.includes(allowed)),
  );

export interface AxeScope {
  /** Проверить только эту часть страницы. */
  include?: string;
  /** Пропустить эти части (причина — в месте вызова). */
  exclude?: readonly string[];
  /** Правила, которые здесь не проверяются (причина — в месте вызова). */
  disable?: readonly string[];
}

export async function expectNoAxeViolations(page: Page, scope: AxeScope = {}) {
  let builder = new AxeBuilder({ page });
  if (scope.include) builder = builder.include(scope.include);
  for (const selector of scope.exclude ?? []) builder = builder.exclude(selector);
  if (scope.disable) builder = builder.disableRules([...scope.disable]);
  const result = await builder.analyze();
  expect(result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
}

/** Кнопка клиента Telegram (MainButton, BackButton) — нативная, в DOM её нет: нажатие — событием
 *  клиента, как его присылает Telegram (`Telegram.WebView.receiveEvent`). */
export async function pressTelegram(
  page: Page,
  event: 'main_button_pressed' | 'back_button_pressed',
) {
  await page.evaluate((name) => {
    const telegram = (
      window as unknown as { Telegram: { WebView: { receiveEvent(e: string, d: unknown): void } } }
    ).Telegram;
    telegram.WebView.receiveEvent(name, {});
  }, event);
}

/** Перейти на вкладку таббара по её подписи. */
export async function openTab(page: Page, name: string) {
  await page
    .getByRole('navigation', { name: /Разделы|Odeljci/ })
    .getByRole('link', { name })
    .click();
}

/** Перейти на S31 по таббару. */
export const openProfile = (page: Page, name = 'Профиль') => openTab(page, name);
