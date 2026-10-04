// Фейк backend переписки (DEVELOPMENT_PLAN 6.4) — как сервер 6.3: GET /conversations (вкладки по
// роли, свежие первыми), POST /conversations (начатый диалог — тот же, 200), GET
// /conversations/{id}/messages (последние, `direction=older` — раньше), POST …/messages (повтор
// `client_msg_id` — то же сообщение; до договорённости телефон — «•••»), POST …/read, POST …/deal
// (сделка `proposed`; пока идёт прежняя — 409 `deal_in_progress`, после завершения или отмены —
// снова можно), POST …/share-contact (после договорённости, 6.5) и GET /me/badges. Контакты открыты,
// как у сервера (`contacts_open`): сделка диалога договорена, под спором или завершена — или стороны
// уже договаривались в этом диалоге (ADR-0010, 2026-10-04). «Собеседник пишет» — `incoming`;
// `pastDeal` — договорённость диалога позади; `failNext` — следующая отправка падает ошибкой (ключ
// не занимается: повтор выполнится заново). Время — от NOW.
// Блокировки (4.7) — у фейка `safety`: с заблокированным писать нельзя (409 `blocked`).
import type {
  ContactShareIn,
  ConversationOut,
  ConversationStartIn,
  DealProposalIn,
  MessageIn,
  MessageOut,
  ReadIn,
} from '@sosed/api-client';

import type { BackendReply } from './backend.ts';
import { problem } from './backend.ts';
import { ME } from './fixtures.ts';
import type { SafetyBackend } from './safetyBackend.ts';

const NOW = Date.parse('2026-10-02T10:00:00Z');
const MINUTE_MS = 60_000;
const MASK = '•••';
const PHONE = /\+?\d[\d\s()-]{6,}\d/g;
/** Договорились: контакты открыты (как OPEN_DEALS сервера). */
const OPEN: ReadonlySet<string> = new Set(['agreed', 'disputed', 'completed']);
/** Договорённость идёт: второе «Договорились» — 409 (как ACTIVE_DEALS сервера). */
const ACTIVE: ReadonlySet<string> = new Set(['proposed', 'agreed', 'disputed']);
/** Прошлая сделка `pastDeal`. */
export const PAST_DEAL_ID = '01a0e003-0000-7000-8000-000000000002';

/** Диалоги макета S29: прямой со специалистом, по отклику на заявку клиента и свой отклик. */
export const CONVERSATION_IDS = {
  direct: '01a0f000-0000-7000-8000-000000000001',
  job: '01a0f000-0000-7000-8000-000000000002',
  performer: '01a0f000-0000-7000-8000-000000000003',
} as const;
export const SPECIALIST_PROFILE_ID = '01a0e001-0000-7000-8000-00000000000a';
const ALEKSEY = '01a0e001-0000-7000-8000-000000000001';
const NIKOLA = '01a0e001-0000-7000-8000-000000000002';
const DMITRY = '01a0e001-0000-7000-8000-000000000003';
const JOB_ID = '01a0e002-0000-7000-8000-000000000001';

interface Dialog {
  conversation: Omit<ConversationOut, 'last_message' | 'unread' | 'contacts_open'>;
  messages: MessageOut[];
  /** Прочитано мной до этого id. */
  readUpTo: string | null;
  /** Стороны уже договаривались в этом диалоге: контакты открыты при любой следующей сделке. */
  agreedBefore?: boolean;
}

/** Открыты ли контакты диалога — правило сервера (messaging/application/contacts.py). */
function contactsOpen(dialog: Dialog): boolean {
  return OPEN.has(dialog.conversation.deal?.status ?? '') || dialog.agreedBefore === true;
}

let sequence = 0;
/** id растут со временем, как UUIDv7: порядок строк — порядок сообщений. */
function nextId(at: number): string {
  sequence += 1;
  const time = at.toString(16).padStart(12, '0');
  const tail = sequence.toString(16).padStart(12, '0');
  return `${time.slice(0, 8)}-${time.slice(8, 12)}-7000-8000-${tail}`;
}

function message(
  senderId: string | null,
  body: string | null,
  at: number,
  extra: Partial<MessageOut> = {},
): MessageOut {
  return {
    id: nextId(at),
    kind: 'text',
    mine: senderId === ME.id,
    sender_id: senderId,
    body,
    masked: false,
    prepayment: false,
    hidden: false,
    offer: null,
    contact: null,
    event: null,
    client_msg_id: null,
    created_at: new Date(at).toISOString(),
    ...extra,
  };
}

export class ChatBackend {
  dialogs = new Map<string, Dialog>();
  /** Следующая отправка — ошибка (ключ не занят). */
  failNext: BackendReply | null = null;
  sent: MessageIn[] = [];
  reads: string[] = [];
  proposals: DealProposalIn[] = [];
  starts: ConversationStartIn[] = [];
  shares: ContactShareIn[] = [];
  jobsBadge = 0;
  /** Блокировки (4.7): чьи — у фейка жалоб и блокировок. */
  safety: SafetyBackend | null = null;

  /** Три диалога макета S29: в прямом — замаскированный телефон и два непрочитанных. */
  seed(): this {
    const direct = CONVERSATION_IDS.direct;
    this.dialogs.set(direct, {
      conversation: conversation(direct, {
        kind: 'direct',
        my_role: 'client',
        counterpart_id: ALEKSEY,
        counterpart_name: 'Алексей Морозов',
        counterpart_profile_id: SPECIALIST_PROFILE_ID,
        created_at: new Date(NOW - 20 * MINUTE_MS).toISOString(),
      }),
      messages: [
        message(
          ME.id,
          'Здравствуйте! Нужно повесить люстру. Сможете сегодня?',
          NOW - 20 * MINUTE_MS,
        ),
        message(ALEKSEY, 'Добрый день! Могу сегодня в 19:00.', NOW - 14 * MINUTE_MS),
        message(ALEKSEY, `Позвоните мне: ${MASK}`, NOW - 13 * MINUTE_MS, { masked: true }),
      ],
      readUpTo: null,
    });
    const job = CONVERSATION_IDS.job;
    this.dialogs.set(job, {
      conversation: conversation(job, {
        kind: 'job_response',
        my_role: 'client',
        counterpart_id: NIKOLA,
        counterpart_name: 'Никола Петрович',
        job_id: JOB_ID,
        job_title: 'Повесить люстру',
        created_at: new Date(NOW - 40 * MINUTE_MS).toISOString(),
      }),
      messages: [
        message(NIKOLA, 'Mogu danas posle 18h', NOW - 40 * MINUTE_MS, {
          kind: 'offer',
          offer: {
            price_type: 'fixed',
            price_amount: 350_000,
            availability_note: 'Сегодня, 19:00',
          },
        }),
      ],
      readUpTo: null,
    });
    const performer = CONVERSATION_IDS.performer;
    this.dialogs.set(performer, {
      conversation: conversation(performer, {
        kind: 'job_response',
        my_role: 'performer',
        counterpart_id: DMITRY,
        counterpart_name: 'Дмитрий Соколов',
        job_id: '01a0e002-0000-7000-8000-000000000002',
        job_title: 'Собрать шкаф PAX',
        deal: {
          id: '01a0e003-0000-7000-8000-000000000001',
          status: 'agreed',
          title: 'Собрать шкаф PAX',
        },
        created_at: new Date(NOW - 26 * 60 * MINUTE_MS).toISOString(),
      }),
      messages: [message(ME.id, 'Спасибо, тогда до четверга!', NOW - 25 * 60 * MINUTE_MS)],
      readUpTo: null,
    });
    return this;
  }

  /** Договорились, и сделка позади — завершена или отменена: «Договорились» в ленте, контакты
   *  открыты и дальше, вторая сторона показывает Telegram (6.5). */
  pastDeal(conversationId: string, status: 'completed' | 'cancelled'): this {
    const dialog = this.dialogs.get(conversationId);
    if (!dialog) throw new Error(`unknown conversation ${conversationId}`);
    const title = dialog.conversation.job_title ?? 'Повесить люстру';
    dialog.conversation = {
      ...dialog.conversation,
      deal: { id: PAST_DEAL_ID, status, title },
      counterpart_telegram: '@aleksey_m',
    };
    dialog.agreedBefore = true;
    dialog.messages.push(
      message(null, null, NOW - 10 * MINUTE_MS, {
        kind: 'system',
        event: { type: 'deal_agreed', deal_id: PAST_DEAL_ID, by: null, reason: null },
      }),
    );
    return this;
  }

  /** Собеседник пишет: сообщение появится при следующем опросе S30. */
  incoming(conversationId: string, body: string, at = Date.now()): MessageOut {
    const dialog = this.dialogs.get(conversationId);
    if (!dialog) throw new Error(`unknown conversation ${conversationId}`);
    const item = message(dialog.conversation.counterpart_id, body, at);
    dialog.messages.push(item);
    return item;
  }

  unread(dialog: Dialog): number {
    return dialog.messages.filter(
      (item) =>
        !item.mine &&
        item.sender_id !== null &&
        !item.hidden &&
        (dialog.readUpTo === null || item.id > dialog.readUpTo),
    ).length;
  }

  out(dialog: Dialog): ConversationOut {
    const side = this.safety?.side(dialog.conversation.counterpart_id) ?? null;
    return {
      ...dialog.conversation,
      contacts_open: contactsOpen(dialog),
      last_message: dialog.messages.at(-1) ?? null,
      unread: this.unread(dialog),
      last_message_at: dialog.messages.at(-1)?.created_at ?? null,
      blocked: side !== null,
      blocked_by_me: side === 'by_me',
    };
  }

  handle(method: string, url: URL, body: unknown): BackendReply | null {
    const path = url.pathname.replace(/^\/api\/v1/, '');
    if (method === 'GET' && path === '/me/badges') {
      const messages = [...this.dialogs.values()].reduce((sum, item) => sum + this.unread(item), 0);
      return { status: 200, body: { jobs: this.jobsBadge, messages } };
    }
    if (path === '/conversations') {
      if (method === 'GET') return this.list(url.searchParams);
      if (method === 'POST') return this.start(body as ConversationStartIn);
    }
    const match = /^\/conversations\/([^/]+)\/(messages|read|deal|share-contact)$/.exec(path);
    const dialog = match ? this.dialogs.get(match[1] ?? '') : undefined;
    if (!match || !dialog) return problem(404, 'conversation_not_found');
    const action = match[2];
    if (action === 'messages' && method === 'GET') return this.page(dialog, url.searchParams);
    if (action === 'messages' && method === 'POST') return this.send(dialog, body as MessageIn);
    if (action === 'read' && method === 'POST') {
      dialog.readUpTo = (body as ReadIn).message_id;
      this.reads.push((body as ReadIn).message_id);
      return { status: 204, body: null };
    }
    if (action === 'deal' && method === 'POST') return this.propose(dialog, body as DealProposalIn);
    if (action === 'share-contact' && method === 'POST') {
      return this.shareContact(dialog, body as ContactShareIn);
    }
    return null;
  }

  private list(params: URLSearchParams): BackendReply {
    const role = params.get('role');
    const items = [...this.dialogs.values()]
      .filter((dialog) => role === null || dialog.conversation.my_role === role)
      .map((dialog) => this.out(dialog))
      .sort((a, b) =>
        (b.last_message_at ?? b.created_at).localeCompare(a.last_message_at ?? a.created_at),
      );
    return { status: 200, body: { items, next_cursor: null } };
  }

  private start(target: ConversationStartIn): BackendReply {
    this.starts.push(target);
    // по профилю — прямой диалог с этим специалистом, как `direct_of` сервера: диалог по отклику
    // с ним же — другой
    const found = [...this.dialogs.values()].find(
      (dialog) =>
        target.profile_id &&
        dialog.conversation.kind === 'direct' &&
        dialog.conversation.counterpart_profile_id === target.profile_id,
    );
    if (found) return { status: 200, body: { id: found.conversation.id, created: false } };
    const id = nextId(Date.now());
    this.dialogs.set(id, {
      conversation: conversation(id, {
        kind: target.profile_id ? 'direct' : 'job_response',
        my_role: 'client',
        counterpart_id: ALEKSEY,
        counterpart_name: 'Алексей Морозов',
        counterpart_profile_id: target.profile_id ?? null,
        response_id: target.response_id ?? null,
        created_at: new Date().toISOString(),
      }),
      messages: [],
      readUpTo: null,
    });
    return { status: 201, body: { id, created: true } };
  }

  private page(dialog: Dialog, params: URLSearchParams): BackendReply {
    const limit = Number(params.get('limit') ?? '20');
    const cursor = params.get('cursor');
    const direction = params.get('direction') ?? 'older';
    const all = dialog.messages;
    let items: MessageOut[];
    let older: string | null = null;
    if (direction === 'newer') {
      items = all.filter((item) => cursor === null || item.id > cursor).slice(0, limit);
    } else {
      const before = cursor === null ? all : all.filter((item) => item.id < cursor);
      items = before.slice(-limit);
      older = before.length > limit ? (items[0]?.id ?? null) : null;
    }
    return {
      status: 200,
      body: {
        conversation: this.out(dialog),
        items,
        older_cursor: older,
        newer_cursor: items.at(-1)?.id ?? null,
      },
    };
  }

  private send(dialog: Dialog, input: MessageIn): BackendReply {
    if (this.failNext) {
      const reply = this.failNext;
      this.failNext = null;
      return reply;
    }
    if (dialog.conversation.status !== 'open') {
      return problem(409, 'conversation_closed', {
        conversation_status: dialog.conversation.status,
      });
    }
    if (this.safety?.side(dialog.conversation.counterpart_id)) {
      return problem(409, 'conversation_closed', { conversation_status: 'blocked' });
    }
    const repeated = dialog.messages.find(
      (item) => item.mine && input.client_msg_id && item.client_msg_id === input.client_msg_id,
    );
    if (repeated) return { status: 201, body: repeated };
    this.sent.push(input);
    const masked = contactsOpen(dialog) ? input.body : input.body.replace(PHONE, MASK);
    const item = message(ME.id, masked, Date.now(), {
      masked: masked !== input.body,
      client_msg_id: input.client_msg_id ?? null,
    });
    dialog.messages.push(item);
    return { status: 201, body: item };
  }

  /** «Поделиться контактом» (S54): только после договорённости; контакт — сообщением. */
  private shareContact(dialog: Dialog, input: ContactShareIn): BackendReply {
    if (!contactsOpen(dialog)) return problem(409, 'contacts_locked');
    this.shares.push(input);
    const value = input.contact_type === 'telegram' ? '@elena_k' : '+381641234567';
    const item = message(ME.id, null, Date.now(), {
      kind: 'contact_share',
      contact: { type: input.contact_type, value },
    });
    dialog.messages.push(item);
    return { status: 201, body: item };
  }

  private propose(dialog: Dialog, terms: DealProposalIn): BackendReply {
    if (dialog.conversation.kind !== 'direct') {
      return problem(409, 'cannot_propose', { reason: 'choose_response' });
    }
    const current = dialog.conversation.deal;
    if (current && ACTIVE.has(current.status)) {
      return problem(409, 'deal_in_progress', { deal_id: current.id });
    }
    this.proposals.push(terms);
    const dealId = nextId(Date.now());
    dialog.conversation = {
      ...dialog.conversation,
      deal: { id: dealId, status: 'proposed', title: terms.title },
    };
    dialog.messages.push(
      message(null, null, Date.now(), {
        kind: 'system',
        event: {
          type: 'deal_proposed',
          deal_id: dealId,
          by: dialog.conversation.my_role,
          reason: null,
        },
      }),
    );
    return { status: 201, body: { deal_id: dealId } };
  }
}

function conversation(
  id: string,
  fields: Partial<Omit<ConversationOut, 'last_message' | 'unread' | 'contacts_open'>> &
    Pick<ConversationOut, 'kind' | 'my_role' | 'counterpart_id' | 'created_at'>,
): Omit<ConversationOut, 'last_message' | 'unread' | 'contacts_open'> {
  return {
    id,
    status: 'open',
    counterpart_name: null,
    counterpart_profile_id: null,
    counterpart_telegram: null,
    job_id: null,
    job_title: null,
    response_id: null,
    deal: null,
    last_message_at: null,
    blocked: false,
    blocked_by_me: false,
    ...fields,
  };
}
