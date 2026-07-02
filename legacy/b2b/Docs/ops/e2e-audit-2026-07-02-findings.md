# E2E Audit — 2026-07-02 (full lifecycle, own-eyes)

Clean local stack (DB wiped → migrate → lookups seeded). Walked the real UI as buyer,
platform operator, seller. Findings logged as they surfaced; fixes applied on branch
`fix/e2e-audit-2026-07-02`.

## CRITICAL / HIGH

### F1 (HIGH, FIXED) — Toaster never mounted → every toast silently invisible
`toast.success/error` is called in ~30 components, but no `<Toaster>` was mounted
anywhere (not in main.tsx nor App.tsx). Result: ALL user feedback — success confirmations
AND error messages — silently did nothing. A user clicking "Отправить заявку" that failed
got zero feedback. Fix: mount `<Toaster position="top-right" richColors closeButton />`
at the root in main.tsx (outside ErrorBoundary so feedback survives a subtree crash).

### F2 (HIGH, FIXED) — "Отправить заявку поставщику" silent dead-end for free-text заявки
A manually-typed заявка (no catalog-linked lines) implies no seller. Backend `submit_request`
enforces a ≥1-recipient invariant (`NO_RECIPIENTS` 400), but the buyer UI had no recipient
picker — so submit always 400'd, and with F1's missing Toaster the error was invisible.
Net: the primary buyer CTA did nothing, no explanation. Fix: added a supplier-picker dialog
(uses the existing `usePartnerSuppliers` + `useRouteDeal`); when a заявка has no catalog lines
and no prior routing, submit opens the picker → routes to chosen sellers → submits.

### F3 (MEDIUM, FIXED) — token/refresh 500 on a valid-but-dead token (crash + cookie never cleared)
`CookieTokenRefreshView` only caught `TokenError`. A structurally-valid refresh token whose
user no longer exists (e.g. after a DB reset) raised `CustomUser.DoesNotExist` → 500, and the
stale cookie was never cleared, so the browser replayed the dead token on every visit. Fix:
catch `(TokenError, User.DoesNotExist)` → 401 + clear the refresh cookie.

## MEDIUM / process

### F4 (MEDIUM, process) — KYC L2 approvable with ZERO documents, no INN
Operator KYC-approve dialog let me confirm L2 for a company with 0 uploaded documents and
no INN — the whole point of KYC. World-standard: require ≥1 document + INN before L2, or at
least warn. Not yet fixed — flagged for decision (hard-block vs. soft-warn).

## Observations (not bugs)
- Registration → setup-password email → profile → operator KYC dashboard all work cleanly.
- Preflight AI quality check (advisory) fires and gives sensible per-line hints. 
- Unified shell (Phase C Slice B) renders correctly for the buyer (single-side: only buy nav).

### F5 (MEDIUM, UX, to-review) — КП line grid shows «Маржа 0%» + cost-only Сумма while the quote total applies the markup
Margin is a QUOTE-LEVEL markup (Настройки КП → «Маржа КП %»), not per-line. When a 20%
quote markup is applied, the right-rail economics correctly show it (gross margin 16.7%,
Итого 141.12M), but each line's «Маржа» column still renders 0% and «Сумма» = cost×qty
(105M, not 126M). A seller scanning the line grid sees 0% margin + cost-only line totals
that don't sum to the К-оплате total — the line view and the total tell different stories.
REFINED after observing a stage transition: the line grid is actually STALE — it does NOT
reactively recompute when the quote-level margin changes. Saving «Настройки КП → Маржа 20%»
updated the right-rail total (126M) but left every line at «Маржа 0%» / cost-only Сумма.
Only after «На согласование» (a server round-trip) did the grid recompute to 17% / marked-up
Сумма (91.2M/34.8M). So while PRICING, the seller cannot see per-line marked-up prices —
they see 0% margin and cost sums that contradict the total. Fix: recompute line prices
client-side (or refetch the quote) immediately after the margin setting saves.

### F6 (LOW, UX) — per-line «Маржа» cell looks editable but isn't
A seller naturally clicks the «Маржа» column to set a line margin; it's a display-only
computed span (margin is quote-level). No affordance signals this. Minor friction.

## ⚠️ HEADLINE FINDING

### F7 (CRITICAL — financial misrepresentation) — UZS-priced КП shown to buyer with a «$» sign, off by the FX rate
Repro: seller prices a КП in UZS (line currency «UZ»); the builder correctly shows «UZS 141,120,000».
Buyer opens the received КП → sees «$141,120,000.00» / «$11,400,000.00 per wheelset».

Root cause (two layers):
1. `crm.Quote.quote_currency` is **None** after the seller builds a UZS quote — the КП never
   records the currency it is denominated in. Stored `total_incl_vat = 141120000.00` (raw UZS).
2. `frontend/src/store/currencyStore.ts::format(amountUSD)` assumes EVERY amount is USD. It prefixes
   «$» in USD mode (or multiplies by the FX rate in UZS mode). The buyer's КП view calls this global
   `formatCurrency` on the quote's UZS amounts → a 141M-UZS quote reads as «$141,120,000» (~$11k shown
   as if $141M — a ~12,650× overstatement). Toggling the buyer to UZS makes it WORSE (would multiply
   the already-UZS number by the rate).

Why it matters: RailTech is an Uzbekistan marketplace — sellers WILL price in UZS, so this fires on
the majority of real quotes. A buyer receiving «$141,120,000» for railway parts either panics or loses
all trust. Directly the "negative user experience / reputation" risk the audit targets. Also affects the
downloaded КП PDF (same amounts) and every downstream doc (contract/invoice).

Recommended fix (needs care — money display architecture, not a one-liner):
- Persist the quote's denomination currency (populate `quote_currency` from the builder's KP currency;
  default to the company/most-common line currency; never leave None on send).
- Make money rendering currency-AWARE: format an amount in ITS OWN document currency + symbol
  (UZS→«сум», USD→«$»), instead of routing every value through the USD-assuming global toggle. The
  global USD/UZS toggle should CONVERT a known-currency amount, not reinterpret an unlabelled number.
- Add a serializer field exposing the quote/line currency so the buyer view can format correctly.
Deferred from this session (high blast-radius on all money display) — flagged as #1 for a focused fix.
