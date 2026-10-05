// Фейк backend заявок. Создание (5.2): POST /jobs запоминает тело и Idempotency-Key и, как сервер,
// на повтор с тем же ключом отвечает той же заявкой, а тот же ключ с другим телом — 422
// `idempotency_key_reused`; `failNext` — ответ на следующий POST ошибкой (ключ не занимается:
// повтор выполнится заново). `autoModerate` — автопроверка, как у сервера: ответ POST и PATCH —
// «на проверке», а сохранённая заявка уже опубликована следующей версией. Лента (5.3): GET /jobs — заявки J1–J6 SPEC §4
// (J1–J3 — как на артборде S13) с фильтрами и курсором, GET /jobs/count — их число, POST
// /jobs/{id}/hide — «не подходит»; GET /jobs/{id} — созданная заявка (владельцу) или заявка ленты.
// Сохранённые заявки (S12, S15): GET /me/favorites/jobs, PUT и DELETE /me/favorites/job/{id}.
// Отклики (5.5): POST /jobs/{id}/responses с ключом идемпотентности, места и суточная квота как у
// сервера; GET, PATCH /responses/{id} и /withdraw; GET /me/responses — чипы групп и «сегодня N из
// M»; шаблоны /me/response-templates — не больше двух, первый — основной. GET /jobs/{id} отдаёт
// свой отклик (`my_response`) и место, занятое им. Свои заявки клиента (5.6): GET /me/jobs, отклики
// карточками GET /jobs/{id}/response-cards (отмечают просмотренными), закрыть, продлить,
// пригласить. Выбор исполнителя и сделка (6.2): POST /responses/{id}/accept и /decline, сделки —
// GET /me/deals, GET /deals/{id}/card, POST /deals/{id}/complete и /cancel, ответ на «Договорились»
// из чата — /confirm и /decline (S53, 6.5); спор S52 (6.1c) — POST /deals/{id}/dispute,
// …/respond и …/withdraw, фото — из MediaBackend (`media`); сторона — клиент или
// исполнитель (`dealRole`). Подписки на заявки (5.7): /me/job-alerts — список, новая с ключом
// идемпотентности (не больше десяти), правка, удаление; лента и счётчик с `feed=alerts` — заявки
// категорий и бюджета включённых подписок. Время публикации — от E2E_NOW: в e2e часы браузера
// стоят на нём же.
import type {
  JobAlertIn,
  JobAlertOut,
  JobAlertPatchIn,
  DealCardDisputeOut,
  DealCardDisputePhotoOut,
  DealCardOut,
  DealCancelIn,
  DisputeAnswerIn,
  DisputeIn,
  DisputeOut,
  DealOut,
  HistoryDealOut,
  JobCardOut,
  JobClientOut,
  JobIn,
  JobOut,
  JobStatus,
  MyResponseOut,
  MyReviewOut,
  ReplyIn,
  ResponseGroup,
  ResponseIn,
  ResponseJobOut,
  ResponseOfferIn,
  ResponseStatus,
  ResponseTemplateIn,
  ResponseTemplateOut,
  ResponseTemplatePatchIn,
  ResponseCardOut,
  ReviewIn,
  ReviewOut,
  Urgency,
} from '@sosed/api-client';

import type { BackendReply } from './backend.ts';
import type { MediaBackend } from './mediaBackend.ts';
import { problem } from './backend.ts';
import { CATEGORY_IDS, DISTRICT_IDS, E2E_NOW } from './fixtures.ts';

const NOW = '2026-10-02T10:00:00Z';
const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const PARA = 100;
const MAX_RESPONSES = 5;
const MAX_SAVED = 100;
const MAX_TEMPLATES = 2;
const MAX_ALERTS = 10;
/** Суточная квота откликов новичка (§13.3). */
const DAILY_RESPONSES = 10;
const ACTIVE: ReadonlySet<ResponseStatus> = new Set(['submitted', 'viewed', 'shortlisted']);
const GROUPS: Record<ResponseGroup, ReadonlySet<ResponseStatus>> = {
  active: ACTIVE,
  accepted: new Set(['accepted']),
  not_selected: new Set(['not_selected', 'declined']),
  archive: new Set(['withdrawn']),
};

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

/** Заявка в карточке «Мои отклики». */
export function responseJobOf(card: JobCardOut): ResponseJobOut {
  return {
    id: card.id,
    title: card.title,
    status: 'published',
    category_id: card.category_id,
    city_id: 1,
    district_id: card.district_id,
    urgency: card.urgency,
    preferred_from: card.preferred_from,
    preferred_to: card.preferred_to,
    budget_type: card.budget_type,
    budget_min: card.budget_min,
    budget_max: card.budget_max,
    budget_unit: card.budget_unit,
    responses_count: card.responses_count,
    max_responses: card.max_responses,
    published_at: card.published_at,
  };
}

const priceOf = (body: ResponseOfferIn) => ({
  type: body.price_type,
  amount:
    body.price_amount === null || body.price_amount === undefined
      ? null
      : { amount: body.price_amount, currency: 'RSD' as const },
});

/** «Мои отклики» как на артборде S17: выбран — люстра, ждёт решения — шкаф (первый отклик),
 *  не выбран — смеситель. Места заявок ленты эти отклики уже учитывают. */
export function myResponsesFixture(feed: FeedFixture[] = FEED_JOBS): MyResponseOut[] {
  const job = (title: string) => {
    const found = feed.find((item) => item.card.title === title);
    if (!found) throw new Error(`no feed job ${title}`);
    return responseJobOf(found.card);
  };
  const base = { review: 'clear' as const, is_first: false, decided_at: null };
  return [
    {
      ...base,
      id: '0199dd10-0000-7000-8000-000000000001',
      status: 'accepted',
      message: 'Здравствуйте! Могу сегодня в 19:00, приеду со своим инструментом.',
      price: { type: 'fixed', amount: money(3500) },
      availability_note: 'сегодня в 19:00',
      created_at: at(50),
      updated_at: at(50),
      decided_at: at(10),
      job: job('Повесить люстру'),
    },
    {
      ...base,
      id: '0199dd10-0000-7000-8000-000000000002',
      status: 'submitted',
      message: 'Соберу шкаф за пару часов, есть опыт с PAX.',
      price: { type: 'fixed', amount: money(5000) },
      availability_note: 'завтра с 10:00',
      is_first: true,
      created_at: at(90),
      updated_at: at(90),
      job: job('Собрать шкаф PAX, 2 м'),
    },
    {
      ...base,
      id: '0199dd10-0000-7000-8000-000000000003',
      status: 'not_selected',
      message: 'Заменю смеситель сегодня, картридж привезу.',
      price: { type: 'fixed', amount: money(2000) },
      availability_note: null,
      created_at: at(180),
      updated_at: at(1),
      decided_at: at(1),
      job: job('Течёт смеситель на кухне'),
    },
  ];
}

/** Свои заявки клиента как на артборде S22: люстра — три отклика, уборка — ждёт откликов,
 *  уборка после ремонта — закрыта. Карточки ленты с теми же заголовками, но владельцу. */
export function myJobsFixture(feed: FeedFixture[] = FEED_JOBS): JobOut[] {
  const own = (title: string, patch: Partial<JobOut>): JobOut => {
    const found = feed.find((item) => item.card.title === title);
    if (!found) throw new Error(`no feed job ${title}`);
    return {
      ...feedJobOut(found),
      id: `0199dd30-0000-7000-8000-${String(feed.indexOf(found) + 1).padStart(12, '0')}`,
      viewer_role: 'owner',
      point_exact: found.point,
      address_private: 'Народног фронта 12',
      views_count: 12,
      notified_count: 7,
      new_responses: 0,
      client: null,
      ...patch,
    };
  };
  const cleaning = feed.find((item) => item.card.title.startsWith('Генеральная уборка'));
  return [
    own('Повесить люстру', { responses_count: 3, new_responses: 2 }),
    own(cleaning?.card.title ?? 'Генеральная уборка, 2-комн. квартира', {
      responses_count: 0,
      views_count: 4,
    }),
    own('Течёт смеситель на кухне', {
      title: 'Уборка после ремонта',
      status: 'closed',
      close_reason: 'hired_here',
      closed_at: '2026-09-14T15:00:00Z',
      responses_count: 0,
    }),
  ];
}

/** Отклики на люстру как на артборде S23: первый — с рейтингом и телефоном, подработка, третий —
 *  на сербском. */
export function responseCardsFixture(): ResponseCardOut[] {
  const base = {
    status: 'submitted' as const,
    availability_note: null,
    is_first: false,
    is_new: false,
    revision: 1,
  };
  const performer = {
    profile_id: null,
    kind: null,
    avatar: null,
    district: null,
    whole_city: false,
    rating: null,
    rating_count: 0,
    is_new: true,
    phone_verified: false,
  };
  return [
    {
      ...base,
      id: '0199dd40-0000-7000-8000-000000000001',
      message: 'Могу сегодня в 19:00, свой инструмент и стремянка',
      price: { type: 'fixed', amount: money(3500) },
      availability_note: 'сегодня в 19:00',
      is_first: true,
      is_new: true,
      created_at: at(12),
      performer: {
        ...performer,
        display_name: 'Алексей Морозов',
        profile_id: '0199dd50-0000-7000-8000-000000000001',
        kind: 'pro',
        district: { id: DISTRICT_IDS.Лиман, name: 'Лиман' },
        rating: 4.9,
        rating_count: 37,
        is_new: false,
        phone_verified: true,
      },
    },
    {
      ...base,
      id: '0199dd40-0000-7000-8000-000000000002',
      message: 'Буду в 20:00',
      price: { type: 'fixed', amount: money(3000) },
      is_new: true,
      created_at: at(8),
      performer: { ...performer, display_name: 'Иван Гаврилов' },
    },
    {
      ...base,
      id: '0199dd40-0000-7000-8000-000000000003',
      message: 'Mogu danas posle 18h',
      price: { type: 'fixed', amount: money(4500) },
      created_at: at(3),
      performer: {
        ...performer,
        display_name: 'Никола Петрович',
        profile_id: '0199dd50-0000-7000-8000-000000000003',
        kind: 'pro',
        district: { id: DISTRICT_IDS.Детелинара, name: 'Детелинара' },
        rating: 4.7,
        rating_count: 18,
        is_new: false,
      },
    },
  ];
}

/** Шаблоны как на артборде S57 — два: основной и «В боте». */
export function templatesFixture(): ResponseTemplateOut[] {
  return [
    {
      id: '0199dd20-0000-7000-8000-000000000001',
      title: 'Могу сегодня',
      message: 'Здравствуйте! Могу сегодня вечером, приеду со своим инструментом.',
      price: { type: 'from', amount: money(2000) },
      availability_note: 'сегодня',
      primary: true,
      updated_at: at(600),
    },
    {
      id: '0199dd20-0000-7000-8000-000000000002',
      title: 'Свой инструмент',
      message: 'Приеду со своим инструментом и стремянкой. Работаю аккуратно, убираю за собой.',
      price: { type: 'from', amount: money(2500) },
      availability_note: 'завтра',
      primary: false,
      updated_at: at(700),
    },
  ];
}

/** Раздел каталога → он и его услуги: id услуг раздела N — N01…N99 (fixtures.CATEGORY_IDS). */
const withChildren = (id: number) => (job: number) => job === id || Math.floor(job / 100) === id;

/** Подписки как на артборде S18: «Мастер на час» — до 3 км, от 2 000 RSD, по-русски, сразу;
 *  «Сборка мебели» — весь город, подборкой. */
export function alertsFixture(): JobAlertOut[] {
  const criteria = (patch: Partial<JobAlertOut['criteria']>): JobAlertOut['criteria'] => ({
    category_ids: [],
    city_id: 1,
    district_ids: [],
    center: null,
    radius_km: null,
    min_budget: null,
    urgencies: [],
    languages: ['ru'],
    ...patch,
  });
  return [
    {
      id: '0199dd40-0000-7000-8000-000000000001',
      criteria: criteria({
        category_ids: [CATEGORY_IDS['handyman'] ?? 0],
        center: { lat: 45.2671, lon: 19.8335 },
        radius_km: 3,
        min_budget: 2_000 * PARA,
      }),
      delivery: 'instant',
      is_active: true,
      paused_until: null,
      week_count: 8,
      created_at: '2026-09-20T10:00:00Z',
    },
    {
      id: '0199dd40-0000-7000-8000-000000000002',
      criteria: criteria({ category_ids: [CATEGORY_IDS['furniture-assembly'] ?? 0] }),
      delivery: 'digest',
      is_active: true,
      paused_until: null,
      week_count: 3,
      created_at: '2026-09-21T10:00:00Z',
    },
  ];
}

/** Id n-й заявки, созданной через фейк, — в форме UUID, как у сервера: по нему её находят `/share`
 *  (7.4) и разбор ссылок. */
export function createdJobId(n: number): string {
  return `0199dd60-0000-7000-8000-${String(n).padStart(12, '0')}`;
}

export class JobsBackend {
  /** Принятые POST /jobs и прямые запросы: тело, ключ и кому — все, включая повторы. */
  readonly posts: { body: JobIn; key: string | null; directTo?: string | null }[] = [];
  readonly jobs = new Map<string, JobOut>();
  /** «Не подходит»: id скрытых заявок ленты. */
  readonly hidden = new Set<string>();
  /** Сохранённые заявки: id, новые первыми. */
  saved: string[] = [];
  /** Параметры каждого GET /jobs — что прислал экран. */
  readonly feedRequests: URLSearchParams[] = [];
  private readonly byKey = new Map<string, JobOut>();
  /** Тело первого запроса с ключом: другое тело с тем же ключом сервер отклоняет. */
  private readonly bodyByKey = new Map<string, string>();
  /** Статус новой заявки: на проверке или сразу опубликована. */
  status: JobStatus = 'pending_moderation';
  /** Автопроверка сразу после ответа: заявка «на проверке» тут же опубликована, версия +1. */
  autoModerate = false;
  failNext: BackendReply | null = null;
  /** Ответ на следующий POST /jobs/{id}/hide ошибкой. */
  failNextHide: BackendReply | null = null;
  /** Отклики исполнителя, новые первыми. */
  responses: MyResponseOut[] = [];
  /** Принятые POST /jobs/{id}/responses: заявка, тело и ключ — все, включая повторы. */
  readonly responsePosts: { jobId: string; body: ResponseIn; key: string | null }[] = [];
  private readonly responsesByKey = new Map<string, MyResponseOut>();
  /** Заявки, на которые откликнулись здесь: их место ещё не учтено в ленте. */
  private readonly answered = new Set<string>();
  /** Отклики за сегодня — «сегодня откликов: N из 10». */
  respondedToday = 0;
  /** Ответ на следующий POST /jobs/{id}/responses ошибкой. */
  failNextRespond: BackendReply | null = null;
  /** Шаблоны по порядку: первый — основной. */
  templates: ResponseTemplateOut[] = [];
  /** Отклики на свои заявки карточками (S23): id заявки → карточки. */
  readonly responseCards = new Map<string, ResponseCardOut[]>();
  /** Приглашённые профили: id заявки → id профилей по порядку. */
  readonly invites = new Map<string, string[]>();
  /** Закрытия и продления — что прислал экран. */
  readonly actions: { jobId: string; action: 'close' | 'extend'; reason?: string }[] = [];
  /** Сделки (6.2): id → карточка S26 глазами `dealRole`. */
  readonly deals = new Map<string, DealCardOut>();
  /** Решения по откликам и действия в сделках — что прислал экран. */
  readonly decisions: { id: string; action: string; reason?: string }[] = [];
  /** Кто смотрит сделки: клиент (по умолчанию) или выбранный исполнитель. */
  dealRole: DealCardOut['my_role'] = 'client';
  /** Файлы, загруженные экраном (S52): фото спора показываются по ним, как у backend. */
  media: MediaBackend | null = null;
  /** Отзывы клиента по сделкам (7.3): id сделки → что прислал экран S27. */
  readonly reviews = new Map<string, ReviewOut>();
  /** «Обо мне» на S28: полученные отзывы исполнителя. */
  readonly received: MyReviewOut[] = [];
  /** Ответы на отзывы — что прислал экран S28. */
  readonly replies: { reviewId: string; body: string }[] = [];
  /** Подписки на заявки по порядку создания (S18). */
  alerts: JobAlertOut[] = [];
  /** Принятые POST и PATCH /me/job-alerts: тело и ключ — все, включая повторы. */
  readonly alertWrites: {
    method: string;
    body: JobAlertIn | JobAlertPatchIn;
    key: string | null;
  }[] = [];
  private readonly alertsByKey = new Map<string, JobAlertOut>();

  /** Свои заявки клиента (S22) и отклики люстры (S23), как на артбордах. */
  seedMine(): this {
    for (const job of myJobsFixture(this.feedJobs)) this.jobs.set(job.id, job);
    const [chandelier] = myJobsFixture(this.feedJobs);
    if (chandelier) this.responseCards.set(chandelier.id, responseCardsFixture());
    return this;
  }
  private readonly templatesByKey = new Map<string, ResponseTemplateOut>();

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
    ifMatch: string | null = null,
  ): BackendReply | null {
    const path = url.pathname.replace(/^\/api\/v1/, '');
    if (path.startsWith('/me/favorites/job')) {
      return signedIn ? this.favorites(method, path) : problem(401, 'not_authenticated');
    }
    if (method === 'GET' && path === '/me/jobs') {
      return signedIn ? this.mineList() : problem(401, 'not_authenticated');
    }
    const own = /^\/jobs\/([^/]+)\/(response-cards|close|extend|invites)$/.exec(path);
    if (own) {
      return signedIn
        ? this.owner(method, own[1] ?? '', own[2] ?? '', body)
        : problem(401, 'not_authenticated');
    }
    const decide = /^\/responses\/([^/]+)\/(accept|decline|shortlist)$/.exec(path);
    if (method === 'POST' && decide) {
      return signedIn
        ? this.decide(decide[1] ?? '', decide[2] ?? '')
        : problem(401, 'not_authenticated');
    }
    if (path === '/me/deals' || path.startsWith('/deals/')) {
      return signedIn ? this.dealt(method, path, body) : problem(401, 'not_authenticated');
    }
    if (path === '/me/deal-history' || path === '/me/reviews' || path.startsWith('/reviews/')) {
      return signedIn
        ? this.reviewed(method, path, url.searchParams, body)
        : problem(401, 'not_authenticated');
    }
    if (path === '/me/responses' || path.startsWith('/responses/')) {
      return signedIn
        ? this.mine(method, path, url.searchParams, body)
        : problem(401, 'not_authenticated');
    }
    if (path.startsWith('/me/response-templates')) {
      return signedIn ? this.templated(method, path, body, key) : problem(401, 'not_authenticated');
    }
    if (path.startsWith('/me/job-alerts')) {
      return signedIn ? this.alerted(method, path, body, key) : problem(401, 'not_authenticated');
    }
    const respond = /^\/jobs\/([^/]+)\/responses$/.exec(path);
    if (method === 'POST' && respond) {
      return signedIn
        ? this.respond(respond[1] ?? '', body as ResponseIn, key)
        : problem(401, 'not_authenticated');
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
    const direct = /^\/specialists\/([^/]+)\/requests$/.exec(path);
    if (method === 'POST' && direct) {
      return signedIn
        ? this.create(body as JobIn, key, direct[1] ?? null)
        : problem(401, 'not_authenticated');
    }
    const job = /^\/jobs\/([^/]+)$/.exec(path);
    if (method === 'GET' && job) return this.get(job[1] ?? '');
    if (method === 'PATCH' && job) {
      return signedIn
        ? this.update(job[1] ?? '', body as JobIn, ifMatch)
        : problem(401, 'not_authenticated');
    }
    return null;
  }

  /** Принятые PATCH /jobs/{id}: тело и If-Match. */
  readonly updates: { jobId: string; body: JobIn; ifMatch: string | null }[] = [];

  /** Правка своей заявки, как у сервера: If-Match не той версии — 412 `stale_version`. */
  update(id: string, body: JobIn, ifMatch: string | null): BackendReply {
    this.updates.push({ jobId: id, body, ifMatch });
    const job = this.jobs.get(id);
    if (!job) return problem(404, 'job_not_found');
    if (ifMatch !== null && ifMatch !== `"${job.version}"`) {
      return problem(412, 'stale_version', {
        detail: 'Данные устарели. Обновите страницу и повторите.',
      });
    }
    const edited: JobOut = {
      ...jobOut(id, body, this.autoModerate ? 'pending_moderation' : job.status),
      viewer_role: 'owner',
      responses_count: job.responses_count,
      views_count: job.views_count,
      new_responses: job.new_responses,
      published_at: job.published_at,
      version: job.version + 1,
    };
    this.jobs.set(id, this.moderated(edited));
    return { status: 200, body: edited };
  }

  /** Что лежит после ответа: с автопроверкой заявка на проверке уже опубликована (версия +1). */
  private moderated(job: JobOut): JobOut {
    if (!this.autoModerate || job.status !== 'pending_moderation') return job;
    return { ...job, status: 'published', version: job.version + 1, published_at: NOW };
  }

  /** Автопроверка или модератор поменяли заявку: статус, служебные поля и версия +1. */
  touch(id: string, patch: Partial<JobOut>): JobOut {
    const job = this.jobs.get(id);
    if (!job) throw new Error(`no job ${id}`);
    const touched = { ...job, ...patch, version: job.version + 1 };
    this.jobs.set(id, touched);
    return touched;
  }

  /** Новая заявка; `directTo` — прямой запрос этому профилю (5.6): `visibility = direct`. */
  create(body: JobIn, key: string | null, directTo: string | null = null): BackendReply {
    this.posts.push({ body, key, directTo });
    if (this.failNext) {
      const reply = this.failNext;
      this.failNext = null;
      return reply;
    }
    if (!key) return problem(400, 'idempotency_key_required');
    const known = this.byKey.get(key);
    if (known && this.bodyByKey.get(key) !== JSON.stringify(body)) {
      return problem(422, 'idempotency_key_reused', {
        detail: 'Этот Idempotency-Key уже использован с другими данными.',
      });
    }
    if (known) return { status: 201, body: known };
    const created = jobOut(createdJobId(this.jobs.size + 1), body, this.status);
    const job: JobOut = directTo ? { ...created, visibility: 'direct' } : created;
    this.jobs.set(job.id, this.moderated(job));
    this.byKey.set(key, job);
    this.bodyByKey.set(key, JSON.stringify(body));
    return { status: 201, body: job };
  }

  get(id: string): BackendReply {
    const own = this.jobs.get(id);
    if (own) return { status: 200, body: own };
    const listed = this.feedJobs.find((item) => item.card.id === id);
    if (!listed) return problem(404, 'job_not_found');
    const mine = this.responses.find((item) => item.job.id === id);
    const job = feedJobOut(listed);
    return {
      status: 200,
      body: {
        ...job,
        responses_count: this.taken(listed.card),
        my_response: mine ? { id: mine.id, status: mine.status, review: mine.review } : null,
      },
    };
  }

  /** Занятые места: из ленты и свой активный отклик, отправленный здесь. */
  private taken(card: JobCardOut): number {
    const mine = this.responses.find((item) => item.job.id === card.id);
    const added = mine && this.answered.has(card.id) && ACTIVE.has(mine.status) ? 1 : 0;
    return card.responses_count + added;
  }

  /** Отклик, как у сервера: ключ обязателен, повтор с ним — тот же отклик; своя заявка, повтор,
   *  нет мест — 409; чужой шаблон — 404; квота дня — 429. */
  respond(jobId: string, body: ResponseIn, key: string | null): BackendReply {
    this.responsePosts.push({ jobId, body, key });
    if (this.failNextRespond) {
      const reply = this.failNextRespond;
      this.failNextRespond = null;
      return reply;
    }
    if (!key) return problem(400, 'idempotency_key_required');
    const known = this.responsesByKey.get(key);
    if (known) return { status: 201, body: known };
    const listed = this.feedJobs.find((item) => item.card.id === jobId);
    if (!listed) return problem(404, 'job_not_found');
    if (body.template_id && !this.templates.some((item) => item.id === body.template_id)) {
      return problem(404, 'response_template_not_found');
    }
    if (this.responses.some((item) => item.job.id === jobId)) {
      return problem(409, 'already_responded');
    }
    if (this.taken(listed.card) >= listed.card.max_responses) {
      return problem(409, 'job_full', { limit: listed.card.max_responses });
    }
    if (this.respondedToday >= DAILY_RESPONSES) return problem(429, 'daily_responses_limit');
    const now = new Date(E2E_NOW).toISOString();
    const response: MyResponseOut = {
      id: `0199dd10-0000-7000-8000-${String(this.responses.length + 100).padStart(12, '0')}`,
      status: 'submitted',
      review: 'pending',
      message: body.message,
      price: priceOf(body),
      availability_note: body.availability_note ?? null,
      is_first: this.taken(listed.card) === 0,
      created_at: now,
      updated_at: now,
      decided_at: null,
      job: { ...responseJobOf(listed.card), responses_count: this.taken(listed.card) + 1 },
    };
    this.responses = [response, ...this.responses];
    this.answered.add(jobId);
    this.responsesByKey.set(key, response);
    this.respondedToday += 1;
    return { status: 201, body: response };
  }

  /** Свои заявки: новые первыми — как сохранены (созданные здесь — первыми). */
  mineList(): BackendReply {
    const items = [...this.jobs.values()].reverse();
    return { status: 200, body: { items } };
  }

  /** Действия владельца над своей заявкой (S23). */
  owner(method: string, jobId: string, action: string, body: unknown): BackendReply | null {
    const job = this.jobs.get(jobId);
    if (!job) return problem(404, 'job_not_found');
    if (action === 'response-cards' && method === 'GET') {
      const items = this.responseCards.get(jobId) ?? [];
      // ответ отмечает отклики просмотренными: второй раз они уже не новые
      this.responseCards.set(
        jobId,
        items.map((item) => ({ ...item, is_new: false })),
      );
      this.jobs.set(jobId, { ...job, new_responses: 0 });
      return { status: 200, body: { items } };
    }
    const now = new Date(E2E_NOW).toISOString();
    if (action === 'close' && method === 'POST') {
      const reason = (body as { reason: JobOut['close_reason'] }).reason;
      this.actions.push({ jobId, action: 'close', reason: reason ?? undefined });
      const closed: JobOut = { ...job, status: 'closed', close_reason: reason, closed_at: now };
      this.jobs.set(jobId, closed);
      return { status: 200, body: closed };
    }
    if (action === 'extend' && method === 'POST') {
      this.actions.push({ jobId, action: 'extend' });
      const extended: JobOut = {
        ...job,
        status: 'published',
        extensions_count: job.extensions_count + 1,
        expires_at: new Date(new Date(E2E_NOW).getTime() + 7 * 24 * HOUR_MS).toISOString(),
      };
      this.jobs.set(jobId, extended);
      return { status: 200, body: extended };
    }
    if (action === 'invites') {
      if (method === 'POST') {
        const ids = (body as { profile_ids: string[] }).profile_ids;
        const known = this.invites.get(jobId) ?? [];
        this.invites.set(jobId, [...known, ...ids.filter((id) => !known.includes(id))]);
      }
      const items = (this.invites.get(jobId) ?? []).map((profile_id) => ({
        profile_id,
        invited_at: now,
      }));
      return { status: 200, body: { items, limit: 10 } };
    }
    return null;
  }

  /** Решение клиента по отклику своей заявки (S24, S25): выбрать — сделка, отклонить. */
  decide(responseId: string, action: string): BackendReply {
    const owner = [...this.responseCards.entries()].find(([, cards]) =>
      cards.some((card) => card.id === responseId),
    );
    const job = owner ? this.jobs.get(owner[0]) : undefined;
    const card = owner?.[1].find((item) => item.id === responseId);
    if (!owner || !job || !card) return problem(404, 'response_not_found');
    if (!ACTIVE.has(card.status)) return problem(409, 'response_not_active');
    if (job.status !== 'published') return problem(409, 'job_not_open');
    this.decisions.push({ id: responseId, action });
    const status: ResponseCardOut['status'] =
      action === 'accept' ? 'accepted' : action === 'decline' ? 'declined' : 'shortlisted';
    const cards = owner[1].map((item) =>
      item.id === responseId
        ? { ...item, status }
        : action === 'accept' && ACTIVE.has(item.status)
          ? { ...item, status: 'not_selected' as const }
          : item,
    );
    this.responseCards.set(job.id, cards);
    if (action !== 'accept') {
      const changed = {
        ...job,
        responses_count: action === 'decline' ? job.responses_count - 1 : job.responses_count,
      };
      this.jobs.set(job.id, changed);
      return { status: 200, body: changed };
    }
    const assigned: JobOut = { ...job, status: 'assigned', responses_count: 0 };
    this.jobs.set(job.id, assigned);
    const deal = dealCardFixture(job, card, 'client');
    this.deals.set(deal.id, deal);
    return { status: 200, body: { deal_id: deal.id, job: assigned } };
  }

  /** Сделки стороне: списки, карточка S26, «Работа выполнена» и отмена с причиной. */
  dealt(method: string, path: string, body: unknown): BackendReply | null {
    const viewer = (deal: DealCardOut): DealCardOut =>
      deal.my_role === this.dealRole ? deal : asOther(deal);
    if (method === 'GET' && path === '/me/deals') {
      const items = [...this.deals.values()].reverse().map((deal) => dealOut(viewer(deal)));
      return { status: 200, body: { items, next_cursor: null } };
    }
    const disputed = /^\/deals\/([^/]+)\/dispute(?:\/(respond|withdraw))?$/.exec(path);
    if (method === 'POST' && disputed) {
      return this.disputed(disputed[1] ?? '', disputed[2] ?? 'open', body);
    }
    const match = /^\/deals\/([^/]+)\/(card|complete|cancel|confirm|decline|review)$/.exec(path);
    const found = this.deals.get(match?.[1] ?? '');
    if (!match) return null;
    if (!found) return problem(404, 'deal_not_found');
    const deal = viewer(found);
    if (method === 'GET' && match[2] === 'card') return { status: 200, body: deal };
    const now = new Date(E2E_NOW).toISOString();
    if (method === 'POST' && match[2] === 'review') {
      // S27: клиент по завершённой сделке, пока окно открыто, один раз
      if (deal.my_review) return problem(409, 'review_exists');
      if (deal.review_until === null) return problem(409, 'review_not_allowed');
      const sent = body as ReviewIn;
      const review: ReviewOut = {
        id: `01a0e004-0000-7000-8000-${String(this.reviews.size + 1).padStart(12, '0')}`,
        kind: 'deal',
        deal_id: deal.id,
        rating: sent.rating,
        criteria: (sent.criteria ?? {}) as Record<string, number>,
        body: sent.body ?? null,
        work_title: null,
        status: 'under_review',
        created_at: now,
        published_at: null,
        reply: null,
      };
      this.reviews.set(deal.id, review);
      this.deals.set(found.id, {
        ...found,
        my_review: { id: review.id, status: review.status, rating: review.rating },
        review_until: null,
      });
      return { status: 201, body: review };
    }
    if (method === 'POST' && (match[2] === 'confirm' || match[2] === 'decline')) {
      // S53: ответ на «Договорились» — только пока предложение ждёт
      if (deal.status !== 'proposed') return problem(409, 'deal_not_active');
      this.decisions.push({ id: deal.id, action: match[2] });
      const answered: DealCardOut =
        match[2] === 'confirm'
          ? {
              ...deal,
              status: 'agreed',
              awaits_my_confirmation: false,
              proposal_expires_at: null,
              timeline: { ...deal.timeline, agreed_at: now },
            }
          : {
              ...deal,
              status: 'cancelled',
              cancel_reason: 'no_agreement',
              cancelled_by_me: true,
              awaits_my_confirmation: false,
              proposal_expires_at: null,
              timeline: { ...deal.timeline, cancelled_at: now },
            };
      this.deals.set(deal.id, answered);
      return { status: 200, body: dealOut(answered) };
    }
    if (deal.status !== 'agreed') return problem(409, 'deal_not_active');
    let changed: DealCardOut;
    if (method === 'POST' && match[2] === 'complete') {
      this.decisions.push({ id: deal.id, action: 'complete' });
      const both = deal.timeline.other_mark_at !== null;
      changed = {
        ...deal,
        status: both ? 'completed' : 'agreed',
        timeline: {
          ...deal.timeline,
          my_mark_at: deal.timeline.my_mark_at ?? now,
          completed_at: both ? now : null,
        },
      };
    } else if (method === 'POST' && match[2] === 'cancel') {
      const reason = (body as DealCancelIn).reason;
      this.decisions.push({ id: deal.id, action: 'cancel', reason });
      changed = {
        ...deal,
        status: 'cancelled',
        cancel_reason: reason,
        cancelled_by_me: true,
        timeline: { ...deal.timeline, cancelled_at: now },
      };
    } else {
      return null;
    }
    this.deals.set(deal.id, changed);
    return { status: 200, body: dealOut(changed) };
  }

  /** Спор S52 (6.1c) глазами `dealRole`: открыть по идущей сделке, ответ второй стороны (один),
   *  отзыв открывшим — как у backend; ответ — спор со статусом сделки. */
  private disputed(dealId: string, action: string, body: unknown): BackendReply {
    const found = this.deals.get(dealId);
    if (!found) return problem(404, 'deal_not_found');
    const viewer = found.my_role === this.dealRole;
    const deal = viewer ? found : asOther(found);
    const now = new Date(E2E_NOW).toISOString();
    const current = deal.dispute;
    const active = current !== null && !['resolved', 'withdrawn'].includes(current.status);
    let dispute: DealCardDisputeOut;
    let status: DealCardOut['status'] = deal.status;
    if (action === 'open') {
      if (deal.status !== 'agreed') return problem(409, 'deal_not_active');
      const sent = body as DisputeIn;
      this.decisions.push({ id: deal.id, action: 'dispute', reason: sent.kind });
      dispute = {
        id: `0199df00-0000-7000-8000-${deal.id.slice(-12)}`,
        deal_id: deal.id,
        deal_status: 'disputed',
        status: 'open',
        kind: sent.kind,
        opened_by_me: true,
        description: sent.description,
        photos: this.photos(sent.media_ids ?? []),
        respond_by: new Date(Date.parse(now) + 48 * 60 * 60 * 1000).toISOString(),
        response: null,
        response_photos: [],
        responded_at: null,
        unanswered_at: null,
        withdrawn_at: null,
        outcome: null,
        reason_code: null,
        resolved_at: null,
        created_at: now,
      };
      status = 'disputed';
    } else if (!current || !active) {
      return problem(404, 'dispute_not_found');
    } else if (action === 'respond') {
      if (current.opened_by_me || current.status === 'answered') {
        return problem(409, 'dispute_state_conflict');
      }
      const sent = body as DisputeAnswerIn;
      this.decisions.push({ id: deal.id, action: 'respond' });
      dispute = {
        ...current,
        status: 'answered',
        response: sent.text,
        response_photos: this.photos(sent.media_ids ?? []),
        responded_at: now,
      };
    } else {
      if (!current.opened_by_me) return problem(409, 'dispute_state_conflict');
      this.decisions.push({ id: deal.id, action: 'withdraw' });
      dispute = { ...current, status: 'withdrawn', withdrawn_at: now };
      status = 'agreed';
    }
    dispute = { ...dispute, deal_status: status };
    const changed: DealCardOut = { ...deal, status, dispute };
    this.deals.set(found.id, viewer ? changed : asOther(changed));
    const reply: DisputeOut = dispute;
    return { status: action === 'open' ? 201 : 200, body: reply };
  }

  /** Фото спора: загруженные экраном — из MediaBackend; неизвестные — без вариантов. */
  private photos(ids: readonly string[]): DealCardDisputePhotoOut[] {
    return ids.map((id) => {
      const ref = this.media?.ref(id);
      return { id, placeholder: ref?.placeholder ?? null, variants: ref?.variants ?? [] };
    });
  }

  /** S28: «Сделки и отзывы», «Мои отзывы» и ответ на отзыв о себе (7.3). */
  reviewed(
    method: string,
    path: string,
    params: URLSearchParams,
    body: unknown,
  ): BackendReply | null {
    if (method === 'GET' && path === '/me/deal-history') {
      const items = [...this.deals.values()]
        .reverse()
        .map((deal) => historyOut(deal.my_role === this.dealRole ? deal : asOther(deal)));
      return { status: 200, body: { items, next_cursor: null } };
    }
    if (method === 'GET' && path === '/me/reviews') {
      const items =
        params.get('direction') === 'written'
          ? [...this.reviews.values()].map((review) => writtenOut(review, this.deals))
          : this.received;
      return { status: 200, body: { items, next_cursor: null } };
    }
    const reply = /^\/reviews\/([^/]+)\/reply$/.exec(path);
    if (method === 'POST' && reply) {
      const index = this.received.findIndex((review) => review.id === reply[1]);
      const review = this.received[index];
      if (!review) return problem(404, 'review_not_found');
      if (review.reply) return problem(409, 'reply_exists');
      const text = (body as ReplyIn).body.trim();
      this.replies.push({ reviewId: review.id, body: text });
      const now = new Date(E2E_NOW).toISOString();
      const answered: MyReviewOut = {
        ...review,
        reply: { body: text, at: now, status: 'under_review' },
        can_reply: false,
      };
      this.received[index] = answered;
      return { status: 201, body: answered };
    }
    return null;
  }

  /** «Мои отклики» и свой отклик: список с чипами, правка и отзыв, пока клиент не решил. */
  mine(method: string, path: string, params: URLSearchParams, body: unknown): BackendReply | null {
    if (method === 'GET' && path === '/me/responses') return this.myPage(params);
    const match = /^\/responses\/([^/]+)(\/withdraw)?$/.exec(path);
    const found = this.responses.find((item) => item.id === match?.[1]);
    if (!match) return null;
    if (!found) return problem(404, 'response_not_found');
    if (method === 'GET' && !match[2]) return { status: 200, body: found };
    if (!ACTIVE.has(found.status)) return problem(409, 'response_not_active');
    const now = new Date(E2E_NOW).toISOString();
    let changed: MyResponseOut;
    if (method === 'PATCH' && !match[2]) {
      const offer = body as ResponseOfferIn;
      changed = {
        ...found,
        message: offer.message,
        price: priceOf(offer),
        availability_note: offer.availability_note ?? null,
        review: 'pending',
        updated_at: now,
      };
    } else if (method === 'POST' && match[2]) {
      changed = { ...found, status: 'withdrawn', updated_at: now };
    } else {
      return null;
    }
    this.responses = this.responses.map((item) => (item.id === found.id ? changed : item));
    return { status: 200, body: changed };
  }

  private myPage(params: URLSearchParams): BackendReply {
    const group = params.get('status') as ResponseGroup | null;
    const found = this.responses.filter((item) => !group || GROUPS[group].has(item.status));
    const limit = Number(params.get('limit') ?? 20);
    const cursor = params.get('cursor');
    const start = cursor ? Number(cursor.replace(/^r/, '')) : 0;
    const count = (statuses: ReadonlySet<ResponseStatus>) =>
      this.responses.filter((item) => statuses.has(item.status)).length;
    return {
      status: 200,
      body: {
        items: found.slice(start, start + limit),
        next_cursor: start + limit < found.length ? `r${start + limit}` : null,
        counts: {
          all: this.responses.length,
          active: count(GROUPS.active),
          accepted: count(GROUPS.accepted),
          not_selected: count(GROUPS.not_selected),
          archive: count(GROUPS.archive),
        },
        today: { used: this.respondedToday, limit: DAILY_RESPONSES },
      },
    };
  }

  /** Шаблоны: не больше двух (третий — 409), «сделать основным» ставит первым, удаление
   *  сдвигает. */
  templated(method: string, path: string, body: unknown, key: string | null): BackendReply | null {
    const list = () => this.templates.map((item, index) => ({ ...item, primary: index === 0 }));
    if (path === '/me/response-templates') {
      if (method === 'GET') return { status: 200, body: { items: list(), limit: MAX_TEMPLATES } };
      if (method !== 'POST') return null;
      if (!key) return problem(400, 'idempotency_key_required');
      const known = this.templatesByKey.get(key);
      if (known) return { status: 201, body: known };
      if (this.templates.length >= MAX_TEMPLATES) {
        return problem(409, 'response_templates_full', { limit: MAX_TEMPLATES });
      }
      const input = body as ResponseTemplateIn;
      const created: ResponseTemplateOut = {
        id: `0199dd20-0000-7000-8000-${String(this.templatesByKey.size + 100).padStart(12, '0')}`,
        title: input.title.trim(),
        message: input.message,
        price: priceOf(input),
        availability_note: input.availability_note ?? null,
        primary: this.templates.length === 0,
        updated_at: new Date(E2E_NOW).toISOString(),
      };
      this.templates = [...this.templates, created];
      this.templatesByKey.set(key, created);
      return { status: 201, body: created };
    }
    const id = /^\/me\/response-templates\/([^/]+)$/.exec(path)?.[1];
    const found = this.templates.find((item) => item.id === id);
    if (!found) return problem(404, 'response_template_not_found');
    if (method === 'DELETE') {
      this.templates = this.templates.filter((item) => item.id !== found.id);
      return { status: 204, body: null };
    }
    if (method !== 'PATCH') return null;
    const patch = body as ResponseTemplatePatchIn;
    const edited: ResponseTemplateOut = {
      ...found,
      title: patch.title?.trim() ?? found.title,
      ...(patch.message && patch.price_type
        ? {
            message: patch.message,
            price: priceOf({
              message: patch.message,
              price_type: patch.price_type,
              price_amount: patch.price_amount,
            }),
            availability_note: patch.availability_note ?? null,
          }
        : {}),
    };
    const others = this.templates.filter((item) => item.id !== found.id);
    this.templates = patch.primary
      ? [edited, ...others]
      : this.templates.map((item) => (item.id === found.id ? edited : item));
    return { status: 200, body: list().find((item) => item.id === found.id) };
  }

  /** Подписки, как у сервера: до десяти, новая — с ключом; условия правки — целиком. */
  alerted(method: string, path: string, body: unknown, key: string | null): BackendReply | null {
    if (path === '/me/job-alerts') {
      if (method === 'GET') return { status: 200, body: { items: this.alerts, limit: MAX_ALERTS } };
      if (method !== 'POST') return null;
      this.alertWrites.push({ method, body: body as JobAlertIn, key });
      if (!key) return problem(400, 'idempotency_key_required');
      const known = this.alertsByKey.get(key);
      if (known) return { status: 201, body: known };
      if (this.alerts.length >= MAX_ALERTS) return problem(409, 'job_alerts_full', { limit: MAX_ALERTS });
      const input = body as JobAlertIn;
      const created: JobAlertOut = {
        id: `0199dd41-0000-7000-8000-${String(this.alertsByKey.size + 1).padStart(12, '0')}`,
        criteria: criteriaOut(input.criteria),
        delivery: input.delivery ?? 'instant',
        is_active: true,
        paused_until: null,
        week_count: this.matching(alertParams(input.criteria)).length,
        created_at: new Date(E2E_NOW).toISOString(),
      };
      this.alerts = [...this.alerts, created];
      this.alertsByKey.set(key, created);
      return { status: 201, body: created };
    }
    const id = /^\/me\/job-alerts\/([^/]+)$/.exec(path)?.[1];
    const found = this.alerts.find((item) => item.id === id);
    if (!found) return problem(404, 'job_alert_not_found');
    if (method === 'DELETE') {
      this.alerts = this.alerts.filter((item) => item.id !== found.id);
      return { status: 204, body: null };
    }
    if (method !== 'PATCH') return null;
    const patch = body as JobAlertPatchIn;
    this.alertWrites.push({ method, body: patch, key });
    const edited: JobAlertOut = {
      ...found,
      criteria: patch.criteria ? criteriaOut(patch.criteria) : found.criteria,
      delivery: patch.delivery ?? found.delivery,
      is_active: patch.is_active ?? found.is_active,
      paused_until: patch.is_active ? null : found.paused_until,
    };
    this.alerts = this.alerts.map((item) => (item.id === found.id ? edited : item));
    return { status: 200, body: edited };
  } // prettier-ignore

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
    const subscribed = params.get('feed') === 'alerts' ? this.alerts.filter((alert) => alert.is_active) : null;
    return this.feedJobs
      .filter((item) => !this.hidden.has(item.card.id))
      .filter(({ card }) => subscribed === null || subscribed.some((alert) => fits(alert, card)))
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

/** Условия подписки из тела запроса — как их вернёт сервер. */
function criteriaOut(input: JobAlertIn['criteria']): JobAlertOut['criteria'] {
  return {
    category_ids: input.category_ids,
    city_id: input.city_id,
    district_ids: input.district_ids ?? [],
    center: input.center ?? null,
    radius_km: input.radius_km ?? null,
    min_budget: input.min_budget ?? null,
    urgencies: input.urgencies ?? [],
    languages: input.languages ?? [],
  };
}

/** Параметры ленты, которыми фейк считает «N заявок за неделю» новой подписки. */
function alertParams(input: JobAlertIn['criteria']): URLSearchParams {
  const params = new URLSearchParams();
  for (const id of input.category_ids) params.append('category', String(id));
  if (input.min_budget) params.set('budget_from', String(input.min_budget));
  return params;
}

/** Заявка подходит подписке: категория с подкатегориями и бюджет «от» (договорные — да). */
function fits(alert: JobAlertOut, card: JobCardOut): boolean {
  const { category_ids: categories, min_budget: budget } = alert.criteria;
  const amount = (card.budget_max ?? card.budget_min)?.amount ?? null;
  return (
    categories.some((id) => withChildren(id)(card.category_id)) &&
    (budget === null || amount === null || amount >= budget)
  );
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
    views_count: null,
    notified_count: null,
    new_responses: null,
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
    views_count: 0,
    notified_count: 0,
    new_responses: 0,
    moderation_note: null,
    version: 1,
    created_at: NOW,
    published_at: status === 'published' ? NOW : null,
    expires_at: null,
    closed_at: null,
    close_reason: null,
  };
}

/** Сделка из выбранного отклика глазами клиента: исполнитель, район, окно и вехи. */
export function dealCardFixture(
  job: JobOut,
  card: ResponseCardOut,
  role: DealCardOut['my_role'],
): DealCardOut {
  const now = new Date(E2E_NOW).toISOString();
  const deal: DealCardOut = {
    id: `0199de00-0000-7000-8000-${card.id.slice(-12)}`,
    status: 'agreed',
    origin: 'job_response',
    my_role: 'client',
    title: job.title,
    price: { type: card.price.type, amount: card.price.amount },
    scheduled_at: job.preferred_from,
    preferred_from: job.preferred_from,
    preferred_to: job.preferred_to,
    urgency: job.urgency,
    availability_note: card.availability_note,
    budget: job.budget_min,
    counterpart: {
      role: 'performer',
      display_name: card.performer.display_name,
      profile_id: card.performer.profile_id,
      avatar: card.performer.avatar,
      rating: card.performer.rating,
      rating_count: card.performer.rating_count,
      is_new: card.performer.is_new,
      phone_verified: card.performer.phone_verified,
      telegram: '@aleksey_m',
    },
    place: {
      city: { id: job.city_id, name: 'Нови-Сад' },
      district: job.district_id ? { id: job.district_id, name: 'Лиман' } : null,
      address: 'бул. Цара Лазара, 56, кв. 12',
      point: POINT,
    },
    timeline: {
      responded_at: card.created_at,
      agreed_at: now,
      my_mark_at: null,
      other_mark_at: null,
      completed_at: null,
      cancelled_at: null,
    },
    awaits_my_confirmation: false,
    cancelled_by_me: null,
    cancel_reason: null,
    job_id: job.id,
    response_id: card.id,
    conversation_id: null,
    version: 1,
    proposed_at: null,
    proposal_expires_at: null,
    my_review: null,
    review_until: null,
    dispute: null,
  };
  return role === 'client' ? deal : asOther(deal);
}

/** Та же сделка глазами второй стороны: роль, контрагент и отметки меняются местами; отзыв пишет
 *  только клиент. */
function asOther(deal: DealCardOut): DealCardOut {
  const performer = deal.my_role === 'client';
  return {
    ...deal,
    my_review: performer ? null : deal.my_review,
    review_until: performer ? null : deal.review_until,
    my_role: performer ? 'performer' : 'client',
    counterpart: performer
      ? {
          role: 'client',
          display_name: 'Елена К.',
          profile_id: null,
          avatar: null,
          rating: null,
          rating_count: 0,
          is_new: false,
          phone_verified: true,
          telegram: '@elena_k',
        }
      : { ...deal.counterpart, role: 'performer' },
    timeline: {
      ...deal.timeline,
      my_mark_at: deal.timeline.other_mark_at,
      other_mark_at: deal.timeline.my_mark_at,
    },
    cancelled_by_me: deal.cancelled_by_me === null ? null : !deal.cancelled_by_me,
    dispute: deal.dispute ? { ...deal.dispute, opened_by_me: !deal.dispute.opened_by_me } : null,
  };
}

/** `GET /me/deals` и ответы действий: сделка в форме DealOut. */
function dealOut(deal: DealCardOut): DealOut {
  return {
    id: deal.id,
    status: deal.status,
    origin: deal.origin,
    my_role: deal.my_role,
    title: deal.title,
    category_id: null,
    price: deal.price,
    scheduled_at: deal.scheduled_at,
    client_id: '0199dd00-0000-7000-8000-00000000c11e',
    performer_id: '0199dd00-0000-7000-8000-0000000000ff',
    profile_id: deal.counterpart.profile_id,
    job_id: deal.job_id,
    response_id: deal.response_id,
    conversation_id: deal.conversation_id,
    awaits_my_confirmation: deal.awaits_my_confirmation,
    i_marked_done: deal.timeline.my_mark_at !== null,
    other_marked_done: deal.timeline.other_mark_at !== null,
    agreed_at: deal.timeline.agreed_at,
    completed_at: deal.timeline.completed_at,
    cancelled_at: deal.timeline.cancelled_at,
    cancelled_by_me: deal.cancelled_by_me,
    cancel_reason: deal.cancel_reason,
    version: deal.version,
    created_at: deal.timeline.agreed_at ?? new Date(E2E_NOW).toISOString(),
  };
}

/** «Договорились» из прямого диалога ждёт ответа исполнителя (S53, 6.5): условия, район без
 *  адреса, срок 72 ч. Смотрит исполнитель — клиент предложил. */
export function proposedDealFixture(conversationId: string): DealCardOut {
  const proposedAt = new Date(E2E_NOW);
  return {
    id: '0199de00-0000-7000-8000-00000000c0de',
    status: 'proposed',
    origin: 'chat',
    my_role: 'performer',
    title: 'Повесить люстру',
    price: { type: 'fixed', amount: { amount: 350_000, currency: 'RSD' } },
    scheduled_at: new Date(proposedAt.getTime() + 9 * 60 * 60 * 1000).toISOString(),
    preferred_from: null,
    preferred_to: null,
    urgency: null,
    availability_note: null,
    budget: null,
    counterpart: {
      role: 'client',
      display_name: 'Елена К.',
      profile_id: null,
      avatar: null,
      rating: null,
      rating_count: 0,
      is_new: false,
      phone_verified: false,
      telegram: null,
    },
    place: {
      city: { id: 1, name: 'Нови-Сад' },
      district: { id: DISTRICT_IDS.Лиман, name: 'Лиман' },
      address: null,
      point: null,
    },
    timeline: {
      responded_at: null,
      agreed_at: null,
      my_mark_at: null,
      other_mark_at: null,
      completed_at: null,
      cancelled_at: null,
    },
    awaits_my_confirmation: true,
    cancelled_by_me: null,
    cancel_reason: null,
    job_id: null,
    response_id: null,
    conversation_id: conversationId,
    version: 1,
    proposed_at: proposedAt.toISOString(),
    proposal_expires_at: new Date(proposedAt.getTime() + 72 * 60 * 60 * 1000).toISOString(),
    my_review: null,
    review_until: null,
    dispute: null,
  };
}

/** Сделка строкой S28 (BFF `GET /me/deal-history`). */
function historyOut(deal: DealCardOut): HistoryDealOut {
  return {
    id: deal.id,
    status: deal.status,
    my_role: deal.my_role,
    title: deal.title,
    price: deal.price,
    scheduled_at: deal.scheduled_at,
    counterpart: {
      id: '01a0e001-0000-7000-8000-0000000000ff',
      role: deal.counterpart.role,
      display_name: deal.counterpart.display_name,
    },
    completed_at: deal.timeline.completed_at,
    cancelled_at: deal.timeline.cancelled_at,
    cancelled_by_me: deal.cancelled_by_me,
    cancel_reason: deal.cancel_reason,
    created_at: deal.timeline.agreed_at ?? new Date(E2E_NOW).toISOString(),
    my_review: deal.my_review,
    review_until: deal.review_until,
  };
}

/** Свой отзыв в «Моих» S28. */
function writtenOut(review: ReviewOut, deals: Map<string, DealCardOut>): MyReviewOut {
  const deal = review.deal_id ? deals.get(review.deal_id) : undefined;
  return {
    id: review.id,
    kind: review.kind,
    deal_id: review.deal_id,
    deal_title: deal?.title ?? null,
    work_title: review.work_title,
    counterpart_name: deal?.counterpart.display_name ?? null,
    rating: review.rating,
    criteria: review.criteria,
    body: review.body,
    status: review.status,
    created_at: review.created_at,
    published_at: review.published_at,
    reply: null,
    can_reply: false,
  };
}

/** Завершённая сделка клиента (7.3): обе отметили «Работа выполнена» час назад, отзыв ещё можно
 *  оставить 14 дней. */
export function completedDealFixture(job: JobOut, card: ResponseCardOut): DealCardOut {
  const done = new Date(Date.parse(E2E_NOW) - 60 * 60 * 1000).toISOString();
  const until = new Date(Date.parse(done) + 14 * 24 * 60 * 60 * 1000).toISOString();
  const deal = dealCardFixture(job, card, 'client');
  return {
    ...deal,
    status: 'completed',
    timeline: { ...deal.timeline, my_mark_at: done, other_mark_at: done, completed_at: done },
    review_until: until,
  };
}

/** Полученный отзыв исполнителя (S28 «Обо мне»): опубликован, ответа ещё нет. */
export function receivedReviewFixture(): MyReviewOut {
  return {
    id: '01a0e004-0000-7000-8000-0000000000aa',
    kind: 'deal',
    deal_id: '01a0e003-0000-7000-8000-0000000000aa',
    deal_title: 'Собрать шкаф PAX',
    work_title: null,
    counterpart_name: 'Елена К.',
    rating: 5,
    criteria: { quality: 5 },
    body: 'Всё собрал быстро и аккуратно',
    status: 'published',
    created_at: new Date(Date.parse(E2E_NOW) - 2 * 24 * 60 * 60 * 1000).toISOString(),
    published_at: new Date(Date.parse(E2E_NOW) - 2 * 24 * 60 * 60 * 1000).toISOString(),
    reply: null,
    can_reply: true,
  };
}
