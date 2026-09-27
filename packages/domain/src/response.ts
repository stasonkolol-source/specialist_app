// Отклик: статусы, переходы и действия (ARCHITECTURE §7.9, PRODUCT S16, S17, S24).

export const RESPONSE_STATUSES = [
  'submitted',
  'viewed',
  'shortlisted',
  'accepted',
  'declined',
  'withdrawn',
  'not_selected',
] as const;
export type ResponseStatus = (typeof RESPONSE_STATUSES)[number];

export const RESPONSE_TRANSITIONS: Readonly<Record<ResponseStatus, readonly ResponseStatus[]>> = {
  submitted: ['viewed', 'withdrawn', 'not_selected'],
  viewed: ['shortlisted', 'declined', 'withdrawn', 'accepted', 'not_selected'],
  shortlisted: ['accepted', 'declined', 'withdrawn', 'not_selected'],
  // сделка отменена — заявка снова открыта, клиент может выбрать прежних кандидатов
  not_selected: ['viewed'],
  accepted: ['declined', 'withdrawn'],
  declined: [],
  withdrawn: [],
};

/** Занимают место на заявке (`responses_count`). */
export const ACTIVE_RESPONSE_STATUSES: readonly ResponseStatus[] = [
  'submitted',
  'viewed',
  'shortlisted',
];

export function isActiveResponse(status: ResponseStatus): boolean {
  return ACTIVE_RESPONSE_STATUSES.includes(status);
}

export function canTransitionResponse(from: ResponseStatus, to: ResponseStatus): boolean {
  return RESPONSE_TRANSITIONS[from].includes(to);
}

export type ResponseClientAction = 'choose' | 'shortlist' | 'decline' | 'write' | 'open_deal';
export type ResponsePerformerAction = 'withdraw' | 'open_deal';

export function responseClientActions(status: ResponseStatus): ResponseClientAction[] {
  switch (status) {
    case 'submitted':
    case 'viewed':
      return ['choose', 'write', 'shortlist', 'decline'];
    case 'shortlisted':
      return ['choose', 'write', 'decline'];
    case 'accepted':
      return ['open_deal', 'write'];
    case 'not_selected':
    case 'declined':
    case 'withdrawn':
      return [];
  }
}

export function responsePerformerActions(status: ResponseStatus): ResponsePerformerAction[] {
  if (isActiveResponse(status)) return ['withdraw'];
  return status === 'accepted' ? ['open_deal'] : [];
}

/** Вкладки S17 «Мои отклики». */
export type ResponseTab = 'active' | 'selected' | 'not_selected' | 'archive';

export function responseTab(status: ResponseStatus): ResponseTab {
  if (isActiveResponse(status)) return 'active';
  if (status === 'accepted') return 'selected';
  if (status === 'withdrawn') return 'archive';
  return 'not_selected';
}

/** Метка «откликнулся первым» — самый ранний отклик заявки. */
export function firstResponseId<T extends { id: string; createdAt: string }>(
  responses: readonly T[],
): string | null {
  const [first] = [...responses].sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt));
  return first?.id ?? null;
}
