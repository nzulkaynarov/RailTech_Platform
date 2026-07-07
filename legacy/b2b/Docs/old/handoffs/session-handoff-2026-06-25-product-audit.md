# Session handoff — 2026-06-25 — Product-quality audit & remediation

> Cross-machine source of truth (Claude Code memory is machine-local; this travels via
> `git pull`). Read this first. Branch: **`fix/core-flow-integrity`** (pushed).
> Open the PR: https://github.com/nzulkaynarov/RailTech_SaaS_B2B/compare/main...fix/core-flow-integrity?expand=1

## Why this session happened (the owner's mandate — keep it standing)
The OWNER walked the platform as a real user and stumbled on friction that "it compiles /
tests pass" never caught (cart→заявка lost params, chat bot replied to self, КП constructor
inert, basis/charge articles dead, admin still authored КП). The mandate is a **cardinal
shift**: stop firefighting point-fixes; act as a **product manager who looks with their own
eyes and benchmarks every flow against the WORLD STANDARD** (Ariba/Amazon Business/Stripe/
Intercom), find the whole iceberg (owner only names the tip), and fix FLOWS holistically.
Verify by re-walking as a user, not by tsc/tests alone. **AI features are all wanted back
after the core is solid.** See memory `feedback_product_quality_eyes_on` + `feedback_favor_world_standard`.

## The audit (ruthless multi-agent, benchmarked) — 29 findings: 4 BLOCKER + 16 MAJOR + 9 minor
Verdict: the КП cost-engine (the commercial heart) was "wired for show" — Incoterm flags
toggled column visibility but didn't drive math; the basis/charge apparatus was inert on a
clean prod DB (seed lived in `core_seed`, not migrations); approving a КП produced no
contract; AI leaked across the buyer/seller trust boundary 3 ways.

## DONE on `fix/core-flow-integrity` (4 commits; 376 backend tests + tsc -b + i18n all green)
**Blockers** — B1 approve_quote auto-creates the Contract (`crm/services/quotes.py`, actor=None
system path); B2 buyer accepted-КП "Open contract" CTA (`RequestDetailPage.tsx`); B3 Incoterm
+ charge engine moved seed→migrations `master_data/0008` + `crm/0036` (alive on clean prod,
IRON RULE 1), `core_seed.py` trimmed to demo-only; B4 cart→заявка inherits product
uom/MPN/ГОСТ/ТНВЭД (`buyer_add_request_items`).
**Majors** — M1/M2 `calculate_item_prices` gates per-line freight/customs by basis flags +
`set_quote_delivery_basis`→`recalculate_quote` (no ghost cost; `select_for_update(of=self)`);
M3 document charge-templates carry only non-line costs (insurance/cert), freight/customs are
per-line (no double-bill) — edited `0036` `CHARGE_TEMPLATES`; M5/M6 chat reply-assist gated to
SELLER (front `DealChatPanel.tsx` + back `ai_chat.py` `seller_company_routed_to_deal`); M7
Unfold `QuoteAdmin`/`QuoteItemInline` locked oversight-only; M8/M9 AI import persists clean
`name_canonical` (`sourcing/tasks.py`); M10 anthropic SDK pin; M11 buyer summary charges row;
M12 serializer `product_mpn`/`product_uom` fallbacks + review-grid display.
**Test infra** — `test_quote_charges` made seed-robust (get_or_create + global-template
isolation autouse fixture). New regression tests: cart-inherit, Incoterm-flag-gating,
charge-engine-seed, ai-chat role gate, admin-oversight.

## Verification done
376 backend tests green (`pytest --create-db`), `tsc -b` clean, `check_i18n_symmetry.py` OK.
Eyes-on (Dockerized Playwright): buyer + seller apps load cleanly, **0 JS errors**, dashboards
look professional. NOTE: `seller.local` (SUPPLIER+CLIENT) defaults to **Buyer context** — must
use the sidebar context switcher to reach the seller КП builder; automated switch was flaky, so
the **КП-builder cost-engine UX still needs a manual seller-context walkthrough** by the owner.

## REMAINING (continue on this same branch — NOT done)
- **Minors m1-m8**: AI pre-commit review gate (`ImportRequestDialog`); `name_canonical`
  editable in review grid (serializer + `RequestItemsEditor`); cart payload self-describing
  (`CartDrawer` send uom/mpn/gost); UoM `unece_code` field (don't conflate lookup code with
  Rec-20); **КП-settings panel** (VAT rate / tax_country / valid_until / currency — seller-
  guarded PATCH; PAIRS with M7 since authoring moved off Unfold); charges row when it nets to
  0; КП-builder empty-state (no quote → EmptyState + Generate, not a dead toolbar); explicit
  `ADMIN_REACHABLE_PAGES` allowlist. Also **M4** `seller_pays_insurance` now drives the
  insurance template, but `seller_pays_delivery` is still decorative — wire a last-mile row or drop it.
- **Restore AI #3/#6/#8** (КП-vs-заявка diff, PDF contract/invoice extraction, conversational
  заявка builder): **stashed** (`git stash list` → "partial AI #3/#6/#8 workflow"). It was a
  PARTIAL/stopped workflow — assess before un-stashing; new files: `crm/services/ai_diff.py`,
  `crm/views/ai_diff.py`, `sourcing/services_ai_extract.py`, `components/CRM/CoverageCheck.tsx`.
- **Integrate AdminCatalogPage refactor** (708→145 lines): worktree branch
  `worktree-agent-a6ef8f30e14d59a74` commit `2b89bcb` (split into `pages/admin-catalog/*`).
  Verify tsc + browser before merging.

## How to continue (verification playbook — agents lie about success)
Local Postgres via `docker-compose.override.yml` (`db` service, sslmode=disable). Tests:
`docker compose exec -T backend python -m pytest -q -p no:cacheprovider --create-db` (use
`--create-db` — the seed migrations changed). tsc: `docker run --rm -v "$PWD":/work -w /work
node:22 bash -lc 'cd frontend && npx tsc -b'`. i18n: `python3 scripts/check_i18n_symmetry.py`.
Browser: rebuild frontend (`docker compose up -d --build frontend`) + restart backend, then
`frontend/e2e/run-in-docker.sh <spec> --workers=1` (PW_VERSION=v1.61.0-jammy). Accounts:
buyer.local@ / seller.local@ / admin@railtech.uz, pw `Test1234!` (machine-local — re-provision).

## Follow-up findings (post-merge, 2026-06-25 EOD)
- **Owner-reported "seller opens заявка in CRM → thrown to a DIFFERENT КП (all КП)"**: investigated
  thoroughly in the merged code, **could NOT reproduce**. Full flow `crm-deals` → row → 
  `request-detail/{deal.id}` → `deal-quote/{deal.id}` resolves to the CORRECT КП (verified by browser
  repro: clicking "покупка" → request-detail/4 → deal-quote/4). Backend clean (1 quote/deal, 0
  cross-deal leaks, `Deal.active_quote` is `self.quotes`-scoped). `deal-quote/4` vs `/7` render
  different correct КП. QuotesPage PDF actions correctly pass quote-id→quote-endpoint. **NEED exact
  repro steps from the owner** (which screen + which "open" button), or it was already fixed by a
  prior merge. React Query keys (`['deals', id]`, `['quote-items', {deal_id}]`) are correctly id-scoped
  (no stale-cache path found).
- **КП builder (`QuoteBuilderGrid`) has untranslated English strings** (seen in browser): "Quote
  builder", "Commercial Offer", "Select Incoterm", "Landed Cost", "Margin", "Discount", "No match
  found", "before VAT", "AI catalog match", "Add", "Save". Mixed-language for a RU seller — wrap in
  `t()` + add RU/EN keys. Concrete next-session task.
