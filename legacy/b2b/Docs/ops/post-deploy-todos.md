# Post-deploy TODOs

Open work after the 2026-06-02 production cutover. Not blockers, but tracked so they don't drift out of sight. See also `deploy/RUNBOOK-b2b-vps.md` and `Docs/adr/0002-role-responsibilities.md`.

## Infrastructure / ops

- **Sentry / error aggregation.** Production errors only land in container logs (`docker logs railtech_backend_prod`) and Caddy access logs. Hook up Sentry before real customer onboarding.
- **DMARC record.** DNS has MX/SPF/DKIM (see `Docs/ops/email-setup.md`) but `_dmarc` TXT is missing. Plan: `v=DMARC1; p=none; rua=mailto:postmaster@railtech.uz`. Gmail 2024+ requires DMARC for bulk senders; low-volume transactional mail mostly survives without it, but spam classification will be borderline.
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

## Test debt (informational — already noted in audit 2026-04-27)

- `crm/services/` has no service-level tests for `force_approve_quote`, `send_deal_message`, `QuoteLifecycleService`, Deal FSM transitions — only the smoke `crm/test_enterprise_cycle.py` exercises them implicitly.
- `accounts/services/` lacks unit tests for `verify_company_kyc`, `bulk_verify_kyc`, `upload_kyc_document`.
- No DRF integration tests for new admin endpoints (force-approve quote, force-cancel contract, KYC actions).
- Frontend has zero component tests for `AdminDataTable`, `DetailKPIGrid`, `DealsKanban`, `GenerateQuoteDialog`, `OnboardingChecklist` — only stores are covered.

Coverage target: 50%+ (currently ~30%, enforced by `--cov-fail-under=30` in CI).
