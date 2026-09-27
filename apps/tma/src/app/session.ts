// Вход Mini App (ADR-0009): initData из launch params → POST /auth/telegram → токены в памяти.
// Тот же обмен — колбэк onReauth api-client, когда refresh не помог (сессия отозвана или истекла).
import type { AuthOut, MeOut } from '@sosed/api-client';
import { identityAuthenticateTelegram, setSession } from '@sosed/api-client';
import type { Platform } from '@sosed/platform';

export interface Auth {
  /** true — сессия есть: вход по initData удался. Параллельные вызовы делят один запрос. */
  signIn(): Promise<boolean>;
}

/** `onSignedIn` — после каждого удачного входа с пользователем из ответа (тот же MeOut, что /me).
 *  `onRefused` — вход отклонён: санкция на аккаунт (403 `restricted`), 426, техработы, сеть. */
export function createAuth(
  platform: Platform,
  onSignedIn: (user: MeOut) => void = () => undefined,
  onRefused: (error: unknown) => void = () => undefined,
): Auth {
  let pending: Promise<boolean> | null = null;

  const exchange = async (): Promise<boolean> => {
    const initData = platform.launch.rawInitData;
    if (!initData) return false; // браузер без Telegram: вход появится с кнопкой «Войти» (этап 2)
    let auth: AuthOut;
    try {
      auth = await identityAuthenticateTelegram({ authorization: `tma ${initData}` });
    } catch (error) {
      setSession(null);
      onRefused(error);
      return false;
    }
    setSession({ accessToken: auth.access_token, refreshToken: auth.refresh_token });
    onSignedIn(auth.user);
    return true;
  };

  return {
    signIn() {
      pending ??= exchange().finally(() => {
        pending = null;
      });
      return pending;
    },
  };
}
