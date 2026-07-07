# Session handoff — 2026-07-01 — CI recovery + Phase C plan

> **READ FIRST on the other machine.** `git pull`. Memory is machine-local; this git doc is the
> cross-machine source of truth. Supersedes `session-handoff-2026-07-01-eod.md`.

## ⬜ ONE open PR — `fix/tenant-isolation-hardening` (8 commits). Everything else is in `main`.
Verify the CI re-run is green, then merge. Contents (in order):
1. `fix(security)` **cross-tenant cache leak** — `queryClient.clear()` on login+logout (shared browser:
   user B was served user A's cached deals/quotes; extracted `frontend/src/lib/queryClient.ts` singleton).
2. `test(security)` **Phase C invariant guard** — `crm/tests/test_context_scoping.py`: a pure buyer
   forging any `X-Active-Context` header sees ZERO seller КП on `/crm/quotes/` (and `/crm/deals/`).
   MUST stay green through every Phase C slice.
3. `fix(api)` **spectacular crash** — `CompanyViewSet.get_permissions()` hit `AnonymousUser.is_platform_admin`
   during schema-gen → `getattr(..., False)`.
4. `chore(ci)` **lint cleanup** — black reformatted 75 files (black 24), isort 31, flake8 46→0
   (facade re-exports → `__all__`; `# noqa: E402`; removed unused imports incl. `Q`/`HEAD_ORDER` from the
   quotes.py→rfq.py split; test vars → bare calls; lambda→def). Frontend eslint `/[.\-]/`→`/[.-]/`.
5. `fix(ci)` **pytest collection conflict** — `catalog/tests.py` (legacy file) vs `catalog/tests/`
   (package) both = module `catalog.tests`. Moved the file's tests into `catalog/tests/test_domain_taxonomy.py`.
6. `fix(catalog)` DomainConstraints test used `.create()` on a **seeded** DomainType → `get_or_create`.
7. `fix(ci)` **backend-test under `--nomigrations`** — `conftest.py django_db_setup` now runs
   `CREATE EXTENSION IF NOT EXISTS pg_trgm` (fixes 7 `SIMILARITY()` failures); `master_data` seeds
   `FulfillmentStatus`; role-access `lookups` seeds `ContractStatus`.
8. `fix(ci)` **regenerated stale `schema.json` + `schema.d.ts`** (crash had blocked regen for many merges;
   224 paths; verified DEBUG-independent so CI's regen matches).

**All 4 previously-red CI jobs fixed + verified locally CI-faithfully** (see recipes). CI billing was
restored, so the gate runs again now.

## ⚠️ WHY it broke — CI was billing-blocked for weeks
Deploys ran on the self-hosted runner (skips the CI gate), so `main` accumulated: black/flake8 drift,
a crashing `spectacular` (→ badly stale committed schema), and latent `--nomigrations` test gaps
(pg_trgm + unseeded lookups) that a local `--reuse-db` DB masks. **Lesson: run the FULL CI gate locally
before claiming green — not just `pytest`+`npm run build`.**

## ✅ CI-faithful local recipes (this is the key takeaway — reuse these)
- **flake8/black/isort** (config at REPO ROOT — must run from root, NOT the backend container which only
  mounts `backend/`): `docker run --rm -v "$(pwd)":/repo -w /repo python:3.12-slim sh -c "pip install -q
  flake8 'black>=24,<25' 'isort>=5,<6'; flake8 backend/; black --check backend/; isort --check-only backend/"`
- **eslint**: `docker build --target builder -t fe -f frontend/Dockerfile frontend` then
  `docker run --rm fe npm run lint` (only ERRORS fail `eslint .`; the ~29 react-refresh warnings don't).
- **backend-test** (CI uses `--nomigrations --reuse-db` from `pyproject.toml addopts`): the local
  `--reuse-db` DB has pg_trgm+seeds from a prior migrated state and MASKS failures →
  `docker compose exec -T backend pytest --create-db -q` to get a fresh schema-only DB like CI. Full
  suite = **563 passed** that way.
- **api-contract**: `docker compose exec -T backend python manage.py spectacular --format openapi-json
  --file schema.json` then regen types (`npm run gen:api-types` / openapi-typescript 7.13.0), `git diff
  --exit-code backend/schema.json frontend/src/api/schema.d.ts`. Schema is env-independent.
- **gh** installed (2.95.0) but auth is **per-machine** — run `gh auth login` on each box (agent can't
  authenticate). Not required this round; logs were pasted + reproduced locally.

## NEXT — Phase C (unify buyer/seller shell), from the adversarial design workflow
**Verdict:** safe to build incrementally — the security boundary is `is_seller()` gating BEFORE the
`X-Active-Context` header is read, so the header can only NARROW. **Invariant:** *seller-scoped rows are
produced ONLY by the `is_seller`/platform-admin-gated helpers in `accounts/services/permissions.py`
(`seller_visible_deal_ids`/`seller_acting_company_ids`/`seller_sees_all_deals`); the header may only
narrow, never widen.* Guard it with the Slice-1 contract test (done) — keep it green through every slice.

**Required guards:** (1) never branch to seller scope on `acting_context()` alone — `is_seller` first;
(2) client always emits a concrete header, default the NARROWER `BUYER` (`activeStatus || 'BUYER'`);
(3) backend: empty/SPA header → BUYER scope (defense-in-depth); (4) cost/margin redaction stays
ownership/permission-gated, NEVER header/`showPrices`-derived; (5) **context-key the list caches**
(`['deals', activeStatus]`, `['quotes', activeStatus]`, …) before removing the switcher — else a dual
user navigating seller→buyer reads the other context's cached rows (the login/logout `clear()` in this
PR only covers identity change, not intra-session context change).

**Slice order (each shippable + eyes-on BOTH contexts, low-risk first):**
- 1 contract test ✅ (merged in PR #189).
- 3+5 **page-derived context ✅ DONE — branch `feat/phase-c-page-context` (verify CI + merge).**
  `api/client.ts` sends a concrete header default `BUYER`; `App.tsx` `pageContextOf()` + the context
  guard ADOPTS a page's context for a user who has that capability (invalidating queries) instead of
  bouncing. Pure buyer/seller still bounced (no other verified statusEntry). Switcher kept. Eyes-on
  verified BOTH ways (dual user: #crm-deals→SELLER, #my-requests→BUYER). Guards #1/#2 satisfied.
- 2 backend empty-header→BUYER safety net — LOWER priority now (guard #2 makes the SPA never send empty;
  empty already resolves to routing-scope not see-all; contract test proves pure buyers safe). Optional.
- 4 nav curation — dedup overlapping targets (`shell.deals`→my-requests(buy)/crm-deals(sell); both
  `shell.catalog` & `nomenclature`→the same `products` page) with distinct labels.
- **NEXT ⇒ Slice B (unified nav):** show BOTH sides' nav sections for a DUAL user (buildNavigation gates
  by the user's VERIFIED statusEntries, not the single active context) so no manual switcher is needed to
  reach the other context — clicking a context-unique item already flips context via `pageContextOf`.
  DESIGN: attach each item's `side` to the resolved nav item; AppShell onClick does `setActiveStatus(side)`
  + invalidate for buy/sell items (handles shared-but-side-labelled items like Каталог(buy)/Номенклатура
  (sell), both id=`products`, which `pageContextOf` treats as neutral). Dedup the deals label. RISK: changes
  the nav for all users — must eyes-on BOTH a pure buyer AND a pure seller (need those logins), not just
  the dual test user, before merge.
- 6 context chrome (cart/badges) follows resolved context; 7 remove switcher (needs guard #5 cache-keying);
  8 merge Documents pages; 9 merge Deals page (high risk); 10 merge Dashboard (high risk). Guard #5
  (context-key list caches OR invalidate-on-context-change) is currently satisfied by the
  invalidateQueries() on both the switcher AND the page-derived adoption — keep that when removing the switcher.

Also outstanding (owner-decision, from 07-01-eod handoff): reassign-product was RE-WIRED into the builder
(«Привязать товар», merged); `crm/status-choices/` + `sourcing/requests/` are FE-orphaned BE endpoints
(candidate removal); `supportApi.deleteTicket` / `adminApi.openBreakGlass`(G2) / `accountsApi.getCompanyTypes`
still unwired.

## Eyes-on loop (works locally, owner carte blanche)
`docker compose ps` = live app. FE change → `docker compose up -d --build frontend` → drive the
authenticated Chrome tab (Claude-in-Chrome). Context switcher top-left; URL reload defaults to Покупатель
→ switch to Продавец then navigate IN-APP. Backend visual (PDF) via `manage.py shell` + WeasyPrint to a
mounted path, then Read it. Hard limits: no typing passwords / no printing live tokens (safety layer).
