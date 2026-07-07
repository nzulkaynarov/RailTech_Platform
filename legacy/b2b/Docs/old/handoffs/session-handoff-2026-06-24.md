# Session handoff — 2026-06-24 (continue on another machine)

> **Read first when resuming.** Claude auto-memory is machine-local and does NOT travel
> between computers — THIS file (git) is the cross-machine source of truth. Pairs with
> `session-handoff-2026-06-23.md`, ADR `Docs/adr/0003-multi-tenant-admin-planes.md`,
> and the two live remediation plans `Docs/ops/ui-audit-2026-06-24.md` +
> `Docs/ops/catalog-audit-2026-06-24.md`.

## State of `main` (all merged this session)
- **КП cost-engine** (ТНВЭД, Incoterm basis flags, charges, discounts) + **per-Incoterm charge
  templates** (now per-company, managed in the React org-admin Settings → Templates tab).
- **Tenancy foundation** (ADR-0003): 3 admin planes; `WorkspaceRole.OWNER` displays as
  **«Администратор компании»** (code stable); never-orphan invariant; member-role delegation
  (`set_member_workspace_role`).
- **UI audit remediation A–D** (plan: `Docs/ops/ui-audit-2026-06-24.md`): i18n status-code fix,
  auth-link guards, Excel NaN guard, Help mailto, **seller nav dead-ends removed** (Leads/Clients/
  Analytics are IsPlatformAdmin-only), ~1,100 LOC dead code deleted, buyer dashboard enriched,
  **quote-statuses 500 + admin-dashboard 500s fixed**.
- **#14 — seller deal/КП consolidation** (Salesforce/HubSpot model): ONE pipeline (CRM→Deals) → ONE
  deal record (request-detail) → focused КП builder (deal-quote). Removed Sourcing→Requests list +
  DealDetailSheet + SourcingMatchPage.

## Open branch — **`feat/catalog-hardening`** (pushed, needs PR/merge)
Catalog audit (44 findings; multi-agent + browser/API verified). Plan: `Docs/ops/catalog-audit-2026-06-24.md`.
**Fixed + tested so far** (`backend/catalog/tests/test_cost_gate.py`, 231 backend green):
- **C1 (CRITICAL)** supplier cost leak — `offers[]`/`base_price` no longer returned to buyers (gated by
  `owner_company` in `_CostGateMixin`, catalog/serializers.py).
- **H1 (HIGH)** seller can edit own product — `IsProductManagerOrAdmin` now checks `owner_company_id`
  (was the deprecated `manufacturer_id` → 403 on every edit).

**Catalog remaining (wave order in the plan doc):**
1. Security: **C2** SupplierOffer has NO tenant scoping (any seller spoofs/reads competitor offers),
   **C3** bulk import leaves products orphaned (no owner_company), **M6** make `owner_company` read-only
   for non-admin.
2. Broken seller flow: **H3** sellers have NO offer-pricing UI (offers only in admin page); **H2** offer
   create dead-end; **owner can't see own DRAFT product** (get_queryset excludes unpublished).
3. Admin lists: **H4** client-side pagination over a 20-row server slice (catalog/categories/groups/offers).
4. Validation/import: **H5/H6** railway-group rule → 500 not 400; **M3/M4/M5** import price/progress/dry-run.
5. Dead-code: delete the `PublicCatalog.tsx`/`ProductDetailModal.tsx`/`DomainAdaptiveSidebar.tsx` tree
   (mounted nowhere) + dead `catalogApi.importExcel`/`exportTemplate`.
> Catalog needs data to test: run `docker compose exec backend python manage.py seed_demo` (55 products etc.).

## Two business features to build (owner's case, world-standard, NOT yet implemented)
1. **Seller-managed (offline/classic) client** — let a seller create a client (company + contact email,
   no self-registration), parse their заявка, build the КП. Today `CreateDealDialog` takes only a title.
   Standard CRM "rep-created account/contact + quote".
2. **КП email delivery on send** — `QuoteLifecycleService.send_to_client` currently creates only an in-app
   Notification, **no email**. World standard = email the КП PDF (+ link) to the client on send (registered
   buyer → in-app + email; offline client → email only). Infra exists: `notifications.emails.send_templated_email`
   + EmailLog + the F1.6-rendered PDF — just add a КП email template + the send call.

## Multi-tenancy program (ADR-0003) — remaining
- **Step 4 — multi-seller routing (THE confidentiality keystone, still open).** Today `seller_sees_all_deals`
  is see-all; `seller.local` sees an EMPTY Deals pipeline because RFQs aren't routed to a target seller.
  Needs заявка→target-seller(s) FK/M2M + queryset scoping + buyer UI to pick seller(s). Without it
  multi-seller can't be enabled and the seller pipeline stays empty.
- Org-admin: roles + charge-templates done; the configurable RBAC field-group matrix still optional.

## Verify channel + test accounts (machine-local — recreate per machine)
- Browser verification works via **Dockerized Playwright**: `frontend/e2e/run-in-docker.sh <spec> --workers=1`
  (PW_VERSION=v1.61.0-jammy) against `localhost:5173`. node_modules must be present; rebuild frontend with
  `docker compose up -d --build frontend` before E2E (prod nginx image isn't hot-reloaded). I CAN verify
  frontend myself this way — see `feedback_verify_running_app`.
- Local accounts (pw `Test1234!`): `buyer.local@`, `seller.local@` (SUPPLIER OWNER, ACTIVE sub),
  `admin@railtech.uz` (Platform Admin). Set with `manage.py shell` `set_password`. seed_demo users pw `Demo1234!`.
- Bring-up: gitignored `docker-compose.override.yml` (local PG) + `.env`; `make up && make migrate && make seed`
  + `init_superadmin`; `seed_demo` for catalog/deals. `tsc -b` via `docker run --rm -v "$PWD":/work -w /work node:22 bash -lc 'cd frontend && npx tsc -b'`.

## ⚠ Before switching: ensure pushed
`feat/catalog-hardening` is pushed (C1/H1). main is current. Nothing uncommitted. On the new machine:
`git pull origin main` + check out `feat/catalog-hardening` to continue catalog waves.
