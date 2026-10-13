# Session handoff — 2026-06-25 (PM / evening continuation)

> Cross-machine source of truth (Claude Code memory is machine-local; this travels via
> `git pull`). Continues `session-handoff-2026-06-25.md` (AM: RBAC matrix + AI semantic match).
> This PM session shipped 7 verified waves on top of that. Read this one first.

## State of `main` — everything below is MERGED
Main is well past the AM handoff. Verified-and-merged this PM session, in order:
1. **RBAC cost-gate** (`feat/rbac-cost-gate`, #127) — КП cost/margin now gated on the
   `quote.view_cost_margin` permission (`can_view_quote_costs`) + readable permission labels.
   Cleaned up 14 stale remote branches (only `main` + active branches remain).
2. **Catalog waves 3-4 + dead-code + i18n** (#128) — H4 admin pagination (full set, not 20-row
   slice), H5/H6 railway-rule → 400 not 500, M3 import price validation, M9/M10 MPN+ТНВЭД
   round-trip; deleted the unreachable `components/Catalog/` tree; raw `*_name` → t() via lib/codes.
3. **MS-routing keystone slices 1-2** (#129) — the confidentiality fix. `DealSellerRouting`
   (Deal↔seller M2M) + migration 0033/0034; `seller_visible_deal_ids` / `seller_can_access_deal`
   scope sellers to ROUTED deals across deals/quotes/billing/messages list querysets + the
   `IsCompanyMemberOrPlatformAdmin` object perm. Replaces the old `seller_sees_all_deals` see-all
   leak. Routing inferred from `product.owner_company` at `submit_request`. AppShell invalidates
   React Query on Buyer↔Seller context switch (the `['deals']` key lacked context).
4. **MS-routing slices 3-4 + i18n remainder** (#130) — Deal serializers expose `target_sellers_data`;
   `route_request_to_sellers` service + `POST deals/{id}/route/` + `GET deals/suppliers/`; buyer
   seller-picker in CreateDealDialog (optional, for free-text RFQs) + "Routed to:" display.
   **MS-routing is now COMPLETE.**
5. **UX wave** (#131) — list-page error states (a failed fetch no longer looks like empty success)
   across ~18 pages; ConfirmActionDialog on bare irreversible actions (deactivate user, suspend
   sub, catalog deletes); catalog polish (no-op sort headers removed, publish affordance); backend:
   import-FAILURE status fix + cart→request `can_buy` server guard.
6. **AI #5 + #7** (#132) — #5 bilingual catalog-match (`name_canonical` in ITEM_SCHEMA +
   QuoteItem field + migration 0035; `_shortlist_products` trigram-searches name AND canonical →
   Latin query preselects Cyrillic; proven 0 vs 2). #7 pre-flight заявка quality check (advisory,
   `services_ai_preflight`, `POST sourcing/preflight-check/`, PreflightWarnings UI on DRAFT requests).

## OPEN right now — `feat/ai-wave4-pim-chat` (in flight when this was written)
AI #2 (PIM product enrichment — seller "AI enrich" suggests description/specs/category in the
product form) + AI #4 (deal-chat "Suggest reply" draft). Both additive, AI#1 pattern. If this
branch exists unmerged on resume: verify (the recurring checks below) then merge. NOTE the agents
were told NOT to edit `core/urls.py`/`core/settings.py` — the routes + throttle scopes
(`ai_enrich`, `ai_chat`, 20/min) must be wired there by hand from each agent's `apiContract`.

## ⚠ Hard-won lessons RE-CONFIRMED this session (the verification playbook)
Agents repeatedly reported success that did NOT hold — every wave I caught something:
- **They claim "tsc passed" but it didn't** — a pagination agent left 3 type errors; always run
  `tsc -b` (via `docker run --rm -v "$PWD":/work -w /work node:22 bash -lc 'cd frontend && npx tsc -b'`).
- **They don't return `localeKeys`** even when asked → new `t()` calls render raw. ALWAYS run
  `python3 scripts/check_i18n_symmetry.py` and add the missing keys yourself (single writer).
- **They may reference endpoints/hooks that don't exist** → grep to confirm wiring is real
  (one was a false alarm — `bulk_publish` existed — but check every time).
- **Always eyes-on in the browser** after frontend work (Dockerized Playwright; recipe below).
- **Shared files = single writer**: locales, `core/urls.py`, `core/settings.py` — have agents
  RETURN what they need; you merge. Assign disjoint file/domain buckets otherwise.
Standard per-wave verify: git-status (files real) → makemigrations --check → merge localeKeys →
full backend `pytest -q -p no:cacheprovider` → `tsc -b` → i18n symmetry → browser eyes-on → commit.

## Remaining backlog (master-scope `Docs/ops/master-scope-2026-06-24.md`)
- **NOT done by design — risky for blind multi-agent:** F4.x god-component splits (>500-line
  modules), F3.2 flowStore→React-Query (RequestDetailPage buyer still on flowStore), F4.3
  userStore→authStore. Do these CAREFULLY one at a time with component tests, not fan-out.
- **More AI** (roadmap `docs/ops/ai-features-roadmap-2026-06-18.md`): #3 КП-vs-заявка diff,
  #6 PDF contract/invoice extraction, #8 conversational заявка builder.
- **P0 commercial — deliberately deferred by owner** until the stability bar: real payment
  (Click/Payme), E-IMZO e-sign, in-country UZ DB (ЗРУ-547), payment idempotency.
- **Infra:** structured JSON logging + request-id, Sentry-frontend activation, staging buffer.

## Verify channel + local accounts (machine-local — recreate per machine)
- Browser: `frontend/e2e/run-in-docker.sh <spec> --workers=1` (PW_VERSION=v1.61.0-jammy) vs
  `localhost:5173`; rebuild first: `docker compose up -d --build frontend`.
- Accounts (pw `Test1234!`): `buyer.local@`, `seller.local@` (SUPPLIER+CLIENT → **defaults to
  BUYER context**, switch the sidebar to Seller to see the seller pipeline), `admin@railtech.uz`
  (Platform Admin — set its pw with `set_password` if login fails; the real one is in `.env`).
- `seed_demo` populates catalog (55 products) + demo deals. AI needs `ANTHROPIC_API_KEY` in `.env`
  (present locally; `AI_IMPORT_ENABLED` auto-derives). Backend tests: `pytest -q -p no:cacheprovider`.
