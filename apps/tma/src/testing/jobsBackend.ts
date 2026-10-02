// Фейк backend заявок. Создание (5.2): POST /jobs запоминает тело и Idempotency-Key и, как сервер,
// на повтор с тем же ключом отвечает той же заявкой; `failNext` — ответ на следующий POST ошибкой
// (ключ не занимается: повтор выполнится заново). Лента (5.3): GET /jobs — заявки J1–J6 SPEC §4
// (J1–J3 — как на артборде S13) с фильтрами и курсором, GET /jobs/count — их число, POST
// /jobs/{id}/hide — «не интересно»; GET /jobs/{id} — созданная заявка (владельцу) или заявка ленты.
// Сохранённые заявки (S12, S15): GET /me/favorites/jobs, PUT и DELETE /me/favorites/job/{id}.
// Время публикации — от E2E_NOW: в e2e часы браузера стоят на нём же.
import type {
  JobCardOut,
  JobClientOut,
  JobIn,
  JobOut,
  JobStatus,
  Urgency,
} from '@sosed/api-client';

import type { BackendReply } from './backend.ts';
import { problem } from './backend.ts';
import { CATEGORY_IDS, DISTRICT_IDS, E2E_NOW } from './fixtures.ts';

const NOW = '2026-10-02T10:00:00Z';
const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const PARA = 100;
const MAX_RESPONSES = 5;
const MAX_SAVED = 100;

export interface FeedFixture {
  card: JobCardOut;
  /** Полное описание для S15; в ленте — оно же (короче 280 знаков). */
  description: string;
  languages: string[];
  client: JobClientOut;
  /** Публичная точка: «≈ 1,2 км от вас» на S15 — от неё. */
  point: { lat: number; lon: number };
}

const at = (minutesAgo: number) =>
  new Date(new Date(E2E_NOW).getTime() - minutesAgo * MINUTE_MS).toISOString();

const money = (rsd: number | null) =>
  rsd === null ? null : { amount: rsd * PARA, currency: 'RSD' as const };

function fixture(
  index: number,
  fields: Partial<JobCardOut> & Pick<JobCardOut, 'title' | 'category_id' | 'urgency'>,
  extra: Omit<FeedFixture, 'card'>,
): FeedFixture {
  const id = `0199dd00-0000-7000-8000-${String(index).padStart(12, '0')}`;
  const photos = fields.photos ?? [];
  return {
    ...extra,
    card: {
      id,
      description: extra.description,
      preferred_from: null,
      preferred_to: null,
      budget_type: 'fixed',
      budget_min: null,
      budget_max: null,
      budget_unit: 'work',
      district_id: null,
      distance_m: null,
      photos,
      photos_count: photos.length,
      responses_count: 0,
      max_responses: MAX_RESPONSES,
      published_at: at(index * 10),
      ...fields,
    },
  };
}

const photo = (job: number, number: number, variant: 'thumb' | 'md') => ({
  url: `/cdn/job-${job}-${number}/${variant}.webp`,
  width: variant === 'thumb' ? 320 : 800,
  height: variant === 'thumb' ? 240 : 600,
  placeholder: null,
});

const ELENA: JobClientOut = {
  display_name: 'Елена К.',
  member_since: '2026-07-01T09:00:00Z',
  jobs_count: 2,
  phone_verified: true,
};

const MARKO: JobClientOut = {
  display_name: 'Марко П.',
  member_since: '2026-09-20T09:00:00Z',
  jobs_count: 1,
  phone_verified: false,
};

const POINT = { lat: 45.2471, lon: 19.8435 };

/** Заявки ленты SPEC §4 (JOBS): J2, J1, J3 — первые, как на артборде S13; дальше J4–J6. */
export const FEED_JOBS: FeedFixture[] = [
  fixture(
    1,
    {
      title: 'Течёт смеситель на кухне',
      category_id: CATEGORY_IDS.plumbing ?? 0,
      urgency: 'asap',
      budget_type: 'negotiable',
      district_id: DISTRICT_IDS.Центр,
      distance_m: 2000,
      responses_count: 4,
      published_at: at(5),
    },
    {
      description: 'Капает из-под крана. Нужно заменить картридж или смеситель целиком.',
      languages: ['ru', 'sr'],
      client: MARKO,
      point: POINT,
    },
  ),
  fixture(
    2,
    {
      title: 'Повесить люстру',
      category_id: CATEGORY_IDS.chandeliers ?? 0,
      urgency: 'today',
      // сегодня 18:00–21:00 по Белграду (UTC+2)
      preferred_from: '2026-10-05T16:00:00Z',
      preferred_to: '2026-10-05T19:00:00Z',
      budget_min: money(5000),
      district_id: DISTRICT_IDS.Лиман,
      distance_m: 1200,
      responses_count: 3,
      photos: [photo(2, 1, 'thumb'), photo(2, 2, 'thumb')],
      published_at: at(15),
    },
    {
      description:
        'Потолок бетонный, крюк есть. Люстра на 5 рожков — её нужно собрать, повесить и подключить. Стремянки у меня нет.',
      languages: ['ru'],
      client: ELENA,
      point: POINT,
    },
  ),
  fixture(
    3,
    {
      title: 'Собрать шкаф PAX, 2 м',
      category_id: CATEGORY_IDS['furniture-assembly'] ?? 0,
      urgency: 'this_week',
      budget_type: 'range',
      budget_min: money(4000),
      budget_max: money(6000),
      district_id: DISTRICT_IDS.Детелинара,
      distance_m: 3000,
      responses_count: 1,
      published_at: at(60),
    },
    { description: '', languages: [], client: MARKO, point: POINT },
  ),
  fixture(
    4,
    {
      title: 'Генеральная уборка, 2-комн. квартира',
      category_id: CATEGORY_IDS.cleaning ?? 0,
      urgency: 'this_week',
      budget_min: money(7000),
      district_id: DISTRICT_IDS.Грбавица,
      distance_m: 4500,
      published_at: at(3 * 60),
    },
    {
      description: 'Окна, кухня и ванная. Средства есть, нужен пылесос.',
      languages: [],
      client: MARKO,
      point: POINT,
    },
  ),
  fixture(
    5,
    {
      title: 'Помочь с переездом: 1-комн., 3 этаж без лифта',
      category_id: CATEGORY_IDS.moving ?? 0,
      urgency: 'flexible',
      preferred_from: '2026-10-12T08:00:00Z',
      budget_min: money(12000),
      district_id: DISTRICT_IDS.Лиман,
      distance_m: 1500,
      responses_count: 2,
      published_at: at(5 * 60),
    },
    {
      description: 'Шкаф, диван, коробки. Машина нужна своя.',
      languages: ['ru'],
      client: ELENA,
      point: POINT,
    },
  ),
  fixture(
    6,
    {
      title: 'Маникюр с покрытием на дому',
      category_id: CATEGORY_IDS.nails ?? 0,
      urgency: 'today',
      budget_type: 'range',
      budget_min: null,
      budget_max: money(3000),
      district_id: DISTRICT_IDS['Нова Детелинара'],
      distance_m: 5200,
      responses_count: 5,
      published_at: at(26 * 60),
    },
    { description: 'Гель-лак, короткие ногти.', languages: ['sr'], client: MARKO, point: POINT },
  ),
];

/** Раздел каталога → он и его услуги: id услуг раздела N — N01…N99 (fixtures.CATEGORY_IDS). */
const withChildren = (id: number) => (job: number) => job === id || Math.floor(job / 100) === id;

export class JobsBackend {
  /** Принятые POST /jobs: тело и ключ — все, включая повторы. */
  readonly posts: { body: JobIn; key: string | null }[] = [];
  readonly jobs = new Map<string, JobOut>();
  /** «Не интересно»: id скрытых заявок ленты. */
  readonly hidden = new Set<string>();
  /** Сохранённые заявки: id, новые первыми. */
  saved: string[] = [];
  /** Параметры каждого GET /jobs — что прислал экран. */
  readonly feedRequests: URLSearchParams[] = [];
  private readonly byKey = new Map<string, JobOut>();
  /** Статус новой заявки: на проверке или сразу опубликована. */
  status: JobStatus = 'pending_moderation';
  failNext: BackendReply | null = null;
  /** Ответ на следующий POST /jobs/{id}/hide ошибкой. */
  failNextHide: BackendReply | null = null;

  /** Заявки ленты: по умолчанию J1–J6; замер прокрутки ставит свою тысячу. */
  readonly feedJobs: FeedFixture[];

  constructor(feedJobs: FeedFixture[] = FEED_JOBS) {
    this.feedJobs = feedJobs;
  }

  /** Ответ на запрос `/jobs*`; null — запрос не к заявкам. `signedIn` — с токеном. */
  handle(
    method: string,
    url: URL,
    body: unknown,
    key: string | null,
    signedIn: boolean,
  ): BackendReply | null {
    const path = url.pathname.replace(/^\/api\/v1/, '');
    if (path.startsWith('/me/favorites/job')) {
      return signedIn ? this.favorites(method, path) : problem(401, 'not_authenticated');
    }
    if (method === 'GET' && path === '/jobs') return this.feed(url.searchParams);
    if (method === 'GET' && path === '/jobs/count') return this.count(url.searchParams);
    const hide = /^\/jobs\/([^/]+)\/hide$/.exec(path);
    if (method === 'POST' && hide) {
      return signedIn ? this.hide(hide[1] ?? '') : problem(401, 'not_authenticated');
    }
    if (method === 'POST' && path === '/jobs') {
      return signedIn ? this.create(body as JobIn, key) : problem(401, 'not_authenticated');
    }
    const job = /^\/jobs\/([^/]+)$/.exec(path);
    if (method === 'GET' && job) return this.get(job[1] ?? '');
    return null;
  }

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
    const own = this.jobs.get(id);
    if (own) return { status: 200, body: own };
    const listed = this.feedJobs.find((item) => item.card.id === id);
    return listed ? { status: 200, body: feedJobOut(listed) } : problem(404, 'job_not_found');
  }

  feed(params: URLSearchParams): BackendReply {
    this.feedRequests.push(params);
    const found = this.matching(params);
    const limit = Number(params.get('limit') ?? 20);
    const cursor = params.get('cursor');
    const start = cursor ? Number(cursor.replace(/^c/, '')) : 0;
    if (Number.isNaN(start)) return problem(422, 'invalid_cursor');
    const items = found.slice(start, start + limit);
    const next = start + limit < found.length ? `c${start + limit}` : null;
    return { status: 200, body: { items, next_cursor: next } };
  }

  count(params: URLSearchParams): BackendReply {
    const hours = params.get('new_hours');
    const since = hours ? new Date(E2E_NOW).getTime() - Number(hours) * HOUR_MS : null;
    const found = this.matching(params).filter(
      (card) => since === null || new Date(card.published_at).getTime() >= since,
    );
    return { status: 200, body: { count: found.length } };
  }

  hide(id: string): BackendReply {
    if (this.failNextHide) {
      const reply = this.failNextHide;
      this.failNextHide = null;
      return reply;
    }
    if (!this.feedJobs.some((item) => item.card.id === id)) return problem(404, 'job_not_found');
    this.hidden.add(id);
    return { status: 204, body: null };
  }

  /** Сохранённые: список открытых, новые первыми; сохранить — видимую, до ста; убрать — молча. */
  favorites(method: string, path: string): BackendReply | null {
    if (method === 'GET' && path === '/me/favorites/jobs') {
      const items = this.saved
        .map((id) => this.feedJobs.find((item) => item.card.id === id)?.card)
        .filter((card) => card !== undefined)
        // у списка нет точки зрителя — расстояния нет, как у сервера
        .map((card) => ({ ...card, distance_m: null }));
      return { status: 200, body: { items } };
    }
    const id = /^\/me\/favorites\/job\/([^/]+)$/.exec(path)?.[1];
    if (!id) return null;
    if (method === 'DELETE') {
      this.saved = this.saved.filter((item) => item !== id);
      return { status: 204, body: null };
    }
    if (method !== 'PUT') return null;
    if (!this.feedJobs.some((item) => item.card.id === id)) return problem(404, 'job_not_found');
    if (this.saved.includes(id)) return { status: 204, body: null };
    if (this.saved.length >= MAX_SAVED) {
      return problem(409, 'saved_jobs_full', { limit: MAX_SAVED });
    }
    this.saved = [id, ...this.saved];
    return { status: 204, body: null };
  }

  /** Фильтры ленты, как у сервера: расстояние — только с точкой зрителя. */
  private matching(params: URLSearchParams): JobCardOut[] {
    const categories = params.getAll('category').map(Number);
    const districts = params.getAll('district').map(Number);
    const urgencies = params.getAll('urgency') as Urgency[];
    const languages = params.getAll('lang');
    const point = params.has('lat') && params.has('lon');
    const radius = params.get('radius_km');
    const budget = params.get('budget_from');
    return this.feedJobs
      .filter((item) => !this.hidden.has(item.card.id))
      .filter(({ card }) => categories.length === 0 || categories.some((id) => withChildren(id)(card.category_id)))
      .filter(({ card }) => districts.length === 0 || districts.includes(card.district_id ?? 0))
      .filter(({ card }) => urgencies.length === 0 || urgencies.includes(card.urgency))
      .filter((item) => languages.length === 0 || item.languages.length === 0 || item.languages.some((code) => languages.includes(code)))
      .filter(({ card }) => params.get('has_photos') !== 'true' || card.photos_count > 0)
      .filter(({ card }) => budget === null || ((card.budget_max ?? card.budget_min)?.amount ?? 0) >= Number(budget))
      .filter(({ card }) => radius === null || (card.distance_m ?? Infinity) <= Number(radius) * 1000)
      .map(({ card }) => ({ ...card, distance_m: point ? card.distance_m : null }));
  } // prettier-ignore
}

/** Заявка ленты для S15: зритель — не владелец, фото — вариант md. */
function feedJobOut({ card, description, languages, client, point }: FeedFixture): JobOut {
  return {
    id: card.id,
    viewer_role: 'viewer',
    status: 'published',
    visibility: 'public',
    title: card.title,
    description,
    content_lang: 'ru',
    category_id: card.category_id,
    urgency: card.urgency,
    preferred_from: card.preferred_from,
    preferred_to: card.preferred_to,
    budget_type: card.budget_type,
    budget_min: card.budget_min,
    budget_max: card.budget_max,
    budget_unit: card.budget_unit,
    city_id: 1,
    district_id: card.district_id,
    point_public: point,
    point_exact: null,
    address_private: null,
    languages,
    media_ids: [],
    photos: card.photos.map((thumb) => ({
      ...thumb,
      url: thumb.url.replace('/thumb.webp', '/md.webp'),
      width: 800,
      height: 600,
    })),
    client,
    max_responses: card.max_responses,
    responses_count: card.responses_count,
    my_response: null,
    extensions_count: 0,
    moderation_note: null,
    version: 1,
    created_at: card.published_at,
    published_at: card.published_at,
    expires_at: null,
    closed_at: null,
    close_reason: null,
  };
}

export function jobOut(id: string, body: JobIn, status: JobStatus): JobOut {
  const amount = (value: number | null | undefined) =>
    value == null ? null : { amount: value, currency: 'RSD' as const };
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
    budget_min: amount(body.budget_min),
    budget_max: amount(body.budget_max),
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
    max_responses: MAX_RESPONSES,
    responses_count: 0,
    my_response: null,
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
