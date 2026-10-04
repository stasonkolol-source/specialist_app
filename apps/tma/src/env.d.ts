/// <reference types="vite/client" />

/** Версия приложения из package.json (vite define): X-Client `tma/<версия>` и release Sentry. */
declare const __APP_VERSION__: string;

interface ImportMetaEnv {
  readonly VITE_SENTRY_DSN?: string;
  readonly VITE_MEDIA_ORIGINS?: string;
  /** Имя бота без @: ссылки «Открыть в Telegram» браузерной оболочки (8.1). */
  readonly VITE_TELEGRAM_BOT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
