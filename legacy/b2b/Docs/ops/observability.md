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

## Frontend (one install away)

`frontend/src/lib/observability.ts` is the single activation point. It is a no-op
today (logs to console) so it ships with zero new dependencies — the prod build
runs `npm ci` against the committed lockfile, and adding a dep requires
regenerating that lockfile on a machine with Node.

**Activate:**
1. `cd frontend && npm i @sentry/react` (commit the updated `package-lock.json`)
2. In `observability.ts`: uncomment the `import * as Sentry` line and the two
   `Sentry.*` blocks.
3. Set `VITE_SENTRY_DSN` (and optionally `VITE_SENTRY_ENVIRONMENT`) in the build
   env — add it to the `.env` block in `deploy-b2b.yml`. Vite bakes
   `VITE_*` vars into the build, so it must be present at build time.

The root `ErrorBoundary` already calls `captureError()`, so once Sentry is wired
every React render crash is reported automatically.
