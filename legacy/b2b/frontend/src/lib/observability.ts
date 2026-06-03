/**
 * Frontend observability — single activation point for error reporting.
 *
 * Currently a no-op (logs to console in dev) so it ships with ZERO new
 * dependencies. To turn on Sentry — which would have surfaced the raw-i18n-key,
 * pointer-events, and KYC-button bugs in a dashboard instead of via a user —
 * follow Docs/ops/observability.md:
 *   1. `cd frontend && npm i @sentry/react`
 *   2. uncomment the Sentry block below + the import
 *   3. set VITE_SENTRY_DSN in the deploy build env
 *
 * Kept dependency-free until then because the prod build runs `npm ci` against
 * a committed package-lock; adding the dep requires regenerating the lockfile.
 */

// import * as Sentry from '@sentry/react';

const DSN = import.meta.env.VITE_SENTRY_DSN as string | undefined;

let initialised = false;

/** Initialise error reporting once, at app startup. Safe to call when DSN is unset. */
export function initObservability(): void {
  if (initialised || !DSN) return;
  initialised = true;
  // Sentry.init({
  //   dsn: DSN,
  //   environment: import.meta.env.VITE_SENTRY_ENVIRONMENT ?? 'production',
  //   tracesSampleRate: 0,
  // });
}

/** Report a captured error (e.g. from an ErrorBoundary). No-op until Sentry is wired. */
export function captureError(error: unknown, context?: Record<string, unknown>): void {
  if (DSN) {
    // Sentry.captureException(error, context ? { extra: context } : undefined);
    return;
  }
  // Dev/no-DSN fallback: keep it visible in the console.
  // eslint-disable-next-line no-console
  console.error('[observability] captured error:', error, context ?? '');
}
