# RailTech B2B SaaS Frontend

B2B SaaS platform for the railway equipment industry. Built with React 18 + TypeScript, bundled with Vite 7, styled with Tailwind CSS 4 and shadcn/ui (New York theme).

## Quick Start

```bash
npm install          # Install dependencies
npm run dev          # Start dev server on port 5174
npm run build        # Type-check (tsc -b) then Vite build
npm run lint         # ESLint (flat config, v9)
npm run lint:tsc     # TypeScript check without emit
npm run preview      # Preview production build
```

## Architecture

```
src/
├── api/             # Axios client + domain API modules
├── components/      # UI and domain components
│   ├── ui/          # shadcn/ui primitives + custom reusable components
│   ├── Auth/        # Login, KYC registration, password setup
│   ├── Cabinet/     # Client dashboard, company profile, team settings
│   ├── Catalog/     # Product catalog (grid/table views, product cards)
│   ├── Dashboard/   # Dashboard widgets (deal split view, contextual chat)
│   ├── Layout/      # AppShell, ManagerShell, ErrorBoundary
│   ├── Shared/      # ErrorBoundary, FABSupportButton, OnboardingTour
│   ├── Admin/       # Admin panels (nomenclature, users, KYC, quotes, analytics)
│   └── Sourcing/    # Sourcing hub, quote builder, Excel upload
├── pages/           # Top-level page components
├── store/           # Zustand state stores (auth, user, cart, flow, task, domain, theme)
├── hooks/           # React Query hooks per domain
├── i18n/            # i18next config + locale JSON files (ru, en)
├── lib/             # Shared utilities (cn())
├── utils/           # Validation schemas (Zod), decimal utilities
├── layouts/         # AppShell layout wrapper
├── data/            # Mock/static data
└── assets/          # Images, icons
```

## Key Technologies

| Technology | Purpose |
|-----------|---------|
| React 18 + TypeScript | UI framework |
| Vite 7 | Build tool |
| Tailwind CSS 4 | Styling |
| shadcn/ui (New York) | UI component library |
| Zustand | Global state management |
| React Query | Server state / data fetching |
| i18next | Internationalization (ru, en) |
| Zod | Schema validation |
| Axios | HTTP client with JWT interceptors |
| Lucide React | Icons |

## Internationalization (i18n)

All user-facing text uses the i18next translation system:

- **Languages**: Russian (default), English
- **Locale files**: `src/i18n/locales/ru.json`, `src/i18n/locales/en.json`
- **Usage**: `const { t } = useTranslation()` then `t('key.path')`
- **Key sections**: `common`, `auth`, `catalog`, `dashboard`, `quote`, `admin`, `team`, `company`, `profileForm`, `passwordSetup`, `registration`, `nomenclaturePanel`, `userPanel`, `kycManager`, `nav`, `errors`

### Adding new translations

1. Add the key to both `ru.json` and `en.json`
2. Use `t('section.key')` in JSX
3. For interpolation: `t('key', { variable: value })`

## State Management

All global state is managed with Zustand (no React Context):

| Store | Key | Purpose |
|-------|-----|---------|
| `authStore` | `railtech-auth` | JWT tokens, login/logout, role mapping |
| `userStore` | — | Screen routing, company status, KYC |
| `cartStore` | — | Shopping cart items |
| `flowStore` | — | Procurement flow, deal stages |
| `taskStore` | — | Background task tracking |
| `domainStore` | — | Domain/company status |
| `themeStore` | — | Theme preferences |

## API Integration

- **Base URL**: `${VITE_API_URL}/api/v1`
- **Auth**: JWT Bearer tokens with automatic refresh on 401
- **Error handling**: Centralized `getErrorMessage()` utility
- **React Query**: staleTime 3min, gcTime 10min

## Authentication

1. Login via `POST /api/v1/auth/token/`
2. Tokens stored in Zustand → persisted to localStorage
3. Automatic token refresh via Axios interceptor
4. Roles: `GUEST`, `CLIENT`, `SALES_MANAGER`, `ACCOUNT_MANAGER`, `ADMIN`
5. KYC levels: `L1_UNVERIFIED`, `PROFILE_SUBMITTED`, `L2_VERIFIED`, `L3_CONTRACTED`

## Error Handling

- Root `<ErrorBoundary>` wraps `<MainApp>` in `App.tsx`
- API errors use `getErrorMessage()` for user-friendly messages
- Silent catch blocks include `console.error()` for debugging

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `VITE_API_URL` | Backend API base URL |
| `VITE_WS_URL` | WebSocket URL for real-time features |

## Claude Code Integration

Custom slash commands are available in `.claude/commands/`:

| Command | Purpose |
|---------|---------|
| `/commit` | Smart commit with conventional format |
| `/lint-fix` | ESLint lint + auto-fix |
| `/build-check` | Full TypeScript + Vite build verification |
| `/review-pr` | PR code review checklist |
| `/new-component` | Generate shadcn/ui component scaffold |
| `/new-page` | Generate page component scaffold |
| `/new-hook` | Generate React Query hook + API module |
| `/new-store` | Generate Zustand store |
| `/audit-a11y` | Accessibility audit checklist |
| `/check-i18n` | Find missing translations and i18n issues |

## Docker

Multi-stage build: Node 20 (build) → Nginx Alpine (serve). Build args: `VITE_API_URL`, `VITE_WS_URL`.
