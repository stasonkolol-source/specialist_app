// Бот Mini App для кабинета S33: если боту нельзя писать, честно говорим, как открыть канал —
// ссылка на чат с ботом (там «Старт», ADR-0011) рядом с requestWriteAccess. Имя — из сборки
// (`VITE_TELEGRAM_BOT`, без @), читается при вызове: тест задаёт его через `vi.stubEnv`.

/** Имя бота без @; пусто — ссылки на чат нет (остаётся только запрос разрешения). */
export function telegramBot(): string | null {
  return import.meta.env.VITE_TELEGRAM_BOT?.trim() || null;
}

/** Чат с ботом: Telegram покажет «Старт», и бот сможет писать. */
export function botChatLink(bot: string): string {
  return `https://t.me/${bot}`;
}
