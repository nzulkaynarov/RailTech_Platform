# Session handoff — 2026-06-26 (prod bug-fixes + КП cost-engine F3.8 + deploy incident)

> Cross-machine source of truth (Claude Code memory is machine-local; this travels via
> `git pull`). LATEST — read this first. Continues session-handoff-2026-06-25-eod.md.

## TL;DR
Fixed four owner-reported prod bugs and reshaped the КП cost engine to the agreed F3.8 model.
All MERGED into `main` (PR #145) and **deployed to prod** (after clearing a deploy incident).
A couple of КП-builder items are still pending (below) — that's where to resume.

## Merged to main today (PR #145, branch fix/auth-reload-and-polish) — all eyes-on verified
1. **Logout on browser reload** — `authStore.initAuth` did a RAW fetch refresh that bypassed the
   apiClient refresh mutex → it raced the interceptor refresh other components trigger on mount.
   With ROTATE_REFRESH_TOKENS + BLACKLIST on, two concurrent refreshes blacklist each other →
   401 → logout (prod latency made it bite). Fix: initAuth just calls /me; the FIRST 401 mints
   the access via the single mutex'd interceptor refresh (exactly one refresh, no race).
2. **AI parser "not working"** — NOT a prod bug: prod infra healthy (key set, worker fresh, recent
   AI calls 200). It was a LOCAL stale celery-worker: **celery does NOT auto-reload** like Daphne,
   so the worker process held a pre-`gtin`-removal model in memory → `process_excel_import` crashed
   `column crm_quoteitem.gtin does not exist`. Fix = restart the worker. Added a CLAUDE.md pitfall
   note. Prod deploy rebuilds the worker, so prod was always fine.
3. **КП total ignored line items ($224 instead of ~$68k)** — the buyer's request lines and the
   seller's КП are the SAME quote (created by the BUYER → `prepared_by` = buyer). The own-КП
   scoping (audit H1) keyed on prepared_by's *seller* company → filtered out the seller's own
   items → item PATCH 404 → prices never persisted → recalc summed zeros. Fix: a routed seller
   sees/edits the quote's items unless it was prepared by a COMPETING seller company (explicit
   member subquery, no M2M negation). `crm/views/quotes.py` QuoteItemViewSet + QuoteChargeViewSet.
4. **"Открыть КП" opened a DIFFERENT deal's КП** — `crmApi.getQuoteItems` sent `?deal_id=`, but the
   backend filterset key is `quote__deal_id` → DRF silently ignored it → the builder loaded the
   seller's items across ALL deals. Fix: send `quote__deal_id`.
5. **КП cost engine → F3.8 (unified, owner-confirmed)** — see next section. Plus three mislabeled
   columns fixed: quantity header «Ед. изм.»→«Кол-во»; per-row «Итого с НДС»→«Сумма» (it's excl
   VAT — `quote.lineTotal`); landed «Стоимость доставки»→«Себестоимость» (RU).

## КП cost-engine model — F3.8 (THE agreed logic — keep it)
Owner directive (roadmap F3.8 + session-handoff-2026-06-23 line 27, confirmed today):
- **Per-line (individual):** ONLY себестоимость (base) + customs duty (inherently per-line — rate
  by ТНВЭД). `landed_cost = base + customs`. Logistics is NEVER per-line.
- **Whole-КП (на всю партию, document-level charges):** freight/logistics, insurance, packing,
  certification, commission, client discount, etc. — entered ONCE at the bottom.
- **Unified table across all Incoterms**; choosing a basis AUTO-ADDS its document charges
  (`apply_charge_template_to_quote` / DEFAULT_CHARGES_BY_BASIS: DDP→[INSURANCE, CERTIFICATION],
  CIF→[INSURANCE]…), it does NOT toggle per-line columns.
- Implemented: `calculate_item_prices` (landed = base + customs; logistics always 0; no basis
  gating). Frontend removed the per-line «Логистика» column. Charges dropdown excludes only
  `CUSTOMS` (the per-line cost) via `PER_LINE_CHARGE_CODES = ['CUSTOMS']`; freight/logistics is now
  a batch charge. Cost tests rewritten to the new model.
- Current per-line columns: `# · Наименование · Код ТНВЭД · Кол-во · Базовая цена FCA · Таможня ·
  Себестоимость · Маржа · Скидка · Сумма`.

## ⏭ PENDING — resume here tomorrow (NOT done)
1. **Remove the per-line «Скидка» column** (agreed, was mid-edit when interrupted). Reasoning: a
   discount is a WHOLE-ORDER lever, not per-item — and it already exists as the document charge
   «Скидка клиенту». Keeping both risks double-discount. Action: drop the «Скидка» column header +
   cell from `QuoteBuilderGrid.tsx` (the per-line `discount_percent` then stays 0; discount is
   applied via the batch charge). **Margin stays per-line** (per-item pricing lever for the two
   projections) — UNLESS the owner asks to make it a single КП-level markup (open question).
2. **КП-builder ERGONOMICS (world-standard, owner-raised)** — large КП are uncomfortable, vertical
   & horizontal. Diagnosis: the table header is NOT sticky (`TableHeader` line ~282, add
   `sticky top-0 z-10`); the first column (Наименование) is NOT frozen (add `sticky left-0` + bg);
   the page isn't height-bounded so the WHOLE page scrolls instead of just the grid (DealQuotePage
   wrapper is `flex flex-col gap-6`; the shell content is `<main className="flex-1 overflow-y-auto
   p-6">` in AppShell.tsx line 588). World-standard (Ariba/SAP/Excel grid): 3-zone fixed frame —
   compact sticky toolbar, scrollable grid with sticky header + frozen first column + dense rows,
   sticky totals footer; only the grid scrolls. Compact the tall DealQuotePage header (text-2xl
   title + icon + subtitle + send row) to give the grid more vertical room.
3. **Deploy robustness** — the deploy fails intermittently on `node:22-alpine` / `nginx:stable-alpine`
   **TLS handshake timeout to registry-1.docker.io** (Docker Hub anonymous flake/rate-limit). Make
   it resilient: `docker login` on the runner (kills anonymous rate-limit) OR a registry mirror in
   `/etc/docker/daemon.json` OR pin+cache base images. Worth a small ops PR.

## Deploy incident today (resolved) — how to handle if it recurs
PR #145 deploy hung, then failed. Two distinct issues:
- **Stuck self-hosted runner**: GitHub showed "running 8 min" but the box had NO Runner.Worker /
  build / migrate process — a dispatch wedge. Fix: `systemctl restart
  actions.runner.nzulkaynarov-RailTech_SaaS_B2B.vps-b2b.service` (on prod box 176.101.56.141), then
  Cancel + Re-run the workflow. (There are TWO runners on the box; the RailTech one was wedged.)
- **Docker Hub TLS timeout** on `docker build` (base-image metadata). Fix: pre-pull the base images
  on the box (`docker pull node:22-alpine nginx:stable-alpine`, retry — it's intermittent), then
  Re-run. Verified the deploy then completed: build → migrate → containers recreated
  («Up N minutes (healthy)»), images rebuilt, backend /health 200.

## Verify recipe (unchanged) + this-machine specifics
- Backend tests: `docker compose exec -T backend python -m pytest <path> -p no:cacheprovider --create-db -q`.
- tsc: `docker run --rm -v "$PWD/frontend":/app -w /app node:22 sh -c "npx tsc --noEmit"`.
- i18n: `python3 scripts/check_i18n_symmetry.py`. Frontend: `docker compose up -d --build frontend`.
- **After ANY model/migration change, restart celery-worker** (`docker compose restart celery-worker`)
  — it does not auto-reload (today's AI-import bug).
- Eyes-on: Dockerized Playwright at localhost:5173. Browser renders EN unless you set
  `localStorage.i18nextLng='ru'` — verify i18n in RU, an EN browser hides RU-leak bugs (and showed
  a false "i18n broken" alarm today). `seller.local`/`buyer.local`/`admin@railtech.uz`, pw `Test1234!`.
  seller.local needs a `DealSellerRouting` to a deal to even open its КП builder (MS-routing).
- Prod (read-only unless authorized): `ssh root@176.101.56.141`, REPO `/opt/railtech-b2b`,
  `$COMPOSE = docker compose -f docker-compose.yml -f docker-compose.prod.yml`.

## Lessons reinforced today
- **Verify in the browser, in RU locale, eyes-on** — an EN browser + spurious test selectors gave
  two false alarms (i18n "broken", "Add did nothing"). Real bugs (КП total, wrong-КП) were only
  caught by walking the flow + reading the actual API responses.
- **A deploy "hang" is usually infra** (stuck runner / Docker Hub), not the merge — check the box
  (Runner.Worker? build/migrate procs? container ages?) before suspecting code.
