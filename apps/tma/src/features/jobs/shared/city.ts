// Город ленты S13: свой у вошедшего (home_city_id), иначе — первый открытый (Нови-Сад в пилоте).
// Гость тоже видит ленту (DEVELOPMENT_PLAN 5.3): без /me город — по умолчанию.
import type { CityOut } from '@sosed/api-client';
import { useIdentityGetMe } from '@sosed/api-client';
import { defaultCity, useCities } from '@sosed/hooks';
import { useLocale } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';

export function useFeedCity(): CityOut | null {
  const locale = useLocale();
  const platform = usePlatform();
  const inTelegram = platform.launch.rawInitData !== null;
  const me = useIdentityGetMe({ query: { enabled: inTelegram } });
  const cities = useCities(locale);
  // вошедший ждёт свой город: иначе лента загрузилась бы дважды
  if (!cities.data || (inTelegram && me.isPending)) return null;
  const id = defaultCity(cities.data, me.data?.home_city_id ?? null);
  return cities.data.find((city) => city.id === id) ?? null;
}
