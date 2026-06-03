# Stability Program — from firefighting to confidence

**Goal:** stop finding bugs by clicking through prod, and instead let an automated
safety net prove the core flow works on every change — so partners and clients
can be invited without fear of a hidden break.

**The core value we protect:** a buyer sends a single or mass RFQ (КП) without
pain; sellers/manufacturers cut manual work and human error. Everything below is
in service of keeping *that* flow always working.

## The layers of the net (defence in depth)

| Layer | What it catches | Where |
|---|---|---|
| **1. Golden-path E2E (backend)** | Any break in RFQ → bid → КП → contract → invoice → payment → CLOSED_WON | `backend/crm/tests/test_golden_path.py` — runs in CI `backend-test` |
| **2. Service unit/integration tests** | FSM, money math, KYC, quote override, chat, capability gates | `backend/**/tests/` + `test_enterprise_cycle.py` |
| **3. Migration check** | Breakage that only shows on a fresh DB deploy | CI `migration-check` (clean Postgres) |
| **4. Frontend unit tests** | Money drift, error-code rendering, store logic | CI `frontend-test` (vitest) |
| **5. i18n symmetry + used-key scan** | Raw keys on screen, ru/en desync, duplicate shadowing | CI `i18n-symmetry` |
| **6. Type + lint gates** | Type drift, dead code, style | CI `frontend-lint`, `backend-lint` |
| **7. Browser E2E (Playwright)** | The actual buyer/seller clicks end-to-end | `frontend/e2e/` — manual workflow (see below) |
| **8. Observability (Sentry)** | Whatever the net missed — seen in a dashboard, not by a client | backend live behind `SENTRY_DSN`; frontend ready |
| **9. Manual smoke (10 min)** | Final human eyes before a release | `Docs/ops/smoke-checklist.md` |
| **10. Staging buffer** | Catches it on staging, not prod | `Docs/ops/staging.md` (needs DNS) |

If layers 1–6 are green, **the core business flow provably works** — that is the
"I know it's stable" signal. CI gates `docker-build` on all of them, so a red
test blocks the merge that would otherwise reach prod.

## What is DONE (this program)

- ✅ Golden-path E2E test + capability-gate guards (layer 1)
- ✅ Closed the named test debt: `verify_company_kyc`, `bulk_verify_kyc`,
  `upload_kyc_document`, `force_approve_quote`, `reject_quote`, `send_deal_message`
- ✅ `frontend-test` job wired into CI and into the `docker-build` gate
- ✅ Root `ErrorBoundary` mounted in `main.tsx` (no more white-screen crashes)
- ✅ Frontend unit tests for the money helpers and `translateApiError`
- ✅ Backend Sentry wired (inert until `SENTRY_DSN` is set)
- ✅ Hardened i18n scanner (duplicates + used-but-missing keys) — already in CI

## What needs ONE manual step to activate (no code left to write)

- **Frontend Sentry:** `cd frontend && npm i @sentry/react`, uncomment the block
  in `src/lib/observability.ts`, set `VITE_SENTRY_DSN` in the deploy build env.
  (Left out of the lockfile so `npm ci` keeps passing until you install it.)
- **Backend Sentry:** set `SENTRY_DSN` (and optionally `SENTRY_ENVIRONMENT`,
  `SENTRY_TRACES_SAMPLE_RATE`) in the `production` GitHub environment secrets.
- **Browser E2E:** `cd frontend && npm i -D @playwright/test && npx playwright install`,
  then run `.github/workflows/e2e.yml` (manual trigger). See `Docs/ops/e2e.md`.
- **OpenAPI → TS types:** `cd frontend && npm i -D openapi-typescript`, then
  `npm run gen:api-types`. Turns backend field renames into TS compile errors.
- **Staging:** add DNS for `staging.b2b.railtech.uz`, a `staging` GitHub
  environment, and a Caddy block — then `deploy-staging.yml` goes live. See
  `Docs/ops/staging.md`.

## The release ritual (target state)

1. Open a PR → CI runs layers 1–6 automatically. Red = do not merge.
2. Merge to `staging` → auto-deploys to staging → run the 10-min smoke checklist.
3. Promote to `main` → auto-deploys to prod. Sentry watches for anything missed.

Until staging exists, the interim ritual is: **work on a branch, let CI go green,
then merge to `main`** (never push half-built work straight to the prod branch).
