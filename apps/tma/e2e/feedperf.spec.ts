// Прокрутка ленты S13 на 1 000 заявок (DEVELOPMENT_PLAN 5.3): с процессором ×4 медленнее (CDP)
// прокрутка колесом до конца не даёт long tasks — задач главного потока длиннее 50 мс. Список
// виртуальный, страницы по 20 догружаются на ходу. Порог — 50 мс, утверждает владелец. Только
// Chromium (троттлинг — через CDP) и только по `make feed-perf`: в общем прогоне e2e тест
// пропускается — тормозить остальные незачем.
import { expect, test } from '@playwright/test';

import { E2E_NOW, ME } from '../src/testing/fixtures.ts';
import type { FeedFixture } from '../src/testing/jobsBackend.ts';
import { FEED_JOBS, JobsBackend } from '../src/testing/jobsBackend.ts';
import { open, openTab } from './support.ts';

const JOBS = 1_000;
const PAGE = 20;
const LONG_TASK_MS = 50;
/** Шаг колеса — меньше экрана: прокрутка «пальцем», а не прыжками. */
const STEP_PX = 600;
const MAX_STEPS = 2_000;

/** Тысяча заявок из J1–J6: у каждой свой id и время — новые сверху. */
function thousand(): FeedFixture[] {
  const newest = new Date(E2E_NOW).getTime();
  return Array.from({ length: JOBS }, (_, index) => {
    const source = FEED_JOBS[index % FEED_JOBS.length] as FeedFixture;
    return {
      ...source,
      card: {
        ...source.card,
        id: `0199ee00-0000-7000-8000-${String(index).padStart(12, '0')}`,
        title: `${source.card.title} · ${index + 1}`,
        published_at: new Date(newest - index * 60_000).toISOString(),
      },
    };
  });
}

test('feed-perf: 1 000 заявок прокручиваются без long tasks (CPU ×4)', async ({
  page,
  browserName,
}, info) => {
  test.skip(!process.env['FEED_PERF'], 'только make feed-perf');
  test.skip(browserName !== 'chromium' || info.project.name !== 'chromium-360', 'Chromium 360');
  test.setTimeout(240_000);
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const jobs = new JobsBackend(thousand());
  const watch = await open(page, 'theme=light&lang=ru', { signedIn: true, me: ME, jobs });
  await openTab(page, 'Заявки');
  await expect(page.getByRole('heading', { name: 'Заявки рядом', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible();

  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  await page.evaluate(() => {
    const marks = window as unknown as { longTasks: number[] };
    marks.longTasks = [];
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) marks.longTasks.push(entry.duration);
    }).observe({ type: 'longtask' });
  });

  // колесом до конца ленты: пока последняя страница не пришла и «Показать ещё» не пропала
  const more = page.getByRole('button', { name: 'Показать ещё' });
  for (let step = 0; step < MAX_STEPS && (await more.count()) > 0; step += 1) {
    await page.mouse.wheel(0, STEP_PX);
    await page.waitForTimeout(16);
  }
  await expect(more).toHaveCount(0);
  // последняя страница пришла — докрутить до последней карточки
  const last = page.getByRole('heading', { name: /· 1000$/u, level: 2 });
  for (let step = 0; step < MAX_STEPS && (await last.count()) === 0; step += 1) {
    await page.mouse.wheel(0, STEP_PX);
    await page.waitForTimeout(16);
  }
  await expect(last).toBeAttached();

  const long = await page.evaluate(() => (window as unknown as { longTasks: number[] }).longTasks);
  const cards = await page.getByRole('heading', { level: 2 }).count();
  console.log(
    `feed-perf: ${jobs.feedRequests.length} страниц, в DOM ${cards} карточек из ${JOBS}; long tasks — ${long.length}, самая долгая — ${Math.round(Math.max(0, ...long))} мс (порог ${LONG_TASK_MS} мс)`,
  );
  expect(jobs.feedRequests).toHaveLength(JOBS / PAGE);
  expect(cards).toBeLessThan(50);
  expect(long.filter((duration) => duration > LONG_TASK_MS)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});
