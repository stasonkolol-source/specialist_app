// Sentry фронта: SDK грузится отдельным чанком и только при заданном DSN — бюджет первого экрана.
// Настройки и очистка событий — там же, в ленивом чанке (sentry-client.ts).
export async function initSentry(dsn: string | undefined): Promise<void> {
  if (!dsn) return;
  const { startSentry } = await import('./sentry-client.ts');
  startSentry(dsn);
}
