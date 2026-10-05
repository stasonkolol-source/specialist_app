// «Весь Нови-Сад» над районами S32c и S34 (решение владельца 2026-10-05): специалисту, который
// выезжает в любой район, не нужно прокликивать их все. Отдельного «весь город» в профиле нет:
// включённый переключатель — это все районы города в PUT /me/profile/areas.

/** MAX_AREAS профиля (backend specialists/domain/profile.py): больше районов не сохранить. */
export const MAX_AREAS = 30;

type Districts = readonly { id: number }[];

/** «Весь город» доступен: районы есть и все помещаются в профиль. */
export function wholeCityAvailable(districts: Districts): boolean {
  return districts.length > 0 && districts.length <= MAX_AREAS;
}

/** Отмечены все районы города. */
export function coversCity(districts: Districts, ids: readonly number[]): boolean {
  return districts.length > 0 && districts.every((district) => ids.includes(district.id));
}

/** «Весь город» до того, как его трогали: районов ещё нет, а специалист выезжает — включён;
 *  районы уже есть — включён, только если отмечены все. */
export function wholeCityDefault(
  districts: Districts,
  ids: readonly number[],
  travels: boolean,
): boolean {
  if (!wholeCityAvailable(districts)) return false;
  return ids.length === 0 ? travels : coversCity(districts, ids);
}
