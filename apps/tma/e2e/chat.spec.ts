// Переписка S29–S30 (DEVELOPMENT_PLAN 6.4) и договорённость S53–S54 (6.5) на фейках backend.
// S29 — три диалога макета: прямой со скрытым телефоном («контакт скрыт») и двумя непрочитанными,
// по отклику на заявку и свой отклик с «Договорились»; время — коротко, как в Telegram. S30 —
// прямой диалог: памятка о предоплате, подпись дня, маска контакта с подсказкой «контакты
// откроются после договорённости», «Договориться» в шапке; тёмная тема — эталон D30. S53 —
// исполнитель по ссылке `d_` из бота видит «… предлагает договориться», условия и срок 72 ч и
// подтверждает. S54 — после договорённости «Сделка» в шапке, как на артборде, и шторка
// «Поделиться контактом» из полосы сделки под шапкой. S30 после завершённой сделки — снова
// «Договориться» в шапке (она не прокручивается; условия — из прошлой сделки), в полосе «Прошлая
// сделка» второй строкой Telegram и «Поделиться контактом». S24 — SecondaryButton «Написать»
// открывает диалог по отклику. Скриншоты × тема × язык, axe-core; имена скриншотов начинаются с
// кода артборда.
import { encodeStartParam } from '@sosed/links';
import { expect, test } from '@playwright/test';

import { ChatBackend, CONVERSATION_IDS } from '../src/testing/chatBackend.ts';
import { E2E_NOW, ME } from '../src/testing/fixtures.ts';
import {
  JobsBackend,
  proposedDealFixture,
  responseCardsFixture,
} from '../src/testing/jobsBackend.ts';
import { THEMES, expectNoAxeViolations, open, openTab, pressTelegram, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Сообщения',
    title: 'Сообщения',
    hint: 'Телефоны и ссылки видны только после договорённости',
    safety:
      'Не вносите предоплату незнакомым исполнителям. Платите после того, как работа сделана.',
    masked: 'Контакты откроются после договорённости — так безопаснее',
    hidden: 'контакт скрыт',
    day: '2 октября',
    agree: 'Договориться',
    proposal: 'Елена К. предлагает договориться',
    // getByText(регулярка) сверяет сырой текст, а типограф ставит неразрывные пробелы — пробел как \s
    expires: /^Если\sне\sответить\sза\s72\sчаса,\sдоговорённость\sотменится/,
    share: 'Поделиться контактом',
    username: 'Имя пользователя Telegram',
    deal: 'Сделка',
    past: 'Прошлая сделка «Повесить люстру»',
    terms: 'Договорились?',
    what: 'Что делаем',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Poruke',
    title: 'Poruke',
    hint: 'Telefoni i linkovi se vide tek posle dogovora',
    safety: 'Ne plaćajte unapred nepoznatim izvođačima. Platite tek kad posao bude završen.',
    masked: 'Kontakti će se otvoriti posle dogovora — tako je bezbednije',
    hidden: 'kontakt sakriven',
    day: '2. oktobar',
    agree: 'Dogovorite se',
    proposal: 'Елена К. predlaže dogovor',
    expires: /^Ako\sne\sodgovorite\sza\s72\ssata,\sdogovor\sće\sbiti\sotkazan/,
    share: 'Podelite kontakt',
    username: 'Korisničko ime u Telegram-u',
    deal: 'Dogovor',
    past: 'Prethodni dogovor „Повесить люстру“',
    terms: 'Dogovoreno?',
    what: 'Šta radimo',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    // тёмная S30 — эталон D30: GREP=D30 находит её по имени теста
    const dark = theme === 'dark' ? ' (D30)' : '';
    test(`S29, S30${dark} ${theme} ${l.locale}: диалоги и прямой диалог до договорённости`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const chat = new ChatBackend().seed();
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        chat,
      });
      const snap = async (name: string, fullPage = true) => {
        expect(real(watch.problems)).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(name, { fullPage });
        await expectNoAxeViolations(page);
        watch.problems.length = 0;
      };

      await openTab(page, l.tab);
      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
      await expect(page.getByRole('link', { name: /Алексей Морозов/ })).toBeVisible();
      await expect(page.getByRole('link', { name: /Никола Петрович/ })).toBeVisible();
      await expect(page.getByRole('link', { name: /Дмитрий Соколов/ })).toBeVisible();
      await expect(page.getByText(l.hint)).toBeVisible();
      await snap(`S29-chats-${theme}-${l.locale}.png`);

      await page.getByRole('link', { name: /Алексей Морозов/ }).click();
      // шапка диалога: собеседник ссылкой на S08 и «Договориться» — полосы сделки нет
      await expect(page.getByRole('link', { name: /^Алексей Морозов/ })).toBeVisible();
      await expect(page.getByRole('main').getByRole('button', { name: l.agree })).toBeVisible();
      await expect(page.getByText(l.safety)).toBeVisible();
      // день — подписью над перепиской; скрытый телефон — словами
      await expect(page.getByText(l.day, { exact: true })).toBeVisible();
      await expect(page.getByText(l.hidden, { exact: true })).toBeVisible();
      await expect(page.getByText(l.masked)).toBeVisible();
      // открытый диалог отмечает новое прочитанным: счётчик на вкладке гаснет
      await expect.poll(() => chat.reads.length).toBeGreaterThan(0);
      // переписка прокручена к последнему сообщению, композер прилип к низу: снимок экрана, как
      // артборд 390×844, а не всей страницы
      await expect(page.getByText(l.masked)).toBeInViewport();
      await snap(`S30-chat-${theme}-${l.locale}.png`, false);
    });

    test(`S53 ${theme} ${l.locale}: предложение договориться из бота`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const jobs = new JobsBackend();
      const deal = proposedDealFixture(CONVERSATION_IDS.direct);
      jobs.deals.set(deal.id, deal);
      jobs.dealRole = 'performer';
      const start = encodeStartParam({ type: 'deal', id: deal.id });
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${start}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs,
        chat: new ChatBackend().seed(),
      });

      await expect(page.getByRole('heading', { name: l.proposal, level: 1 })).toBeVisible();
      await expect(page.getByRole('region', { name: 'Повесить люстру' })).toBeVisible();
      await expect(page.getByText(l.expires)).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S53-confirm-agreement-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);

      // «Подтвердить» — MainButton mock-клиента: сделка договорена, предложение пропадает
      await pressTelegram(page, 'main_button_pressed');
      await expect(page.getByRole('heading', { name: l.proposal })).toBeHidden();
      expect(jobs.decisions).toEqual([{ id: deal.id, action: 'confirm' }]);
      // WebKit после подтверждения пишет в консоль, что CSP `style-src 'self'` не дал применить
      // встроенную таблицу стилей: экран при этом верный (находка отчёта 2026-10-04)
      expect(real(watch.problems, ['Refused to apply a stylesheet'])).toEqual([]);
    });

    test(`S54 ${theme} ${l.locale}: поделиться контактом после договорённости`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const start = encodeStartParam({ type: 'chat', id: CONVERSATION_IDS.performer });
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${start}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        chat: new ChatBackend().seed(),
      });

      // в шапке — «Сделка», как на артборде; «Поделиться контактом» — второй строкой полосы сделки
      const header = page
        .locator('header')
        .filter({ has: page.getByRole('heading', { name: 'Дмитрий Соколов', level: 1 }) });
      await expect(header.getByRole('button', { name: l.deal })).toBeVisible();
      await page.getByRole('main').getByRole('button', { name: l.share }).click();
      const sheet = page.getByRole('dialog', { name: l.share });
      // варианты — галочками, как на артборде: первый отмечен
      await expect(sheet.getByRole('checkbox', { name: new RegExp(l.username) })).toBeChecked();
      await expect(sheet.getByText('@elena_k')).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      // шторка закреплена на экране: снимок экрана, как артборд 390×844, а не всей страницы
      await expect(page).toHaveScreenshot(`S54-share-contact-${theme}-${l.locale}.png`);
      await expectNoAxeViolations(page, { include: '[role="dialog"]' });
    });
  }
}

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S30 ${theme} ${l.locale}: после завершённой сделки — договориться снова`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const chat = new ChatBackend().seed().pastDeal(CONVERSATION_IDS.direct, 'completed');
      const start = encodeStartParam({ type: 'chat', id: CONVERSATION_IDS.direct });
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${start}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        chat,
      });

      // снова «Договориться» — в шапке: она не прокручивается, а диалог открыт в конце переписки.
      // Telegram второй стороны и «Поделиться контактом» — второй строкой полосы прошлой сделки.
      // <header> внутри main — не landmark: ищем по заголовку
      const header = page
        .locator('header')
        .filter({ has: page.getByRole('heading', { name: 'Алексей Морозов', level: 1 }) });
      const again = header.getByRole('button', { name: l.agree });
      await expect(again).toBeInViewport();
      await expect(page.getByRole('main').getByRole('button', { name: l.agree })).toHaveCount(1);
      await expect(header.getByRole('button', { name: l.share })).toHaveCount(0);
      await expect(page.getByText(l.past)).toBeVisible();
      await expect(page.getByRole('main').getByRole('button', { name: l.share })).toBeVisible();
      await expect(header.getByRole('button', { name: /Telegram/ })).toHaveCount(0);
      await expect(
        page.getByRole('main').getByRole('button', { name: 'Telegram: @aleksey_m' }),
      ).toBeVisible();
      await expect(page.getByText(l.masked)).toBeInViewport();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S30-chat-again-${theme}-${l.locale}.png`);
      await expectNoAxeViolations(page);

      // та же шторка условий: «что делаем» — из прошлой сделки
      await again.click();
      const sheet = page.getByRole('dialog', { name: l.terms });
      await expect(sheet.getByRole('textbox', { name: l.what })).toHaveValue('Повесить люстру');
    });
  }
}

test('S24: SecondaryButton «Написать» открывает диалог по отклику', async ({ page }) => {
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const chat = new ChatBackend();
  const watch = await open(page, 'theme=light&lang=ru', {
    signedIn: true,
    jobs: new JobsBackend().seedMine(),
    chat,
  });
  const [aleksey] = responseCardsFixture();

  await openTab(page, 'Заявки');
  await page.getByRole('link', { name: 'Мои заявки' }).click();
  await page.getByRole('link', { name: /Повесить люстру/ }).click();
  await page.getByRole('link', { name: /^Алексей Морозов/ }).click();
  await expect(page.getByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeVisible();

  // «Написать» — SecondaryButton mock-клиента: нативная, в DOM её нет
  await pressTelegram(page, 'secondary_button_pressed');
  await expect(page.getByRole('textbox', { name: 'Сообщение' })).toBeVisible();
  expect(chat.starts).toEqual([{ response_id: aleksey?.id }]);
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});
