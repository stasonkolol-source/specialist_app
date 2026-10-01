// Кабинет исполнителя в памяти — как backend 2.8a–2.11: профиль, «чего не хватает», прайс,
// портфолио и фото профиля. Один и тот же для MSW в Vitest (testing/msw.ts) и page.route в e2e
// (e2e/api.ts): мастер S32a–c проходит по нему от «профиля нет» до «на проверке». Файлы работ и
// фото — из MediaBackend: что загружено и как обработано.
import type {
  CompletenessOut,
  HintOut,
  PortfolioLimitsOut,
  ProfileCreateIn,
  ProfileOut,
  ProfileUpdateIn,
  ServiceIn,
  ServiceOut,
  ServiceUpdateIn,
  WorkIn,
  WorkOut,
} from '@sosed/api-client';

import type { BackendReply } from './backend.ts';
import { problem } from './backend.ts';
import { PROFILE_DRAFT } from './fixtures.ts';
import { MediaBackend } from './mediaBackend.ts';

/** Лимиты портфолио — LIMITS backend: 60 фото и 6 роликов. */
export const PORTFOLIO_LIMITS: PortfolioLimitsOut = { image: 60, video: 6 };

/** Что приложение прислало: запросы по порядку, как «METHOD путь» и тело. */
export type BackendLog = { request: string; body: unknown }[];

export interface ProfileBackendOptions {
  /** Работы портфолио по порядку. */
  works?: readonly WorkOut[];
  /** Файлы: загрузки S37 и S34 и их обработка. */
  media?: MediaBackend;
}

export class ProfileBackend {
  profile: ProfileOut | null;
  services: ServiceOut[];
  works: WorkOut[];
  readonly media: MediaBackend;
  readonly log: BackendLog = [];

  constructor(
    profile: ProfileOut | null = null,
    services: ServiceOut[] = [],
    { works = [], media = new MediaBackend() }: ProfileBackendOptions = {},
  ) {
    this.services = [...services];
    this.works = [...works];
    this.media = media;
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
    if (request === 'PUT /me/profile/services/order') {
      return this.reorder((body as { service_ids: string[] }).service_ids);
    }
    const service = /^PATCH \/me\/profile\/services\/(.+)$/.exec(request);
    if (service?.[1]) return this.changeService(service[1], body as ServiceUpdateIn);
    const removed = /^DELETE \/me\/profile\/services\/(.+)$/.exec(request);
    if (removed?.[1]) return this.removeService(profile, removed[1]);
    const portfolio = this.portfolio(profile, request, body);
    if (portfolio) return portfolio;
    switch (request) {
      case 'GET /me/profile':
        return this.ok(this.refresh(profile));
      case 'PUT /me/profile/avatar': {
        const { media_id } = body as { media_id: string | null };
        if (media_id === null) return this.save({ ...profile, avatar: null });
        const avatar = this.media.ref(media_id);
        if (!avatar) return problem(404, 'media_not_found');
        return this.save({ ...profile, avatar });
      }
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

  /** Портфолио S37: файлы работ — свежие из media (обработка меняет их статус и варианты). */
  private portfolio(profile: ProfileOut, request: string, body: unknown): BackendReply | null {
    this.works = this.works.map((work) => ({
      ...work,
      media: (work.media && this.media.ref(work.media.id)) ?? work.media,
    }));
    const list = () => this.ok({ items: this.works, limits: PORTFOLIO_LIMITS });
    if (request === 'GET /me/profile/portfolio') return list();
    if (request === 'POST /me/profile/portfolio') return this.addWork(profile, body as WorkIn);
    if (request === 'PUT /me/profile/portfolio/order') {
      const ids = (body as { item_ids: string[] }).item_ids;
      const known = new Set(this.works.map((work) => work.id));
      if (ids.length !== known.size || ids.some((id) => !known.has(id))) {
        return problem(422, 'invalid_portfolio', { field: 'item_ids' });
      }
      this.works = ids.map((id, position) => {
        const work = this.works.find((item) => item.id === id);
        if (!work) throw new Error(`unknown work ${id}`);
        return { ...work, position };
      });
      return list();
    }
    const caption = /^PATCH \/me\/profile\/portfolio\/(.+)$/.exec(request);
    const removed = /^DELETE \/me\/profile\/portfolio\/(.+)$/.exec(request);
    const id = caption?.[1] ?? removed?.[1];
    if (!id) return null;
    const work = this.works.find((item) => item.id === id);
    if (!work) return problem(404, 'portfolio_item_not_found');
    if (caption) {
      const { caption: value } = body as { caption: string | null };
      const text = (value ?? '').split(/\s+/).filter(Boolean).join(' ');
      const changed = { ...work, caption: text || null };
      this.works = this.works.map((item) => (item.id === id ? changed : item));
      return this.ok(changed);
    }
    this.works = this.works
      .filter((item) => item.id !== id)
      .map((item, position) => ({ ...item, position }));
    this.profile = this.refresh(profile);
    return { status: 204, body: null };
  }

  private addWork(profile: ProfileOut, body: WorkIn): BackendReply {
    const media = this.media.ref(body.media_id);
    if (!media) return problem(404, 'media_not_found');
    if (media.status === 'failed' || media.status === 'rejected') {
      return problem(409, 'media_state_conflict');
    }
    // повтор с тем же файлом — та же работа (Idempotency-Key у backend)
    const same = this.works.find((work) => work.media?.id === media.id);
    if (same) return { status: 201, body: same };
    const kind = media.kind === 'video' ? 'video' : 'image';
    const limit = PORTFOLIO_LIMITS[kind];
    if (this.works.filter((work) => work.kind === kind).length >= limit) {
      return problem(409, 'portfolio_full', { kind, limit });
    }
    const work: WorkOut = {
      id: `0199dd00-0000-7000-8000-${String(this.works.length + 501).padStart(12, '0')}`,
      kind,
      caption: body.caption ?? null,
      position: this.works.length,
      media,
    };
    this.works.push(work);
    this.profile = this.refresh(profile);
    return { status: 201, body: work };
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
    const clear = new Set(body.clear ?? []);
    const money = (amount: number | null | undefined, previous: ServiceOut['price_min']) =>
      amount == null ? previous : { amount, currency: 'RSD' as const };
    const next: ServiceOut = {
      ...current,
      title: body.title ?? current.title,
      price_type: body.price_type ?? current.price_type,
      price_min: money(body.price_min, current.price_min),
      price_max: clear.has('price_max') ? null : money(body.price_max, current.price_max),
      description: clear.has('description') ? null : (body.description ?? current.description),
      category_id: clear.has('category_id') ? null : (body.category_id ?? current.category_id),
      unit: clear.has('unit') ? null : (body.unit ?? current.unit),
      duration_min: clear.has('duration_min') ? null : (body.duration_min ?? current.duration_min),
      is_active: body.is_active ?? current.is_active,
    };
    this.services[index] = next;
    if (this.profile) this.profile = this.refresh(this.profile);
    return this.ok(next);
  }

  private reorder(ids: string[]): BackendReply {
    const known = new Set(this.services.map((service) => service.id));
    if (ids.length !== known.size || ids.some((id) => !known.has(id))) {
      return problem(422, 'invalid_service_order');
    }
    this.services = ids.map((id, position) => {
      const service = this.services.find((item) => item.id === id);
      if (!service) throw new Error(`unknown service ${id}`);
      return { ...service, position };
    });
    return this.ok({ items: this.services });
  }

  private removeService(profile: ProfileOut, id: string): BackendReply {
    if (!this.services.some((service) => service.id === id)) {
      return problem(404, 'service_not_found');
    }
    this.services = this.services
      .filter((service) => service.id !== id)
      .map((service, position) => ({ ...service, position }));
    this.profile = this.refresh(profile);
    return { status: 204, body: null };
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
    const avatar = profile.avatar && (this.media.ref(profile.avatar.id) ?? profile.avatar);
    const fresh = { ...profile, avatar };
    return { ...fresh, missing, completeness: completeness(fresh, this.services, this.works) };
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
/** Работ в портфолио, чтобы клиенту было из чего понять уровень, — ENOUGH_WORKS backend. */
const ENOUGH_WORKS = 3;

/** Полнота профиля — как specialists/domain/completeness.py: веса проверок и подсказки по порядку. */
function completeness(
  profile: ProfileOut,
  services: readonly ServiceOut[],
  works: readonly WorkOut[],
): CompletenessOut {
  const active = services.filter((service) => service.is_active);
  const undescribed = active.filter((service) => !service.description?.trim()).length;
  const travels = profile.work_modes.includes('at_client');
  const pro = profile.kind === 'pro';
  const hint = (code: string, count: number | null = null): HintOut => ({ code, count });
  const checks: [number, boolean, HintOut][] = [
    [15, profile.category_ids.length > 0, hint('category_ids')],
    [15, Boolean(profile.headline), hint('headline')],
    [15, profile.work_modes.length > 0 && (profile.district_ids.length > 0 || !travels), hint('area_ids')],
    ...(pro ? [[15, active.length > 0, hint('services')] as [number, boolean, HintOut]] : []),
    [20, (profile.about ?? '').trim().length >= ABOUT_ENOUGH, hint('about')],
    [15, works.length >= ENOUGH_WORKS, hint('portfolio', Math.max(ENOUGH_WORKS - works.length, 0))],
    [10, profile.avatar !== null, hint('avatar')],
    [10, profile.languages.length > 0, hint('languages')],
  ]; // prettier-ignore
  if (pro) {
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
