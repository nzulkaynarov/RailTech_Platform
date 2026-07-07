# Session handoff — 2026-06-30 (unified-nav + wedge strategy + loop integrity)

**Read this first on the new machine** (memory is machine-local; this travels via git). Anti-
hallucination: it states what's in `main` vs open PRs, the do-NOT-rebuild list, and what's next.

`git pull` on `main`, then read this + `Docs/adr/0005-unified-navigation.md` +
`Docs/adr/0006-wedge-loop-and-entitlements.md` (the two canons).

---

## TL;DR — where we are

The owner sharpened the product to a **wedge**: nail ONE loop — **client request → fast quality
КП → signed contract** — speed as the moat, AI as the accelerator; do NOT build ERP/EDO/Marketplace
(parity trap vs 1С/Didox). Everything is being unified to one capability-driven platform (one
account model, subscription expands capabilities) and the request→quote→contract loop is being made
flawless (no dead-ends) + de-serialised (ownership/queue) before AI is layered on and monetised.

Two ADRs are the canon: **ADR-0005** (unified capability-driven navigation) and **ADR-0006** (wedge:
the loop is the product, entitlements wrap it). Both are in the repo.

---

## Branches — state + MERGE ORDER (anti-hallucination)

Merge in this order; each was verified green at push:

1. **`feat/phase-d-u2-delegated-admin`** — U2: gate the company-admin hub by CompanyRole PERMISSION
   (settings.edit / team.manage) instead of WorkspaceRole OWNER (delegated company admin; also fixes
   a dual buyer+seller owner losing the hub in BUYER context). Backend `is_company_owner` →
   `member_has_permission`, team invite/capabilities → team.manage; FE `useHasCompanyPermission` hook
   + SettingsPage + 4 Cabinet panels. 124 accounts tests green. **EYES-ON PENDING** (see Infra).
2. **`feat/move0-loop-integrity`** — ✅ **ALREADY MERGED to main (PR #163)**. (ADR-0006 Move 0.)
3. **`feat/move1-cuts-move2-assignment`** — Move 2 (deal ownership/claimable queue, BE+FE) + Move 1
   safe FE-orphan cuts. **Conflict with main already resolved + pushed** (merged main in, kept both
   Move 0 P0-1 tests §6 + Move 2 assignment tests §7). 237 crm tests green. **merges clean now.**
   FE eyes-on PENDING (see Infra).

Earlier in the session these were already merged to main: charge-cascade + pre-merge audit fixes
(PR #161), roles-and-settings (U1 + U5 + ADR-0005 Phase A/B nav, PR #162), КП approval workflow
(PR #160). Plus everything from prior sessions.

---

## What's in `main` now — DO NOT REBUILD

- **ADR-0005 unified nav (Phase A+B):** `frontend/src/config/navigation.tsx` (`buildNavigation` +
  TENANT_NAV, capability-gated, hide-not-disable) drives AppShell; `MeSerializer.capabilities`
  (`backend/accounts/serializers.py`) is the single capability projection the FE reads
  (`accounts/users/me/`). userStore stores `capabilities`.
- **U1:** default CompanyRoles seeded on company creation + role assigned on invite + backfill mig
  accounts 0030 (`accounts/services/roles.py ensure_default_company_roles` / `default_company_role_for`).
- **U5:** min/target margin editable in «Дефолты КП» (CompanyDefaultsSettings).
- **ADR-0006 Move 0 (loop integrity):** swallowed FSM errors fixed in `crm/services/quotes.py`
  send_to_client/approve_quote/reject_quote (capture+raise; send auto-advances RFQ_OPEN→CALCULATING
  →QUOTE_SENT); seller re-match permission (was IsPlatformAdmin→403); contract notifications to both
  sides + the КП author (prepared_by, not NULL deal.manager) on PENDING_CLIENT + SIGNED; auto
  CONTRACT_SIGNED→CLOSED_WON on both-signed (`crm/services/contracts.py _finalize_if_signed`);
  expire_stale_quotes notifies prepared_by.
- Charge cascade (sort_order + sequential calc), КП unit-economics + guardrails, approval workflow,
  per-company doc numbering, DocumentProfile, access matrix (G4), operator sub-roles (G1) + break-
  glass (G2) — all in main from this + prior sessions.

---

## Roadmap status (ADR-0006 wedge + ADR-0005 nav)

- **Move 0 — loop integrity:** ✅ merged.
- **Move 1 — cut ballast:** SAFE FE orphans (Leads/Analytics/Clients pages) ✅ done on branch #3.
  **DEFERRED (do as careful per-feature migration passes — woven across ~20 files + drop tables/FK):**
  Fulfillment model, Payment-ledger + Act (EDO-dupe), the Lead model + leads/analytics BE endpoints.
- **Move 2 — deal ownership / claimable work-queue:** ✅ done on branch #3 (BE tested 237 green; FE
  «Взять в работу» button compiles). `Deal.assigned_to`+`assigned_at` (mig crm 0051);
  `crm/services/assignment.py` (claim/release/assign, claim-lock, routing-bound); notification
  fan-out fixed (routed sellers only + deep-link). World-standard claimable queue, NOT a literal
  5-person round-robin (owner's case = illustration).
- **Move 3 — AI moat (NEXT, highest leverage):** wire `backend/sourcing/services_ai.py
  match_lines_to_catalog` (built but UNWIRED — only called in tests) into the intake→КП flow; intake
  completeness/exception + confidence; pricing-assist from SupplierOffer; draft-КП. THIS is the moat
  (speed via AI), not Kanban.
- **Move 4 — single Deal-workspace UX + time-to-first-КП metric + entitlement monetization.**
- **ADR-0005 remaining phases:** C (merge buyer+seller into ONE shell — note: the context switcher
  drives `X-Active-Context` which scopes backend data, so this needs a page-derived-context redesign,
  NOT a pure FE change — security-adjacent), D (U2 done on branch #3; U4 = split «Мой профиль»=user
  vs «Компания»=org hub + DocumentProfile inherits requisites from Company → kill duplicate ИНН/logo),
  E (KYC-floor on the BACKEND — today KYC gates NOTHING in business logic, «after KYC=minimum» is
  FE-cosmetic only; Layer-0 gap; also enforce the dead `catalog.*` perms), F (Клиенты-REST
  ContactViewSet, unified document direction-view, global +Создать).

**Entitlement model (ADR-0006 §3, for the paid layer):** one `company_entitlements (feature_key,
access, limit, credits, expires_at)` table + `has_entitlement(company, feature_key)` helper on
`accounts/services/permissions.py`; app checks feature_key NOT plan name; demo-mode = an entitlement
state (КП build free + watermark PDF, gate send/export; AI capped credits); feature-flags separate
from entitlements. Free floor for role-policy (OWNER+basic roles free; sell custom roles) + AI (the
permission engine КП reads stays free — else circular). Split `crm/services/quotes.py` (~1.9k lines,
free RFQ + paid КП mixed) into rfq.py/quoting.py BEFORE gating КП as an entitlement.

---

## Feedback lessons locked this session (apply them)

- **EXAMPLES ≠ SPECS:** the owner's concrete cases (e.g. «5 сотрудников») are illustrations of a
  problem class, not literal requirements — generalize to the world-standard, scale-agnostic pattern.
- **FAVOR WORLD STANDARD:** decide for international best practice over the owner's literal wish; advise
  it, don't be a yes-man (pushed back on inbox/outbox primary nav → object-based; on "unify=fewer
  tests" → "unify cuts DUPLICATE tests but shared core = shared blast radius → reinvest in
  seam/contract tests + visual-regression + feature flags").
- **ADVERSARIAL / EYES-ON:** verify in the running app, attack your own merged code; the audits this
  session found REAL bugs in code (swallowed FSM errors, re-match 403, charge cost leak).

---

## ⚠️ Infra blockers + EYES-ON debt (carry over)

- **Docker Hub registry was timing out** (`auth.docker.io` token fetch) on this machine, and
  `nginx:stable-alpine` (the frontend final-stage base) is NOT cached → **`docker compose build
  frontend` / container recreate fails**. WORKAROUND used: `docker build --target builder` (node
  stage, cached) verifies tsc+vite compile WITHOUT the nginx pull. On the new machine, if the
  registry is reachable, `docker compose up -d --build --force-recreate frontend` should work.
- **EYES-ON PENDING (verify in the running app on the new machine):** (1) U2 — a delegated
  «Администратор компании» (non-OWNER) sees + uses the company-admin hub; (2) Move 2 — the «Взять в
  работу» claim button + owner badge on the DealsKanban card, and the routed-only RFQ notification;
  (3) Move 1 — the removed pages don't break nav. All compile (tsc builder-stage); none eyes-on'd.

---

## Local re-provisioning on the new machine (memory is machine-local)

- `docker compose up -d --build` + `make migrate` + `make seed`; `init_superadmin`.
- `docker-compose.override.yml` (gitignored) provides the local Postgres `db` service;
  `.env` → `DATABASE_URL=postgresql://railtech:railtech@db:5432/railtech?sslmode=disable`.
- Test accounts are machine-local — re-provision (buyer.local / seller.local(+sub) / admin
  @railtech.uz). Browser eyes-on harness (Claude-in-Chrome) needs a logged-in session.
- Tests: `docker compose exec -T backend pytest crm/ accounts/ -q -p no:cacheprovider`; i18n
  `python3 scripts/check_i18n_symmetry.py`; FE compile `cd frontend && docker build --target builder .`.

---

## Key file anchors

- Nav: `frontend/src/config/navigation.tsx`, `frontend/src/layouts/AppShell.tsx`,
  `frontend/src/App.tsx` (route guards + page union).
- Capabilities/entitlements: `backend/accounts/serializers.py` (MeSerializer.capabilities),
  `backend/accounts/services/permissions.py` (member_has_permission — add has_entitlement here).
- Loop: `backend/crm/services/{deals,quotes,contracts,assignment}.py`, `backend/crm/tasks.py`,
  `backend/crm/views/{deals,quotes}.py`, `backend/notifications/signals.py`.
- AI (unwired moat): `backend/sourcing/services_ai.py` (match_lines_to_catalog), `sourcing/services.py`.
- Canons: `Docs/adr/0005-unified-navigation.md`, `Docs/adr/0006-wedge-loop-and-entitlements.md`.
