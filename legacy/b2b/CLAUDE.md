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
nginx/                      # Production nginx.conf (rate limiting, caching, WebSocket)
Docs/                       # 23 docs (specs, roadmap, audits, mockups, presentations)
```

## Key Architecture Decisions

- **No React Router** — client-side state machine via `useUserStore.screen` + `useState<Page>` in App.tsx
- **B2B Multi-tenancy** — via `CompanyMember` join table, not schema/DB isolation
- **Deal FSM** — DRAFT → KYC_PENDING → SOURCING → CALCULATING → QUOTE_SENT → CONTRACT_SIGNED → CLOSED_WON/CLOSED_LOST
- **Dual Redis** — redis:6379 (Channels/WebSocket), redis-celery:6380 (Celery broker+results)
- **Dual Storage** — MinIO (public/private/temp buckets) with local filesystem fallback
- **Financial precision** — `decimal.js` on frontend, `DecimalField` on backend, `QuoteItemHistory` audit trail
- **Auth model** — `CustomUser` with email as USERNAME_FIELD, `SystemRole` FK for RBAC

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
- **State:** Zustand stores with `persist` middleware for auth/theme/demo; no Redux

## Testing

- **Backend:** pytest + pytest-django, markers: slow, integration, unit; coverage threshold: 50%
- **Frontend:** vitest + @testing-library/react + jsdom
- **CI:** GitHub Actions — 6 jobs (backend-lint, backend-test, frontend-lint, frontend-build, docker-build, security)

## Common Pitfalls

- Frontend is a **production build** served by nginx — `import.meta.env.DEV` is always `false` in Docker
- `demoStore.isDemoMode` controls simulation buttons on PendingVerificationPage
- No URL-based routing — navigation is state-driven, so browser back/forward doesn't work
- `DATABASE_URL` query params (like `channel_binding=require`) are passed as DB OPTIONS
- Volume mount `./backend:/app` enables hot-reload for backend; frontend needs rebuild (`docker compose up -d --build frontend`)
