// Публичный API кабинета специалиста для маршрутов: мастер S32a–c, кабинет S33, правка S34.
// Экраны — отдельными чанками через свои index.ts (маршруты грузят их лениво).
export type { BecomeSearch } from './shared/paths.ts';
export { BECOME_PATHS, CABINET_PATHS, becomeSearch } from './shared/paths.ts';
