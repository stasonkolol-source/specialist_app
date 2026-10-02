// Холодный старт Главной S03 (DEVELOPMENT_PLAN 4.8): < 2,5 с на «среднем Android» — профиль
// Lighthouse mobile: процессор ×4 медленнее, сеть «медленный 4G» (RTT 150 мс, 1,6 Мбит/с вниз,
// 750 Кбит/с вверх). Собранное приложение, пустой кэш (новый контекст браузера), ответы API — с
// задержкой 200 мс (фикстуры приходят мгновенно, а сеть их бы задержала). Замер — до заголовка
// Главной и до LCP. Только Chromium (троттлинг — через CDP) и только по `make coldstart`: в общем
// прогоне e2e тест пропускается — тормозить остальные незачем.
import { expect, test } from '@playwright/test';

import { open } from './support.ts';

const BUDGET_MS = 2_500;
const API_DELAY_MS = 200;
const TITLE = 'Найдём мастера рядом';
/** Lighthouse mobile (simulated throttling «Slow 4G» + 4× CPU). */
const NETWORK = {
  offline: false,
  latency: 150,
  downloadThroughput: (1.6 * 1024 * 1024) / 8,
  uploadThroughput: (750 * 1024) / 8,
};

test('coldstart: Главная на «среднем Android» быстрее 2,5 с', async ({
  page,
  browserName,
}, info) => {
  test.skip(!process.env['COLDSTART'], 'только make coldstart');
  test.skip(browserName !== 'chromium' || info.project.name !== 'chromium-360', 'Chromium 360');

  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', NETWORK);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  // время появления заголовка и LCP — изнутри страницы, от начала навигации
  await page.addInitScript((title) => {
    const marks = window as unknown as { titleAt?: number; lcp?: number };
    new MutationObserver((_, observer) => {
      const heading = [...document.querySelectorAll('h1')].find((h) => h.textContent === title);
      if (heading) {
        marks.titleAt = performance.now();
        observer.disconnect();
      }
    }).observe(document, { childList: true, subtree: true, characterData: true });
    new PerformanceObserver((list) => {
      const last = list.getEntries().at(-1);
      if (last) marks.lcp = last.startTime;
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  }, TITLE);

  const watch = await open(page, 'theme=light&lang=ru', { delayMs: API_DELAY_MS });
  await expect(page.getByRole('heading', { name: TITLE, level: 1 })).toBeVisible({
    timeout: 15_000,
  });
  const { titleAt, lcp } = await page.evaluate(() => {
    const marks = window as unknown as { titleAt?: number; lcp?: number };
    return { titleAt: marks.titleAt, lcp: marks.lcp };
  });
  console.log(
    `coldstart: заголовок Главной — ${Math.round(titleAt ?? NaN)} мс, LCP — ${Math.round(lcp ?? NaN)} мс (бюджет ${BUDGET_MS} мс)`,
  );
  expect(watch.unexpectedApi).toEqual([]);
  expect(titleAt).toBeLessThan(BUDGET_MS);
});
