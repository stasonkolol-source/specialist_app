// «Отзывы до платформы» в памяти — как backend 7.6а: приглашения специалиста S55 (пять мест: ждущая
// отзыва и использованная ссылка место занимают, истёкшая — нет; отозвать — неиспользованную) и
// форма S56 по ссылке с отзывом по ней. Путь специалиста `/me/profile/review-invites*` приходит сюда
// из ProfileBackend (там же видно, опубликован ли профиль), публичный `/review-invites/{token}` — из
// e2e/api.ts и testing/msw.ts. Отзывы ждут модератора: в список S55 они попадают «На модерации».
import type {
  InviteReviewIn,
  InviteSpecialistOut,
  ReviewInviteIn,
  ReviewInviteOut,
  ReviewOut,
} from '@sosed/api-client';
import { encodeStartParam } from '@sosed/links';

import type { BackendReply } from './backend.ts';
import { problem } from './backend.ts';
import { E2E_NOW, specialistCardFor } from './fixtures.ts';
import type { BackendLog } from './profileBackend.ts';

/** Мест под приглашения — LIMIT backend. */
export const INVITES_LIMIT = 5;
/** Бот e2e-сборки (VITE_TELEGRAM_BOT в e2e:build): ссылки `t.me/<bot>?startapp=ri_…`. */
const BOT = 'sosed_e2e_bot';
const DAY_MS = 24 * 60 * 60 * 1000;
/** Статусы, которые место занимают: ждущая ссылка и использованная (отзыв снят — место не
 *  возвращается). */
const TAKES_SLOT = new Set(['waiting', 'under_review', 'published', 'removed']);

/** Приглашение S55 с токеном `n` и ссылкой на него. */
export function inviteFixture(
  n: number,
  fields: Partial<ReviewInviteOut> & Pick<ReviewInviteOut, 'status' | 'created_at'>,
): ReviewInviteOut {
  const token = `0199ff00-0000-4000-8000-${String(n).padStart(12, '0')}`;
  const start = encodeStartParam({ type: 'review_invite', id: token });
  return {
    token,
    url: `https://t.me/${BOT}?startapp=${start}`,
    start_param: start,
    client_name: null,
    reviewer_name: null,
    rating: null,
    expires_at: new Date(Date.parse(fields.created_at) + 30 * DAY_MS).toISOString(),
    used_at: null,
    published_at: null,
    ...fields,
  };
}

/** Приглашения артборда S55 при часах E2E_NOW: два опубликованных отзыва, один на модерации и
 *  ссылка Андрею, которая ждёт отзыва, — «4 из 5 · осталось 1». */
export function invitesFixture(now = Date.parse(E2E_NOW)): ReviewInviteOut[] {
  const ago = (days: number) => new Date(now - days * DAY_MS).toISOString();
  return [
    inviteFixture(4, { status: 'waiting', client_name: 'Андрей В.', created_at: ago(2) }),
    inviteFixture(3, {
      status: 'under_review',
      client_name: 'Татьяна',
      reviewer_name: 'Татьяна М.',
      rating: 5,
      created_at: ago(4),
      used_at: ago(1),
    }),
    inviteFixture(2, {
      status: 'published',
      reviewer_name: 'Ксения Д.',
      rating: 5,
      created_at: ago(9),
      used_at: ago(7),
      published_at: ago(5),
    }),
    inviteFixture(1, {
      status: 'published',
      reviewer_name: 'Олег Р.',
      rating: 5,
      created_at: ago(20),
      used_at: ago(16),
      published_at: ago(14),
    }),
  ];
}

/** Кто просит отзыв на S56: Алексей Морозов карточки S08, категории — на языке запроса. */
export function inviteSpecialistFor(locale: string | null): InviteSpecialistOut {
  const card = specialistCardFor(locale);
  return {
    profile_id: card.id,
    display_name: card.display_name,
    first_name: card.display_name.split(' ')[0] ?? card.display_name,
    avatar: card.avatar,
    headline: card.headline,
    categories: card.categories,
  };
}

export interface InvitesBackendOptions {
  /** Ссылку S56 открыл сам специалист (`is_own`). */
  own?: boolean;
  /** Этот человек уже оставлял отзыв до платформы об этом специалисте. */
  reviewed?: boolean;
  /** Часы backend: ссылки истекают через 30 дней, «отправлена 2 дня назад». */
  now?: () => Date;
}

export class InvitesBackend {
  items: ReviewInviteOut[];
  /** Отзывы по ссылкам: токен → что прислал клиент. */
  readonly reviews = new Map<string, InviteReviewIn>();
  readonly log: BackendLog = [];
  private readonly own: boolean;
  private reviewed: boolean;
  private readonly now: () => Date;
  private created = 0;

  constructor(
    items: readonly ReviewInviteOut[] = [],
    { own = false, reviewed = false, now = () => new Date() }: InvitesBackendOptions = {},
  ) {
    this.items = [...items];
    this.own = own;
    this.reviewed = reviewed;
    this.now = now;
  }

  get taken(): number {
    return this.items.filter((invite) => TAKES_SLOT.has(invite.status)).length;
  }

  /** `/me/profile/review-invites*` специалиста; null — запрос не сюда. `published` — профиль
   *  опубликован: только тогда можно создать ссылку. */
  handleMine(request: string, body: unknown, published: boolean): BackendReply | null {
    if (request === 'GET /me/profile/review-invites') {
      return { status: 200, body: { items: this.items, limit: INVITES_LIMIT, taken: this.taken } };
    }
    if (request === 'POST /me/profile/review-invites') {
      this.log.push({ request, body });
      if (!published) return problem(409, 'review_invites_unavailable');
      if (this.taken >= INVITES_LIMIT) {
        return problem(409, 'review_invites_full', { limit: INVITES_LIMIT });
      }
      const name = ((body as ReviewInviteIn | undefined)?.client_name ?? '').trim();
      this.created += 1;
      const invite = inviteFixture(100 + this.created, {
        status: 'waiting',
        client_name: name || null,
        created_at: this.now().toISOString(),
      });
      this.items = [invite, ...this.items];
      return { status: 201, body: invite };
    }
    const revoke = /^DELETE \/me\/profile\/review-invites\/(.+)$/.exec(request);
    if (!revoke) return null;
    this.log.push({ request, body });
    const invite = this.items.find((item) => item.token === revoke[1]);
    if (!invite) return problem(404, 'review_invite_not_found');
    if (invite.used_at !== null) return problem(409, 'review_invite_used');
    this.items = this.items.filter((item) => item !== invite);
    return { status: 204, body: null };
  }

  /** `GET` и `POST /review-invites/{token}`: форма S56 и отзыв по ссылке; null — не сюда. */
  handlePublic(
    method: string,
    pathname: string,
    body: unknown,
    signedIn: boolean,
    locale: string | null,
  ): BackendReply | null {
    const match = /^\/api\/v1\/review-invites\/([^/]+)$/.exec(pathname);
    if (!match) return null;
    // отозванная, истёкшая, использованная и несуществующая ссылка — одинаковые 404
    const invite = this.items.find((item) => item.token === match[1] && item.status === 'waiting');
    if (method === 'GET') {
      if (!invite) return problem(404, 'not_found');
      return {
        status: 200,
        body: {
          specialist: inviteSpecialistFor(locale),
          expires_at: invite.expires_at,
          is_own: this.own,
        },
      };
    }
    if (method !== 'POST') return null;
    this.log.push({ request: `POST ${pathname}`, body });
    if (!signedIn) return problem(401, 'not_authenticated');
    if (!invite) return problem(404, 'review_invite_not_found');
    if (this.own) return problem(409, 'own_profile_review');
    if (this.reviewed) return problem(409, 'pre_platform_review_exists');
    const sent = body as InviteReviewIn;
    const at = this.now().toISOString();
    this.reviews.set(invite.token, sent);
    this.reviewed = true;
    this.items = this.items.map((item) =>
      item === invite
        ? { ...item, status: 'under_review', reviewer_name: 'Ирина С.', rating: sent.rating, used_at: at }
        : item,
    ); // prettier-ignore
    const review: ReviewOut = {
      id: `01a0e004-0000-7000-8000-${String(this.reviews.size + 500).padStart(12, '0')}`,
      kind: 'pre_platform',
      deal_id: null,
      rating: sent.rating,
      criteria: {},
      body: sent.body ?? null,
      work_title: sent.work_title ?? null,
      status: 'under_review',
      created_at: at,
      published_at: null,
      reply: null,
    };
    return { status: 201, body: review };
  }
}
