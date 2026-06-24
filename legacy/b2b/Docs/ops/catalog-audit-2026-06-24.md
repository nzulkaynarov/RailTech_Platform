# Catalog audit & remediation plan — 2026-06-24

Multi-agent catalog audit (6 surfaces) + browser/API verification. Catalog seeded
(`seed_demo`: 55 products / 37 categories / 4 groups / 50 offers; **0 brands**). 44 findings.
Fix in waves, each verified.

## ✅ Fixed this pass (verified by API + regression tests `catalog/tests/test_cost_gate.py`)
- **C1 — supplier cost leak to buyers (CRITICAL security).** `ProductSerializer`/`ProductListSerializer`
  returned `offers[]` + `base_price` to every viewer; React only hid them client-side → a buyer read
  the seller's cost + supplier identity via the API. Added `_CostGateMixin`: cost fields stripped
  unless the viewer is platform admin or a member of the product's `owner_company`.
- **H1 — seller couldn't edit/delete own product (HIGH).** `IsProductManagerOrAdmin.has_object_permission`
  checked the deprecated `obj.manufacturer_id` (always NULL after the brand/owner split) → 403 on every
  PATCH/DELETE. Now checks `owner_company_id` (legacy fallback kept).

## CRITICAL — remaining (do next)
- **C2 — no tenant scoping on SupplierOffer.** `catalog/views/offers.py` has no `perform_create`/object
  perm; `supplier` taken from the request body; `get_queryset` lists ALL suppliers' offers → a seller can
  spoof/edit a competitor's offers and read everyone's. Fix: derive supplier from the user's seller
  company, scope the queryset, add object permission.
- **C3 — bulk-imported products orphaned.** `sourcing/catalog_import.py _apply_product()` never sets
  `owner_company` (ctx.supplier is available) → importing seller can't see/manage their own cards. Set it.

## HIGH — broken core flows
- **H2 — offer creation dead-end.** `product` not in `SupplierOfferSerializer.fields`; no `perform_create`
  → POST drops product → 400/IntegrityError on the non-null FK.
- **H3 — sellers have NO offer-pricing UI.** Only the admin-gated offers page exists; the seller
  `ProductFormSheet` has no price/currency/stock/delivery fields → a seller cannot set a price anywhere
  (admin must not act for them, ADR-0002). Build a seller offer surface.
- **H4 — client-side pagination over a 20-row server slice** (catalog/categories/groups/offers admin
  pages): search/sort/Pager/stat tiles operate on the first 20 rows only → incomplete lists + wrong totals.
- **H5 — RAILWAY "≥1 equipment group" not enforced on API create** (`clean()` skipped when pk is None;
  empty m2m fires no signal) — only the frontend toast guards it.
- **H6 — last-group removal raises django `ValidationError` → HTTP 500** (no DRF handler) instead of 400.
- **(new) Owner can't retrieve own DRAFT product** — `ProductViewSet.get_queryset` excludes unpublished
  even for the owning seller (surfaced as a 404 in the H1 test). Sellers can't manage their own drafts.

## MEDIUM
- M1 offers admin shows raw stock FK int (no `stock_status_data`). M2 supplier picker lists ALL companies
  (no SUPPLIER filter, capped at 20). M3 import accepts negative/zero prices + name-without-price empty
  cards. M4 ImportStatusView omits `meta` → no live progress. M5 dry-run `checkedOk` true even when 100%
  rows failed. **M6 `owner_company` writable → once H1 lands a seller can PATCH it to another tenant —
  make read-only for non-admin.** M7 `hs_code` absent from serializer + seller form (only Excel/Django).
  M8 four `*FormSheet` do `setState` in `useMemo` (render-phase mutation, drops edits on refetch). M9
  `ProductResource` import/export omits MPN + hs_code + owner_company (round-trip data loss). M10
  export-template XLSX omits MPN (dedup key) + hs_code; diverges from ProductResource. M11/M12 admin
  search/offer-validation gaps (subsumed by H4/H2).

## LOW
- Stale docstrings (permissions.py MANUFACTURER ref — this caused H1; sourcing "Staff only"; lookups Neon).
- Blank status on create → product never PUBLISHED, no publish affordance.
- Import FAILURE returns misleading `{status:'completed'}`; dry-run dedup weaker than commit.
- No-op sort headers (`sortKey=""`) look clickable; category Select has no clear/None.
- cart→request has no `can_buy` backend guard (UI-hidden only).

## Dead code — delete (don't fix bugs in dead copies)
`PublicCatalog.tsx` + `ProductDetailModal.tsx` + `DomainAdaptiveSidebar.tsx` (+ subcomponents) are mounted
NOWHERE (App.tsx uses `ProductManagement`; `CatalogShell` doesn't exist). Their findings (no-op "Add to
Request", hardcoded `45 pcs`/`14-21 days`, fake mfgInfo) are moot. Also delete the dead `catalogApi.importExcel`
/ `exportTemplate` duplicates. **Verify-unreachable then delete the tree.**

## Wave order
1. **Security cluster:** C2 (offer scoping) + C3 (import owner) + M6 (owner_company read-only) → backend, verifiable.
2. **Broken seller flow:** H2 + H3 (offer creation + seller pricing UI) + the DRAFT get_queryset fix.
3. **Admin lists:** H4 (server pagination) across the 4 admin pages + M1/M2.
4. **Validation/UX:** H5/H6 (railway-group 400 not 500) + M3/M4/M5 (import) + M8 (form state) + M7/M9/M10 (hs_code/MPN).
5. **Dead-code deletion** (PublicCatalog tree + dead catalogApi methods).
6. **LOW** polish.
