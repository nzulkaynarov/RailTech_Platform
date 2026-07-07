# Performance Audit — 2026-04-12

## Scope

Full-stack performance review of the RailTech B2B SaaS platform covering backend query patterns, Celery task resilience, frontend bundle size, Nginx caching, and WebSocket channel configuration.

## Findings and Fixes

### 1. Backend: N+1 Queries in Dashboard Endpoints

**Problem:** Dashboard and analytics views fired individual `.count()` queries per status/stage inside Python loops, causing O(N) database round-trips where a single query would suffice.

**Fix:** Replaced loop-based `.count()` calls with `aggregate()` using conditional `Count('id', filter=Q(...))`. Single query returns all counters at once.

**Pattern:**
```python
# Before (N+1)
for stage in stages:
    result[stage.code] = Deal.objects.filter(stage=stage).count()

# After (single query)
stats = Deal.objects.aggregate(
    total=Count('id'),
    draft=Count('id', filter=Q(stage__code='DRAFT')),
    sourcing=Count('id', filter=Q(stage__code='SOURCING')),
    # ...
)
```

**Impact:** Dashboard API response time reduced from multiple DB round-trips to a single aggregated query.

### 2. Backend: Missing select_related / prefetch_related

**Problem:** List endpoints for Deals, Quotes, and Products triggered lazy-loaded FK queries (stage, company, assigned_to, category, etc.) on every serialized object.

**Fix:** Added `select_related()` for FK fields and `prefetch_related()` for M2M/reverse relations in all list querysets.

### 3. Celery Tasks: Missing Safety Limits

**Problem:** Celery tasks (Excel import, catalog import) had no time limits, retry configuration, or backoff strategy. A stuck task could block a worker indefinitely.

**Fix:** All tasks now have:
- `time_limit=600` (hard kill at 10 minutes)
- `soft_time_limit=540` (SoftTimeLimitExceeded at 9 minutes for graceful cleanup)
- `max_retries=3`
- `autoretry_for=(Exception,)`
- `retry_backoff=True` (exponential backoff)

### 4. Smart Match: Missing Trigram Indexes

**Problem:** `Product.name` and `Product.gost_drawing` trigram similarity searches (`TrigramSimilarity`) performed full table scans without GIN indexes.

**Fix:** Added GIN trigram indexes:
```python
class Meta:
    indexes = [
        GinIndex(name='idx_product_name_trgm', fields=['name'], opclasses=['gin_trgm_ops']),
        GinIndex(name='idx_product_gost_trgm', fields=['gost_drawing'], opclasses=['gin_trgm_ops']),
    ]
```

**Prerequisite:** `pg_trgm` extension must be enabled (handled via migration `CREATE EXTENSION IF NOT EXISTS pg_trgm`).

### 5. Frontend: Bundle Size — Vendor Chunk Splitting

**Problem:** Single vendor chunk exceeded recommended size limits, increasing initial load time.

**Fix:** Configured Vite `manualChunks` to split vendor bundle:
- `react` — React + ReactDOM + React Router
- `charts` — Recharts
- `i18n` — i18next + react-i18next
- `state` — Zustand + React Query
- `radix` — Radix UI primitives (shadcn dependencies)
- `http` — Axios

### 6. Nginx: Authenticated API Cache Leak Risk

**Problem:** Nginx proxy_cache configuration could potentially cache authenticated API responses if `Authorization` header was not properly excluded.

**Fix:** Verified and enforced: Nginx NEVER caches responses for requests with `Authorization` header. Static assets use aggressive caching (1y for hashed assets), API routes use `no-cache`.

### 7. WebSocket Channel Layer Configuration

**Problem:** Default Django Channels layer configuration used conservative capacity limits that could drop messages under load.

**Fix:** Tuned channel layer settings:
- `capacity=300` (up from default 100)
- `expiry=60` seconds

### 8. Exception Handling: Bare except Clauses

**Problem:** Several modules used bare `except Exception` or `except:` which masked specific errors and made debugging difficult.

**Fix:** Replaced with specific exception types (`ValidationError`, `OSError`, `ValueError`, `ObjectDoesNotExist`) throughout business logic in services.py modules.

### 9. View Module Size

**Problem:** `crm/views.py` and `accounts/views.py` exceeded 500 lines, violating the file length convention and making navigation difficult.

**Fix:**
- `crm/views.py` split into package `crm/views/` with 7 modules: deals, quotes, messages, analytics, billing, bids, leads
- `accounts/views.py` split into package `accounts/views/` with 5 modules: company, users, auth, applications, lookups

### 10. Shared Validators

**Problem:** File upload validation (size limits, allowed types, extension checks) was duplicated across multiple apps.

**Fix:** Extracted shared validators into `core/validators.py` and imported from all apps that handle file uploads.

## Conventions Established

All findings led to new coding conventions added to CLAUDE.md:

1. Use `aggregate()` for dashboard stats, never `.count()` in loops
2. Celery tasks require time_limit, soft_time_limit, max_retries, autoretry_for, retry_backoff
3. Specific exception handling only, no bare `except Exception`
4. Descriptive variable names, no single-letter variables in business logic
5. Max 50 lines per function, max 500 lines per module
6. Max 5 parameters per function, use dataclasses for complex signatures
7. Dashboard endpoints use per-user cache with 30-60s TTL
8. List endpoints always use select_related/prefetch_related
9. Frontend vendor chunks split by domain (react, charts, i18n, state, radix, http)
10. Nginx never caches authenticated API responses
