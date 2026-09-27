// S01 «Запуск» (DEVELOPMENT_PLAN 1.5b): вход по initData до роутера. Пока идёт вход — экран
// запуска; после — первый экран по app/launch.ts (онбординг, deep link или открытый адрес), его
// чанк загружается заранее, чтобы после S01 не мелькал пустой экран. Ответ входа — тот же MeOut,
// что GET /me: он ложится в кэш /me. Нет сети или сбой сервера — S49 с «Повторить». Санкцию на
// аккаунт, техработы и 426 показывает StartupGate (стор S49); после его «Повторить» этот экран
// монтируется заново и входит ещё раз (неудачный вход не запоминается). Удачный вход разводит по
// экранам один раз за сессию: S49 посреди работы (техработы, ошибка рендера) тоже монтирует этот
// экран заново, но итог входа при запуске к тому времени устарел — пользователь уже прошёл
// онбординг или ушёл с экрана deep link.
import { getIdentityGetMeQueryKey } from '@sosed/api-client';
import type { SystemState } from '@sosed/hooks';
import { systemStateOf } from '@sosed/hooks';
import { useQueryClient } from '@tanstack/react-query';
import type { AnyRouter } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';

import { LaunchScreen } from '../features/onboarding/index.ts';
import { SystemScreen } from '../features/service/s49-system/index.ts';
import { launchHref } from './launch.ts';
import type { Auth } from './session.ts';

/** Доля полосы S01: конфиг уже есть, идёт вход. */
export const SIGN_IN_PROGRESS = 0.8;
/** Дольше не ждём чанк первого экрана: без него роутер покажет экран, когда тот догрузится. */
const PRELOAD_TIMEOUT_MS = 3000;
/** Роутеры, которые вход при запуске уже развёл по экранам: повторный монтаж их не трогает. */
const routed = new WeakSet<AnyRouter>();

interface Outcome {
  attempt: number;
  /** `ready` — первый экран выбран; иначе — почему войти не удалось. */
  result: 'ready' | SystemState;
}

export interface LaunchGateProps {
  launch: Auth['launch'];
  /** Цель deep link этого запуска (routes/startapp.ts); `null` — открыли без него. */
  deepLink: string | null;
  router: AnyRouter;
  children: ReactNode;
}

export function LaunchGate({ launch, deepLink, router, children }: LaunchGateProps) {
  const queryClient = useQueryClient();
  const [attempt, setAttempt] = useState(0);
  const [outcome, setOutcome] = useState<Outcome | null>(() =>
    routed.has(router) ? { attempt: 0, result: 'ready' } : null,
  );

  useEffect(() => {
    if (routed.has(router)) return;
    let active = true;
    void (async () => {
      const result = await launch();
      if (!active) return;
      if (result.kind === 'failed') {
        setOutcome({ attempt, result: systemStateOf(result.error) });
        return;
      }
      const user = result.kind === 'signed-in' ? result.user : null;
      if (user) queryClient.setQueryData(getIdentityGetMeQueryKey(), user);
      const href = launchHref(user, router.history.location, deepLink);
      if (href) {
        await Promise.race([
          // адрес строкой (с ?next=): buildLocation разбирает href сам, `to` при нём не нужен
          router
            .preloadRoute({ href } as Parameters<AnyRouter['preloadRoute']>[0])
            .catch(() => undefined),
          new Promise((resolve) => setTimeout(resolve, PRELOAD_TIMEOUT_MS)),
        ]);
        if (!active) return;
        router.history.replace(href);
      }
      routed.add(router);
      setOutcome({ attempt, result: 'ready' });
    })();
    return () => {
      active = false;
    };
  }, [attempt, launch, deepLink, router, queryClient]);

  if (outcome?.result === 'ready') return children;
  if (outcome) {
    return (
      <SystemScreen
        state={outcome.result}
        onRetry={() => setAttempt(outcome.attempt + 1)}
        retrying={outcome.attempt !== attempt}
      />
    );
  }
  return <LaunchScreen progress={SIGN_IN_PROGRESS} />;
}
