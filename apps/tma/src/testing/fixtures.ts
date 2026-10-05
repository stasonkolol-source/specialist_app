// Демо-данные design/SPEC.md §4 — одни и те же во всех экранах, тестах и скриншотах.
// Ответы существующих эндпоинтов — типами api-client; данные экранов, для которых API ещё нет
// (специалисты, заявки, отклики), — формой из SPEC: шаги этапа 1 заменят их моделями OpenAPI.
import type {
  CardReviewOut,
  CardReviewsOut,
  CardServiceOut,
  CardServicesOut,
  CardWorkOut,
  CardWorksOut,
  CategoryCountsOut,
  CategoryOut,
  CityOut,
  ClientConfigOut,
  DistrictOut,
  MeOut,
  NotificationOut,
  NotificationPageOut,
  NotificationSettingsOut,
  NotificationType,
  ProfileOut,
  ServiceOut,
  ShareIn,
  ShareOut,
  SpecialistCardOut,
  SpecialistPageOut,
  SpecialistProfileOut,
  SuggestOut,
  TelegramChannelOut,
  WorkKind,
  WorkOut,
} from '@sosed/api-client';
import { encodeStartParam, isUuid } from '@sosed/links';

import { draftDocument } from './legal.ts';

export const CITY = 'Нови-Сад';

export const DISTRICTS = [
  'Лиман',
  'Грбавица',
  'Детелинара',
  'Нова Детелинара',
  'Центр',
  'Адице',
  'Телеп',
  'Подбара',
] as const;

export const CATEGORIES = [
  {
    id: 'handyman',
    name: 'Мастер на час',
    icon: 'wrench',
    sub: ['электрика', 'сантехника', 'сборка мебели', 'люстры и карнизы'],
  },
  { id: 'beauty', name: 'Бьюти', icon: 'scissors', sub: ['маникюр', 'брови и ресницы', 'стрижки'] },
  { id: 'cleaning', name: 'Уборка', icon: 'broom', sub: [] },
  { id: 'moving', name: 'Переезды', icon: 'truck', sub: [] },
  {
    id: 'tutors',
    name: 'Репетиторы',
    icon: 'book',
    sub: ['сербский язык для взрослых', 'английский'],
  },
] as const;

export interface SpecialistFixture {
  name: string;
  initials: string;
  avatar: 'av1' | 'av2' | 'av3' | 'av4' | 'av5';
  title: string;
  rating: number | null;
  reviews: number;
  district: string;
  distanceKm: number | null;
  price: string | null;
  languages: string[];
  /** Профиль подработки (SPEC §4: бейдж «Подработка»); по умолчанию — специалист. */
  kind?: 'casual';
}

export const SPECIALISTS: SpecialistFixture[] = [
  { name: 'Алексей Морозов', initials: 'АМ', avatar: 'av1', title: 'Электрик · мелкий ремонт · люстры', rating: 4.9, reviews: 37, district: 'Лиман', distanceKm: 1.5, price: 'от 2 000 RSD за выезд', languages: ['ru', 'sr'] },
  { name: 'Мария Ковалёва', initials: 'МК', avatar: 'av4', title: 'Маникюр и педикюр · гель-лак', rating: 5.0, reviews: 52, district: 'Грбавица', distanceKm: 2, price: 'от 2 500 RSD', languages: ['ru'] },
  { name: 'Дмитрий Соколов', initials: 'ДС', avatar: 'av2', title: 'Сборка мебели · полки · карнизы', rating: 4.8, reviews: 21, district: 'Детелинара', distanceKm: 3, price: 'от 1 800 RSD за предмет', languages: ['ru', 'en'] },
  { name: 'Ольга Власова', initials: 'ОВ', avatar: 'av5', title: 'Уборка квартир', rating: 4.9, reviews: 44, district: 'Центр', distanceKm: 2.5, price: '1 000 RSD/час', languages: ['ru', 'uk'] },
  { name: 'Никола Петрович', initials: 'НП', avatar: 'av3', title: 'Vodoinstalater — сантехник', rating: 4.7, reviews: 18, district: 'Адице', distanceKm: 4, price: 'от 3 000 RSD', languages: ['sr', 'en'] },
  { name: 'Анна Лебедева', initials: 'АЛ', avatar: 'av4', title: 'Сербский язык для взрослых', rating: 5.0, reviews: 29, district: 'онлайн и у себя', distanceKm: null, price: '1 500 RSD/урок', languages: ['ru', 'sr'] },
  { name: 'Сергей Титов', initials: 'СТ', avatar: 'av2', title: 'Переезды · грузчики · фургон', rating: 4.8, reviews: 33, district: 'Телеп', distanceKm: null, price: 'от 3 500 RSD/час', languages: [] },
  { name: 'Екатерина Руденко', initials: 'ЕР', avatar: 'av1', title: 'Брови и ресницы', rating: 4.9, reviews: 40, district: 'Подбара', distanceKm: null, price: 'от 2 400 RSD', languages: [] },
  { name: 'Иван Гаврилов', initials: 'ИГ', avatar: 'av3', title: 'Подработка: переезды и сборка', rating: null, reviews: 0, district: 'Лиман', distanceKm: null, price: null, languages: [], kind: 'casual' },
]; // prettier-ignore

export interface JobFixture {
  code: string;
  title: string;
  where: string;
  when: string;
  budget: string;
  photos: number;
  responses: number;
  urgent?: boolean;
}

export const JOBS: JobFixture[] = [
  { code: 'J1', title: 'Повесить люстру', where: 'Лиман, ≈ 1,2 км', when: 'сегодня 18:00–21:00', budget: '5 000 RSD, фикс', photos: 2, responses: 3 },
  { code: 'J2', title: 'Течёт смеситель на кухне', where: 'Центр, ≈ 2 км', when: 'срочно', budget: 'договорная', photos: 1, responses: 4, urgent: true },
  { code: 'J3', title: 'Собрать шкаф PAX, 2 м', where: 'Детелинара, ≈ 3 км', when: 'на неделе', budget: '4 000–6 000 RSD', photos: 1, responses: 1 },
  { code: 'J4', title: 'Генеральная уборка, 2-комн. квартира', where: 'Грбавица', when: 'суббота', budget: '7 000 RSD', photos: 0, responses: 0 },
  { code: 'J5', title: 'Помочь с переездом: 1-комн., 3 этаж без лифта', where: 'Лиман → Адице', when: '12 октября', budget: '12 000 RSD', photos: 0, responses: 2 },
  { code: 'J6', title: 'Маникюр с покрытием на дому', where: 'Нова Детелинара', when: 'сегодня', budget: 'до 3 000 RSD', photos: 0, responses: 5 },
]; // prettier-ignore

/** Клиент демо-данных — Елена К. (ЕК, av2); тот же пользователь у mock-платформы. */
export const ME: MeOut = {
  id: '01a0e259-a46c-75cb-8a6f-c52d857316af',
  display_name: 'Елена К.',
  ui_locale: 'ru',
  trust_level: 0,
  phone_verified: false,
  created_at: '2026-09-27T10:12:00Z',
  home_city_id: 1,
  intent: 'client',
  consents: { terms: 'draft-1', privacy: 'draft-1', age_18: 'draft-1' },
  consent_required: false,
  can_post_jobs: true,
  can_respond: true,
  can_message: true,
  deletion_scheduled_at: null,
  privacy: { show_telegram: true },
};

/** Запрос на удаление аккаунта S45: принят 1 октября, исполнится через 7 дней — 8 октября. */
export const DELETION_REQUESTED_AT = '2026-10-01T12:00:00Z';
export const DELETION_EXECUTE_AFTER = '2026-10-08T12:00:00Z';

/** Новый пользователь сразу после первого входа: ни города, ни намерения, ни согласия (S02a). */
export const NEW_USER: MeOut = {
  ...ME,
  home_city_id: null,
  intent: null,
  consents: {},
  consent_required: true,
  can_post_jobs: false,
  can_respond: false,
  can_message: false,
};

/** Вернувшийся пользователь после новой редакции правил: снова только S02c. */
export const OUTDATED_CONSENTS_USER: MeOut = {
  ...ME,
  consents: { terms: 'draft-0', privacy: 'draft-0', age_18: 'draft-0' },
  consent_required: true,
  can_post_jobs: false,
  can_respond: false,
  can_message: false,
};

/** Согласие с действующими версиями CLIENT_CONFIG: ответ POST /me/consents. */
export const accepted = (me: MeOut): MeOut => ({
  ...me,
  consents: { terms: 'draft-1', privacy: 'draft-1', age_18: 'draft-1' },
  consent_required: false,
  can_post_jobs: true,
  can_respond: true,
  can_message: true,
});

/** Города seeds/geo/cities.yaml: пилот Нови-Сад и Белград «скоро»; названия — на языке запроса. */
const CITY_NAMES: Record<string, [string, string]> = {
  ru: ['Нови-Сад', 'Белград'],
  'sr-Cyrl': ['Нови Сад', 'Београд'],
  'sr-Latn': ['Novi Sad', 'Beograd'],
};

export function citiesFor(locale: string | null): CityOut[] {
  const [noviSad, belgrade] = CITY_NAMES[locale ?? 'ru'] ?? CITY_NAMES.ru ?? ['', ''];
  return [
    { id: 1, slug: 'novi-sad', name: noviSad, status: 'active', center: { lat: 45.2671, lon: 19.8335 } },
    { id: 2, slug: 'beograd', name: belgrade, status: 'soon', center: { lat: 44.8125, lon: 20.4573 } },
  ];
} // prettier-ignore

/** POST /me/telegram/write-access: разрешение из Mini App. */
export const WRITE_ACCESS: TelegramChannelOut = {
  writable: true,
  granted_via: 'mini_app',
  granted_at: '2026-09-27T10:13:00Z',
};

/** Как client-config dev-стенда: черновики draft-1 правил и политики (0.27), флаг техработ выключен. */
export const CLIENT_CONFIG: ClientConfigOut = {
  min_versions: { tma: '0.1.0' },
  flags: { 'goods.segment': true, 'platform.maintenance': false },
  legal_versions: { terms: 'draft-1', privacy: 'draft-1' },
  legal_documents: { terms: draftDocument('terms'), privacy: draftDocument('privacy') },
  // K23, Q25: контакт поддержки не назначен — S43 и S47 показывают «скоро»
  support_username: null,
};

/** «Сейчас» демо-данных уведомлений (S42): как в e2e сервиса — 2 октября, 18:07 по Белграду. */
export const NOTIFICATIONS_NOW = new Date('2026-10-02T18:07:00+02:00');

const NOTIFICATION_TEXTS: Record<'ru' | 'sr-Latn', [string, string][]> = {
  ru: [
    ['Сделка подтверждена', 'Алексей Морозов · «Повесить люстру» · сегодня в 19:00, 3\u00a0500 RSD'],
    ['Новое сообщение', 'Алексей Морозов: «Буду в 19:00, стремянка с собой»'],
    ['Новый отклик', 'Никола Петрович · 4\u00a0500 RSD · «Повесить люстру», откликов 3 из 5'],
    ['Заявка прошла проверку', '«Повесить люстру» опубликована, исполнители рядом получили уведомление'],
    ['Как прошла уборка?', 'Оцените работу Ольги Власовой — отзыв поможет другим клиентам'],
    ['Проверка уведомлений', 'Бот может писать вам: так приходят отклики, сообщения и решения модерации'],
  ],
  'sr-Latn': [
    ['Dogovor je potvrđen', 'Aleksej Morozov · „Kačenje lustera“ · danas u 19:00, 3\u00a0500 RSD'],
    ['Nova poruka', 'Aleksej Morozov: „Biću u 19:00, merdevine nosim“'],
    ['Nova ponuda', 'Nikola Petrović · 4\u00a0500 RSD · „Kačenje lustera“, ponuda 3 od 5'],
    ['Zahtev je prošao proveru', '„Kačenje lustera“ je objavljen, stručnjaci u blizini su obavešteni'],
    ['Kako je prošlo čišćenje?', 'Ocenite rad Olge Vlasove — utisak pomaže drugim klijentima'],
    ['Provera obaveštenja', 'Bot može da vam piše: tako stižu ponude, poruke i odluke moderacije'],
  ],
}; // prettier-ignore

/** Тип, минуты до NOTIFICATIONS_NOW, прочитано, deep link — как макет S42. */
const NOTIFICATION_ROWS: [NotificationType, number, boolean, string | null][] = [
  ['deal.proposed', 2, false, encodeStartParam({ type: 'home' })],
  ['message.received', 5, false, encodeStartParam({ type: 'home' })],
  ['response.received', 12, true, encodeStartParam({ type: 'home' })],
  ['moderation.decision', 15, true, encodeStartParam({ type: 'legal', document: 'terms' })],
  ['review.request', 23 * 60 + 27, true, encodeStartParam({ type: 'home' })],
  ['system.test', 30 * 60 + 2, true, null],
];

/** GET /me/notifications: тексты — на языке запроса, как у backend. */
export function notificationsFor(locale: string | null): NotificationPageOut {
  const texts = NOTIFICATION_TEXTS[locale === 'sr-Latn' ? 'sr-Latn' : 'ru'];
  const items = NOTIFICATION_ROWS.map(([type, minutes, read, link], index): NotificationOut => {
    const [title, body] = texts[index] ?? ['', ''];
    const createdAt = new Date(NOTIFICATIONS_NOW.getTime() - minutes * 60_000).toISOString();
    return { id: `0199aa00-0000-7000-8000-00000000000${index}`, type, title, body, link, created_at: createdAt, read };
  }); // prettier-ignore
  return { items, next_cursor: null, unread_count: items.filter((item) => !item.read).length };
}

/** GET /me/notification-settings: бот писать не может (канала нет) — S42 показывает баннер. */
export const NOTIFICATION_SETTINGS: NotificationSettingsOut = {
  groups: [
    { group: 'job_matches', telegram: true, in_app: true, mandatory: false },
    { group: 'responses', telegram: true, in_app: true, mandatory: false },
    { group: 'messages', telegram: true, in_app: true, mandatory: false },
    { group: 'deals', telegram: true, in_app: true, mandatory: false },
    { group: 'marketing', telegram: false, in_app: false, mandatory: false },
    { group: 'goods_launch', telegram: false, in_app: false, mandatory: false },
    { group: 'account', telegram: true, in_app: true, mandatory: true },
  ],
  quiet_hours: { enabled: true, start: '22:00:00', end: '08:00:00', time_zone: 'Europe/Belgrade' },
  digest_hour: 9,
  telegram: null,
};

/** Язык ответов справочников, как у backend: sr-Latn или ru (для остальных). */
const latin = (locale: string | null) => locale === 'sr-Latn';

/** Каталог GET /categories — разделы и подкатегории SPEC §4 (CATEGORIES); у листьев id ≥ 100. */
const CATEGORY_TREE: [string, string, string, string, [string, string, string][]][] = [
  ['handyman', 'wrench', 'Мастер на час', 'Majstor na sat', [
    ['electrical', 'Электрика', 'Elektrika'],
    ['plumbing', 'Сантехника', 'Vodoinstalacije'],
    ['furniture-assembly', 'Сборка мебели', 'Montaža nameštaja'],
    ['chandeliers', 'Люстры и карнизы', 'Lusteri i garnišne'],
  ]],
  ['beauty', 'scissors', 'Бьюти', 'Lepota', [
    ['nails', 'Маникюр', 'Manikir'],
    ['brows-and-lashes', 'Брови и ресницы', 'Obrve i trepavice'],
    ['hair', 'Стрижки', 'Šišanje'],
  ]],
  ['cleaning', 'broom', 'Уборка', 'Čišćenje', []],
  ['moving', 'truck', 'Переезды', 'Selidbe', []],
  ['tutors', 'book', 'Репетиторы', 'Časovi', [
    ['serbian-for-adults', 'Сербский язык для взрослых', 'Srpski za odrasle'],
    ['english', 'Английский', 'Engleski'],
  ]],
]; // prettier-ignore

/** id категорий каталога по slug: «электрика» — 101, «люстры и карнизы» — 104. */
export const CATEGORY_IDS: Record<string, number> = Object.fromEntries(
  CATEGORY_TREE.flatMap(([slug, , , , children], index) => [
    [slug, index + 1],
    ...children.map(([child], childIndex) => [child, (index + 1) * 100 + childIndex + 1]),
  ]),
);

export function categoriesFor(locale: string | null): CategoryOut[] {
  const node = (slug: string, icon: string | null, ru: string, sr: string): CategoryOut => ({
    id: CATEGORY_IDS[slug] ?? 0,
    slug,
    name: latin(locale) ? sr : ru,
    icon,
    price_hint: null,
    tags: [],
    children: [],
  });
  return CATEGORY_TREE.map(([slug, icon, ru, sr, children]) => ({
    ...node(slug, icon, ru, sr),
    children: children.map(([child, childRu, childSr]) => node(child, null, childRu, childSr)),
  }));
}

/** Районы Нови-Сада SPEC §4 (DISTRICTS) и муниципалитет «весь город»: id районов — с 11. */
const DISTRICT_NAMES_LATIN: Record<(typeof DISTRICTS)[number], string> = {
  Лиман: 'Liman',
  Грбавица: 'Grbavica',
  Детелинара: 'Detelinara',
  'Нова Детелинара': 'Nova Detelinara',
  Центр: 'Centar',
  Адице: 'Adice',
  Телеп: 'Telep',
  Подбара: 'Podbara',
};

export const DISTRICT_IDS: Record<(typeof DISTRICTS)[number], number> = Object.fromEntries(
  DISTRICTS.map((name, index) => [name, index + 11]),
) as Record<(typeof DISTRICTS)[number], number>;

export function districtsFor(locale: string | null): DistrictOut[] {
  const center = { lat: 45.2671, lon: 19.8335 };
  return [
    { id: 1, slug: 'novi-sad', name: latin(locale) ? 'Novi Sad' : 'Нови-Сад', kind: 'municipality', parent_id: null, center },
    ...DISTRICTS.map((name, index): DistrictOut => ({
      id: index + 11,
      slug: DISTRICT_NAMES_LATIN[name].toLowerCase().replace(' ', '-'),
      name: latin(locale) ? DISTRICT_NAMES_LATIN[name] : name,
      kind: 'neighborhood',
      parent_id: 1,
      center,
    })),
  ];
} // prettier-ignore

/** Нови-Сад для фейка «района по точке»: рамка вокруг города (точка mock-клиента — в Лимане). */
const NOVI_SAD_BOUNDS = { south: 45.15, north: 45.35, west: 19.6, east: 19.95 };

/** GET /geo/districts/locate (S20b «Определить по геолокации») для фейков Vitest и e2e: точка в
 *  Нови-Саде — Лиман, за городом — 404 `outside_city`, как у backend. */
export function locatedDistrict(
  params: URLSearchParams,
  locale: string | null,
): { status: number; body: unknown } {
  const lat = Number(params.get('lat'));
  const lon = Number(params.get('lon'));
  const b = NOVI_SAD_BOUNDS;
  const district = districtsFor(locale).find((item) => item.id === DISTRICT_IDS['Лиман']);
  if (!(lat > b.south && lat < b.north && lon > b.west && lon < b.east) || !district) {
    const code = 'outside_city';
    return { status: 404, body: { type: 'about:blank', title: code, status: 404, code, trace_id: 'test' } };
  }
  return { status: 200, body: district };
} // prettier-ignore

/** Черновик сразу после S32a: «Специалист» без категорий, текста, формата и прайса. */
export const PROFILE_DRAFT: ProfileOut = {
  id: '0199bb00-0000-7000-8000-000000000001',
  kind: 'pro',
  status: 'draft',
  display_name: ME.display_name,
  headline: null,
  about: null,
  languages: [],
  city_id: 1,
  category_ids: [],
  district_ids: [],
  travel_radius_km: null,
  work_modes: [],
  listed_in_catalog: true,
  rejection_reason: null,
  missing: ['category_ids', 'headline', 'work_modes', 'services'],
  completeness: {
    percent: 0,
    hints: [
      ...['category_ids', 'headline', 'area_ids', 'services', 'about'].map((code) => ({
        code,
        count: null,
      })),
      { code: 'portfolio', count: 3 },
      ...['avatar', 'languages'].map((code) => ({ code, count: null })),
    ],
  },
  available_until: null,
  avatar: null,
  published_at: null,
  version: 1,
};

/** Заполненный черновик артбордов S32b–c: электрик в Лимане, Грбавице, Центре и Нова Детелинаре. */
export const PROFILE_FILLED: ProfileOut = {
  ...PROFILE_DRAFT,
  headline: 'Электрик · мелкий ремонт · люстры',
  about: 'Электрик, 12 лет опыта, в Нови-Саде с 2022 года. Свой инструмент и стремянка до 3\u00a0м.',
  languages: ['ru', 'sr'],
  category_ids: [CATEGORY_IDS['electrical'] ?? 0, CATEGORY_IDS['chandeliers'] ?? 0],
  district_ids: [DISTRICT_IDS['Лиман'], DISTRICT_IDS['Грбавица'], DISTRICT_IDS['Центр'], DISTRICT_IDS['Нова Детелинара']],
  travel_radius_km: 5,
  work_modes: ['at_client'],
  missing: [],
  completeness: { percent: 90, hints: [{ code: 'service_descriptions', count: 1 }] },
  version: 4,
}; // prettier-ignore

/** Первая позиция прайса артборда S32c: «Выезд и диагностика» — 2 000 RSD (в пара). */
export const FIRST_SERVICE: ServiceOut = {
  id: '0199bb00-0000-7000-8000-000000000101',
  title: 'Выезд и диагностика',
  description: null,
  category_id: null,
  price_type: 'fixed',
  price_min: { amount: 200_000, currency: 'RSD' },
  price_max: null,
  unit: null,
  duration_min: null,
  position: 0,
  is_active: true,
};

/** Позиция прайса демо-данных: id по номеру, цена в динарах. */
function priceItem(
  n: number,
  title: string,
  category: 'electrical' | 'chandeliers',
  dinars: number,
  extra: Partial<ServiceOut> = {},
): ServiceOut {
  return {
    id: `0199bb00-0000-7000-8000-00000000040${n}`,
    title,
    description: null,
    category_id: CATEGORY_IDS[category] ?? null,
    price_type: 'fixed',
    price_min: { amount: dinars * 100, currency: 'RSD' },
    price_max: null,
    unit: null,
    duration_min: null,
    position: n,
    is_active: true,
    ...extra,
  };
}

/** Работа портфолио демо-данных: id по номеру, файл обработан. Вариантов нет — плитка со
 *  штриховкой и подписью, как на артборде S37. */
function work(n: number, caption: string | null, kind: WorkKind = 'image'): WorkOut {
  const id = `0199dd00-0000-7000-8000-${String(n + 1).padStart(12, '0')}`;
  return {
    id,
    kind,
    caption,
    position: n,
    media: {
      id: `0199ce00-0000-7000-8000-${String(n + 1).padStart(12, '0')}`,
      kind,
      status: 'ready',
      placeholder: null,
      variants: [],
      video_url: kind === 'video' ? `/cdn/${id}/video.mp4` : null,
      duration_ms: kind === 'video' ? 42_000 : null,
    },
    status: 'published',
  };
}

/** Портфолио артборда S37: работы электрика с подписями, вторая — ролик. */
export const PORTFOLIO: WorkOut[] = [
  'Люстра, Лиман', 'Подсветка кухни', 'Щиток', 'Бра в спальне', 'Розетки на кухне', 'Карниз',
  'Люстра, Грбавица', 'Кабель-канал', 'Выключатели', 'Точечные светильники', 'Люстра в прихожей',
  'Замена автомата', 'Подсветка лестницы', 'Розетка в ванной', 'Люстра, Центр', 'Щиток, Телеп',
].map((caption, n) => work(n, caption, n === 1 ? 'video' : 'image')); // prettier-ignore

/** Прайс артборда S35: электрика и люстры с карнизами, одна позиция скрыта. */
export const PRICE_LIST: ServiceOut[] = [
  priceItem(0, 'Выезд и диагностика', 'electrical', 2000, { description: 'Приеду, найду причину, назову цену работы' }),
  priceItem(1, 'Мастер на час', 'electrical', 2000, { price_type: 'hourly', unit: 'hour' }),
  priceItem(2, 'Розетка или выключатель', 'electrical', 1000, { price_type: 'per_unit', unit: 'item' }),
  priceItem(3, 'Замена автомата', 'electrical', 1500, { price_type: 'from' }),
  priceItem(4, 'Установка люстры', 'chandeliers', 2500, {
    price_type: 'from',
    duration_min: 120,
    description: 'Сборка и подвес люстры до 5 рожков, подключение. Крюк или монтажная планка — по месту.',
  }),
  priceItem(5, 'Установка карниза', 'chandeliers', 1500, { price_type: 'from' }),
  priceItem(6, 'Бра или светильник', 'chandeliers', 1200, { is_active: false }),
]; // prettier-ignore

/** Запрос, по которому выдача пуста (как у backend — с подсказками). */
export const NOBODY_QUERY = 'никого';
/** Опечатка, которую выдача «поправляет»: «Возможно, вы имели в виду …». */
export const TYPO_QUERY = 'elektricr';
/** e2e: часы браузера стоят на утре 5 октября, «Свободен сегодня» — до 20:00 по Белграду, как
 *  на макете S05; без этого подпись менялась бы с каждым прогоном и скриншоты расходились. */
export const E2E_NOW = '2026-10-05T08:00:00Z';
export const E2E_AVAILABLE_UNTIL = '2026-10-05T18:00:00Z';
const THREE_HOURS_MS = 3 * 60 * 60 * 1000;

/** Единица цены SPEC §4 по её подписи: «от 2 000 RSD за выезд» — visit, «1 000 RSD/час» — hour. */
const PRICE_UNITS: readonly (readonly [RegExp, string])[] = [
  [/за выезд$/, 'visit'],
  [/за предмет$/, 'item'],
  [/\/час$/, 'hour'],
  [/\/урок$/, 'lesson'],
];

function priceUnitOf(price: string | null): string | null {
  return (price && PRICE_UNITS.find(([pattern]) => pattern.test(price))?.[1]) || null;
}

/** Карточки выдачи S05 из специалистов SPEC §4 (SPECIALISTS): как GET /specialists. У первого —
 *  «сегодня до» и подтверждённый телефон, у последнего (без отзывов) — «Новый специалист». */
export function cardsFor(
  locale: string | null,
  availableUntil = new Date(Date.now() + THREE_HOURS_MS).toISOString(),
): SpecialistCardOut[] {
  return SPECIALISTS.map((fixture, index): SpecialistCardOut => {
    const district = (DISTRICTS as readonly string[]).includes(fixture.district)
      ? (fixture.district as (typeof DISTRICTS)[number])
      : null;
    return {
      profile_id: `0199cc00-0000-7000-8000-${String(index + 1).padStart(12, '0')}`,
      display_name: fixture.name,
      headline: fixture.title,
      kind: fixture.kind ?? 'pro',
      avatar: null,
      district: district
        ? {
            id: DISTRICT_IDS[district],
            name: latin(locale) ? DISTRICT_NAMES_LATIN[district] : district,
          }
        : null,
      distance_m: fixture.distanceKm === null ? null : fixture.distanceKm * 1000,
      languages: fixture.languages,
      category_ids: [],
      price_from: fixture.price ? Number(fixture.price.replace(/\D/g, '')) * 100 : null,
      price_from_unit: priceUnitOf(fixture.price),
      negotiable: false,
      rating: fixture.rating,
      rating_count: fixture.reviews,
      is_new: fixture.reviews < 3,
      available_until: index === 0 ? availableUntil : null,
      badges: index === 0 ? ['phone_verified'] : [],
    };
  });
}

/** Выдача как у backend 4.2: «доступен сегодня» и языки фильтруют, текст NOBODY_QUERY — пусто. */
export function searchFound(
  params: URLSearchParams,
  cards: readonly SpecialistCardOut[],
): SpecialistCardOut[] {
  if (params.get('q') === NOBODY_QUERY) return [];
  const languages = params.getAll('languages');
  return cards.filter(
    (card) =>
      (params.get('available_today') !== 'true' || card.available_until !== null) &&
      (languages.length === 0 || card.languages.some((lang) => languages.includes(lang))),
  );
}

/** Страница GET /specialists: курсор — смещение, опечатка TYPO_QUERY поправлена. */
export function searchPage(
  params: URLSearchParams,
  cards: readonly SpecialistCardOut[],
): SpecialistPageOut {
  const all = searchFound(params, cards);
  const offset = Number(params.get('cursor') ?? 0);
  const end = offset + Number(params.get('limit') ?? 20);
  return {
    items: all.slice(offset, end),
    next_cursor: end < all.length ? String(end) : null,
    category_ids: [],
    did_you_mean: params.get('q') === TYPO_QUERY ? 'Električar' : null,
    hints: all.length === 0 ? ['relax_filters', 'post_job'] : [],
  };
}

/** GET /specialists/by-category: «Мастер на час» с подкатегориями, «Электрика», «Уборка». */
export const CATEGORY_COUNTS: CategoryCountsOut = {
  items: [
    { category_id: CATEGORY_IDS['handyman'] ?? 0, count: 12 },
    { category_id: CATEGORY_IDS['electrical'] ?? 0, count: 5 },
    { category_id: CATEGORY_IDS['cleaning'] ?? 0, count: 3 },
  ],
};

/** Карточка S08–S10 — первый специалист выдачи (Алексей Морозов), как на артбордах. */
export const CARD_PROFILE_ID = '0199cc00-0000-7000-8000-000000000001';

/** Аккаунт специалиста карточки (4.7: «Заблокировать» на S08): у фикстур — тот же id с другим
 *  префиксом, чтобы фейки находили профиль по аккаунту и обратно. */
export const userIdOf = (profileId: string) => `01a0e600${profileId.slice(8)}`;
/** Профиль, который скрыт или снят: BFF отвечает 404. */
export const HIDDEN_PROFILE_ID = '0199cc00-0000-7000-8000-000000000404';

const categoryName = (slug: string, locale: string | null) =>
  categoriesFor(locale)
    .flatMap((node) => [node, ...node.children])
    .find((node) => node.slug === slug)?.name ?? slug;

const districtName = (name: (typeof DISTRICTS)[number], locale: string | null) => ({
  id: DISTRICT_IDS[name],
  name: latin(locale) ? DISTRICT_NAMES_LATIN[name] : name,
});

/** Позиция прайса артборда S09: id по номеру, цена в динарах. */
function cardService(
  n: number,
  title: string,
  category: string,
  dinars: number,
  extra: Partial<CardServiceOut> = {},
): CardServiceOut {
  return {
    id: `0199bb00-0000-7000-8000-00000000050${n}`,
    title,
    description: null,
    category_id: CATEGORY_IDS[category] ?? null,
    price_type: 'fixed',
    price_min: { amount: dinars * 100, currency: 'RSD' },
    price_max: null,
    unit: null,
    duration_min: null,
    ...extra,
  };
}

/** Прайс артборда S09 в порядке позиций: первые три — «Цены» на S08, группы — по первой позиции. */
export const CARD_SERVICES: CardServiceOut[] = [
  cardService(1, 'Выезд и диагностика', 'handyman', 2000, { unit: 'visit', duration_min: 60 }),
  cardService(2, 'Установка люстры', 'chandeliers', 2500, { price_type: 'from', unit: 'item', duration_min: 120 }),
  cardService(3, 'Розетка или выключатель', 'electrical', 1000, { unit: 'item', duration_min: 60 }),
  cardService(4, 'Мастер на час', 'handyman', 2000, { price_type: 'hourly', description: 'Мелкий ремонт' }),
  cardService(5, 'Срочный выезд', 'handyman', 3000, { unit: 'visit', description: 'В течение 2 часов' }),
  cardService(6, 'Точечный светильник', 'chandeliers', 600, { unit: 'item', duration_min: 60 }),
  cardService(7, 'Бра', 'chandeliers', 1200, { unit: 'item', duration_min: 60 }),
  cardService(8, 'Замена автомата в щитке', 'electrical', 1500, { unit: 'item', duration_min: 60 }),
  cardService(9, 'Прокладка кабеля', 'electrical', 400, { price_type: 'from', description: 'Открыто или в штробе' }),
]; // prettier-ignore

/** Работы артбордов S08 и S10: 18 штук, третья — ролик. Вариантов нет — плитки со штриховкой и
 *  подписью, как на артбордах. */
export const CARD_WORKS: CardWorkOut[] = [
  'Люстра, Лиман', 'Щиток', 'Подсветка кухни', 'Люстра на 5 рожков', 'Бра в спальне',
  'Розетки на кухне', 'Карниз', 'Люстра, Грбавица', 'Кабель-канал', 'Выключатели',
  'Точечные светильники', 'Люстра в прихожей', 'Замена автомата', 'Подсветка лестницы',
  'Розетка в ванной', 'Люстра, Центр', 'Щиток, Телеп', 'Подсветка ниши',
].map((caption, n): CardWorkOut => {
  const kind = n === 2 ? 'video' : 'image';
  const id = `0199dd00-0000-7000-8000-${String(n + 101).padStart(12, '0')}`;
  return {
    id,
    kind,
    caption,
    photo: {
      placeholder: null,
      variants: [],
      video_url: kind === 'video' ? `/cdn/${id}/video.mp4` : null,
      duration_ms: kind === 'video' ? 42_000 : null,
    },
  };
}); // prettier-ignore

/** Отзывы артборда S11: услуги — категории каталога на языке запроса; на третий ответил
 *  специалист (7.3), как на артборде. */
export function cardReviewsFor(locale: string | null): CardReviewOut[] {
  const review = (
    n: number,
    author: string,
    rating: number,
    category: string,
    publishedAt: string,
    body: string,
    reply: CardReviewOut['reply'] = null,
  ): CardReviewOut => ({
    id: `0199ee00-0000-7000-8000-00000000000${n}`,
    kind: 'deal',
    author_name: author,
    rating,
    criteria: {},
    body,
    category: { id: CATEGORY_IDS[category] ?? 0, name: categoryName(category, locale) },
    published_at: publishedAt,
    reply,
  });
  return [
    review(1, 'Ирина С.', 5, 'chandeliers', '2026-09-24T15:00:00Z', 'Повесил две люстры и заменил розетку. Пришёл вовремя, всё аккуратно, убрал за собой.'),
    review(2, 'Павел Н.', 5, 'electrical', '2026-08-28T12:00:00Z', 'Быстро нашёл, почему выбивает автомат, и заменил его. Всё объяснил по-русски.'),
    review(3, 'Светлана Б.', 4, 'chandeliers', '2026-08-12T09:00:00Z', 'Люстру повесил хорошо, но опоздал на полчаса — правда, предупредил заранее.', { body: 'Спасибо! Застрял в пробке на мосту — в следующий раз выеду раньше.', at: '2026-08-12T18:00:00Z' }),
  ];
} // prettier-ignore

/** Отзывы вкладки «До платформы · 2» артборда S11 (7.6а): по приглашениям S55 — Ксения Д. и Олег
 *  Р.; вместо услуги — «что делал мастер», текст пишет клиент. */
export function prePlatformReviews(): CardReviewOut[] {
  const review = (
    n: number,
    author: string,
    workTitle: string,
    publishedAt: string,
    body: string,
  ): CardReviewOut => ({
    id: `0199ee00-0000-7000-8000-00000000010${n}`,
    kind: 'pre_platform',
    author_name: author,
    rating: 5,
    criteria: {},
    body,
    category: null,
    work_title: workTitle,
    published_at: publishedAt,
    reply: null,
  });
  return [
    review(1, 'Ксения Д.', 'Проводка в ванной и светильники', '2026-09-30T10:00:00Z', 'Поменял проводку в ванной и повесил светильники. Всё сделал за день, объяснил, что и зачем.'),
    review(2, 'Олег Р.', 'Розетки на кухне', '2026-09-21T16:00:00Z', 'Перенёс розетки на кухне под новый гарнитур, аккуратно и без пыли.'),
  ];
} // prettier-ignore

/** GET /specialists/{id}/reviews артборда S11: 37 отзывов, 35 — на пять звёзд; вкладка «До
 *  платформы» (`kind=pre_platform`, 7.6а) — два отзыва по приглашениям, сводка та же. */
export function cardRatingFor(locale: string | null, kind: string | null = null): CardReviewsOut {
  return {
    summary: {
      rating: 4.9,
      count: 37,
      is_new: false,
      distribution: [0, 0, 1, 1, 35],
      criteria: { quality: 4.9, punctuality: 4.8, communication: 5.0, price: 4.8 },
    },
    items: kind === 'pre_platform' ? prePlatformReviews() : cardReviewsFor(locale),
    next_cursor: null,
    // «До платформы · 2» артборда S11
    pre_platform_count: 2,
  };
}

/** GET /specialists/{id} артборда S08: «Сегодня до» — `availableUntil`, по умолчанию через 3 часа. */
export function specialistCardFor(
  locale: string | null,
  availableUntil = new Date(Date.now() + THREE_HOURS_MS).toISOString(),
): SpecialistProfileOut {
  const areas = (['Лиман', 'Грбавица', 'Центр', 'Нова Детелинара'] as const).map((name) =>
    districtName(name, locale),
  );
  return {
    id: CARD_PROFILE_ID,
    user_id: userIdOf(CARD_PROFILE_ID),
    kind: 'pro',
    display_name: 'Алексей Морозов',
    headline: 'Электрик · мелкий ремонт · люстры',
    about:
      'Электрик, 12 лет опыта, в Нови-Саде с 2022 года. Свой инструмент и стремянка до 3\u00A0м.',
    avatar: null,
    city: { id: 1, name: latin(locale) ? 'Novi Sad' : 'Нови-Сад' },
    district: areas[0] ?? null,
    areas,
    travel_radius_km: null,
    work_modes: ['at_client'],
    languages: ['ru', 'sr'],
    categories: ['electrical', 'chandeliers'].map((slug) => ({
      id: CATEGORY_IDS[slug] ?? 0,
      name: categoryName(slug, locale),
    })),
    available_until: availableUntil,
    is_founding: false,
    rating: 4.9,
    rating_count: 37,
    is_new: false,
    badges: ['phone_verified'],
    response_time_minutes: 15,
    services: CARD_SERVICES.slice(0, 3),
    services_count: CARD_SERVICES.length,
    works: CARD_WORKS.slice(0, 3),
    works_count: CARD_WORKS.length,
    reviews: cardReviewsFor(locale).slice(0, 1),
    published_at: '2026-09-20T10:00:00Z',
  };
}

/** Карточка остальных специалистов выдачи: из карточки S05, без прайса и работ. */
export function plainCardFor(card: SpecialistCardOut): SpecialistProfileOut {
  return {
    id: card.profile_id,
    user_id: userIdOf(card.profile_id),
    kind: card.kind,
    display_name: card.display_name,
    headline: card.headline,
    about: null,
    avatar: null,
    city: { id: 1, name: CITY },
    district: card.district,
    areas: card.district ? [card.district] : [],
    travel_radius_km: null,
    work_modes: [],
    languages: card.languages,
    categories: [],
    available_until: card.available_until,
    is_founding: false,
    rating: card.rating,
    rating_count: card.rating_count,
    is_new: card.is_new,
    badges: card.badges,
    response_time_minutes: null,
    services: [],
    services_count: 0,
    works: [],
    works_count: 0,
    reviews: [],
    published_at: null,
  };
}

/** GET /specialists/{id}/services: группы — категории в порядке первой позиции, на языке запроса. */
export function cardServicesFor(locale: string | null): CardServicesOut {
  const groups = [...new Set(CARD_SERVICES.map((service) => service.category_id))];
  const slugs = Object.fromEntries(Object.entries(CATEGORY_IDS).map(([slug, id]) => [id, slug]));
  return {
    items: CARD_SERVICES,
    categories: groups
      .filter((id): id is number => id !== null)
      .map((id) => ({ id, name: categoryName(slugs[id] ?? '', locale) })),
  };
}

export const CARD_WORKS_OUT: CardWorksOut = { items: CARD_WORKS };

const PROFILE_PATH = /^\/api\/v1\/specialists\/([^/]+)(\/services|\/portfolio|\/reviews)?$/;

const notFound = {
  type: 'about:blank',
  title: 'Not Found',
  status: 404,
  code: 'not_found',
  trace_id: null,
};

/**
 * BFF карточки S08–S10 по фикстурам, как backend: Алексей Морозов — по артбордам, остальные из
 * выдачи — без прайса и работ, HIDDEN_PROFILE_ID и незнакомые — 404. `null` — путь не карточки
 * (`/specialists/count`, `/specialists/by-category` — у выдачи).
 */
export function cardReply(
  pathname: string,
  locale: string | null,
  availableUntil?: string,
  params?: URLSearchParams,
): { status: number; body: unknown } | null {
  const [, id = '', page] = PROFILE_PATH.exec(pathname) ?? [];
  if (!isUuid(id)) return null;
  const search = cardsFor(locale, availableUntil).find((card) => card.profile_id === id);
  const full = id === CARD_PROFILE_ID;
  if (!full && !search) return { status: 404, body: notFound };
  if (page === '/services') {
    return { status: 200, body: full ? cardServicesFor(locale) : { items: [], categories: [] } };
  }
  if (page === '/portfolio') return { status: 200, body: full ? CARD_WORKS_OUT : { items: [] } };
  if (page === '/reviews') {
    const empty: CardReviewsOut = {
      summary: {
        rating: null,
        count: 0,
        is_new: true,
        distribution: [0, 0, 0, 0, 0],
        criteria: {},
      },
      items: [],
      next_cursor: null,
      pre_platform_count: 0,
    };
    return {
      status: 200,
      body: full ? cardRatingFor(locale, params?.get('kind') ?? null) : empty,
    };
  }
  const card = full ? specialistCardFor(locale, availableUntil) : plainCardFor(search!);
  return { status: 200, body: card };
}

/** GET /suggest: категории дерева, у которых слово названия начинается с введённого, — на языке
 *  запроса; как у backend 4.3a — с двух букв, не больше восьми. */
export function suggestFor(q: string, locale: string | null): SuggestOut {
  const text = q.trim().toLowerCase();
  if (text.length < 2) return { items: [] };
  const nodes = categoriesFor(locale).flatMap((node) => [node, ...node.children]);
  const items = nodes
    .filter((node) =>
      node.name
        .toLowerCase()
        .split(/\s+/)
        .some((word) => word.startsWith(text)),
    )
    .slice(0, 8)
    .map((node) => ({
      category_id: node.id,
      name: node.name,
      icon: node.icon,
      term: node.name,
      fuzzy: false,
    }));
  return { items };
}

/** Код приглашения вошедшего в ссылках «Поделиться» (7.4). */
export const SHARE_REF = 'E2Eref01';
export const SHARE_BOT = 'sosed_rs_bot';

/** POST /share (7.4): ссылка `t.me/<bot>?startapp=s_…|j_…` — у вошедшего с кодом `_r` и
 *  карточкой для shareMessage, у гостя — без. Неизвестный тип — 422, не UUID — 404. */
export function shareReply(body: unknown, signedIn: boolean): { status: number; body: unknown } {
  const { entity_type: type, entity_id: id } = (body ?? {}) as Partial<ShareIn>;
  if (type !== 'specialist' && type !== 'job') {
    return { status: 422, body: { status: 422, code: 'validation_error', title: 'Invalid' } };
  }
  if (!id || !isUuid(id)) {
    return { status: 404, body: { status: 404, code: 'not_found', title: 'Not found' } };
  }
  const start = encodeStartParam({
    type,
    id,
    ...(signedIn ? { ref: SHARE_REF } : {}),
  });
  const out: ShareOut = {
    url: `https://t.me/${SHARE_BOT}?startapp=${start}`,
    start_param: start,
    text: type === 'job' ? 'Заявка' : 'Специалист',
    prepared_message_id: signedIn ? `prepared-${type}` : null,
  };
  return { status: 200, body: out };
}
