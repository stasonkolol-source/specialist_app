import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Без globals Testing Library не чистит DOM сама
afterEach(cleanup);

// jsdom не умеет прокрутку, а роутер восстанавливает её при переходах
window.scrollTo = () => undefined;
