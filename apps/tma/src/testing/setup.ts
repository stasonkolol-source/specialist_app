import { closeReport } from '@sosed/hooks';
import { cleanup, configure } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';

import { server } from './msw.ts';

// Первый экран файла под нагрузкой (turbo гоняет тесты пакетов параллельно) бывает дольше секунды
configure({ asyncUtilTimeout: 3000 });

// Запрос без обработчика — ошибка теста: экран не должен ходить в неописанный API
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  // Без globals Testing Library не чистит DOM сама
  cleanup();
  // шторка жалобы S46 — одна на приложение (4.7): следующий тест начинает без неё
  closeReport();
});
afterAll(() => server.close());

// jsdom не умеет прокрутку, а роутер восстанавливает её при переходах
window.scrollTo = () => undefined;
