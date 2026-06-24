# Company roles & access matrix — design (2026-06-25)

Replace the home-grown, confusing **Buy/Sell toggles** with a world-standard
**Role + Permission-set** model: a company admin creates named role templates and ticks
permission checkboxes for what a member may do. Grounded in a multi-agent world-practice
study (Salesforce / HubSpot / Stripe / Atlassian / Pipedrive / QuickBooks) + our schema +
ADR-0003. Owner directive: "admin creates role templates + checkboxes; keep it simple;
each company has its own positions & policy."

## Why (the problem)
- The Team screen shows raw **Buy / Sell** switches — no serious B2B SaaS does this; enterprise
  clients expect roles + permissions. Confusing ("ступор"), looks unfinished.
- WorkspaceRole is a fixed global preset list shown as Russian "должности" in the EN UI.
- The term **OWNER** is retired from display (ADR-0003): code stays `OWNER`, shows
  "Company administrator".

## World standard (research, cited in rbac-matrix-research)
Role + Permission-set pattern: admins create **named roles** (job titles) → tick **permission
checkboxes** grouped by category → **assign members to roles**. Ship 3–5 default templates.
**Anti-patterns to avoid:** per-user permission matrices (unmaintainable), >10 junk custom
roles, last-admin lockout, ungated sensitive ops. **Gate the sensitive:** financials/payments,
pricing/margin/cost visibility, discounts, contract signing, data export, user/role management,
catalog publish, destructive deletes.

## Model
- **`CompanyRole`** (per company): `company FK`, `name` (company-defined), `permissions`
  (set of permission codes), `is_system` (the immutable "Company administrator" full-rights role,
  never deletable — never-orphan invariant, ADR-0003), `created_by`. A company has many roles.
- **Permission catalog** = a fixed set of codes in `accounts/constants.py` (the checkboxes),
  grouped (below). The MODEL stays simple: a role just holds a list of these codes.
- **`CompanyMember.role`** → points at a `CompanyRole` (per company). Migration converts the
  current WorkspaceRole presets into seeded `CompanyRole` templates per company + maps members.
- **`can_sell` / `can_buy`** → DERIVED from permissions (sell = has any sales perm; buy = any
  procurement perm); the raw toggles are **removed from the UI** (kept as computed props for the
  existing context-switcher until fully migrated).

## Permission catalog (the checkboxes) — sensitive-first
- **Sales / КП:** `quote.build`, `quote.send`, `quote.view_cost_margin` (see cost/logistics/
  customs/margin/charges), `quote.edit_pricing_discounts`.
- **Procurement / Buyer:** `request.create`, `quote.approve`, `contract.sign`, `payment.record`.
- **Catalog:** `catalog.manage` (products/offers), `catalog.publish`.
- **Company admin:** `team.manage` (invite/roles), `settings.edit`, `charge_templates.manage`.
- **Data:** `data.export`.
(view_cost_margin drives the existing КП cost/margin redaction — crm/serializers.py:90-116.)

## Default role templates (starting points; company can clone/edit/rename)
- **Company administrator** — all permissions (is_system, immutable).
- **Sales manager** — quote.build/send/view_cost_margin/edit_pricing, catalog.manage.
- **Procurement manager** — request.create, quote.approve, contract.sign, payment.record.
- **Finance / Accountant** — payment.record, quote.view_cost_margin, data.export.
- **Viewer** — read-only (no sensitive perms).

## Enforcement (Rule 8 — services layer)
- Add `member_has_permission(user, company_id, perm)` in accounts/services/permissions.py
  (extends `is_member_of(capability=)`, perm = role permission check).
- Re-key existing guards onto permissions: `quote.send` (quotes.py:83), `contract.sign`
  (contracts.py), `payment.record` (billing.py:178), `quote.approve` (views/quotes.py:250),
  `catalog.manage` (core/permissions IsProductManagerOrAdmin / IsOfferSupplierOrAdmin).
- КП cost/margin redaction keyed on `quote.view_cost_margin` (replaces is_seller-only).
- Frontend only HIDES; the service is the source of truth.

## UI — Settings → "Team & Roles" (replaces Buy/Sell)
- **Roles** sub-tab: list company roles; "Add role" → name + grouped permission checkboxes
  (with an "impact preview" before save); presets shown as clone-able templates.
- **Members** sub-tab: each member shows a **Role** dropdown (company's roles); no Buy/Sell.
- "Company administrator" role can't be emptied of its last holder (transfer first).
- All localized via i18n (permission group/labels), no raw DB names.

## Phasing
1. **Backend:** CompanyRole model + permission catalog + migration (WorkspaceRole presets →
   per-company CompanyRoles, map members, seed the 5 templates) + `member_has_permission` +
   re-key guards + redaction. Tests.
2. **Frontend:** Settings "Team & Roles" (role editor + member assignment); remove Buy/Sell.
   Browser-verified.
3. **Cleanup:** retire raw can_sell/can_buy from UI; purge legacy WorkspaceRoles
   (Директор/Бухгалтер/Сотрудник — same class as the retired SystemRoles).

## Non-goals (now)
Role hierarchies / inheritance, ABAC data-scope filters, per-record permissions — explicitly
out (world-standard simple RBAC; can layer later).
