/**
 * Frontend observability — single activation point for error reporting.
 *
 * Activated 2026-06-03 (commit follows). Sentry init is gated on
 * VITE_SENTRY_DSN — when unset (dev without a project), captureError falls
 * back to console.error so nothing is silently dropped.
 *
 * See Docs/dev/ops/observability.md.
 */

import * as Sentry from '@sentry/react';

const DSN = import.meta.env.VITE_SENTRY_DSN as string | undefined;

let initialised = false;

/** Initialise error reporting once, at app startup. Safe to call when DSN is unset. */
export function initObservability(): void {
  if (initialised || !DSN) return;
  initialised = true;
  Sentry.init({
    dsn: DSN,
    environment: (import.meta.env.VITE_SENTRY_ENVIRONMENT as string | undefined) ?? 'production',
    tracesSampleRate: 0,
  });
}

/** Report a captured error (e.g. from an ErrorBoundary). No-op until Sentry is wired. */
export function captureError(error: unknown, context?: Record<string, unknown>): void {
  if (DSN) {
    Sentry.captureException(error, context ? { extra: context } : undefined);
    return;
  }
  // Dev/no-DSN fallback: keep it visible in the console.
  console.error('[observability] captured error:', error, context ?? '');
}
