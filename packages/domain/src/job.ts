// Заявка: статусы, переходы и действия по ролям (ARCHITECTURE §7.9, PRODUCT S13–S23).
import type { ResponseSlots } from './slots.ts';
import { respondState } from './slots.ts';

export const JOB_STATUSES = [
  'draft',
  'pending_moderation',
  'published',
  'rejected',
  'assigned',
  'completed',
  'closed',
  'expired',
  'removed',
] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

/** Переходы state machine backend; клиент по ним прячет недоступные действия, решает всё равно сервер. */
export const JOB_TRANSITIONS: Readonly<Record<JobStatus, readonly JobStatus[]>> = {
  draft: ['pending_moderation'],
  pending_moderation: ['published', 'rejected'],
  rejected: ['pending_moderation'],
  published: ['pending_moderation', 'assigned', 'closed', 'expired', 'removed', 'published'],
  expired: ['published'],
  assigned: ['completed', 'published', 'closed'],
  completed: [],
  closed: [],
  removed: [],
};

export const JOB_URGENCIES = ['asap', 'today', 'this_week', 'flexible'] as const;
export type JobUrgency = (typeof JOB_URGENCIES)[number];

export const JOB_CLOSE_REASONS = [
  'hired_here',
  'hired_elsewhere',
  'not_needed',
  'no_suitable',
  'expired',
  'removed',
] as const;
export type JobCloseReason = (typeof JOB_CLOSE_REASONS)[number];

/** Продлить или переопубликовать можно не больше 3 раз. */
export const JOB_EXTENSIONS_LIMIT = 3;

export function canTransitionJob(from: JobStatus, to: JobStatus): boolean {
  return JOB_TRANSITIONS[from].includes(to);
}

export type JobClientAction =
  'edit' | 'submit' | 'close' | 'extend' | 'republish' | 'invite' | 'share' | 'open_deal';
export type JobPerformerAction = 'respond' | 'share' | 'hide' | 'report';

export function jobClientActions(job: {
  status: JobStatus;
  extensionsCount: number;
}): JobClientAction[] {
  const canExtend = job.extensionsCount < JOB_EXTENSIONS_LIMIT;
  switch (job.status) {
    case 'draft':
      return ['edit', 'submit'];
    case 'pending_moderation':
      return ['edit'];
    case 'rejected':
      return ['edit', 'submit'];
    case 'published':
      return ['edit', 'close', ...(canExtend ? (['extend'] as const) : []), 'invite', 'share'];
    case 'expired':
      return canExtend ? ['republish'] : [];
    case 'assigned':
      return ['open_deal', 'close'];
    case 'completed':
    case 'closed':
    case 'removed':
      return [];
  }
}

/** Исполнитель видит только опубликованные заявки; откликнуться можно, пока есть места и отклика ещё нет. */
export function jobPerformerActions(job: {
  status: JobStatus;
  slots: ResponseSlots;
  hasResponded: boolean;
}): JobPerformerAction[] {
  if (job.status !== 'published') return [];
  const canRespond = respondState(job.slots, job.hasResponded) === 'can_respond';
  return [...(canRespond ? (['respond'] as const) : []), 'share', 'hide', 'report'];
}

/** Вкладки S22 «Мои заявки». */
export type JobTab = 'active' | 'in_work' | 'completed' | 'archive';

export function jobTab(status: JobStatus): JobTab {
  switch (status) {
    case 'draft':
    case 'pending_moderation':
    case 'rejected':
    case 'published':
    case 'expired':
      return 'active';
    case 'assigned':
      return 'in_work';
    case 'completed':
      return 'completed';
    case 'closed':
    case 'removed':
      return 'archive';
  }
}
