// Фейк backend заявок (DEVELOPMENT_PLAN 5.2): POST /jobs запоминает тело и Idempotency-Key и, как
// сервер, на повтор с тем же ключом отвечает той же заявкой; GET /jobs/{id} — созданная заявка.
// `failNext` — ответ на следующий POST ошибкой (ключ не занимается: повтор выполнится заново).
import type { JobIn, JobOut, JobStatus } from '@sosed/api-client';

import type { BackendReply } from './backend.ts';
import { problem } from './backend.ts';

const NOW = '2026-10-02T10:00:00Z';

export class JobsBackend {
  /** Принятые POST /jobs: тело и ключ — все, включая повторы. */
  readonly posts: { body: JobIn; key: string | null }[] = [];
  readonly jobs = new Map<string, JobOut>();
  private readonly byKey = new Map<string, JobOut>();
  /** Статус новой заявки: на проверке или сразу опубликована. */
  status: JobStatus = 'pending_moderation';
  failNext: BackendReply | null = null;

  create(body: JobIn, key: string | null): BackendReply {
    this.posts.push({ body, key });
    if (this.failNext) {
      const reply = this.failNext;
      this.failNext = null;
      return reply;
    }
    if (!key) return problem(400, 'idempotency_key_required');
    const known = this.byKey.get(key);
    if (known) return { status: 201, body: known };
    const job = jobOut(`job-${this.jobs.size + 1}`, body, this.status);
    this.jobs.set(job.id, job);
    this.byKey.set(key, job);
    return { status: 201, body: job };
  }

  get(id: string): BackendReply {
    const job = this.jobs.get(id);
    return job ? { status: 200, body: job } : problem(404, 'job_not_found');
  }
}

export function jobOut(id: string, body: JobIn, status: JobStatus): JobOut {
  const money = (amount: number | null | undefined) =>
    amount == null ? null : { amount, currency: 'RSD' as const };
  return {
    id,
    viewer_role: 'owner',
    status,
    visibility: 'public',
    title: body.title,
    description: body.description ?? '',
    content_lang: 'ru',
    category_id: body.category_id,
    urgency: body.urgency,
    preferred_from: body.preferred_from ?? null,
    preferred_to: body.preferred_to ?? null,
    budget_type: body.budget_type,
    budget_min: money(body.budget_min),
    budget_max: money(body.budget_max),
    budget_unit: body.budget_unit ?? 'work',
    city_id: body.city_id,
    district_id: body.district_id ?? null,
    point_public: null,
    point_exact: null,
    address_private: body.address_private ?? null,
    languages: body.languages ?? [],
    media_ids: body.media_ids ?? [],
    photos: [],
    client: {
      display_name: 'Елена К.',
      member_since: '2026-07-01T09:00:00Z',
      jobs_count: 1,
      phone_verified: false,
    },
    max_responses: 5,
    responses_count: 0,
    extensions_count: 0,
    moderation_note: null,
    version: 1,
    created_at: NOW,
    published_at: status === 'published' ? NOW : null,
    expires_at: null,
    closed_at: null,
    close_reason: null,
  };
}
