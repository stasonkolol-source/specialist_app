// Избранное (DEVELOPMENT_PLAN 4.6) с памятью, как backend: список — карточки выдачи S05, новые
// первыми; сохранить можно только того, кто есть в выдаче, — иначе 404; повтор — без ошибки.
// Общий для MSW (Vitest) и page.route (e2e).
import type { BackendReply } from './backend.ts';
import { problem } from './backend.ts';
import { cardsFor } from './fixtures.ts';

const LIST = '/api/v1/me/favorites';
const ITEM = /^\/api\/v1\/me\/favorites\/profile\/([^/]+)$/;

export class FavoritesBackend {
  /** id профилей, новые первыми. */
  ids: string[];
  private readonly availableUntil: string | undefined;

  constructor(ids: readonly string[] = [], availableUntil?: string) {
    this.ids = [...ids];
    this.availableUntil = availableUntil;
  }

  handle(method: string, pathname: string, locale: string | null): BackendReply | null {
    const cards = cardsFor(locale, this.availableUntil);
    if (pathname === LIST && method === 'GET') {
      const items = this.ids
        .map((id) => cards.find((card) => card.profile_id === id))
        .filter((card) => card !== undefined);
      return { status: 200, body: { items } };
    }
    const id = ITEM.exec(pathname)?.[1];
    if (id === undefined) return null;
    if (method === 'PUT') {
      if (!cards.some((card) => card.profile_id === id)) return problem(404, 'not_found');
      if (!this.ids.includes(id)) this.ids.unshift(id);
      return { status: 204, body: null };
    }
    if (method === 'DELETE') {
      this.ids = this.ids.filter((saved) => saved !== id);
      return { status: 204, body: null };
    }
    return null;
  }
}
