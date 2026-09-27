import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';

import { server } from './msw.ts';

// Запрос без обработчика — ошибка теста: экран не должен ходить в неописанный API
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  // Без globals Testing Library не чистит DOM сама
  cleanup();
});
afterAll(() => server.close());

// jsdom не умеет прокрутку, а роутер восстанавливает её при переходах
window.scrollTo = () => undefined;
