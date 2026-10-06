// Вход Mini App (ADR-0009): initData из launch params → POST /auth/telegram → токены в памяти.
// Тот же обмен — колбэк onReauth api-client, когда refresh не помог (сессия отозвана или истекла).
// Вход при запуске (S01, DEVELOPMENT_PLAN 1.5b) отдаёт ещё и пользователя: ответ входа — тот же
// MeOut, что GET /me, по нему решается онбординг без второго запроса.
import type { AuthOut, MeOut } from '@sosed/api-client';
import { ApiError, identityAuthenticateTelegram, setSession } from '@sosed/api-client';
import type { Platform } from '@sosed/platform';

/** Итог входа. `guest` — войти нечем (браузер без Telegram) или initData отвергнут (401): каталог
 *  смотреть можно, создавать — нет. `failed` — сеть, сбой сервера, санкция, техработы. */
export type Launch =
  | { kind: 'signed-in'; user: MeOut; isNew: boolean }
  | { kind: 'guest' }
  | { kind: 'failed'; error: unknown };

export interface Auth {
  /** true — сессия есть: вход по initData удался. Параллельные вызовы делят один запрос. */
  signIn(): Promise<boolean>;
  /** Вход при запуске: первый вызов начинает обмен, следующие получают тот же итог (StrictMode,
   *  ранний старт в main.tsx). После неудачи (`failed`) следующий вызов входит заново:
   *  «Повторить» на S49. */
  launch(): Promise<Launch>;
}

/** `onSignedIn` — после каждого удачного входа с пользователем из ответа (тот же MeOut, что /me).
 *  `onRefused` — вход отклонён: санкция на аккаунт (403 `restricted`), 426, техработы, сеть. */
export function createAuth(
  platform: Platform,
  onSignedIn: (user: MeOut) => void = () => undefined,
  onRefused: (error: unknown) => void = () => undefined,
): Auth {
  let pending: Promise<Launch> | null = null;
  let launched: Promise<Launch> | null = null;
  let launchFailed = false;
  // initData отвергнут (401) — тот же initData не примут и потом: повторный вход по нему (onReauth
  // на 401 любого запроса гостя) в сеть не идёт — одна попытка входа на запуск
  let refused = false;

  const exchange = async (): Promise<Launch> => {
    const initData = platform.launch.rawInitData;
    if (!initData) return { kind: 'guest' }; // браузер без Telegram: вход появится с кнопкой «Войти» (этап 2)
    if (refused) return { kind: 'guest' };
    let auth: AuthOut;
    try {
      auth = await identityAuthenticateTelegram({ authorization: `tma ${initData}` });
    } catch (error) {
      setSession(null);
      // 401 — initData не принят (устарел после перезагрузки внутри клиента): как гость
      refused = error instanceof ApiError && error.status === 401;
      onRefused(error);
      return refused ? { kind: 'guest' } : { kind: 'failed', error };
    }
    setSession({ accessToken: auth.access_token, refreshToken: auth.refresh_token });
    onSignedIn(auth.user);
    return { kind: 'signed-in', user: auth.user, isNew: auth.is_new };
  };

  const run = (): Promise<Launch> => {
    pending ??= exchange().finally(() => {
      pending = null;
    });
    return pending;
  };

  return {
    async signIn() {
      return (await run()).kind === 'signed-in';
    },
    launch() {
      if (!launched || launchFailed) {
        launchFailed = false;
        launched = run().then((result) => {
          launchFailed = result.kind === 'failed';
          return result;
        });
      }
      return launched;
    },
  };
}
