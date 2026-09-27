// Sentry фронта: SDK грузится отдельным чанком и только при заданном DSN — бюджет первого экрана.
export async function initSentry(dsn: string | undefined, release: string): Promise<void> {
  if (!dsn) return;
  const Sentry = await import('@sentry/react');
  Sentry.init({ dsn, release, sendDefaultPii: false, tracesSampleRate: 0 });
}
