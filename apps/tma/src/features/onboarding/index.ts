// Публичный API онбординга для точки сборки и маршрутов. Экраны S02a–c — отдельными чанками через
// свои index.ts (маршруты грузят их лениво); S01 — в первом чанке: он рисуется до роутера.
export { LaunchScreen } from './s01-launch/index.ts';
export type { OnboardingSearch } from './shared/paths.ts';
export {
  ONBOARDING_PATHS,
  isOnboardingPath,
  onboardingHref,
  onboardingSearch,
  safeNext,
} from './shared/paths.ts';
