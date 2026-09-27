/// <reference types="vite/client" />

/** Версия приложения из package.json (vite define): X-Client `tma/<версия>` и release Sentry. */
declare const __APP_VERSION__: string;

interface ImportMetaEnv {
  readonly VITE_SENTRY_DSN?: string;
  readonly VITE_MEDIA_ORIGINS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
