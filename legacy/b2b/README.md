# RailTech B2B SaaS Platform

B2B marketplace and CRM platform for the railway equipment industry. Built with Django 5.1 (backend) and React 18 + TypeScript (frontend).

## Tech Stack

**Backend:** Python 3.11, Django 5.1, Django REST Framework, Django Channels (WebSocket), Celery + Redis, PostgreSQL 15, WeasyPrint (PDF), MinIO (S3)

**Frontend:** TypeScript, React 18, Vite 7, Tailwind CSS 4, shadcn/ui, Zustand, React Query, i18next (EN/RU)

**Infrastructure:** Docker, Nginx, GitHub Actions CI

## Project Structure

```
├── backend/                 # Django REST API
│   ├── accounts/            # Users, Companies, KYC, Roles
│   ├── catalog/             # Products, Categories, Equipment
│   ├── crm/                 # Deals, Quotes, Messages, Chat
│   ├── sourcing/            # Excel import, async tasks
│   ├── master_data/         # Countries, Currencies, Units
│   ├── notifications/       # Notification center
│   └── core/                # Settings, URLs, ASGI, Middleware
├── frontend/                # React SPA
│   └── src/
│       ├── api/             # Axios API clients
│       ├── components/      # UI components (Admin, Auth, Catalog, CRM, etc.)
│       ├── hooks/           # Custom React hooks
│       ├── i18n/            # EN + RU translations
│       ├── pages/           # Page components
│       └── store/           # Zustand state stores
├── Docs/                    # Architecture, specs, roadmap, mockups
├── nginx/                   # Production Nginx config
├── .claude/commands/        # 21 AI development commands
├── docker-compose.yml       # Development environment
├── docker-compose.prod.yml  # Production overrides
├── Makefile                 # Developer convenience commands
└── pyproject.toml           # Python tooling config
```

## Quick Start (Docker)

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — set DJANGO_SECRET_KEY, SUPERADMIN_PASSWORD, DATABASE_URL

# 2. Start all services
make up
# Or: docker compose up -d --build

# 3. Run migrations and seed data
make migrate
make seed

# 4. Open the app
# Frontend:  http://localhost:5173
# Backend:   http://localhost:8000
# Admin:     http://localhost:8000/admin/
# MinIO:     http://localhost:9001
```

## Quick Start (Local)

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Requires PostgreSQL 15+ and Redis 7+ running locally.

## Available Commands

### Make

```bash
make up / down / logs       # Docker lifecycle
make migrate                # Run Django migrations
make test                   # Run all tests
make lint                   # Run all linters
make format                 # Run formatters (black, isort)
make security               # Run security checks
make shell                  # Backend Django shell
make dbshell                # PostgreSQL shell
```

### Claude AI Commands (21 total)

**Frontend:** `/new-component`, `/new-page`, `/new-hook`, `/new-store`, `/lint-fix`, `/build-check`, `/commit`, `/review-pr`, `/check-i18n`, `/audit-a11y`, `/design-check`

**Backend:** `/new-endpoint`, `/new-model`, `/new-celery-task`, `/run-tests`, `/migrate`, `/security-check`, `/deploy-check`, `/docker-up`, `/api-docs`, `/seed-data`

## Environment Variables

See [.env.example](.env.example) for full documentation. Key variables:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection (Neon Cloud or local) |
| `DJANGO_SECRET_KEY` | Django secret key (generate unique!) |
| `REDIS_URL` | Redis for Django Channels |
| `CELERY_BROKER_URL` | Redis for Celery tasks |
| `VITE_API_URL` | Backend URL for frontend |
| `VITE_WS_URL` | WebSocket URL for real-time chat |
| `MINIO_ENDPOINT` | S3-compatible storage |

## Architecture

```
                    ┌──────────────┐
                    │    Nginx     │  (reverse proxy, SSL, rate limiting)
                    └──────┬───────┘
                   ┌───────┴────────┐
            ┌──────┴───┐      ┌─────┴──────┐
            │ Frontend  │      │  Backend   │
            │ React SPA │      │  Django    │
            │ (Vite)    │      │  Daphne    │
            └───────────┘      └──────┬─────┘
                              ┌───────┼────────┐
                        ┌─────┴──┐ ┌──┴───┐ ┌──┴──────┐
                        │  Redis │ │ PG15 │ │  MinIO  │
                        │ (×2)   │ │      │ │  (S3)   │
                        └────┬───┘ └──────┘ └─────────┘
                             │
                        ┌────┴─────┐
                        │  Celery  │  (worker + beat)
                        └──────────┘
```

**Key features:** Domain-driven product catalog (Railway/General/Services), strict RBAC (5 roles), real-time deal chat (WebSocket), async Excel import with smart matching, PDF quote generation, multi-tenant workspaces, i18n (EN/RU).

## Testing

```bash
# All tests
make test

# Backend only
make test-backend
# or: cd backend && python -m pytest --cov --tb=short

# Frontend only
make test-frontend
# or: cd frontend && npm run test
```

## Documentation

Detailed documentation in the `Docs/` folder:

- **Master System Document.md** — Complete architecture blueprint
- **Business_Logic.md** — User journeys, KYC, pricing
- **Technical_Specification.md** — Backend/Frontend/DB specs
- **Role_Model.md** — RBAC (Guest, Client, Sales Manager, Account Manager, Admin)
- **ROADMAP.md** — Sprint plan (7 sprints)
- **Security_Audit_2026-03-20.md** — Security audit findings and fixes

## License

Proprietary. All rights reserved.
