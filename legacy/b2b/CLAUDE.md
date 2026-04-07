# RailTech B2B SaaS — Claude Code Context

## Project Overview

B2B marketplace for railway equipment (Uzbekistan). Monorepo: Django backend + React frontend + Docker infrastructure.

**Domain:** Railway machinery, general goods, services — procurement, quoting, CRM.

## Tech Stack

- **Backend:** Django 5.1, DRF, Daphne (ASGI), Channels (WebSocket), Celery + Redis, PostgreSQL (Neon Cloud)
- **Frontend:** React 18, TypeScript 5.6, Vite 7, Tailwind CSS 4, shadcn/ui, Zustand 5, React Query 5, i18next (RU/EN)
- **Infra:** Docker Compose (dev), Nginx (prod), MinIO (S3), GitHub Actions CI
- **Auth:** JWT (simplejwt) — access 30min, refresh 7d, rotation enabled
- **PDF:** WeasyPrint
- **Excel:** pandas + openpyxl

## Project Structure

```
backend/                    # Django project
  core/                     # Settings, URLs, ASGI, Celery, middleware, permissions
  accounts/                 # CustomUser, Company, CompanyMember, KYC, Subscriptions
  catalog/                  # Product (PIM), Category, EquipmentGroup, SupplierOffer
  crm/                      # Deal, Quote, QuoteItem, Message, Lead, ActivityLog
  sourcing/                 # Attachment, ImportTask, DomainKeyword, Excel import tasks
  master_data/              # AbstractLookup, Country, Currency, UOM, DeliveryBasis
  notifications/            # Notification, NotificationType
frontend/                   # React app
  src/api/                  # Axios client with JWT interceptor + refresh mutex
  src/store/                # 10 Zustand stores (auth, user, cart, flow, task, theme, currency, domain, demo, loading)
  src/pages/                # Dashboard, ProductManagement, OnboardingPage, ProfilePage, etc.
  src/components/           # shadcn/ui (66 components), Admin, Catalog, Sourcing, Dashboard, Auth, Cabinet
  src/hooks/                # useAccounts, useCatalog, useCRM, useMasterData, use-mobile
  src/i18n/locales/         # ru.json, en.json
  src/layouts/              # AppShell (main SPA shell with shadcn Sidebar)
nginx/                      # Production nginx.conf (rate limiting, caching, WebSocket)
Docs/                       # Architecture, specs, roadmap, mockups, presentations, UI audit
```

## Key Architecture Decisions

- **Minimal URL routing** — auth routes (`/`, `/register`, `/setup-password`) via `useAuthRoute()` hook in App.tsx; main app uses `useState<Page>` state machine (no React Router)
- **B2B Multi-tenancy** — via `CompanyMember` join table, not schema/DB isolation
- **Deal FSM** — DRAFT → KYC_PENDING → SOURCING → CALCULATING → QUOTE_SENT → CONTRACT_SIGNED → CLOSED_WON/CLOSED_LOST
- **Dual Redis** — redis:6379 (Channels/WebSocket), redis-celery:6380 (Celery broker+results)
- **Dual Storage** — MinIO (public/private/temp buckets) with local filesystem fallback
- **Financial precision** — `decimal.js` on frontend, `DecimalField` on backend, `QuoteItemHistory` audit trail
- **Auth model** — `CustomUser` with email as USERNAME_FIELD, `SystemRole` FK for RBAC
- **Company types** — `CompanyType` M2M on Company (CLIENT=Buyer, MANUFACTURER, SUPPLIER=Seller); returned in `/me/` as `company_types[]`
- **Frontend role mapping** — `loadFromAuth()` maps backend CompanyType codes to frontend CompanyStatus (CLIENT→BUYER, SUPPLIER→SELLER, MANUFACTURER→MANUFACTURER)
- **4 Shell layouts** — all use shadcn `<Sidebar>` with `collapsible="icon"`:
  - `AppShell` (hash-based SPA, Buyer/Seller/Manufacturer context switcher)
  - `AdminShell` (React Router, `/admin/*`)
  - `ClientShell` (React Router, `/cabinet/*`)
  - `ManagerShell` (React Router, `/crm/*`)
  - `CatalogShell` (public catalog, top navbar only — no sidebar)
- **Unified shell layout** — all shells use `p-6` content padding, `h-14` header, `<SidebarTrigger>` for mobile

## Database

- **External:** Neon Cloud PostgreSQL (no local postgres in docker-compose)
- **Connection:** `DATABASE_URL` env var parsed via `urlparse`, fallback to individual `POSTGRES_*` vars
- **Auth user:** `accounts.CustomUser` (email login)

## API Surface (prefix: `/api/v1/`)

- `auth/` — register, setup-password, submit-profile, token, token/refresh
- `accounts/` — companies (verify-kyc, upload-document, team, invite), users, me
- `catalog/` — products, offers, equipment-groups, categories, manufacturers
- `crm/` — deals (change-stage), quotes (generate-pdf, send-to-client, approve), quote-items, messages, activity-logs, analytics, leads
- `sourcing/` — requests, import-deal/{id}, import-catalog, import-status/{task_id}
- `master-data/` — countries, currencies, units, delivery-basis
- `notifications/` — CRUD + mark as read
- `health/` — health check (also at root `/health/`)

## Celery Tasks

- `sourcing.tasks.process_excel_import` — Parse Excel for deal, Smart Match, create QuoteItems (queues: default, pdf, imports)
- `sourcing.tasks.process_catalog_import` — Bulk import products to PIM catalog
- Celery Beat — `django_celery_beat.schedulers:DatabaseScheduler`

## Environment

- Config via `.env` file (loaded by python-dotenv from `BASE_DIR.parent/.env`)
- Key vars: `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `REDIS_URL`, `CELERY_BROKER_URL`, `MINIO_*`, `VITE_API_URL`, `VITE_WS_URL`
- Frontend: build-time env via Vite `import.meta.env` (baked into production build)

## Docker Services (dev)

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| redis | redis:7-alpine | 6379 | Django Channels |
| redis-celery | redis:7-alpine | 6380 | Celery broker |
| minio | minio/minio | 9000, 9001 | Object storage |
| minio-init | minio/mc | — | Bucket creation |
| backend | custom (Dockerfile) | 8000 | Django/Daphne ASGI |
| celery-worker | custom (Dockerfile) | — | Async tasks |
| celery-beat | custom (Dockerfile) | — | Scheduled tasks |
| frontend | custom (Dockerfile) | 5173 | React (nginx) |

## Commands

```bash
make up              # docker compose up -d --build
make down            # stop all
make logs            # follow logs
make migrate         # run migrations
make makemigrations  # create migrations
make seed            # loaddata seed_data
make test            # pytest
make lint            # flake8 + black + isort + eslint
make format          # black + isort
make shell           # backend bash
```

## Coding Conventions

- **Python:** black (120 line length), isort (profile=black), flake8; target Python 3.11
- **TypeScript:** strict mode, ESLint, path alias `@/` → `src/`
- **Styling:** Tailwind v4 utility-first, oklch color tokens, CSS variables, dark mode via `.dark` class
- **Models:** `AbstractLookup` base for reference tables (code, name, sort_order, is_active)
- **Serializers:** Nested read, flat write pattern; `_data` suffix for nested representations
- **i18n:** All UI text via `useTranslation()`, keys in `ru.json`/`en.json`
- **State:** Zustand stores with `persist` middleware for auth/theme; no Redux
- **UI:** Only shadcn/ui components + Tailwind semantic tokens. No custom CSS, no hardcoded hex colors, no `text-white`/`text-black` — use `text-foreground`/`text-primary-foreground`
- **Text sizes:** Only Tailwind scale (`text-xs`, `text-sm`, `text-base`, etc.) — NEVER `text-[9px]`, `text-[11px]` or arbitrary pixel values
- **Chart colors:** Use `bg-[var(--color-chart-N)]` for dynamic chart legend dots — this is the correct Tailwind pattern for CSS variable colors. NEVER use inline `style={{ backgroundColor }}` for chart legends
- **Sidebar:** ALL shell layouts must use shadcn `<Sidebar>` + `<SidebarProvider>` + `<SidebarInset>` — NEVER custom `<aside>` with manual collapse state
- **Zod validation messages:** For i18n, use factory pattern: `const createSchema = (t: TFn) => z.object(...)` — call inside component where `t()` is available

## Testing

- **Backend:** pytest + pytest-django, markers: slow, integration, unit; coverage threshold: 50%
- **Frontend:** vitest + @testing-library/react + jsdom
- **CI:** GitHub Actions — 6 jobs (backend-lint, backend-test, frontend-lint, frontend-build, docker-build, security)

## Auth Flow (production)

1. User opens app → `LoginPage` (or `/register` → `KYCRegistrationForm`)
2. Registration: `POST /api/v1/auth/register/` → creates `CustomUser(is_active=False)` + sends email
3. In DEBUG mode, email goes to **backend container logs** (`docker compose logs backend`)
4. User clicks link `/setup-password?uid=...&token=...` → `PasswordSetupPage` → sets password → `is_active=True`
5. Admin approves company via Django admin at `/admin/` (Unfold UI) → action "Подтвердить KYC (L2)"
6. User logs in with JWT → `LoginPage` → main app

**Test accounts (pre-seeded):**
- `admin@railtech.uz` / `admin123` — Admin (superuser)
- `manager@railtech.uz` / `manager123` — Sales Manager
- `client@test.uz` / `client123` — Client

## IRON RULES — VIOLATION PROHIBITED

### Rule 1: No fake data
- NEVER create mock data, static arrays, or fake API responses in production code
- EVERY endpoint MUST query the real database via Django ORM
- If test data is needed — use management commands (`core_seed`, `seed_demo`), not hardcode

### Rule 2: No hardcoded values
- URLs, keys, secrets, IDs — ONLY from environment variables (.env)
- Business constants (limits, prices, settings) — ONLY from DB or config
- Roles, statuses, enum values — compare by `code` field (e.g., `stage_code === 'DRAFT'`), NEVER by translated `name`

### Rule 3: Strict naming
- JS/TS variables and functions: camelCase
- JS/TS classes and types: PascalCase
- API endpoints: kebab-case, plural nouns
- DB tables and columns: snake_case (Django convention)
- Environment variables: UPPER_SNAKE_CASE
- Boolean fields: `is_`/`has_` prefix in DB

### Rule 4: Only shadcn/ui + semantic tokens
- ONLY use components from `@/components/ui/` (shadcn/ui)
- Colors: `bg-primary`, `text-foreground`, `bg-success`, `bg-warning`, `bg-destructive`, `bg-info` — NEVER `bg-emerald-500`, `text-white`, `bg-amber-*`, `bg-red-600`
- Text sizes: ONLY Tailwind scale (`text-xs` minimum) — NEVER `text-[9px]`, `text-[8px]`, `text-[11px]`
- No custom CSS, no inline styles for static values, no `blur-[120px]` decorative hacks
- Chart colors: use `bg-[var(--color-chart-N)]` Tailwind classes, NOT inline `style={{ backgroundColor }}`
- Sidebar: use shadcn `<Sidebar>` primitives, NOT custom `<aside>` elements

### Rule 5: All text via i18n
- ALL user-facing text wrapped in `t()` from `useTranslation()`
- Labels stored in `frontend/src/i18n/locales/ru.json` and `en.json`
- Store files (Zustand) hold i18n KEYS, not raw text — translate in components

### Rule 6: Always read before writing
- ALWAYS read the file with Read tool before editing
- ALWAYS check that imports exist, types are correct, fields match DB schema
- NEVER assume file contents or code structure

### Rule 7: Frontend-backend sync
- Every frontend feature must call a real backend API endpoint
- `userStore.loadFromAuth()` maps backend CompanyType → frontend CompanyStatus
- Use `stage_code` (DB code) for logic, `stage_name` only for display

## ANTI-HALLUCINATION — What does NOT exist

### Tables that DON'T exist
- NO `payments` table — payment not yet implemented
- NO `sessions` table — sessions handled by Django middleware
- NO `roles` table — roles are `SystemRole` (in accounts app), NOT a separate table

### Endpoints that DON'T exist
- NO `PUT /api/v1/accounts/users/{id}/toggle-active/` — not implemented yet
- NO `POST /api/v1/catalog/products/import_excel/` — use `sourcing/import-catalog/` instead
- NO `GET /api/v1/catalog/products/export_template/` — not implemented
- NO `GET /api/v1/crm/deals/{id}/export_pdf/` — PDF export is on quotes, not deals

### Fields that DON'T exist
- `users` table has NO `username` field for login — uses `email` as USERNAME_FIELD
- `deals` table has NO `discount` field
- `products` table has NO `price` field — prices are in `SupplierOffer` (separate table)
- Frontend `Product` type from `data/products.ts` is LEGACY — real products come from `catalogApi.getProducts()`

## Data Transformations

| DB (snake_case) | API Response (snake_case) | Frontend Store |
|-----------------|--------------------------|----------------|
| `first_name` | `first_name` | `firstName` (mapped in loadFromAuth) |
| `stage.code` | `stage_code` | `stage_code` (use for logic) |
| `stage.name` | `stage_name` | `stage_name` (use for display only) |
| `company.types` | `company_types[]` | `activeStatus` (CLIENT→BUYER, SUPPLIER→SELLER) |
| `verification_status.code` | `verification_status` | `kycStatus` |

Transformation happens in: `userStore.loadFromAuth()` and DRF serializers.

## Self-Check Before Commit

1. [ ] New/changed endpoint queries real DB? (no mocks, no hardcode)
2. [ ] Request/response fields match DB schema?
3. [ ] Naming follows conventions? (camelCase in JS, snake_case in DB)
4. [ ] All text wrapped in `t()`? No hardcoded Russian/English strings?
5. [ ] Colors use semantic tokens? (bg-primary, text-success, NOT bg-emerald-500)
6. [ ] Text sizes use Tailwind scale? (text-xs, text-sm, NOT text-[9px])
7. [ ] Using shadcn/ui components? (Button, Input, Table, Sidebar, NOT raw HTML)
8. [ ] Errors handled, not silently swallowed? (toast for user-facing, NOT alert())
9. [ ] Stage/status compared by `code`, not by translated `name`?
10. [ ] Frontend build passes? (`docker compose build frontend`)
11. [ ] No `as any`, `@ts-ignore` unless absolutely necessary with comment?
12. [ ] New i18n keys added to BOTH `ru.json` AND `en.json`? (no desync)
13. [ ] Run `/design-check` and `/check-i18n` skills for automated verification?

## Common Pitfalls

- Frontend is a **production build** served by nginx — `import.meta.env.DEV` is always `false` in Docker
- Auth URL routes (`/`, `/register`, `/setup-password`) handled by `useAuthRoute()` in App.tsx; main app pages use `#hash` navigation
- `DATABASE_URL` query params (like `channel_binding=require`) are passed as DB OPTIONS
- Volume mount `./backend:/app` enables hot-reload for backend; frontend needs rebuild (`docker compose up -d --build frontend`)
- `data/products.ts` exports an EMPTY array — it's legacy, use `catalogApi` for real data
