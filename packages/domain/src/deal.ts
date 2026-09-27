// Сделка: статусы, переходы и действия сторон (ARCHITECTURE §7.9, PRODUCT S26, S27, S52–S54).

export const DEAL_STATUSES = ['proposed', 'agreed', 'completed', 'cancelled', 'disputed'] as const;
export type DealStatus = (typeof DEAL_STATUSES)[number];

export const DEAL_TRANSITIONS: Readonly<Record<DealStatus, readonly DealStatus[]>> = {
  proposed: ['agreed', 'cancelled'],
  agreed: ['completed', 'cancelled', 'disputed'],
  disputed: ['completed', 'cancelled'],
  completed: [],
  cancelled: [],
};

/** «Договорились» ждёт вторую сторону 72 ч; столько же — до автозавершения после подтверждения одной стороной. */
export const DEAL_PROPOSAL_TTL_HOURS = 72;
export const DEAL_AUTO_COMPLETE_HOURS = 72;
/** Окно отзыва после завершения. */
export const REVIEW_WINDOW_DAYS = 14;

export function canTransitionDeal(from: DealStatus, to: DealStatus): boolean {
  return DEAL_TRANSITIONS[from].includes(to);
}

export type DealRole = 'client' | 'performer';

export type DealAction =
  | 'confirm'
  | 'decline'
  | 'complete'
  | 'cancel'
  | 'dispute'
  | 'respond_dispute'
  | 'withdraw_dispute'
  | 'share_contact'
  | 'review'
  | 'report_no_show'
  | 'chat';

export interface DealView {
  status: DealStatus;
  role: DealRole;
  /** Я предложил «Договорились» (для `proposed`). */
  proposedByMe?: boolean;
  /** Я уже нажал «Работа выполнена». */
  completedByMe?: boolean;
  /** Спор открыл я (для `disputed`). */
  disputeOpenedByMe?: boolean;
  /** ISO-время завершения. */
  completedAt?: string | null;
  hasReview?: boolean;
}

function reviewOpen(completedAt: string | null | undefined, now: Date): boolean {
  if (!completedAt) return false;
  const deadline = Date.parse(completedAt) + REVIEW_WINDOW_DAYS * 24 * 3600 * 1000;
  return now.getTime() <= deadline;
}

export function dealActions(deal: DealView, now: Date = new Date()): DealAction[] {
  switch (deal.status) {
    case 'proposed':
      return deal.proposedByMe ? ['chat'] : ['confirm', 'decline', 'chat'];
    case 'agreed':
      return [
        ...(deal.completedByMe ? [] : (['complete'] as const)),
        'cancel',
        'dispute',
        'share_contact',
        'chat',
      ];
    case 'disputed':
      return [deal.disputeOpenedByMe ? 'withdraw_dispute' : 'respond_dispute', 'chat'];
    case 'completed':
      // MVP: отзыв оставляет только клиент
      return deal.role === 'client' && !deal.hasReview && reviewOpen(deal.completedAt, now)
        ? ['review', 'chat']
        : ['chat'];
    case 'cancelled':
      return deal.role === 'client' ? ['report_no_show'] : [];
  }
}
