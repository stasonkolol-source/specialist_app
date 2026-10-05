// Подписка на заявки глазами экранов S18 и S19 (DEVELOPMENT_PLAN 5.7): как её назвать, что
// показать строкой и как перевести форму в тело запроса. Названия у подписки нет — она называется
// по первой своей категории, как в карточке бота B1: «Мастер на час», «… и ещё 2»; подпись под
// названием — подкатегории раздела или раздел услуги. Форма S19 открывается и из шторки S14
// («Сохранить как подписку»): фильтры ленты переходят в неё как есть.
import type { CategoryOut, JobAlertCriteriaIn, JobAlertOut, Urgency } from '@sosed/api-client';
import { paraToRsd, rsdToPara } from '@sosed/domain';
import type { IconName } from '@sosed/ui-web';
import { ICON_NAMES } from '@sosed/ui-web';

import type { FeedLanguage, FeedSearch } from './feed.ts';
import { FEED_LANGUAGES, NEAR_KM, urgencies } from './feed.ts';

/** Подкатегорий в подписи раздела: дальше — «…». */
const CAPTION_CHILDREN = 3;
const FALLBACK_ICON: IconName = 'jobs';

export type AlertArea = 'city' | 'radius' | 'districts';

export interface AlertForm {
  categories: number[];
  area: AlertArea;
  km: number;
  point: { lat: number; lon: number } | null;
  /** Районы подписки, созданной не с этой формы: пока «Где» не меняли, они остаются. */
  districts: number[];
  /** «2 000» — как в поле. */
  budget: string;
  delivery: JobAlertOut['delivery'];
  urgencies: Urgency[];
  langs: string[];
}

export interface AlertName {
  title: string;
  caption: string | null;
  icon: IconName;
}

function parentOf(tree: readonly CategoryOut[], id: number): CategoryOut | null {
  return tree.find((section) => section.children.some((child) => child.id === id)) ?? null;
}

function iconOf(node: Pick<CategoryOut, 'icon'> | null): IconName {
  const name = node?.icon;
  return name && (ICON_NAMES as readonly string[]).includes(name)
    ? (name as IconName)
    : FALLBACK_ICON;
}

/** «Мастер на час» и «Мелкий ремонт, Электрика, Сантехника»; услуга — «Люстры» и «Мастер на час». */
export function alertName(
  tree: readonly CategoryOut[],
  categoryIds: readonly number[],
  more: (title: string, count: number) => string,
): AlertName | null {
  const [first, ...rest] = categoryIds;
  if (first === undefined) return null;
  const section = tree.find((node) => node.id === first);
  const parent = section ? null : parentOf(tree, first);
  const node = section ?? parent?.children.find((child) => child.id === first) ?? null;
  if (!node) return null;
  const title = rest.length > 0 ? more(node.name, rest.length) : node.name;
  const children = section?.children ?? [];
  const caption = section
    ? children.length > 0
      ? children
          .slice(0, CAPTION_CHILDREN)
          .map((child) => child.name)
          .join(', ') + (children.length > CAPTION_CHILDREN ? '…' : '')
      : null
    : (parent?.name ?? null);
  return { title, caption, icon: iconOf(section ?? parent) };
}

/** Языки, которые форма умеет показать; остальные коды — как есть. */
export const isFeedLanguage = (code: string): code is FeedLanguage =>
  (FEED_LANGUAGES as readonly string[]).includes(code);

/** Форма из своей подписки (правка S19). */
export function formOf(alert: JobAlertOut): AlertForm {
  const { criteria } = alert;
  const area: AlertArea = criteria.center
    ? 'radius'
    : criteria.district_ids.length > 0
      ? 'districts'
      : 'city';
  return {
    categories: [...criteria.category_ids],
    area,
    km: criteria.radius_km ?? NEAR_KM,
    point: criteria.center ? { lat: criteria.center.lat, lon: criteria.center.lon } : null,
    districts: [...criteria.district_ids],
    // разряды языка ставит поле (moneyInput)
    budget: criteria.min_budget !== null ? String(paraToRsd(criteria.min_budget)) : '',
    delivery: alert.delivery,
    urgencies: [...criteria.urgencies],
    langs: [...criteria.languages],
  };
}

/** Форма новой подписки — из фильтров ленты S14 (или пустая). */
export function formFromFeed(search: FeedSearch): AlertForm {
  const point =
    search.lat !== undefined && search.lon !== undefined
      ? { lat: search.lat, lon: search.lon }
      : null;
  return {
    categories: [...(search.categories ?? [])],
    area: point && search.near !== undefined ? 'radius' : 'city',
    km: search.near ?? NEAR_KM,
    point,
    districts: [],
    budget: search.budget !== undefined ? String(search.budget) : '',
    delivery: 'instant',
    urgencies: urgencies(search) ?? [],
    langs: [...(search.langs ?? [])],
  };
}

/** Фильтры ленты S14 → адрес формы S19: то же, что видно в шторке. */
export function feedPrefill(search: FeedSearch): FeedSearch {
  const { categories, near, lat, lon, when, urgent, budget, langs } = search;
  return Object.fromEntries(
    Object.entries({ categories, near, lat, lon, when, urgent, budget, langs }).filter(
      ([, value]) => value !== undefined,
    ),
  ) as FeedSearch;
}

/** Тело условий подписки; без категорий — null (форма подсветит поле). */
export function criteriaIn(form: AlertForm, cityId: number): JobAlertCriteriaIn | null {
  if (form.categories.length === 0) return null;
  const digits = form.budget.replace(/\D/g, '');
  const radius = form.area === 'radius' && form.point !== null;
  return {
    category_ids: form.categories,
    city_id: cityId,
    district_ids: form.area === 'districts' ? form.districts : [],
    center: radius ? form.point : null,
    radius_km: radius ? form.km : null,
    min_budget: digits ? rsdToPara(Number(digits)) : null,
    urgencies: form.urgencies,
    languages: form.langs,
  };
}

/** «Только срочные» в форме: среди срочностей подписки — одна `asap`. */
export const urgentOnly = (form: Pick<AlertForm, 'urgencies'>) =>
  form.urgencies.length === 1 && form.urgencies[0] === 'asap';
