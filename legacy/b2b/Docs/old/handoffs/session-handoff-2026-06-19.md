# Session handoff — 2026-06-19 (continue on another machine)

> **Read this first** when resuming. The Claude auto-memory dir is machine-local and does NOT travel between computers — THIS file (in git) is the cross-machine source of truth. Pairs with `docs/ops/roadmap-2026-06-19.md` (the full 7-phase plan) and the audit at `docs/audits/2026-06-18-platform-audit.md`.

## Where we are
Working the platform audit end-to-end. **Everything below is already MERGED to `main`** (8 PRs this session — pull `main` and it's all there). Prod (b2b.railtech.uz) runs on the new self-hosted **DB-VPS** (PostgreSQL 17, WireGuard, Neon retired). Prod is a clean slate (1 superadmin, 0 business data).

## Merged this session (all on main)
1. **Platform audit + review corrections** + dead-SupplierBid frontend cleanup.
2. **redis-py `<8` pin** — redis-py 8.0.0 broke Django Channels WS (cancellation→TimeoutError dropped sockets). Prod-verified 0 timeouts. DO NOT lift the cap until channels_redis supports redis-py 8.
3. **DB-VPS docs** (.env.example / README / CLAUDE.md) — off Neon.
4. **F0.2 subscription gate ENFORCED** — `assert_seller_can_operate()` → `SUBSCRIPTION_REQUIRED` on send-КП / generate+sign contract / generate invoice+act. Superuser + `actor=None` automation exempt. `/me.seller_subscription_operational` drives the SubscriptionStatusBanner.
5. **F1.3** `acks_late`+`reject_on_worker_lost` on `auto_invoice_on_closed_won`; **F1.4** celery-worker healthcheck (dev+prod compose).
6. **F0.4** ExcelUpload persistent error + Retry.
7. **Doc numbering race fix** — `DocumentSequence` model + `next_document_number()` (locked per-year counter) replaces `count()+1` for invoice/act/contract (migration crm/0020). + **buyer request-edit atomicity** (select_for_update on the draft quote).
8. **Confirm dialogs** on irreversible actions (send-КП, approve, convert-lead) + **statusColor** fix (was a dead no-op).
9. **CONFIDENTIALITY — context scoping** (owner found live): a dual seller+buyer user in BUYER context saw every buyer's заявка because `is_seller` see-all ignored the frontend context. Fix: SPA sends `X-Active-Context` header (`api/client.ts`); backend `seller_sees_all_deals(user, request)` narrows a seller to its own company in BUYER context — applied to Deal/Quote/QuoteItem/Message/Contract/Invoice/Payment/Act/Fulfillment. Header only NARROWS. Verified live.
10. **Financial integrity** — `@pghistory.track` on Contract/Invoice/Payment/Act (migration crm/0021) + FK `CASCADE→PROTECT` (Contract.deal, Invoice.deal, Payment.invoice, Act.deal) so financial records can't be silently deleted.
11. **Logout / token-revocation** — `POST /api/v1/auth/logout/` blacklists the refresh token (or `{"all":true}` = all devices); frontend `authStore.logout()` calls it best-effort.

Confidentiality verified intact otherwise: pure CLIENT buyers scoped by company_id; margin/cost hidden from buyers (`QuoteItemSerializer.to_representation`); `is_seller` is company-TYPE-checked (no can_sell-default-True leak).

## Remaining audit items — ONLY big/risky left (do ONE AT A TIME, with verification)
Safe high-value backend items are exhausted. These need careful per-item verification (NOT batch):
1. **Multi-seller routing** (owner-confirmed model): a buyer addresses a заявка to specific seller(s) (one/several); a seller sees ONLY заявки addressed to it. Needs Deal/Quote→target-seller(s) FK/M2M + buyer UI to pick sellers + seller queryset scoped by assignment (replaces today's see-all). Today = single seller RailTech sees all by design → `seller_sees_all_deals` SELLER branch must later filter to addressed deals. Latent cross-seller leak until done.
2. **`Product.manufacturer` → `brand`** dedup — deprecated Company-FK vs catalog.Manufacturer; data-migration + ~11 frontend files + drop. Also fixes the broken railway single-product form (F5.1/F5.2).
3. **Post-sale statuses → `AbstractLookup`** (single source) — big data-migration (CharField→FK); careful with lazy-i18n labels. Today: TextChoices constants in `crm/constants.py` mirror the inline model choices (manual byte-for-byte invariant).
4. **Optimistic locking / ETag** (If-Match) on Quote/Contract/Invoice — backend + frontend. (Buyer-edit already got select_for_update; this is the cross-cutting concurrency token.)
5. **WS-auth** (token in query-string → ticket/`Sec-WebSocket-Protocol`) + **JWT → HttpOnly cookie** (access in memory) — touch the whole auth flow.
6. **god-components** §1.4 (AdminUsersPage 696, AdminDataTable 685, AdminKYCPage 679, PlatformAdminDashboard 673, AppShell 622) — container/presenter split; frontend regression risk.
7. **Owner-raised, not yet started:** notifications are NOT active/live (investigate WS + in-app); UI still raw/unchanged. Plus a planned "big bug-fix pass at the end."

**Deliberately NOT doing:** §1.1 remaining `except Exception` — they isolate side-effects (email/WS/notification) WITH logging; narrowing them risks crashing instead of logging. Correct as-is. Also deferred by owner: external S3/media-backup, deploy-on-CI gate.

## How to continue on the other machine
1. `git pull origin main`. `cp .env.example .env` and fill `DJANGO_SECRET_KEY`, `SUPERADMIN_PASSWORD`, `ANTHROPIC_API_KEY` (for AI import). Local DB = the `db` container from `docker-compose.override.yml` (auto-loads with `make up`).
2. `make up && make migrate && make seed` (seed_demo gives demo data). `init_superadmin` for admin.
3. **Re-provision local test accounts** (the local override `db` is fresh per machine — accounts below exist only on the old Mac). Pipe into `docker compose exec -T backend python -`:
   - buyer.local@railtech.uz — CLIENT company, OWNER, can_buy, KYC L2_VERIFIED.
   - seller.local@railtech.uz — SUPPLIER company, OWNER, can_sell+can_buy, **ACTIVE PREMIUM SupplierSubscription** (needed — F0.2 gate enforced).
   - admin@railtech.uz — superadmin.
   - All password `Test1234!`. MUST set `username=email` (legacy unique field). Pattern: `create_user(email,username=email,password)` + `CompanyMember.update_or_create` + `SupplierSubscription(plan=PREMIUM,status=ACTIVE,valid_until=+365d)`.
4. **Verify workflow** (no Node on host, frontend container is a prod build):
   - Backend tests: throwaway PG on the compose net, `sslmode=disable`, `--create-db` (avoids Neon/DB DROP-hang). Run the FULL `crm/` suite before claiming green (a subset hid an F0.2 regression this session).
   - `tsc -b` via `docker run --rm -v $PWD:/work -w /work node:22 bash -c 'npx tsc -b'` from `frontend/`.
   - i18n: `python3 scripts/check_i18n_symmetry.py`.
   - Browser: `docker compose up -d --build frontend backend` then localhost:5173. Playwright harness `frontend/e2e/run-in-docker.sh` currently FAILS — `@playwright/test` missing in mounted node_modules; needs `npm ci` in `frontend/` first.
5. **Gotchas:** after `.py` edits `docker compose restart backend` (Daphne no autoreload). celery-worker/beat are SEPARATE images — rebuild them after dep changes. Any new prod env must be wired into `deploy-b2b.yml`'s heredoc, not just GitHub secrets.

## Prod servers
- App-VPS `176.101.56.141` (deploy dir `/opt/railtech-b2b`, rsync not git). DB-VPS `170.168.6.209` / private `10.0.0.2` (PG17, key `~/.ssh/railtech_dbvps_ed25519`). WireGuard between them.
