# Session handoff — 2026-06-30 EOD — Move 3 done · Move 4 monetization COMPLETE

> **READ FIRST on the new machine.** `git pull origin main` (everything below is MERGED — no open
> PRs), then read this + `Docs/adr/0006-wedge-loop-and-entitlements.md`. Memory is machine-local;
> this git doc is the cross-machine source of truth. Supersedes the earlier 2026-06-30 handoffs.

## State: all green, deployed
15 PRs merged today (#167–#181). Deploy to b2b.railtech.uz is GREEN (self-hosted runner). **Move 3
(AI moat) DONE. Move 4 (monetization) FUNCTIONALLY COMPLETE end-to-end.** Only polish remains.

## What shipped (merged)
- **Hardening:** post-merge adversarial audit (#167), U2 privesc migration (#168), per-routing
  ownership / hidden competition (#169).
- **Move 3 (AI moat):** pricing-assist (#170), AI draft-КП (#171). (AI #1 catalog-match + #7 preflight
  were already shipped.)
- **Move 4 (monetization):**
  - entitlement layer #172 (`CompanyEntitlement`, `accounts/constants.FeatureKey`, `FREE_FLOOR_FEATURES`,
    `SUBSCRIPTION_BASELINE_FEATURES`, `accounts/services/entitlements.py`).
  - time-to-first-КП metric #173 (`crm/services/metrics.py`, `GET crm/analytics/time-to-first-quote/`).
  - gates: КП **send** #175 (`quote.send`), AI **draft** #177 (`ai.draft` + credits), КП **export** #179
    (`quote.export`, seller cost export only).
  - #179 also **renamed `kp.*→quote.*`** (КП=Quote in English; RFQ=заявка; mig `accounts/0033`).
    Helpers: `quote_send_entitled` / `quote_export_entitled`.
  - FE messages #180 (`apiErrors.{QUOTE_SEND/EXPORT_NOT_ENTITLED, AI_DRAFT_NOT_ENTITLED}` «оформите подписку»).
  - admin control plane #181 (`CompanyEntitlementViewSet` at `/api/v1/admin/entitlements/`,
    OperatorScoped billing.view/manage).
- **Ops:** deploy hotfix #176, handoffs #174 / #178.

## Entitlement model (the contract — read before touching gating)
`has_entitlement(company_id, FeatureKey)`: (1) FREE_FLOOR (ai.match, ai.preflight) → True; (2) an
explicit `CompanyEntitlement` row → ALWAYS wins (ENABLED/DISABLED/DEMO, expiry, credits); (3) else
SUBSCRIPTION_BASELINE (quote.send, quote.export, ai.draft, roles.custom) AND an operational
SupplierSubscription → True. **No lockout** — a subscription grants the baseline; rows are for
promo/demo/disable. `quote_send_entitled`/`quote_export_entitled` = has_entitlement AND not is_demo.
`consume_credit` mirrors the baseline. Migrations: `accounts/0032` (model), `accounts/0033` (rename).

## NEXT — Move 4 POLISH (bounded; each its own PR with tests + `npm run build` + eyes-on)
1. **React-Admin entitlements page** consuming `GET/POST /api/v1/admin/entitlements/` (#181) — list by
   company, grant/DEMO/disable form. Mirror `AdminSubscriptionsPage` / `AdminOperatorRolesPage`. Add a
   PlatformAdminShell nav entry + i18n. (Backend is done.)
2. **Demo-mode watermark** on the КП PDF when `is_demo(seller_company, FeatureKey.QUOTE_SEND)` —
   pass the flag into the `crm/templates/crm/quote_pdf.html` context (render path: `QuoteLifecycleService
   .generate_pdf` / `crm.services.export_quote`).
3. **Single Deal-workspace UX** — merge deal-detail + КП-builder into one seller screen; surface the
   **time-to-first-КП KPI card** there (endpoint #173 exists; FE card intentionally deferred to here).
4. Optional refactor: split `crm/services/quotes.py` (~1.9k lines) into rfq.py / quoting.py.
- Then ADR-0005 phase C (unified buyer+seller shell — security-adjacent: `X-Active-Context` scopes
  backend data) and E (KYC-floor on the BACKEND — today cosmetic only).

## ⚠️ Standing notes
- **CI (GitHub-hosted) was billing-blocked today** ("job not started — payments failed"). Deploy runs
  on a self-hosted runner so it deploys, but the pre-merge green-gate does NOT run. Until billing is
  restored, **verify locally before every merge**: `pytest crm/ accounts/`, `python3
  scripts/check_i18n_symmetry.py`, and **`cd frontend && npm run build`** (the prod `tsc -b` — looser
  `tsc --noEmit` missed a prod error and broke deploy all session, fixed in #176).
- `gh` CLI installed+authed on the 06-30 mac only.

## Verify recipe
`make up && make migrate` (DB through `accounts/0033` + `crm/0052`), restart celery after model changes.
Eyes-on harness: token in-memory + HttpOnly refresh cookie → mint a server-side simplejwt access token
for API checks, or inject the `refresh_token` cookie (path `/api/v1/auth/`, SECURE=False in dev) to
drive a seller session in the browser (context switcher → «Продавец»).
