// Экраны S49 поверх приложения — в первом чанке: без сети они должны показаться. S49b (санкция)
// приходит только ответом сервера — его экран и маршрут грузятся своим чанком.
export { RESTRICTED_PATH } from './paths.ts';
export type { RestrictedScreenProps } from './RestrictedScreen.tsx';
export type { RestrictedState } from './store.ts';
export { reportSystemError, useSystemStore } from './store.ts';
export type { SystemScreenProps } from './SystemScreen.tsx';
export { SystemScreen } from './SystemScreen.tsx';
