// Демо-данные design/SPEC.md §4 — одни и те же во всех экранах, тестах и скриншотах.
// Ответы существующих эндпоинтов — типами api-client; данные экранов, для которых API ещё нет
// (специалисты, заявки, отклики), — формой из SPEC: шаги этапа 1 заменят их моделями OpenAPI.
import type {
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
  TelegramChannelOut,
} from '@sosed/api-client';
import { encodeStartParam } from '@sosed/links';

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
  { name: 'Иван Гаврилов', initials: 'ИГ', avatar: 'av3', title: 'Подработка: переезды и сборка', rating: null, reviews: 0, district: 'Лиман', distanceKm: null, price: null, languages: [] },
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
};

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
