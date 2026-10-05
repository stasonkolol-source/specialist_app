// Гость в браузере (8.1) пишет специалисту в Telegram: ссылка `t.me/<бот>?startapp=s_<id>`
// открывает Mini App сразу на этом профиле — без промежуточной страницы «"Соседи" живут в
// Telegram». Так же устроена «Откликнуться в Telegram» на S15 (jobs/s15-job/telegram.ts).
import { encodeStartParam } from '@sosed/links';

/** Бот Mini App (`VITE_TELEGRAM_BOT` при сборке, без @); пусто — ссылки нет. Читается при вызове:
 *  в сборке Vite подставляет значение, а тест может задать его через `vi.stubEnv`. */
function telegramBot(): string | null {
  return import.meta.env.VITE_TELEGRAM_BOT?.trim() || null;
}

/** Ссылка на профиль в Mini App; без бота — `null` (остаётся обычная кнопка «Написать»). */
export function writeInTelegramLink(
  profileId: string,
  bot: string | null = telegramBot(),
): string | null {
  return bot
    ? `https://t.me/${bot}?startapp=${encodeStartParam({ type: 'specialist', id: profileId })}`
    : null;
}
