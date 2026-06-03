# Post-deploy TODOs

Open work after the 2026-06-02 production cutover. Not blockers, but tracked so they don't drift out of sight. See also `deploy/RUNBOOK-b2b-vps.md` and `Docs/adr/0002-role-responsibilities.md`.

## Infrastructure / ops

- **Sentry / error aggregation.** ⚙️ Backend is wired (inert until `SENTRY_DSN` set); frontend is one `npm i @sentry/react` away. To activate, follow `Docs/ops/observability.md` — set the `SENTRY_DSN` secret in the `production` environment. Do this before real customer onboarding.
- **DMARC tightening.** ✅ Record now in place (`p=none`, 2026-06-03) with aggregate + forensic reports to `dmarc@railtech.uz`. After a few weeks of clean reports, tighten to `p=quarantine` then `p=reject`. See `Docs/ops/email-setup.md`.
- **MinIO replacement.** Currently gated off (CPU lacks x86_64_v2, see `Docs/ops/vps-cpu-constraints.md`). Files persist on the `backend_media_prod` Docker volume and are served by Django `/media` via Caddy — acceptable for low file volume. Revisit when (a) the VPS gets a modern CPU, or (b) media storage exceeds ~5 GB and a public CDN block on `files.b2b.railtech.uz` becomes worthwhile.
- **Neon backups / PITR / branching policy.** Not yet documented; RTO/RPO undefined. Neon free plan covers ~7 days of history; write down the recovery procedure.
- **Public file CDN.** Currently no separate file host. Future option: `files.b2b.railtech.uz` Caddy block → MinIO public bucket (only after CPU upgrade) or a public host directory.

## UI / product (from ADR-0002)

- `AdminUsersPage`: warn "detach from all companies first" before SystemRole change. Backend already returns `ADMIN_ROLE_REQUIRES_NO_MEMBERSHIPS` — frontend just needs a pre-confirmation hint.
- Owner UI for distributing `can_sell` / `can_buy` across team members. Backend endpoint `update-member-capabilities` exists; frontend page pending.
- WorkspaceRole-aware navigation in `AppShell`. Currently filtered by SystemRole + activeStatus only — should hide Sales Analytics from `LOGIST`, etc.

## Onboarding / KYC

- **"Request to join existing company" flow.** After commit `8e7f046`, `submit-profile` rejects an INN that belongs to a stranger (`COMPANY_INN_TAKEN`). A proper join-request flow (gated by existing OWNER or platform admin approval) is still missing. Until then, the only way to join an existing tenant is through the invite-member flow from a current OWNER.
- **Stricter INN validation.** `submit_company_profile` accepts any non-empty string. Realistic validation (regex per country, checksum for RU/UZ) would prevent typo-based collisions.

## Stability program (2026-06-03) — see `Docs/ops/stability-program.md`

Done: golden-path E2E (`backend/crm/tests/test_golden_path.py`, CI gate);
`frontend-test` CI job; root `ErrorBoundary`; frontend money/apiError unit tests;
backend Sentry (inert); hardened i18n scanner. Closed test debt below.

One manual step each to activate: frontend Sentry (`npm i @sentry/react`),
Playwright E2E (`Docs/ops/e2e.md`), OpenAPI→TS types (`Docs/ops/api-types.md`),
staging env (`Docs/ops/staging.md` — needs DNS + `staging` GitHub environment).

## Test debt (mostly closed 2026-06-03)

- ✅ `accounts/services` — `verify_company_kyc`, `bulk_verify_kyc`,
  `upload_kyc_document` now tested (`accounts/tests/test_kyc_service.py`).
- ✅ `crm/services` — `force_approve_quote`, `reject_quote`, `send_deal_message`
  now tested (`crm/tests/test_quote_services.py`); full FSM + lifecycle covered
  by `test_golden_path.py` + `test_enterprise_cycle.py`.
- ⏳ No DRF integration tests for the admin endpoints (force-approve quote,
  force-cancel contract, KYC actions) — service layer is covered; HTTP layer next.
- ⏳ Frontend component tests for `AdminDataTable`, `DetailKPIGrid`, `DealsKanban`,
  `GenerateQuoteDialog`, `OnboardingChecklist` — prerequisite for the T4
  god-component splits. Pure-function tests (money, apiError) are in place.

Coverage target: 50%+ (currently ~30%, enforced by `--cov-fail-under=30` in CI).
