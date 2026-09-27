import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Без globals Testing Library не чистит DOM сама
afterEach(cleanup);
