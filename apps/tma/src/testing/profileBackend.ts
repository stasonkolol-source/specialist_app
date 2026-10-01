// Кабинет исполнителя в памяти — как backend 2.8a–b: профиль, «чего не хватает» и прайс. Один и
// тот же для MSW в Vitest (testing/msw.ts) и page.route в e2e (e2e/api.ts): мастер S32a–c
// проходит по нему от «профиля нет» до «на проверке».
import type {
  CompletenessOut,
  HintOut,
  ProfileCreateIn,
  ProfileOut,
  ProfileUpdateIn,
  ServiceIn,
  ServiceOut,
  ServiceUpdateIn,
} from '@sosed/api-client';

import { PROFILE_DRAFT } from './fixtures.ts';

/** Ответ backend: тело и статус; ошибки — RFC 9457 с `code`. */
export interface BackendReply {
  status: number;
  body: unknown;
}

const problem = (status: number, code: string, extra: Record<string, unknown> = {}) => ({
  status,
  body: { type: 'about:blank', title: code, status, code, trace_id: 'test', ...extra },
});

/** Что приложение прислало: запросы по порядку, как «METHOD путь» и тело. */
export type BackendLog = { request: string; body: unknown }[];

export class ProfileBackend {
  profile: ProfileOut | null;
  services: ServiceOut[];
  readonly log: BackendLog = [];

  constructor(profile: ProfileOut | null = null, services: ServiceOut[] = []) {
    this.services = [...services];
    this.profile = profile && this.refresh(profile);
  }

  /** Ответ на запрос кабинета `/me/profile*`; null — запрос не к кабинету. */
  handle(method: string, path: string, body: unknown): BackendReply | null {
    const resource = path.replace(/^\/api\/v1/, '');
    if (!resource.startsWith('/me/profile')) return null;
    const request = `${method} ${resource}`;
    this.log.push({ request, body });
    return this.route(request, body) ?? problem(404, 'not_found');
  }

  private route(request: string, body: unknown): BackendReply | null {
    if (request === 'POST /me/profile') return this.create(body as ProfileCreateIn);
    if (request === 'GET /me/profile/services') return this.ok({ items: this.services });
    const profile = this.profile;
    if (!profile) return problem(404, 'profile_not_found');
    if (request === 'POST /me/profile/services') return this.addService(profile, body as ServiceIn);
    const service = /^PATCH \/me\/profile\/services\/(.+)$/.exec(request);
    if (service?.[1]) return this.changeService(service[1], body as ServiceUpdateIn);
    switch (request) {
      case 'GET /me/profile':
        return this.ok(profile);
      case 'PATCH /me/profile':
        return this.update(profile, body as ProfileUpdateIn);
      case 'PUT /me/profile/categories': {
        const { category_ids } = body as { category_ids: number[] };
        return this.save({ ...profile, category_ids });
      }
      case 'PUT /me/profile/areas': {
        const { district_ids } = body as { district_ids: number[] };
        return this.save({ ...profile, district_ids });
      }
      case 'PUT /me/profile/availability': {
        const { until } = body as { until: string | null };
        if (until === null) return this.save({ ...profile, available_until: null });
        const at = todayAt(until, new Date());
        if (at <= new Date()) return problem(422, 'availability_past');
        return this.save({ ...profile, available_until: at.toISOString() });
      }
      case 'POST /me/profile/hide':
        if (profile.status === 'hidden') return this.ok(profile);
        if (profile.status !== 'published') return problem(409, 'profile_state_conflict');
        return this.save({ ...profile, status: 'hidden' });
      case 'POST /me/profile/show':
        if (profile.status === 'published') return this.ok(profile);
        if (profile.status !== 'hidden') return problem(409, 'profile_state_conflict');
        return this.save({ ...profile, status: 'published' });
      case 'POST /me/profile/submit':
        if (profile.status !== 'draft') return problem(409, 'profile_state_conflict');
        if (profile.missing.length > 0) {
          return problem(409, 'profile_incomplete', { missing: profile.missing });
        }
        return this.save({ ...profile, status: 'pending_review', rejection_reason: null });
      default:
        return null;
    }
  }

  private ok(body: unknown): BackendReply {
    return { status: 200, body };
  }

  private create(body: ProfileCreateIn): BackendReply {
    if (this.profile) return problem(409, 'profile_exists');
    this.profile = this.refresh({
      ...PROFILE_DRAFT,
      kind: body.kind,
      city_id: body.city_id,
      listed_in_catalog: body.kind === 'pro',
      version: 1,
    });
    return { status: 201, body: this.profile };
  }

  private update(profile: ProfileOut, body: ProfileUpdateIn): BackendReply {
    if (body.kind && body.kind !== profile.kind && profile.status !== 'draft') {
      return problem(409, 'profile_state_conflict');
    }
    const fields = Object.fromEntries(Object.entries(body).filter(([, value]) => value != null));
    const next: ProfileOut = { ...profile, ...fields };
    if (body.kind) next.listed_in_catalog = body.kind === 'pro';
    return this.save(next);
  }

  private save(profile: ProfileOut): BackendReply {
    this.profile = this.refresh({ ...profile, version: profile.version + 1 });
    return this.ok(this.profile);
  }

  private addService(profile: ProfileOut, body: ServiceIn): BackendReply {
    const service: ServiceOut = {
      id: `0199bb00-0000-7000-8000-${String(this.services.length + 201).padStart(12, '0')}`,
      title: body.title,
      description: body.description ?? null,
      category_id: body.category_id ?? null,
      price_type: body.price_type,
      price_min: body.price_min == null ? null : { amount: body.price_min, currency: 'RSD' },
      price_max: body.price_max == null ? null : { amount: body.price_max, currency: 'RSD' },
      unit: body.unit ?? null,
      duration_min: body.duration_min ?? null,
      position: this.services.length,
      is_active: true,
    };
    this.services.push(service);
    this.profile = this.refresh(profile);
    return { status: 201, body: service };
  }

  private changeService(id: string, body: ServiceUpdateIn): BackendReply {
    const index = this.services.findIndex((service) => service.id === id);
    const current = this.services[index];
    if (!current) return problem(404, 'service_not_found');
    const next: ServiceOut = {
      ...current,
      title: body.title ?? current.title,
      description: body.description ?? current.description,
      price_min: body.price_min == null ? current.price_min : { amount: body.price_min, currency: 'RSD' },
    }; // prettier-ignore
    this.services[index] = next;
    if (this.profile) this.profile = this.refresh(this.profile);
    return this.ok(next);
  }

  /** «Чего не хватает» и полнота — как ProfileViews backend: «Специалисту» нужен и прайс. */
  private refresh(profile: ProfileOut): ProfileOut {
    const missing: string[] = [];
    if (profile.category_ids.length === 0) missing.push('category_ids');
    if (!profile.headline) missing.push('headline');
    if (profile.work_modes.length === 0) missing.push('work_modes');
    if (profile.work_modes.includes('at_client') && profile.district_ids.length === 0) {
      missing.push('area_ids');
    }
    if (profile.kind === 'pro' && this.services.length === 0) missing.push('services');
    return { ...profile, missing, completeness: completeness(profile, this.services) };
  }
}

/** Сегодня в `time` («20:00») по Белграду — как today_at backend: летом UTC+2, зимой UTC+1. */
function todayAt(time: string, now: Date): Date {
  const [hour = 0, minute = 0] = time.split(':').map(Number);
  const day = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Belgrade' }).format(now);
  const [year = 0, month = 1, date = 1] = day.split('-').map(Number);
  for (const offset of [2, 1]) {
    const candidate = new Date(Date.UTC(year, month - 1, date, hour - offset, minute));
    const local = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Belgrade',
      hour: '2-digit',
      hourCycle: 'h23',
    }).format(candidate);
    if (Number(local) === hour) return candidate;
  }
  return new Date(Date.UTC(year, month - 1, date, hour - 1, minute));
}

/** «О себе» хотя бы в пару предложений — как ABOUT_ENOUGH backend. */
const ABOUT_ENOUGH = 80;

/** Полнота профиля — как specialists/domain/completeness.py: веса проверок и подсказки по порядку. */
function completeness(profile: ProfileOut, services: readonly ServiceOut[]): CompletenessOut {
  const active = services.filter((service) => service.is_active);
  const undescribed = active.filter((service) => !service.description?.trim()).length;
  const travels = profile.work_modes.includes('at_client');
  const hint = (code: string, count: number | null = null): HintOut => ({ code, count });
  const checks: [number, boolean, HintOut][] = [
    [15, profile.category_ids.length > 0, hint('category_ids')],
    [15, Boolean(profile.headline), hint('headline')],
    [20, (profile.about ?? '').trim().length >= ABOUT_ENOUGH, hint('about')],
    [10, profile.languages.length > 0, hint('languages')],
    [15, profile.work_modes.length > 0 && (profile.district_ids.length > 0 || !travels), hint('area_ids')],
  ]; // prettier-ignore
  if (profile.kind === 'pro') {
    checks.push([15, active.length > 0, hint('services')]);
    const described = active.length > 0 && undescribed === 0;
    checks.push([10, described, hint('service_descriptions', undescribed)]);
  }
  const total = checks.reduce((sum, [weight]) => sum + weight, 0);
  const done = checks.reduce((sum, [weight, ok]) => sum + (ok ? weight : 0), 0);
  const hints = checks
    .filter(([, ok, item]) => !ok && (item.code !== 'service_descriptions' || active.length > 0))
    .map(([, , item]) => item);
  return { percent: Math.floor((done * 100) / total), hints };
}
