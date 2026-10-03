// `?platform=mock` — клиент Telegram из mockTelegramEnv для разработки и e2e в браузере (тема и
// язык — `?theme=`, `?lang=`, версия Bot API клиента — `?tg=`: старый Telegram для экрана «обновите
// Telegram»), ответы попапам по очереди — `?popup=report,ok` (e2e меню чата S30). В dev-сборке
// `?initData=` — настоящий подписанный initData (`make cli ARGS='dev-initdata
// --url'`): вход на стенде из браузера тестовым пользователем; в prod-сборке параметр не действует.
// Своим чанком (app/platform.ts): в Telegram mock-клиент не скачивается.
import type { ColorScheme, Platform } from '@sosed/platform';
import { createMockPlatform } from '@sosed/platform/mock';

export function mockPlatform(params: URLSearchParams): Platform {
  const scheme: ColorScheme = params.get('theme') === 'dark' ? 'dark' : 'light';
  return createMockPlatform({
    colorScheme: scheme,
    languageCode: params.get('lang') ?? 'ru',
    startParam: params.get('start') ?? undefined,
    version: params.get('tg') ?? undefined,
    popupAnswer: params.get('popup')?.split(',') ?? undefined,
    initData: (import.meta.env.DEV && params.get('initData')) || undefined,
  }).platform;
}
