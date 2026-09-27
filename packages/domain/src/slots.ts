// Счётчик мест на заявке (ARCHITECTURE §7.9): не больше max_responses активных откликов, по умолчанию 5.

export const DEFAULT_MAX_RESPONSES = 5;

export interface ResponseSlots {
  total: number;
  taken: number;
  left: number;
  isFull: boolean;
}

/** `responses_count` считает только активные отклики (submitted, viewed, shortlisted). */
export function responseSlots(job: {
  maxResponses?: number;
  responsesCount: number;
}): ResponseSlots {
  const total = job.maxResponses ?? DEFAULT_MAX_RESPONSES;
  const taken = Math.min(Math.max(job.responsesCount, 0), total);
  const left = total - taken;
  return { total, taken, left, isFull: left === 0 };
}

/** Состояние MainButton на S15: «Откликнуться · осталось 2 места», «Вы откликнулись», «Мест нет». */
export type RespondState = 'can_respond' | 'responded' | 'full';

export function respondState(slots: ResponseSlots, hasResponded: boolean): RespondState {
  if (hasResponded) return 'responded';
  return slots.isFull ? 'full' : 'can_respond';
}
