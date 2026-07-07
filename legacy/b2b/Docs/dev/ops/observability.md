# Observability — Sentry

Error reporting so a break is seen in a dashboard with a stack trace, not
discovered by a frustrated client. Both sides are wired to be **inert until a
DSN is set**, so nothing changes in environments that don't configure it.

## Backend (code is live — just set the secret)

`backend/core/settings.py` initialises `sentry-sdk[django]` at the bottom, only
when `SENTRY_DSN` is non-empty. It captures unhandled Django 500s and Celery
task failures.

**Activate:** in the GitHub `production` environment, add secrets:
- `SENTRY_DSN` — required, from the Sentry project
- `SENTRY_ENVIRONMENT` — optional, defaults to `production`
- `SENTRY_TRACES_SAMPLE_RATE` — optional, defaults to `0.0` (no perf tracing)

Then add `SENTRY_DSN` to the `.env` rendering in `.github/workflows/deploy-b2b.yml`
(the `cat > .env` block) so the container sees it. PII is not sent
(`send_default_pii=False`).

## Frontend (code live — just set the secret)

Activated 2026-06-03. `frontend/src/lib/observability.ts` calls
`Sentry.init({ dsn, environment, tracesSampleRate: 0 })` from `initObservability()`
(invoked once in `main.tsx`) when `VITE_SENTRY_DSN` is non-empty; otherwise
`captureError()` falls back to `console.error` so nothing is silently dropped.
The root `ErrorBoundary` calls `captureError()` on render crashes, so every
React-tree crash is reported automatically.

Vite bakes `VITE_*` vars at build time. The chain is:
1. `deploy-b2b.yml` reads `VITE_SENTRY_DSN` from the `production` GitHub
   environment secret and writes it to `/opt/railtech-b2b/.env`.
2. `docker-compose.prod.yml` reads it from `.env` and passes it as a `build.args`
   value to the `frontend` service.
3. `frontend/Dockerfile` accepts `ARG VITE_SENTRY_DSN` and exports it as
   `ENV VITE_SENTRY_DSN=…` before `npm run build`, so Vite picks it up.

**Default activation:** `VITE_SENTRY_DSN` falls back to `SENTRY_DSN` in the
deploy workflow (single Sentry project on backend + frontend), so just setting
`SENTRY_DSN` (which you already need for the backend) activates the SPA too.
The next deploy will ship a Sentry-aware bundle.

**Override (split projects):** add a separate `VITE_SENTRY_DSN` secret to the
GitHub `production` environment to point the SPA at a different Sentry project
than the backend. Optionally also set `VITE_SENTRY_ENVIRONMENT` (defaults to
`production`).

If the secret is unset, the SPA build stays inert: `VITE_SENTRY_DSN` becomes the
empty string, `initObservability()` returns early, and `captureError()` logs to
the browser console.
