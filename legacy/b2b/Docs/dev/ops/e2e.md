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

## Run against the LOCAL docker stack (no Node on the host)

`frontend/e2e/run-in-docker.sh` runs the specs inside the official Playwright
image against the running `make up` stack — useful when the dev machine has no
Node (the committed `node_modules` is a Linux build, unusable on macOS).

```bash
make up                                   # frontend :5173, backend :8000
cd frontend && e2e/run-in-docker.sh "golden-path.spec.ts --workers=1"
```

It forwards `localhost:8000`/`localhost:5173` inside the container to
`host.docker.internal`, because the SPA is a prod build with
`VITE_API_URL=http://localhost:8000` baked in — inside the container `localhost`
would otherwise be the container itself and every API call (incl. login) would
miss the host backend.

**Gotcha that bit us (2026-06-17):** the local `railtech_frontend` image is a
prod build, not hot-reloaded. If a new hash route was added (e.g.
`deal-quote/<id>`, `request-detail/<id>`) and the container predates it, those
routes silently fall through to the dashboard (`parseHashToPage` is fine; the
*built bundle* is stale). Rebuild before E2E:
`docker compose up -d --build frontend`.

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
