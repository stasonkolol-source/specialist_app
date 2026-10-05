// Гость в браузере (8.1) откликается в Telegram: ссылка `t.me/<бот>?startapp=j_<id>` открывает
// Mini App сразу на этой заявке — без промежуточной страницы «"Соседи" живут в Telegram».
import { encodeStartParam } from '@sosed/links';

/** Бот Mini App (`VITE_TELEGRAM_BOT` при сборке, без @); пусто — ссылки нет. */
const TELEGRAM_BOT: string | null = import.meta.env.VITE_TELEGRAM_BOT?.trim() || null;

/** Ссылка на заявку в Mini App; без бота — `null` (кнопка остаётся обычной). */
export function respondInTelegramLink(
  jobId: string,
  bot: string | null = TELEGRAM_BOT,
): string | null {
  return bot
    ? `https://t.me/${bot}?startapp=${encodeStartParam({ type: 'job', id: jobId })}`
    : null;
}
