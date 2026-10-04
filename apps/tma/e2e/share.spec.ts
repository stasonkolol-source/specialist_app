// «Поделиться» (DEVELOPMENT_PLAN 7.4) на mock-платформе: карточка специалиста S08 и заявка S15
// уходят в выбор чата Telegram — карточкой `shareMessage` (вошедшему backend её готовит) или
// ссылкой `t.me/share/url`; ссылка с кодом приглашения `_r` открывает тот же экран у другого
// человека (deeplinks). Разбор каждого golden-вектора в экран — routes/startapp.test.ts.
import { encodeStartParam, parseStartParam } from '@sosed/links';
import type { Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

import { CARD_PROFILE_ID, E2E_NOW, SHARE_BOT } from '../src/testing/fixtures.ts';
import { FEED_JOBS, JobsBackend } from '../src/testing/jobsBackend.ts';
import { open, real } from './support.ts';

/** События клиенту Telegram с этого момента: имя и параметры. */
async function recordTelegram(page: Page) {
  await page.evaluate(() => {
    const target = window as unknown as {
      TelegramWebviewProxy: { postEvent(name: string, data?: string): void };
      sentToTelegram: [string, string | undefined][];
    };
    const proxy = target.TelegramWebviewProxy;
    const original = proxy.postEvent.bind(proxy);
    target.sentToTelegram = [];
    proxy.postEvent = (name, data) => {
      target.sentToTelegram.push([name, data]);
      original(name, data);
    };
  });
  return () =>
    page.evaluate(
      () =>
        (window as unknown as { sentToTelegram: [string, string | undefined][] }).sentToTelegram,
    );
}

/** Отправлено в Telegram: карточка (id) или ссылка (`/share/url?url=…`). */
function sharedVia(sent: [string, string | undefined][]): string | undefined {
  for (const [name, data] of sent) {
    const params = data ? (JSON.parse(data) as Record<string, string>) : {};
    if (name === 'web_app_send_prepared_message') return `card:${params['id']}`;
    if (name === 'web_app_open_tg_link' && params['path_full']?.startsWith('/share/url'))
      return `link:${params['path_full']}`;
  }
  return undefined;
}

const NAME = 'Алексей Морозов';
const CHANDELIER = FEED_JOBS[1]?.card.id ?? '';

test('share: S08 — в выбор чата, ссылка с кодом открывает профиль у другого (deeplinks)', async ({
  page,
}) => {
  const start = encodeStartParam({ type: 'specialist', id: CARD_PROFILE_ID });
  const watch = await open(page, `theme=light&lang=ru&start=${start}`);
  await expect(page.getByRole('heading', { name: NAME, level: 1 })).toBeVisible();
  const sent = await recordTelegram(page);

  const reply = page.waitForResponse((r) => r.url().endsWith('/api/v1/share'));
  await page.getByRole('button', { name: 'Поделиться профилем' }).click();
  const out = (await (await reply).json()) as {
    url: string;
    start_param: string;
    prepared_message_id: string | null;
  };

  const link = parseStartParam(out.start_param);
  expect(link).toMatchObject({ type: 'specialist', id: CARD_PROFILE_ID });
  expect(out.url).toBe(`https://t.me/${SHARE_BOT}?startapp=${out.start_param}`);
  await expect
    .poll(async () => sharedVia(await sent()))
    .toBe(
      out.prepared_message_id
        ? `card:${out.prepared_message_id}`
        : `link:/share/url?${new URLSearchParams({ url: out.url, text: 'Специалист' })}`,
    );
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);

  // тот, кому переслали: ссылка (с `_r`, если делился вошедший) открывает S08
  const other = await page.context().newPage();
  const otherWatch = await open(other, `theme=light&lang=ru&start=${out.start_param}`);
  await expect(other.getByRole('heading', { name: NAME, level: 1 })).toBeVisible();
  expect(real(otherWatch.problems)).toEqual([]);
  expect(otherWatch.unexpectedApi).toEqual([]);
});

test('share: S15 — заявка уходит в чат, ссылка открывает её (deeplinks)', async ({ page }) => {
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const start = encodeStartParam({ type: 'job', id: CHANDELIER });
  const watch = await open(page, `theme=light&lang=ru&start=${start}`, {
    jobs: new JobsBackend(),
  });
  await expect(page.getByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeVisible();
  const sent = await recordTelegram(page);

  const reply = page.waitForResponse((r) => r.url().endsWith('/api/v1/share'));
  await page.getByRole('button', { name: 'Поделиться заявкой' }).click();
  const out = (await (await reply).json()) as { start_param: string };

  expect(parseStartParam(out.start_param)).toMatchObject({ type: 'job', id: CHANDELIER });
  await expect.poll(async () => sharedVia(await sent())).toBeTruthy();
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);

  const other = await page.context().newPage();
  await other.clock.setFixedTime(new Date(E2E_NOW));
  const otherWatch = await open(other, `theme=light&lang=ru&start=${out.start_param}`, {
    jobs: new JobsBackend(),
  });
  await expect(other.getByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeVisible();
  expect(real(otherWatch.problems)).toEqual([]);
  expect(otherWatch.unexpectedApi).toEqual([]);
});
