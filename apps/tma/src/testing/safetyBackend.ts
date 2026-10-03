// Фейк backend жалоб и блокировок (DEVELOPMENT_PLAN 4.7) — как сервер: GET /me/blocks (недавние
// первыми), PUT /me/blocks/{id} (повтор — без ошибки, себя — 409), DELETE (своей блокировки нет —
// тоже 204), POST /reports (причина — из списка типа, повтор на тот же объект — та же жалоба 200,
// двадцать первая — 429 `reports_limit`). `blockedMe` — кто заблокировал меня: переписка с ним
// закрыта (фейк переписки спрашивает `side`). Общий для MSW (Vitest) и page.route (e2e).
import type { BlockedUserOut, ReportIn, ReportOut, SpecialistCardOut } from '@sosed/api-client';
import { allowedReason, reportQueue } from '@sosed/hooks';

import type { BackendReply } from './backend.ts';
import { problem } from './backend.ts';
import { ME, cardsFor, userIdOf } from './fixtures.ts';

const BLOCKS = '/api/v1/me/blocks';
const BLOCK = /^\/api\/v1\/me\/blocks\/([^/]+)$/;
const REPORTS = '/api/v1/reports';
const DAILY_REPORTS = 20;

/** Заблокированные артборда S44: без фото — инициалы. */
export const ARTBOARD_BLOCKS: BlockedUserOut[] = [
  {
    user_id: '01a0e301-0000-7000-8000-000000000001',
    display_name: 'Олег Р.',
    avatar: null,
    profile_id: null,
    blocked_at: '2026-09-14T12:00:00Z',
  },
  {
    user_id: '01a0e301-0000-7000-8000-000000000002',
    display_name: 'Марина Т.',
    avatar: null,
    profile_id: null,
    blocked_at: '2026-09-02T12:00:00Z',
  },
];

const short = (name: string) => {
  const [first = '', ...rest] = name.split(/\s+/);
  const last = rest.at(-1);
  return last ? `${first} ${last.charAt(0).toUpperCase()}.` : first;
};

/** Кого фейк знает: специалисты выдачи по аккаунту — имя «Алексей М.» и профиль, как в ответе. */
function directory(cards: SpecialistCardOut[]): Map<string, Omit<BlockedUserOut, 'blocked_at'>> {
  return new Map(
    cards.map((card) => [
      userIdOf(card.profile_id),
      {
        user_id: userIdOf(card.profile_id),
        display_name: short(card.display_name),
        avatar: null,
        profile_id: card.profile_id,
      },
    ]),
  );
}

export class SafetyBackend {
  blocks: BlockedUserOut[];
  /** Кто заблокировал меня. */
  blockedMe = new Set<string>();
  reports: ReportIn[] = [];
  private readonly known: Map<string, Omit<BlockedUserOut, 'blocked_at'>>;
  private readonly filed = new Map<string, ReportOut>();

  constructor(blocks: readonly BlockedUserOut[] = [], known: readonly BlockedUserOut[] = []) {
    this.blocks = [...blocks];
    this.known = directory(cardsFor('ru'));
    for (const user of known) this.known.set(user.user_id, user);
  }

  /** Блокировка со мной: моя главнее — её можно снять. */
  side(userId: string): 'by_me' | 'by_them' | null {
    if (this.blocks.some((item) => item.user_id === userId)) return 'by_me';
    return this.blockedMe.has(userId) ? 'by_them' : null;
  }

  handle(method: string, pathname: string, body: unknown): BackendReply | null {
    if (pathname === BLOCKS && method === 'GET') {
      return { status: 200, body: { items: this.blocks } };
    }
    if (pathname === REPORTS && method === 'POST') return this.report(body as ReportIn);
    const id = BLOCK.exec(pathname)?.[1];
    if (id === undefined) return null;
    if (method === 'PUT') {
      if (id === ME.id) return problem(409, 'cannot_block_self');
      if (!this.blocks.some((item) => item.user_id === id)) {
        const user = this.known.get(id) ?? {
          user_id: id,
          display_name: 'Пользователь',
          avatar: null,
          profile_id: null,
        };
        this.blocks.unshift({ ...user, blocked_at: new Date().toISOString() });
      }
      return { status: 204, body: null };
    }
    if (method === 'DELETE') {
      this.blocks = this.blocks.filter((item) => item.user_id !== id);
      return { status: 204, body: null };
    }
    return null;
  }

  private report(input: ReportIn): BackendReply {
    if (!allowedReason(input.target_type, input.reason)) {
      return problem(422, 'invalid_report', { field: 'reason', reason: 'not_for_target' });
    }
    const key = `${input.target_type}:${input.target_id}`;
    const open = this.filed.get(key);
    if (open) return { status: 200, body: open };
    if (this.reports.length >= DAILY_REPORTS) {
      return problem(429, 'reports_limit', {
        detail: 'Слишком много жалоб за сутки. Попробуйте завтра или напишите в поддержку.',
      });
    }
    this.reports.push(input);
    const filed: ReportOut = {
      id: `01a0e400-0000-7000-8000-${this.reports.length.toString(16).padStart(12, '0')}`,
      target_type: input.target_type,
      target_id: input.target_id,
      reason: input.reason,
      status: 'open',
      queue: reportQueue(input.reason),
      created_at: new Date().toISOString(),
    };
    this.filed.set(key, filed);
    return { status: 201, body: filed };
  }
}
