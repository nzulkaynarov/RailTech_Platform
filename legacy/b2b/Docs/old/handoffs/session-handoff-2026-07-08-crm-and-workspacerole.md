# Session Handoff — 2026-07-08 — CRM counterparty layer + WorkspaceRole deprecation (Phase E U3)

**Base:** main @ `63e842b` (after PR #249). Working tree clean. Cross-machine handoff (this machine's
`~/.claude` memory does NOT travel — this doc is the source of truth on the other machine).

## ⚠️ URGENT — prod deploy is BLOCKED (infra, not code)

The Deploy workflow for **#248 and #249 both FAILED** at the `Pre-deploy DB backup (gate)` step
(INF-04 pg_dump gate, added in #239). Identical root cause on both:

```
pg_dump: error: connection to server at "10.0.0.2", port 5432 failed:
FATAL: remaining connection slots are reserved for roles with the SUPERUSER attribute
```

- **The DB-VPS (10.0.0.2, PG17) has exhausted its non-superuser connection slots** (`max_connections`
  reached). The backup step can't connect, so the hard gate (`set -euo pipefail`) refuses to deploy.
  This is the INF-04 safety behavior working AS DESIGNED — it will not deploy without a fresh backup.
- **Consequence:** #248 (Phase E U3 Step 1) and #249 (Step 2) are MERGED to main but **NOT deployed**.
  Both are code-only (auth-gate swaps, NO migrations), so prod simply runs the previous auth logic —
  no breakage, just not-yet-live.
- **Prod currently runs main @ #247** (last successful deploy, 2026-07-07 20:52 — the CRM layer A–E).
- **Owner action needed:** free the DB-VPS connection slots / investigate the pool. Likely a
  dj-db-conn-pool saturation (app + celery-worker + celery-worker-ai each hold a pool) or a leak, or
  `max_connections` set too low for the current worker count. Until resolved, **every deploy will keep
  failing on the backup gate** (and the live app may intermittently fail to acquire connections).
  Check: `SELECT count(*), usename FROM pg_stat_activity GROUP BY usename;` on the DB-VPS; consider a
  `docker compose restart backend celery-worker celery-worker-ai` to reset the pools, and/or raise
  `max_connections`.

## What shipped this session (all MERGED to main)

Pursued spec-remaining-2026-07-07 items 3–5 (CRM layer, AI calibration, WorkspaceRole deprecation).

| PR | Item | In main | Deployed |
|---|---|---|---|
| #240 | ADR-0006 amendment (Leads=KEEP) + cut orphan CRMAnalyticsView | ✅ | ✅ |
| #241 | AI match-outcome telemetry (`AIMatchOutcome` + `manage.py ai_match_report`) | ✅ | ✅ |
| #242–#245 | CRM layer Phases A–D (see below) | ✅ | ✅ (via #247) |
| #246 | Phase E U3 Step 0 — remove dead WorkspaceRole approval-FSM + inventory | ✅ | ✅ (via #247) |
| #247 | **Consolidation** — landed #242–#246 into main (stacked-merge fix, see gotcha) | ✅ | ✅ |
| #248 | Phase E U3 Step 1 — 3 view gates → member_has_permission | ✅ | ❌ blocked |
| #249 | Phase E U3 Step 2 — submit_for_review → quote.build | ✅ | ❌ blocked |

### CRM counterparty layer (Phases A–D) — the "книга контрагентов с историей"
- **A (#242):** ActivityLog gains nullable `company`/`contact`/`deal` FKs; 17 producers enriched; 3
  new КП events (sent/accepted/rejected); `GET /api/v1/crm/timeline/`; «История» card on the request page.
- **B (#243):** `CounterpartyRelationship` (crm/0056) — edge with direction CLIENT/SUPPLIER, stage,
  rollups (deals/won/gmv). API `crm/relationships/` + `accounts/contacts/`; «Клиенты»/«Поставщики»
  page (`CounterpartiesPage`); edges auto-created on routing / offline-client / offline-deal.
- **C (#244):** `merge_companies` (fold an OFFLINE duplicate by INN into the survivor, dedupe edges) +
  `auto_populate_history` on KYC verify; admin merge endpoint + `MergeDuplicatesDialog`.
- **D (#245):** CB-invite — `ClientInvite` (accounts/0034) + `send_client_invite` + accept in
  `submit_company_profile` (claim existing offline company, no duplicate); `invite_client` email;
  `POST accounts/contacts/{id}/invite/`; register `?invite=` threading; «Пригласить» button.

### Migration heads in main: `crm/0056`, `accounts/0034`, `sourcing/0007`.

## Phase E U3 — WorkspaceRole deprecation (the remaining track)

Full plan: **`Docs/dev/specs/spec-phase-e-u3-workspacerole-deprecation-2026-07-07.md`**. Key discovery
from the inventory: the КП approval chain is ALREADY permission-native (`crm/services/approvals.py`
on `member_has_permission`); the legacy WorkspaceRole FSM in `quotes.py` was dead code.

- **Step 0 (#246, done):** removed dead `confirm_trade_review`/`director_approve`/`send_back` +
  `_ROLE_QUEUE_STATUSES`.
- **Step 1 (#248, done):** `company.py` `_assert_owner_or_admin`→`settings.edit`,
  `set_member_role`→`team.manage`; `crm/views/quotes.py` ChargeTemplate→`charge_templates.manage`.
  All pure widening (legacy fallback keeps company_role-less OWNER). Adversarially verified SAFE.
  Tests: `accounts/tests/test_workspace_role_deprecation_step1.py`.
- **Step 2 (#249, done):** `submit_for_review` SALES_MANAGER→`member_has_permission(quote.build)`.
  quote.build ∈ _SELL_PERMS so the fallback grants any company_role-less can_sell member (superset of
  old gate; data-check 0/13 lose access). Claim path unchanged. Adversarially verified SAFE. Tests
  updated in `test_quote_approval_chain.py`.
- **⏭ Steps 3+4 (NOT started — HIGHEST RISK, do together, eyes-on required):**
  1. **Never-orphan invariant** on `is_system` instead of WorkspaceRole OWNER — `accounts/services/
     members.py:145/158/190-191/216`. Unify with `roles.py:_is_sole_active_system_admin`.
  2. **Coverage data-migration** — the default «Менеджер по продажам» template lacks `quote.review`/
     `quote.approve_final`, so migrated **ВЭД (FOREIGN_TRADE_SPECIALIST)** members would lose
     trade-review. The migration MUST explicitly grant `quote.review` to ВЭД-derived members and
     `quote.approve_final` to DIRECTOR-derived members. **Cross-check `accounts/migrations/
     0031_demote_overgranted_company_admins.py` first.**
  3. **`can_send_quote_to_client`** — deferred from Step 1 (the only NARROWING site:
     `has_explicit_company_role_perm(quote.send)` has NO legacy fallback, so a company_role-less
     seller would lose send). Move it here, AFTER the coverage migration guarantees quote.send.
  4. **`_fallback_head`** (`crm/services/approvals.py:39`) off `role__code=OWNER` → is_system holder.
  5. Then derivation cleanup: `permissions.py` OWNER fallback + routed-company tie-break (lines 67,
     398-403). After that, `CompanyMember.role` (WorkspaceRole) is label-only.
  - Acceptance: no `has_workspace_role`/`WorkspaceRoleCode` in business authz; existing tenants keep
    access (before/after data test, esp. ВЭД); full approval-FSM suite green + eyes-on
    заявка→КП→контракт on a migrated tenant.

## Other remaining backlog (from spec-remaining-2026-07-07)
- **INF-05/09** (pip-tools lock + psycopg2 source) and **INF-01** (Caddy edge rate-limit) — **owned by
  ANOTHER agent, do not claim.** Confirmed still open.
- **AI threshold calibration** — telemetry shipped (#241); only the tuning of `AI_DRAFT_MATCH_CONFIDENCE`
  remains, and it needs accumulated real traffic. Run `manage.py ai_match_report` once data exists.
- **Leads inbox (frontend)** — ADR-0006 Leads=KEEP implies a leads inbox page + wiring
  `convert_lead_to_deal` into the CRM relationship layer. Not started. ~1–1.5d, product value.
- **Owner-blocked / governance:** GitHub Actions **billing** still broken (CI gates + nightly e2e down
  since ~2026-07-06 — all PRs #231–#249 validated LOCALLY and merged without CI); INF-12 required-check;
  F0.3 (gate deploy on green CI); P0 Click/Payme + E-IMZO + ZRU-547; staging (deferred).

## Gotchas learned this session (avoid repeating)
- **Stacked-PR merge trap:** if a PR's `base` is a feature branch (not main), merging it lands the work
  in that branch, NOT main — GitHub still marks it MERGED. #242–#246 did this and needed the #247
  consolidation. **Fix:** give each stacked PR `base=main` and merge bottom-up (GitHub auto-retargets
  after each merge), or open the consolidating PR to main at the end. #247–#249 correctly used base=main.
- **pytest DB collision:** two concurrent `docker compose exec backend pytest` runs on the same
  `test_railtech` DB deadlock on schema creation (mass "deadlock detected" errors, ~60s). Never launch a
  second suite while one is live; if it happens, kill strays (`docker compose restart backend`) + drop
  the test DB, then run once.
- **Local CI parity:** flake8/black/isort via a host venv at
  `<scratchpad>/lintenv/bin/*` (flake8 + black>=24,<25 + isort>=5,<6); `npm run build` (not
  `tsc --noEmit`); after pulling a lock from another machine run
  `npm install --no-save @rollup/rollup-darwin-arm64`.

## Workflow pattern that worked (ultracode)
scout-workflow (verify plan against current main) → implement solo (interdependent auth edits) →
adversarial-verify workflow (one skeptic per gate: semantics preserved? unintended widening/narrowing?
cross-tenant? prechecks intact?). Caught comment inaccuracies + confirmed each swap SAFE before commit.
