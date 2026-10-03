// Фоновая работа после первого экрана (чанки вкладок, тексты других экранов, Sentry): когда экран
// дочитал свои данные и браузер свободен, — чтобы не отнимать сеть у Главной на медленном
// мобильном. Опрос и медленный ответ не откладывают её надолго: не позже MAX_WAIT_MS.
import type { QueryClient } from '@tanstack/react-query';

/** Столько без запросов в полёте — первый экран дочитал данные (его блоки уже смонтировались). */
const QUIET_MS = 500;
/** Ждать тишины не дольше: бейджи и чат опрашивают сервер. */
const MAX_WAIT_MS = 4000;
/** Простой браузера — не дольше. */
const IDLE_TIMEOUT_MS = 1500;

/** Экономия трафика (Data Saver): загрузок «на будущее» нет — экран загрузит своё, когда откроют. */
export function saveData(): boolean {
  return (navigator as { connection?: { saveData?: boolean } }).connection?.saveData === true;
}

/** Запустить `task`, когда первый экран дочитал данные и браузер свободен; вернуть отмену. */
export function afterFirstScreen(queryClient: QueryClient, task: () => void): () => void {
  let quiet: ReturnType<typeof setTimeout> | undefined;
  let idle: (() => void) | null = null;
  const settle = () => {
    clearTimeout(quiet);
    clearTimeout(cap);
    unsubscribe();
    idle ??= whenIdle(task);
  };
  const check = () => {
    clearTimeout(quiet);
    if (queryClient.isFetching() === 0) quiet = setTimeout(settle, QUIET_MS);
  };
  const unsubscribe = queryClient.getQueryCache().subscribe(check);
  const cap = setTimeout(settle, MAX_WAIT_MS);
  check();
  return () => {
    clearTimeout(quiet);
    clearTimeout(cap);
    unsubscribe();
    idle?.();
    idle = () => undefined;
  };
}

/** requestIdleCallback с пределом; в Safari (Telegram на iOS) его нет — следующая задача. */
function whenIdle(task: () => void): () => void {
  if ('requestIdleCallback' in window) {
    const id = window.requestIdleCallback(task, { timeout: IDLE_TIMEOUT_MS });
    return () => window.cancelIdleCallback(id);
  }
  const id = setTimeout(task, 0);
  return () => clearTimeout(id);
}
