# Browser E2E (Playwright)

Proves the actual buyer/seller **clicks** work end-to-end, complementing the
backend service-level golden path (`backend/crm/tests/test_golden_path.py`).

Kept fully decoupled from the per-push CI gate (no dep in the lockfile; excluded
from vitest, tsc and eslint) so it never blocks normal work until you opt in.

## One-time setup

```bash
cd frontend
npm i -D @playwright/test          # commit the updated package-lock.json
npx playwright install --with-deps chromium
```

## Run

```bash
# against a running app (local dev, staging, or prod for the read-only smoke)
cd frontend
E2E_BASE_URL=https://staging.b2b.railtech.uz npm run test:e2e
```

Or trigger `.github/workflows/e2e.yml` manually from the Actions tab and pass the
target URL.

## What's runnable today vs. TODO

- ✅ `smoke` block (`e2e/golden-path.spec.ts`) — app loads, `#root` not empty,
  no raw i18n keys visible, `/health/` is up. Runs as-is.
- 🚧 `golden path` block — a labelled skeleton. Fill the `TODO` selectors against
  the real UI (prefer `data-testid` or accessible roles/labels), set
  `E2E_BUYER_EMAIL/PASSWORD` (+ seller creds for the two-context bid step), then
  remove the `test.skip`.

## Recommendation

Add `data-testid` to the key controls along the golden path (login fields,
create-deal, add-item, open-RFQ, submit-bid, send-КП, approve) as you fill the
spec — stable hooks beat brittle text selectors and double as living docs.
