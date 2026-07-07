# Session handoff — 2026-06-22 (continue on another machine)

> **Read this first** when resuming. The Claude auto-memory dir is machine-local and does NOT
> travel between computers — THIS file (in git) is the cross-machine source of truth. Pairs with
> `docs/ops/session-handoff-2026-06-19.md` (previous), `docs/ops/roadmap-2026-06-19.md` (the 7-phase
> plan), and the audit at `docs/audits/2026-06-18-platform-audit.md`.

## Where we are
Continuing the platform audit/roadmap. This session delivered AI-import hardening, a buyer bug fix,
production-approximate seed data, **F1.6** (PDF render off the transaction), and **F5.4** (post-sale
statuses → FK lookups). Prod (b2b.railtech.uz) runs on the self-hosted DB-VPS; prod is a clean slate
(1 superadmin, 0 business data) — so the F5.4 data-migrations are structural (no prod data at risk).

## Branch / PR state (verify with `git branch -r` + GitHub)
**Merged to `main`** (PRs merged this session):
- `feat/ai-import-hardening` — resilient AI заявка extractor (per-chunk isolation, stop_reason/refusal/
  truncation handling, `AI_IMPORT_MAX_BYTES`, unit tests).
- `fix/buyer-add-request-item-mpn` — add-request-item was dropping the article (mpn); also `addRequestItem` FE type.
- `feat/pdf-render-on-commit` — **F1.6**: Contract/Invoice/Act/КП PDFs render via Celery `transaction.on_commit`
  (no orphan on rollback, off request thread) + lazy on-demand render fallback in download endpoints.

**Open — pushed, NEEDS PR/merge:**
- `feat/post-sale-status-lookups` — **F5.4 COMPLETE**: post-sale statuses CharField→FK(AbstractLookup) for
  Fulfillment, Contract, Invoice, Act (3 commits, one slice each). Already merged latest `main` into it and
  **resolved the F1.6↔F5.4 conflict** in `crm/services/contracts.py` (combine: FK `status_code`/`_cstatus`
  + on_commit async render) — merge commit pushed, PR is now conflict-free. **Just open/merge the PR.**
- `feat/seed-production-approximate` — production-approximate, rule-compliant `core_seed`: assigns CompanyType
  to seeded companies (was empty → no BUYER/SELLER context), login-able demo users (`SEED_USER_PASSWORD`/
  `Demo1234!`), seller SupplierSubscriptions (ACTIVE; Almalyk MMC = PAST_DUE as an F0.2 gate test). NEEDS PR.

> `gh` CLI is NOT installed in the dev env — open PRs via the GitHub web UI.

## F5.4 — how it was done (pattern for any future status→lookup work)
- New `AbstractLookup` models `ContractStatus/InvoiceStatus/ActStatus/FulfillmentStatus` in `crm/models/lookups.py`,
  seeded in a data migration (mirrors `crm/constants.py` TextChoices — IRON RULE 1).
- CharField→FK via **hand-written data-preserving migrations** (rename aside → add FK → copy by code → drop old);
  the autodetector's `AlterField` would Remove+Add and lose data.
- Contract/Invoice/Act are **pghistory-tracked**: the migration also converts the audit `*event` tables and
  **drops the pgtrigger snapshot triggers before the column swap, recreates them after** (against `status_id`),
  so no event row is written against the changing column. Fulfillment is not tracked (simplest slice — did it first).
- Code: `status_code` model property (null-safe) for comparisons; `_cstatus/_istatus/_astatus` resolvers for
  assignments; queryset filters `status=` → `status__code=`.
- **Serializers keep `status` as the code string (+ `status_name`)** → FRONTEND UNCHANGED. Choices endpoint +
  admin badges + viewset `select_related` updated. Test fixtures seed the new lookups (`--nomigrations` skips the seed).
- Verified: full `crm/` suite **116 passed** with `--create-db`; live `status-choices` returns all four from the tables.

## ⚠ Local-only setup the new machine MUST recreate (both gitignored, do NOT exist after clone)
1. **`docker-compose.override.yml`** — local Postgres 17 (Neon retired). Minimal content:
   ```yaml
   services:
     db:
       image: postgres:17-alpine
       container_name: railtech_db
       environment: {POSTGRES_DB: railtech, POSTGRES_USER: railtech, POSTGRES_PASSWORD: railtech}
       # NO host port mapping — host 5432 is usually taken by a local Postgres.app/Homebrew.
       volumes: [railtech_pgdata:/var/lib/postgresql/data]
       networks: [railtech]
       healthcheck: {test: ["CMD-SHELL","pg_isready -U railtech -d railtech"], interval: 10s, timeout: 5s, retries: 5}
     backend:       {depends_on: {db: {condition: service_healthy}}}
     celery-worker: {depends_on: {db: {condition: service_healthy}}}
     celery-beat:   {depends_on: {db: {condition: service_healthy}}}
   volumes: {railtech_pgdata: {}}
   ```
2. **`.env`** — `cp .env.example .env`, then it already has `DATABASE_URL=postgresql://railtech:railtech@db:5432/railtech?sslmode=disable`.
   Fill `DJANGO_SECRET_KEY`, `SUPERADMIN_PASSWORD`, `ANTHROPIC_API_KEY` (AI import). `SEED_USER_PASSWORD` optional (default `Demo1234!`).
3. After `.env` edits you must recreate containers (Docker reads env at START): `docker compose up -d`.

## Bring-up on the new machine
1. `git pull origin main` (gets F1.6 + everything merged). Check out the two open branches if continuing them.
2. Create the override + `.env` above. `make up && make migrate && make seed` (runs `core_seed`).
   `docker compose exec backend python manage.py init_superadmin`. Optionally `seed_demo` for demo deals/quotes.
3. Re-provision local test accounts (the override `db` is fresh per machine):
   - `buyer.local@railtech.uz` — CLIENT, OWNER, can_buy, KYC L2 — pw `Test1234!`
   - `seller.local@railtech.uz` — SUPPLIER, OWNER, can_sell+can_buy, KYC L2, **ACTIVE PREMIUM SupplierSubscription** — pw `Test1234!`
   - demo users from `core_seed` (e.g. `aziz.kodirov@railtech.uz`) — pw `Demo1234!` (or `SEED_USER_PASSWORD`)
   - `admin@railtech.uz` — superadmin (pw from `.env`). MUST set `username=email` on every user (legacy unique field).
4. Verify: backend tests `docker compose exec -T backend python -m pytest crm/ --create-db` (FULL crm/ suite — a subset
   once hid a regression). `tsc -b` via `docker run --rm -v "$PWD":/work -w /work node:22 bash -lc 'cd frontend && npx tsc -b'`.
   Browser at localhost:5173 after `docker compose up -d --build frontend backend`.
5. Gotchas: after `.py` edits `docker compose restart backend` (Daphne no autoreload). celery-worker/beat are
   SEPARATE images — restart them after task changes. redis-py pinned `<8` (8.0 breaks Channels WS — don't lift).

## Remaining roadmap work (`docs/ops/roadmap-2026-06-19.md`)
Sprint B (integrity) is now **complete** (F1.1/1.2/1.3/1.4/1.5 merged earlier; F1.6 merged; F5.4 PR open). Next:
- **Sprint C — flow/UX (F3.1–F3.6):** consolidate the two seller-КП workspaces; `flowStore` → React Query;
  billing pages redesign to the My-Requests standard; SELLER mid-flow CTA bridges; `isViewerMode` in admin UI.
- **Sprint D — security/API (F2.1–F2.7):** JWT refresh → HttpOnly cookie (access in memory); WS-auth ticket
  instead of token-in-query; `Idempotency-Key` on mutating POSTs; optimistic locking/ETag on Quote/Contract/Invoice;
  URLPathVersioning; API codegen + CI drift-gate (`openapi-typescript` not in package.json yet).
- **Sprint E — catalog (F5.1–F5.3):** `Product.manufacturer`→`brand` dedup (data-migration + ~11 FE files); fix
  single-product form; source-of-truth file for catalog bulk-import.
- **Sprint F — AI features (F6, `docs/ops/ai-features-roadmap-2026-06-18.md`):** all over `sourcing/services_ai.py`.
  Order: #5 bilingual normalize (S) → #1 заявка→catalog matching (M) → #3 КП-vs-заявка diff (M) → #7/#4/#6/#2/#8.
- **Sprint G — structure/tests (F4, F7):** 6 god-components (container/presenter); `onNavigate` prop-drilling →
  context; backend coverage → 50%+; live E2E buyer↔seller run; revive Playwright/golden-path smoke.

## Deferred (owner-confirmed, in memory)
- **Multi-seller routing** — ⚠ latent cross-seller confidentiality leak: today every seller sees every buyer's
  заявка (`seller_sees_all_deals` SELLER branch is see-all, by design for single-seller RailTech). Needs
  заявка→target-seller(s) FK/M2M + buyer UI + queryset scoping. See memory note + roadmap F#1.
- **F0.1** external S3 (R2/B2) for KYC/PDF (local volume now); **payment provider + e-sign** (P0, manual mode).
- **notifications not live** (owner-raised — WS + in-app); UI still raw.
</content>
