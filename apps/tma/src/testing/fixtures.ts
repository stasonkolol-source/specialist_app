// Демо-данные design/SPEC.md §4 — одни и те же во всех экранах, тестах и скриншотах.
// Ответы существующих эндпоинтов — типами api-client; данные экранов, для которых API ещё нет
// (специалисты, заявки, отклики), — формой из SPEC: шаги этапа 1 заменят их моделями OpenAPI.
import type { CityOut, ClientConfigOut, MeOut, TelegramChannelOut } from '@sosed/api-client';

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
