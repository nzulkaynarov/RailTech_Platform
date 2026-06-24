# Session handoff — 2026-06-23 (continue on another machine)

> **Read first when resuming.** Claude auto-memory is machine-local and does NOT travel between
> computers — THIS file (in git) is the cross-machine source of truth. Pairs with
> `session-handoff-2026-06-22.md` (previous) and `roadmap-2026-06-19.md`.

## ⚠️ BEFORE SWITCHING MACHINES — COMMIT & PUSH
All work below is **UNCOMMITTED** on branch `feat/roles-seller-buyer`. It will NOT exist on the other
computer unless you commit and push it first:
```bash
git add -A && git commit && git push -u origin feat/roles-seller-buyer
```
If you read this on the new machine and the code isn't here, the push didn't happen.

## What this session built — КП cost-engine (backend + API, DONE & VERIFIED: 196 backend tests green)

A standards-based КП (quote) cost constructor. Frame: **UBL 2.1** (document/line AllowanceCharge) +
**Incoterms 2020** (cost-responsibility matrix) + landed-cost cost-plus. Deliberately a **minimal usable
layer, NOT a customs/logistics/accounting ERP** (owner directive — specialists enter freight/duty/rate as
numbers; we don't build allocation-by-weight/volume, recoverable import-VAT accounting, or an FX engine).

**Domain decisions locked in (owner-confirmed, best-practice with proof):**
- **ТНВЭД (HS code)** lives on the product card (`Product.hs_code`) so it's never lost; the quote line
  freezes a snapshot (`QuoteItem.hs_code`), inherited on product-assign, ВЭД per-line override wins.
- **Incoterm** changes *which cost rows are shown/mandatory*, not the math. Responsibility encoded as 4
  data flags on `DeliveryBasis` — code reads flags, never `if code=='DDP'`.
- **Per-line vs per-shipment:** only **customs duty** is inherently per-line (rate by ТНВЭД). Freight,
  insurance, overhead (rent/payroll/commission) are **per-shipment** header charges → `QuoteCharge`.
- **Two VATs:** import VAT (at clearance) is recoverable → NOT in margin base, NOT in client КП (it's
  accounting). Output VAT (on sale) sits on top of the client price. Margin is on landed cost net of
  recoverable VAT.
- **Two projections** of one КП: internal cost-sheet (cost/margin/charges — seller+director) vs client
  КП (line prices + total only, in UZS). Enforced server-side (charges/charges_total seller-only).

**Backend delivered (all migrated, seeded, tested):**
- Models: `Product.hs_code`; `Quote.delivery_basis/quote_currency/charges_total`; `QuoteItem.hs_code/
  discount_percent`; `QuoteCharge` (header UBL AllowanceCharge: amount OR `rate_percent` of subtotal,
  `is_deduction`); `ChargeType` lookup; `DeliveryBasis.seller_pays_freight/insurance/import/delivery`.
- Engine `QuoteCalculationService`: line (margin→discount) → subtotal → КП charges/discounts **before VAT**
  (percents resolved in Python) → VAT from `Quote.vat_rate` (DB, never 0.12) → total.
- Migrations: `catalog/0011`, `crm/0027`, `crm/0028`, `master_data/0007`.
- Seeds in `core_seed`: full Incoterms 2020 (11) + flag matrix; 9 ChargeType rows.
- API: serializers expose new fields (+`delivery_basis_data` with flags); `charges`/`charges_total`
  **seller-only** (buyer sees only `total_incl_vat`); endpoint `/api/v1/crm/quote-charges/` (CRUD,
  seller-only write); hs_code inherit in `reassign_quote_item_product`.
- Tests: `crm/tests/test_quote_charges.py` (9), `test_quote_calc.py` (+line-discount). Run:
  `docker compose exec -T backend python -m pytest crm/ catalog/ master_data/ accounts/ sourcing/ -q` → 196 passed.

## Remaining work (the roadmap for КП cost-engine)

1. **Frontend КП-конструктор** — ТНВЭД column; delivery-basis dropdown that reads `delivery_basis_data`
   flags → shows/hides/requires freight/insurance/duty/delivery rows; charges/discounts section (CRUD via
   `/crm/quote-charges/`); per-line `discount_percent`; **two projections** (internal cost-sheet vs client
   КП in UZS, margin hidden). i18n RU/EN for every new label.
   ⚠ **Cannot be visually verified by Claude on the macOS host** (no rollup-darwin — React won't run).
   Claude type-checks via `docker run --rm -v "$PWD":/work -w /work node:22 bash -lc 'cd frontend && npx tsc -b'`;
   **owner verifies visually** at localhost:5173 after `docker compose up -d --build frontend`.
2. **PDF** (`crm/templates/crm/quote_pdf.html` + service) — render charges + Incoterm + UZS; keep the
   client projection (no margin/cost rows). Backend — fully verifiable in-container.
3. **Role policy in settings** — configurable RBAC: editable field-groups (`base_price/logistics/customs/
   margin/charges`) × WorkspaceRole matrix, owner-set in settings; OWNER/director = full edit; enforced in
   `services.py` (Rule 8), frontend only hides. Separate large slice (model + settings UI + guards).

## Bring-up reminders (same as 2026-06-22 handoff)
- Local Postgres via gitignored `docker-compose.override.yml`; `.env` `DATABASE_URL=...@db:5432/...sslmode=disable`.
- `make up && make migrate && make seed` (runs `core_seed` — now also seeds Incoterms+ChargeType).
- After `.py` edits: `docker compose restart backend` (Daphne no autoreload). redis-py pinned `<8`.
