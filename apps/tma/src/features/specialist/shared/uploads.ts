// Транспорт загрузок кабинета (фото профиля, портфолио): веб — XHR с прогрессом и уменьшением фото.
// Отдельным модулем, чтобы Vitest подменял его (vi.mock): в jsdom нет холста и XHR в хранилище.
import type { MediaTransport } from '@sosed/hooks';
import { webMediaTransport } from '@sosed/platform';

export const mediaTransport: MediaTransport = webMediaTransport;
