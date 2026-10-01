// Адаптер платформы — синглтон точки сборки (ADR-0020 §13). `?platform=mock` — клиент Telegram
// из mockTelegramEnv для разработки и e2e в браузере (тема и язык — `?theme=`, `?lang=`, версия
// Bot API клиента — `?tg=`: старый Telegram для экрана «обновите Telegram»). В dev-сборке
// `?initData=` — настоящий подписанный initData (`make cli ARGS='dev-initdata --url'`): вход на
// стенде из браузера тестовым пользователем; в prod-сборке параметр не действует.
import type { ColorScheme, Platform } from '@sosed/platform';
import { createMockPlatform, createPlatform } from '@sosed/platform';

export function selectPlatform(search: string = window.location.search): Platform {
  const params = new URLSearchParams(search);
  if (params.get('platform') !== 'mock') return createPlatform();
  const scheme: ColorScheme = params.get('theme') === 'dark' ? 'dark' : 'light';
  return createMockPlatform({
    colorScheme: scheme,
    languageCode: params.get('lang') ?? 'ru',
    startParam: params.get('start') ?? undefined,
    version: params.get('tg') ?? undefined,
    initData: (import.meta.env.DEV && params.get('initData')) || undefined,
  }).platform;
}
