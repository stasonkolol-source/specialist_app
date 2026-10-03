// Жалобы (S46, DEVELOPMENT_PLAN 4.7): причины по типу объекта — как у сервера (moderation
// domain/reports.py), очередь по причине — для подписи «модератор рассмотрит в течение …».
// Повтор жалобы на тот же объект, пока кейс открыт, сервер отдаёт той же жалобой (200).
import type { ReportIn, ReportInTargetType, ReportReason } from '@sosed/api-client';
import { moderationCreateReport } from '@sosed/api-client';
import { useMutation } from '@tanstack/react-query';

export type ReportTargetType = ReportInTargetType;

/** На что можно пожаловаться и какие причины у каждого типа; порядок — как в шторке. */
export const REPORT_REASONS = {
  profile: ['fraud', 'fake_profile', 'offensive', 'prohibited', 'other'],
  job: ['fraud', 'prohibited', 'spam', 'offensive', 'other'],
  review: ['defamation', 'offensive', 'personal_data', 'spam', 'other'],
  message: ['fraud', 'offensive', 'spam', 'personal_data', 'other'],
  user: ['fraud', 'offensive', 'no_show', 'spam', 'fake_profile', 'other'],
} as const satisfies Record<ReportTargetType, readonly ReportReason[]>;

/** Причина из списка своего типа объекта (сервер на чужую ответит 422). */
export function allowedReason(type: ReportTargetType, reason: ReportReason): boolean {
  return (REPORT_REASONS[type] as readonly ReportReason[]).includes(reason);
}

const SAFETY: ReadonlySet<ReportReason> = new Set(['offensive', 'prohibited', 'illegal']);

/** Очередь кейса (§14.2): угрозы и запрещённое — P0 (в течение часа), остальное — P1 (2 часа). */
export function reportQueue(reason: ReportReason): 'safety' | 'fraud' {
  return SAFETY.has(reason) ? 'safety' : 'fraud';
}

export const MAX_REPORT_COMMENT = 1000;

export function useReport() {
  return useMutation({ mutationFn: (report: ReportIn) => moderationCreateReport(report) });
}
