/// <reference types="vite/client" />

/** Версия приложения из package.json (vite define): X-Client `tma/<версия>`. */
declare const __APP_VERSION__: string;

interface ImportMetaEnv {
  readonly VITE_SENTRY_DSN?: string;
  /** Релиз Sentry — sha деплоя (deploy.yml, как APP_RELEASE backend); пусто — dev. */
  readonly VITE_SENTRY_RELEASE?: string;
  /** Окружение Sentry: stage, production (deploy.yml); пусто — dev. */
  readonly VITE_SENTRY_ENVIRONMENT?: string;
  readonly VITE_MEDIA_ORIGINS?: string;
  /** Имя бота без @: ссылки «Открыть в Telegram» браузерной оболочки (8.1). */
  readonly VITE_TELEGRAM_BOT?: string;
  /** База ассетов карты выбора точки (Q28): `novi-sad.pmtiles`, `fonts/{fontstack}/{range}.pbf`,
   *  `sprites/v4/<flavor>` (scripts/map/README.md). dev — `/map` (путь от корня), stage и prod —
   *  CDN R2; пусто — карты нет, вместо неё список районов. */
  readonly VITE_MAP_ASSETS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
