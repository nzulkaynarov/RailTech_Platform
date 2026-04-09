# RailTech Audit — Implementation Checklist

Audit date: April 2026. Based on the external 6-section audit + systematic CLAUDE.md compliance sweep.

---

## Section 1: Frontend Customs & Hacks

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1.1 | Replace all hardcoded `$` / `сум` currency symbols with `useCurrencyStore.format()` | DONE | Dashboard.tsx, SettingsPage.tsx, ProductManagement.tsx, QuoteBuilderGrid.tsx, AdminDashboard.tsx, ManagerDashboard.tsx, ClientDashboard.tsx |
| 1.2 | Replace all non-semantic Tailwind colors with semantic tokens | DONE | 18+ files: amber→warning, emerald→success, red→destructive, purple→primary, white→foreground |
| 1.3 | Replace all raw `<table>` HTML with shadcn `<Table>` components | DONE | 7 files: ClientDashboard, SourcingGrid, CompanyTeamSettings, CatalogTable, ProductDetailModal, AdminNomenclature, QuoteBuilderGrid |
| 1.4 | Replace native `<button>` / `<input>` with shadcn `<Button>` / `<Input>` | DONE | LanguageSwitcher, ThemeToggle, ProfileCompletionForm (hidden file inputs left as-is — valid exception) |
| 1.5 | Replace inline `style={{ backgroundColor }}` chart legends with `bg-[var(--color-chart-N)]` | DONE | Dashboard.tsx pie charts |
| 1.6 | Replace hardcoded Russian strings in stores with i18n keys | DONE | flowStore.ts (dealStageLabels, requestStatusLabels, rfqNote), authStore.ts (error messages) |

## Section 2: Hardcoded / Fake API Data

| # | Item | Status | Notes |
|---|------|--------|-------|
| 2.1 | Ensure `data/products.ts` exports empty array (no fake products) | DONE | Already exports `[]` — confirmed, uses `catalogApi` for real data |
| 2.2 | `demoCompanies` in flowStore.ts exports empty array | DONE | Loaded from API via `accountsApi` |
| 2.3 | All API endpoints query real database (no mock responses) | DONE | Verified — all Django views use ORM queries |

## Section 3: Documentation

| # | Item | Status | Notes |
|---|------|--------|-------|
| 3.1 | Mermaid architecture diagrams | DONE | `Docs/architecture-diagrams.md` — 10 diagrams: Deal FSM, KYC, Auth, Sourcing, Multi-tenancy, State, WebSocket, Storage, CI/CD, Error handling |
| 3.2 | Auto-generated API documentation (Swagger/ReDoc) | DONE | `drf-spectacular` added — `/api/docs/` (Swagger UI), `/api/redoc/` (ReDoc), `/api/schema/` (OpenAPI YAML) |
| 3.3 | WebSocket message dictionary | DONE | `Docs/websocket-messages.md` — endpoints, message types, lifecycle, auth, examples |

## Section 4: Architecture (Backend)

| # | Item | Status | Notes |
|---|------|--------|-------|
| 4.1 | Audit trail for financial models (Deal, Quote, QuoteItem) | DONE | `django-pghistory` — snapshot + before_update tracking on all 3 models |
| 4.2 | Run `python manage.py pghistory` to create migration | TODO | Requires running inside Docker container: `make shell` then `python manage.py makemigrations` |

## Section 5: Django Admin

| # | Item | Status | Notes |
|---|------|--------|-------|
| 5.1 | `list_editable` for quick inline editing | DONE | Already configured in admin classes |

## Section 6: Shift-Left Automation

| # | Item | Status | Notes |
|---|------|--------|-------|
| 6.1 | Custom ESLint rules enforcing CLAUDE.md | DONE | `railtechPlugin` in `eslint.config.js` — `no-hardcoded-colors` (catches `text-red-500`, `bg-amber-*`, `text-white`, `text-black`) + `no-arbitrary-text-size` (catches `text-[9px]`, `text-[11px]`) |
| 6.2 | Husky + lint-staged pre-commit hooks | DONE | Root `package.json` with husky v9 + lint-staged v15; `.husky/pre-commit` runs `npx lint-staged` |
| 6.3 | i18n sync check script | DONE | `scripts/check-i18n-sync.py` — validates ru.json ↔ en.json key parity (currently 1679 keys, perfect sync) |
| 6.4 | i18n check in CI pipeline | DONE | Added to `.github/workflows/ci.yml` in `frontend-lint` job |

---

## Post-Audit Setup Steps

After pulling these changes, run once to initialize Husky:

```bash
# At repo root
npm install        # installs husky + lint-staged
npx husky          # creates .husky/_/ directory

# Backend — create pghistory migration
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py migrate
```

## Files Changed Summary

**New files:**
- `Docs/architecture-diagrams.md` — Mermaid diagrams
- `Docs/websocket-messages.md` — WebSocket dictionary
- `scripts/check-i18n-sync.py` — i18n validation script
- `package.json` (root) — Husky + lint-staged config
- `.husky/pre-commit` — Git pre-commit hook

**Modified files (backend):**
- `backend/core/settings.py` — added drf-spectacular, pghistory, pgtrigger
- `backend/core/urls.py` — added /api/docs/, /api/redoc/, /api/schema/
- `backend/requirements.txt` — added drf-spectacular, django-pghistory, pgtrigger
- `backend/crm/models.py` — added @pghistory.track decorators

**Modified files (frontend):**
- `frontend/eslint.config.js` — custom railtechPlugin with 2 rules
- `frontend/src/store/flowStore.ts` — i18n keys for labels, semantic colors
- `frontend/src/store/authStore.ts` — i18n keys for error messages
- `frontend/src/i18n/locales/ru.json` — added dealStages, managerDashboard, settings keys
- `frontend/src/i18n/locales/en.json` — same keys, English translations
- `frontend/src/pages/Dashboard.tsx` — formatCurrency, semantic colors, chart dotClass
- `frontend/src/pages/SettingsPage.tsx` — i18n for labels
- `frontend/src/pages/ProductManagement.tsx` — formatCurrency
- `frontend/src/pages/flow/RequestDetailPage.tsx` — t(dealStageLabels[...])
- `frontend/src/components/Admin/AdminDashboard.tsx` — formatCurrency, semantic colors
- `frontend/src/components/Admin/ManagerDashboard.tsx` — full i18n + formatCurrency + semantic colors
- `frontend/src/components/Cabinet/ClientDashboard.tsx` — formatCurrency + semantic colors + shadcn Table
- `frontend/src/components/Sourcing/QuoteBuilderGrid.tsx` — currencyStore.format() + shadcn Table
- `frontend/src/components/Sourcing/SourcingGrid.tsx` — shadcn Table
- `frontend/src/components/Cabinet/CompanyTeamSettings.tsx` — shadcn Table
- `frontend/src/components/Catalog/subcomponents/CatalogTable.tsx` — shadcn Table
- `frontend/src/components/Catalog/subcomponents/ProductDetailModal.tsx` — shadcn Table
- `frontend/src/components/Admin/AdminNomenclature.tsx` — shadcn Table + semantic colors
- 18+ files — non-semantic color token replacements
- 3 files — native button → shadcn Button

**CI:**
- `.github/workflows/ci.yml` — added i18n sync check step
