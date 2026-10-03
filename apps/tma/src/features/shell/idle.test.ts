// Фон после первого экрана (idle.ts): ждёт, пока запросы экрана дочитаются, но не бесконечно.
import { QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { afterFirstScreen } from './idle.ts';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

/** Запрос, который отвечает, когда тест скажет. */
function pending(client: QueryClient) {
  let answer: (value: string) => void = () => undefined;
  void client.prefetchQuery({
    queryKey: ['slow'],
    queryFn: () =>
      new Promise<string>((resolve) => {
        answer = resolve;
      }),
  });
  return (value: string) => answer(value);
}

describe('afterFirstScreen', () => {
  it('waits until the first screen data settles', async () => {
    const client = new QueryClient();
    const answer = pending(client);
    const task = vi.fn();
    afterFirstScreen(client, task);

    await vi.advanceTimersByTimeAsync(1000);
    expect(task).not.toHaveBeenCalled();

    answer('ok');
    await vi.advanceTimersByTimeAsync(1000);
    expect(task).toHaveBeenCalledOnce();
  });

  it('does not wait forever for a slow or polling request', async () => {
    const client = new QueryClient();
    pending(client);
    const task = vi.fn();
    afterFirstScreen(client, task);

    await vi.advanceTimersByTimeAsync(6000);
    expect(task).toHaveBeenCalledOnce();
  });

  it('is cancelled with the screen', async () => {
    const client = new QueryClient();
    const task = vi.fn();
    const cancel = afterFirstScreen(client, task);
    cancel();

    await vi.advanceTimersByTimeAsync(6000);
    expect(task).not.toHaveBeenCalled();
  });
});
