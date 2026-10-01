// Публичный API мастера «Стать специалистом» для маршрутов. Экраны S32a–c — отдельными чанками
// через свои index.ts (маршруты грузят их лениво).
export type { BecomeSearch } from './shared/paths.ts';
export { BECOME_PATHS, becomeSearch } from './shared/paths.ts';
