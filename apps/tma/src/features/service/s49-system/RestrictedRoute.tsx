// Маршрут `/restricted`: S49b после действия, которое сервер отклонил частичной санкцией
// (403 `restricted`: нельзя откликаться, публиковать, писать). Открывает его точка сборки;
// без санкции в сторе (перезагрузка, ссылка) — на главную.
import { Navigate, useRouter } from '@tanstack/react-router';

import { RestrictedScreen } from './RestrictedScreen.tsx';
import { useSystemStore } from './store.ts';

export const RESTRICTED_PATH = '/restricted';

export function RestrictedRoute() {
  const router = useRouter();
  const restriction = useSystemStore((state) => state.restriction);
  if (!restriction) return <Navigate to="/" replace />;
  const back = () => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: '/', replace: true });
  };
  return <RestrictedScreen state={restriction} onBack={back} />;
}
