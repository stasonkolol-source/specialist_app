// Город выдачи: свой у вошедшего (home_city_id), иначе — первый открытый (Нови-Сад в пилоте).
// Гость тоже видит каталог (DEVELOPMENT_PLAN 4.4): без /me город — по умолчанию.
import type { CityOut, SpecialistCardOut } from '@sosed/api-client';
import { getSession, useIdentityGetMe } from '@sosed/api-client';
import { defaultCity, useCities } from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';

export interface CatalogCity {
  city: CityOut | null;
  /** Город ещё решается — ответа городов или /me нет: место под него держит скелетон. */
  pending: boolean;
}

export function useCatalogCityState(): CatalogCity {
  const locale = useLocale();
  // /me — только вошедшему: экраны рисуются после входа (LaunchGate), и гость с отвергнутым
  // initData иначе получал бы 401, повторный вход и город позже на два запроса
  const signedIn = getSession() !== null;
  const me = useIdentityGetMe({ query: { enabled: signedIn } });
  const cities = useCities(locale);
  // вошедший ждёт свой город: иначе выдача загрузилась бы дважды
  if (!cities.data || (signedIn && me.isPending)) {
    return { city: null, pending: cities.isPending || (signedIn && me.isPending) };
  }
  const id = defaultCity(cities.data, me.data?.home_city_id ?? null);
  return { city: cities.data.find((city) => city.id === id) ?? null, pending: false };
}

export function useCatalogCity(): CityOut | null {
  return useCatalogCityState().city;
}

/** «Весь Нови-Сад»: исполнитель выезжает во все районы города (whole_city, QA SMOKE-6). Город —
 *  карточки (S08) или выдачи; не загрузился — «Весь город». */
export function useWholeCity(city: string | null | undefined): string {
  const { t } = useTranslation();
  return city ? t('place.wholeCity', { city }) : t('place.wholeCityPlain');
}

/** Место на карточке выдачи (S03, S05, избранное, шапка S08 до загрузки): основной район, а у
 *  выезжающего во все районы — «Весь Нови-Сад» по городу выдачи (в ней — специалисты города). */
export function useCardArea(
  card: Pick<SpecialistCardOut, 'district' | 'whole_city'>,
): string | null {
  const wholeCity = useWholeCity(useCatalogCity()?.name);
  return card.whole_city ? wholeCity : (card.district?.name ?? null);
}
