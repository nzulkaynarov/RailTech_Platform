# Session handoff — 2026-06-28 — Operator plane G1 done; G2 (break-glass) next

> **READ FIRST on the new machine.** Cross-machine source of truth (Claude Code memory is
> machine-local; this travels via `git pull`). Continues `session-handoff-2026-06-26-admin-planes.md`.
> Canon = `Docs/adr/0004-three-admin-planes-core.md`.

## 0. FIRST ACTION
1. `git pull origin main`. Check whether **PR for `feat/operator-plane-g1-g2` (G1) is merged**
   (`git log --oneline origin/main | grep "operator plane G1"`). If not, it's pushed and awaiting
   the owner: https://github.com/nzulkaynarov/RailTech_SaaS_B2B/pull/new/feat/operator-plane-g1-g2
2. `make up && make migrate` (applies `accounts/0026`+`0027`). Re-provision local accounts (§9 of
   the 06-26 handoff). Then continue at **§3 (NEXT = G2 break-glass)**.

## 1. What shipped this session — ADR-0004 **G1: granular operator sub-roles** (commit `e8f7f77`, branch `feat/operator-plane-g1-g2`)
The Platform Operator was a monolith (one all-powerful `SystemRole.ADMIN`). G1 splits it into
least-privilege sub-roles — the operator-plane analogue of the tenant G4 access matrix. **VERIFIED:
496 backend tests (470+26), tsc green, i18n symmetric, eyes-on in RU, 3-lens adversarial review with
all findings fixed+tested.** Prod's single `admin@railtech.uz` is backfilled to SUPER_OPERATOR → **zero
behaviour change** for it; granular restriction only applies once a narrower role is assigned.

**Backend (do NOT rebuild — grep first):**
- `accounts/models/operators.py` **OperatorRole** (platform-scoped: stable `code`, `permissions` JSON,
  `is_system`, `has_perm`). `CustomUser.operator_role` FK (`accounts/models/users.py`).
- `accounts/constants.py`: `OperatorRoleCode` (SUPPORT/KYC_OFFICER/BILLING_OPERATOR/MODERATOR/
  SUPER_OPERATOR), `OperatorPermission` (12 codes, 6 groups), `OPERATOR_PERMISSION_GROUPS`,
  `OPERATOR_ROLE_TEMPLATES`.
- `accounts/services/permissions.py` **`operator_has_permission(user, perm)`** — superuser→all;
  not `is_platform_admin`→none; `operator_role is None`→all (backward-compat); else role's set.
- `core/permissions.py` **`OperatorScoped`** DRF class — per-action via `view.operator_permissions`
  (dict) or `view.operator_permission` (default); **unmapped action → coarse platform-admin gate**
  (safe-by-default, never a silent lock-out).
- Re-keyed sensitive admin **mutations** onto sub-capabilities (reads/dashboards stay coarse):
  CompanyViewSet verify_kyc/bulk → `kyc.verify`, create/update/destroy → `companies.manage`;
  SupplierSubscriptionViewSet writes → `billing.manage`, reads → `billing.view`;
  CompanyRoleApplication approve/reject/destroy → `moderation.role_applications`;
  Deal.force_change_stage / Quote.force_approve / Contract.cancel+force_cancel →
  `moderation.force_override`; UserViewSet writes → `users.manage`, reads → `users.view`;
  SystemRoleViewSet → `users.view`.
- `accounts/services/operators.py` — operator-role CRUD + `assign_operator_role` (Rule 8), with
  **operator never-orphan**: the last `operators.manage` holder cannot be demoted/deactivated/un-ADMINed.
  Guarded across `assign_operator_role`, `change_user_role` (ADMIN→USER) and `toggle_user_active`
  (`is_last_operator_manager`). Target row `select_for_update`-locked against the demotion race.
- API: `/api/v1/admin/operator-roles/` (CRUD + `assign`), `/api/v1/admin/operator-permissions/`
  (`accounts/views/operators.py`, wired in `core/urls.py`). Migrations `accounts/0026`+`0027`.

**Frontend:** `pages/AdminOperatorRolesPage.tsx` (mirrors the G4 RoleEditorSheet — table + grouped
permission-checkbox editor; `is_system` read-only) + operator-role selector on AdminUsersPage detail;
`adminApi.operatorRolesApi` + `useAdmin` hooks; route `admin-operator-roles` wired in App.tsx (5 spots)
+ PlatformAdminShell nav (ShieldCheck). i18n under `operatorRoles.*` / `operatorPermissions.*`.

**Preset → capability matrix (the security contract; pinned in `accounts/tests/test_operator_roles.py`):**
SUPPORT = view-only (users/companies/kyc/billing `.view`). KYC_OFFICER = + `kyc.verify`.
BILLING_OPERATOR = + `billing.manage`. MODERATOR = + `moderation.role_applications` + `moderation.force_override`.
SUPER_OPERATOR = all (immutable, never-orphan floor).

## 2. ⛔ Do NOT rebuild (exist): OperatorRole / OperatorPermission / operator_has_permission /
OperatorScoped / operators.py service+views / migrations 0026-0027 / AdminOperatorRolesPage / the
re-keyed `operator_permissions` maps. **Grep first.**

## 3. NEXT WORK — ADR-0004 **G2: audited break-glass** (the other half of the operator plane)
ADR-0004 Decision 5.2: a **detective** control layered on the existing `ActivityLog` (NOT a hard
read-gate — that would break the admin dashboard). "Operator access to a tenant's private trade data
records who/when/why/which entity (reason required, time-boxed)."
- **`ActivityLog`** (`crm/models/deals.py`) ALREADY has `reason` (TextField), `entity_type`,
  `entity_id`, `before_data`, `after_data`. `core/audit.py` `log_admin_action(...)` is the writer.
  **Gap:** add a `expires_at` (nullable) for "time-boxed"; the rest is reusable.
- **Gap A (cheap, do first):** `force_approve_quote` (`crm/services/quotes.py:777`) and
  `force_cancel_contract` (`crm/services/contracts.py`) use RAW `ActivityLog.objects.create()` —
  they do NOT set `reason`/`entity_type`/`entity_id` (only embed reason in `detail`). Route them
  through `log_admin_action` (like `transition_deal_stage` already does) so 3/3 force-overrides are
  structurally audited with the reason field.
- **Gap B:** a break-glass "open" path — when an operator views a tenant's private deal/quote/contract
  detail for an override, record an entity-scoped, reason-required, time-boxed `ActivityLog`
  (action `BREAK_GLASS`, `level=WARNING`, `expires_at = now + window`). Endpoint
  `POST /api/v1/admin/break-glass/` + the force-overrides accept/require it.
- **Gap C:** an **admin audit view** — `GET` listing break-glass + `[FORCE_ADMIN]` entries
  (filter by operator/entity/date; the existing `admin/activity/` + `adminApi.getActivity()` is the
  base) + a React «Журнал доступа / Break-glass» page.
- Gate the break-glass endpoint with `moderation.force_override` (the G1 capability).
**Suggested:** one Workflow, phase Backend (expires_at + route the 2 raw creates through audit +
break-glass open/check + endpoint + tests) → phase Frontend (reason prompt before opening tenant
trade detail + audit page, return i18nKeys). Then VERIFY yourself + eyes-on + adversarial pass.

## 4. After G2: G5 (designated primary per company) · G6 (Engineer/Unfold access logging).

## 5. Working rhythm + verify recipe (unchanged from 06-26 §7/§8)
Multi-agent Workflow per phase; agents return `i18nKeys` (you merge into ru/en.json — never let
agents write locales, race). VERIFY YOURSELF — agents over-report: `makemigrations --check`;
`docker compose exec -T backend python -m pytest -q -p no:cacheprovider --reuse-db`; tsc in node:22
(`npm ci` first); `python3 scripts/check_i18n_symmetry.py`; eyes-on in RU (`localStorage.i18nextLng='ru'`).
**Daphne/Celery don't auto-reload** — restart after model/.py changes. `--nomigrations` is in pyproject
addopts, so test fixtures seed lookups from constants (the seed migrations don't run under pytest).

## 6. Discovered, out-of-scope (note for the owner): the **login form** shows a raw i18n key
`auth.passwordLabel` as a red validation error (the API login works fine — `auth/token/` 200). A
pre-existing auth-form Zod/i18n bug, unrelated to the operator plane. Worth a small fix pass.
