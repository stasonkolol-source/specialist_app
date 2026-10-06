// Мастер «Создать заявку» S20a–d и итог S21 (DEVELOPMENT_PLAN 5.2): путь от Главной до
// «опубликована» на фейке backend заявок (автопроверка публикует заявку, S21 перечитывает её сам),
// скриншоты каждого шага × тема × язык (поля заполнены, как на артбордах), axe-core; S21 — «что
// дальше»: отклики придут сюда и в Telegram, до какого числа открыта, «Хотите быстрее? Пригласите
// специалистов»; двойное «Опубликовать» — одна заявка; при выключенном канале бота S21 просит
// разрешение вместо обещания и после согласия обещает. Часы браузера — E2E_NOW (10:00 по
// Белграду): окно «18–21» ещё впереди. Имена скриншотов начинаются с кода артборда (make
// design-compare).
import type { Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

import { E2E_NOW, ME, NOTIFICATION_SETTINGS, WRITE_ACCESS } from '../src/testing/fixtures.ts';
import { JobsBackend } from '../src/testing/jobsBackend.ts';
import { sentRequests } from './api.ts';
import { THEMES, expectNoAxeViolations, open, pressTelegram, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    create: 'Создать заявку',
    what: 'Что нужно сделать?',
    summary: 'Коротко о задаче',
    suggestQuery: 'Люстры',
    title: 'Повесить люстру',
    category: 'Мастер на час → Люстры и карнизы',
    details: 'Подробности',
    detailsText: 'Потолок бетонный, крюк есть. Люстра на 5 рожков, её нужно собрать и подключить.',
    when: 'Когда и где?',
    today: 'Сегодня',
    where: 'Где',
    district: 'Лиман',
    // типограф ставит неразрывные пробелы: \s, а не пробел
    locate: /^Определить\sпо\sгеолокации$/,
    located: /^Район\sопределён:\sЛиман$/,
    address: 'Точный адрес',
    addressText: 'Народног фронта 25, кв. 14',
    budget: 'Сколько готовы заплатить?',
    amount: 'Сумма',
    preview: 'Проверьте заявку',
    pending: 'Заявка на проверке',
    published: 'Заявка опубликована',
    // типограф ставит неразрывные пробелы: \s, а не пробел
    whatNext: /^Отклики\sпридут\sсюда\sи\sв\sTelegram\s—\sбот\sнапишет\sо\sпервом\sже\./,
    invite: 'Хотите быстрее? Пригласите специалистов',
    inviteButton: 'Пригласить',
    allow: 'Присылать в Telegram',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    create: 'Novi zahtev',
    what: 'Šta treba uraditi?',
    summary: 'Ukratko o zadatku',
    suggestQuery: 'Lusteri',
    title: 'Okačiti luster',
    category: 'Majstor na sat → Lusteri i garnišne',
    details: 'Detalji',
    detailsText:
      'Plafon je betonski, kuka postoji. Luster sa 5 sijalica treba sklopiti i povezati.',
    when: 'Kada i gde?',
    today: 'Danas',
    where: 'Gde',
    district: 'Liman',
    locate: /^Odredi\spo\slokaciji$/,
    located: /^Deo\sgrada\sje\sodređen:\sLiman$/,
    address: 'Tačna adresa',
    addressText: 'Narodnog fronta 25, stan 14',
    budget: 'Koliko ste spremni da platite?',
    amount: 'Iznos',
    preview: 'Proverite zahtev',
    pending: 'Zahtev je na proveri',
    published: 'Zahtev je objavljen',
    whatNext: /^Ponude\sstižu\sovde\si\su\sTelegram\s—\sbot\sće\sjaviti\sčim\sstigne\sprva\./,
    invite: 'Želite brže? Pozovite stručnjake',
    inviteButton: 'Pozovi',
    allow: 'Šalji u Telegram',
  },
] as const;

type Texts = (typeof LOCALES)[number];

async function openWizard(page: Page, texts: Texts) {
  await page
    .getByRole('navigation', { name: /Разделы|Odeljci/ })
    .getByRole('link', { name: texts.create })
    .click();
  await expect(page.getByRole('heading', { name: texts.what })).toBeVisible();
}

async function fillWhat(page: Page, texts: Texts) {
  const summary = page.getByRole('textbox', { name: texts.summary });
  // категорию подбирает /suggest по тексту; потом — формулировка как на артборде
  await summary.fill(texts.suggestQuery);
  await expect(page.getByRole('button', { name: texts.category })).toBeVisible();
  await summary.fill(texts.title);
  await page.getByRole('textbox', { name: texts.details }).fill(texts.detailsText);
}

/** `locate` — район «Определить по геолокации» (точка mock-клиента — в Лимане), иначе из списка. */
async function fillWhen(page: Page, texts: Texts, { locate = false } = {}) {
  await page.getByRole('radio', { name: texts.today }).click();
  await page.getByRole('button', { name: '18–21' }).click();
  if (locate) {
    await page.getByRole('button', { name: texts.locate }).click();
    await expect(page.getByText(texts.located)).toBeVisible();
  } else {
    await page.getByRole('button', { name: texts.where }).click();
    await page.getByRole('dialog').getByRole('button', { name: texts.district }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
  }
  await page.getByRole('textbox', { name: texts.address }).fill(texts.addressText);
}

for (const theme of THEMES) {
  for (const texts of LOCALES) {
    test(`S20a–d, S21 заявка ${theme} ${texts.locale}: от Главной до «опубликована»`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const jobs = new JobsBackend();
      // ответ публикации — «на проверке», автопроверка тут же публикует: S21 перечитывает заявку
      jobs.autoModerate = true;
      const watch = await open(page, `theme=${theme}&lang=${texts.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: texts.locale },
        jobs,
        // бот может писать — S21 обещает «бот напишет о первом же»
        notificationSettings: { ...NOTIFICATION_SETTINGS, telegram: WRITE_ACCESS },
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
      await openWizard(page, texts);
      await fillWhat(page, texts);
      await snap(`S20a-create-what-${theme}-${texts.locale}.png`);
      await pressTelegram(page, 'main_button_pressed');

      await expect(page.getByRole('heading', { name: texts.when })).toBeVisible();
      await fillWhen(page, texts, { locate: true });
      await snap(`S20b-create-when-where-${theme}-${texts.locale}.png`);
      await pressTelegram(page, 'main_button_pressed');

      await expect(page.getByRole('heading', { name: texts.budget })).toBeVisible();
      await page.getByRole('textbox', { name: texts.amount }).fill('5000');
      await snap(`S20c-create-budget-${theme}-${texts.locale}.png`);
      await pressTelegram(page, 'main_button_pressed');

      await expect(page.getByRole('heading', { name: texts.preview })).toBeVisible();
      await snap(`S20d-create-preview-${theme}-${texts.locale}.png`);
      await pressTelegram(page, 'main_button_pressed');

      await expect(page.getByRole('heading', { name: texts.published })).toBeVisible();
      await expect(page.getByText(texts.whatNext)).toBeVisible();
      await expect(page.getByRole('heading', { name: texts.invite })).toBeVisible();
      await expect(
        page.getByRole('button', { name: texts.inviteButton, exact: true }).first(),
      ).toBeVisible();
      await snap(`S21-published-${theme}-${texts.locale}.png`);
      expect(jobs.posts).toHaveLength(1);
      expect(jobs.posts[0]?.body).toMatchObject({
        title: texts.title,
        urgency: 'today',
        budget_type: 'fixed',
        budget_min: 500_000,
        address_private: texts.addressText,
      });
    });
  }
}

// SMOKE-8: подпись `Text variant="cap"` с text-danger оставалась серой (.text-text2 позже в CSS),
// и «Далее» без категории молчал. Цвет — вычисленный в браузере, не класс
test('S20a, S20b «Далее» с пустым полем: красная подсказка, поле в фокусе', async ({ page }) => {
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const texts = LOCALES[0];
  const watch = await open(page, 'theme=light&lang=ru', {
    signedIn: true,
    jobs: new JobsBackend(),
  });
  await openWizard(page, texts);
  // к этому заголовку /suggest категорию не подбирает
  await page.getByRole('textbox', { name: texts.summary }).fill('Собрать комод');
  const hint = page.getByText(/^Опишите\sзадачу/);
  await expect(hint).toHaveCSS('color', 'rgb(91, 98, 112)');
  await pressTelegram(page, 'main_button_pressed');

  await expect(page.getByRole('heading', { name: texts.what })).toBeVisible();
  await expect(hint).toHaveCSS('color', 'rgb(198, 40, 40)');
  await expect(page.getByRole('button', { name: 'Выбрать' })).toBeFocused();

  await page.getByRole('textbox', { name: texts.summary }).fill(texts.suggestQuery);
  await expect(page.getByRole('button', { name: texts.category })).toBeVisible();
  await pressTelegram(page, 'main_button_pressed');
  await expect(page.getByRole('heading', { name: texts.when })).toBeVisible();
  await pressTelegram(page, 'main_button_pressed');
  await expect(page.getByText(/^Выберите,\sкогда\sнужен\sисполнитель$/)).toHaveCSS(
    'color',
    'rgb(198, 40, 40)',
  );
  expect(real(watch.problems)).toEqual([]);
});

test('S20d двойное «Опубликовать» — одна заявка', async ({ page }) => {
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const jobs = new JobsBackend();
  const texts = LOCALES[0];
  const watch = await open(page, 'theme=light&lang=ru', { signedIn: true, jobs });
  await openWizard(page, texts);
  await fillWhat(page, texts);
  await pressTelegram(page, 'main_button_pressed');
  await fillWhen(page, texts);
  await pressTelegram(page, 'main_button_pressed');
  await page.getByRole('radio', { name: 'Договорная' }).click();
  await pressTelegram(page, 'main_button_pressed');
  await expect(page.getByRole('heading', { name: texts.preview })).toBeVisible();

  await pressTelegram(page, 'main_button_pressed', { taps: 2 });

  await expect(page.getByRole('heading', { name: texts.pending })).toBeVisible();
  expect(jobs.jobs.size).toBe(1);
  expect(new Set(jobs.posts.map((post) => post.key)).size).toBe(1);
  expect(real(watch.problems)).toEqual([]);
});

test('S21 при выключенном канале бота просит разрешение и включает канал', async ({ page }) => {
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const jobs = new JobsBackend();
  jobs.status = 'published';
  const sent = sentRequests();
  const texts = LOCALES[0];
  const watch = await open(page, 'theme=light&lang=ru', { signedIn: true, jobs, sent });
  await openWizard(page, texts);
  await fillWhat(page, texts);
  await pressTelegram(page, 'main_button_pressed');
  await fillWhen(page, texts);
  await pressTelegram(page, 'main_button_pressed');
  await page.getByRole('radio', { name: 'Договорная' }).click();
  await pressTelegram(page, 'main_button_pressed');
  await expect(page.getByRole('heading', { name: texts.preview })).toBeVisible();
  await pressTelegram(page, 'main_button_pressed');

  await expect(page.getByRole('heading', { name: texts.published })).toBeVisible();
  // бот писать не может — вместо обещания просьба разрешить
  await expect(page.getByText(/^Разрешите\sботу\sписать/)).toBeVisible();
  await page.getByRole('button', { name: texts.allow }).click();

  await expect(page.getByText(texts.whatNext)).toBeVisible();
  await expect(page.getByRole('button', { name: texts.allow })).toHaveCount(0);
  expect(sent.writeAccess).toBe(1);
  expect(real(watch.problems)).toEqual([]);
});
