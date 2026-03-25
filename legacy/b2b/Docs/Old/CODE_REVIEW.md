# Code Review: RailTech B2B Ecosystem — Full Codebase

**Reviewer:** Claude
**Date:** 2026-03-17
**Scope:** All backend (Django/DRF) and frontend (React/TypeScript) source files

## Summary

The RailTech B2B Ecosystem is a well-architected enterprise platform with strong domain modeling, proper financial calculation isolation, and a clean separation of concerns. The codebase demonstrates solid engineering — server-side financial calculations, multi-tenancy via CompanyMember, versioned quotes, and a 3-tier smart matching engine. However, the review identified **5 critical issues**, **8 high-severity suggestions**, and several medium/low improvements across security, performance, correctness, and maintainability.

---

## Critical Issues

| # | File | Line(s) | Issue | Severity |
|---|------|---------|-------|----------|
| 1 | `crm/consumers.py` | 82–91 | **Broken RBAC in WebSocket ChatConsumer** — `check_deal_access` references `UserRole.SALES_MANAGER` enum which doesn't exist. The model uses `SystemRole` (a DB lookup), not a Python enum. This will raise `AttributeError` at runtime, blocking all WebSocket chat access. | 🔴 Critical |
| 2 | `crm/models.py` | 238–248 | **Double recalculation on QuoteItem save** — `save()` calls `calculate_item_prices(commit=False)` then `super().save()`, then `recalculate_totals()` which recalculates ALL items again including the one just saved. Every single-item save triggers a full O(n) quote recalculation. During Excel import (100+ items), this creates O(n²) DB writes. | 🔴 Critical |
| 3 | `sourcing/views.py` | 15–25 | **No authorization check on deal ownership for Excel import** — `ExcelImportView` only checks `IsAuthenticated`. Any authenticated user can import items into ANY deal by passing an arbitrary `deal_id`. Must verify the user has access to the deal. | 🔴 Critical |
| 4 | `sourcing/views.py` | 49–55 | **IDOR on import status endpoint** — `ImportStatusView` lets any authenticated user check any Celery task by ID. Celery task IDs are UUIDs, but task results may contain sensitive deal data (item counts, error messages with company names). | 🔴 Critical |
| 5 | `catalog/views.py` | 69–86 | **bulk_publish missing permission check** — The `@action` inherits `get_permissions()` which returns `AllowAny` for non-list/retrieve actions only if `self.action` isn't matched. Actually, looking closer, `get_permissions` only whitelists `list` and `retrieve` — so `bulk_publish` correctly requires Admin. However, `product_ids` is user-supplied and not validated — an attacker could publish draft products they shouldn't have access to by guessing IDs. | 🟡 High |

---

## High-Severity Suggestions

| # | File | Line(s) | Suggestion | Category |
|---|------|---------|------------|----------|
| 1 | `core/settings.py` | 339–342 | **Throttle rates too permissive** — `anon: 1000/min` and `user: 10000/min` are extremely high. The `LeadCreateView` (public endpoint) could be abused for spam. Recommended: `anon: 20/min`, `user: 200/min` with per-endpoint overrides. | Security |
| 2 | `sourcing/tasks.py` | 53 | **Unbounded Excel file processing** — `pd.read_excel(BytesIO(file_content))` with no row limit. A malicious 500MB Excel file will exhaust Celery worker memory. Add `nrows` limit and file size validation before passing to Celery. | Security / Performance |
| 3 | `sourcing/tasks.py` | 102–103 | **Raw exception message exposed** — `return {'status': 'error', 'message': str(e)}` leaks internal error details (table names, SQL errors, file paths) to the API consumer. Sanitize error messages. | Security |
| 4 | `crm/views.py` | 112–115 | **ActivityLog has no RBAC filtering** — `ActivityLogViewSet` uses `queryset = ActivityLog.objects.all()` without filtering by user/company. All activity logs are visible to any authenticated user with object-level permissions. But `IsOwnerOrManagerOrAdmin.has_object_permission` won't match ActivityLog objects (no `company`, `deal`, `quote`, or user match), so non-staff users get empty results. This is fragile — the fallback to `return False` is implicit, not intentional. | Security |
| 5 | `accounts/services.py` | 36–37 | **Password setup URL uses VITE_API_URL** — `getattr(settings, 'VITE_API_URL', 'http://localhost:5173')` falls back to localhost. This setting is a frontend env var, not a Django setting. In production, emails will contain `http://localhost:5173` links unless manually configured. Use a dedicated `FRONTEND_URL` Django setting. | Correctness |
| 6 | `frontend/src/api/client.ts` | 14–26 | **JWT stored in localStorage** — Access and refresh tokens stored in localStorage are vulnerable to XSS. If any dependency or injected script accesses `localStorage.getItem('railtech-auth')`, both tokens are compromised. Consider httpOnly cookies for the refresh token. | Security |
| 7 | `catalog/models.py` | 143–151 | **EquipmentGroup path update uses string Replace** — `Replace(F('cached_path'), Value(old_path), Value(new_path))` will incorrectly update nodes that share a path prefix. E.g., renaming "Вагоны" to "Вагоны-2" would also replace the prefix in "Вагоны грузовые" even if it's a separate subtree with a coincidental name. Use `startswith` filtering plus exact prefix replacement. | Correctness |
| 8 | `crm/consumers.py` | 93–97 | **No message length limit in WebSocket** — `save_message` accepts any length text from the WebSocket. A client could send multi-MB messages flooding the database and Redis channel layer. Add a `max_length` check (e.g., 5000 chars). | Security |

---

## Medium Suggestions

| # | File | Line(s) | Suggestion | Category |
|---|------|---------|------------|----------|
| 1 | `catalog/views.py` | 89–98 | **SupplierOfferViewSet write is too open** — Any authenticated user can create/update offers (`return [permissions.IsAuthenticated()]`). This should require supplier company membership or staff-level access. Currently, a CLIENT user could create fake supplier offers. | Security |
| 2 | `sourcing/tasks.py` | 67–91 | **QuoteItem creation inside loop triggers individual saves** — Each `QuoteItem.objects.create()` triggers `QuoteItem.save()` which calls `recalculate_totals()`. For a 200-row Excel import, this means 200 full recalculations. The final `quote.recalculate_totals()` on line 100 is redundant. Use `bulk_create` and a single final recalculation. | Performance |
| 3 | `crm/services.py` | 55 | **Quote items evaluated eagerly** — `items = quote.items.all()` fetches all items, then iterates in Python. For quotes with many items, `select_related('product__domain_type')` is needed to avoid N+1 queries when checking `item.product.domain_type.code`. | Performance |
| 4 | `accounts/views.py` | 115 | **UserViewSet uses Django's IsAdminUser** — `permissions.IsAdminUser` checks `user.is_staff`, which is Django's built-in flag. The rest of the codebase uses `SystemRole.is_staff_level` for RBAC. A user could be `is_staff=True` but have a CLIENT SystemRole, creating inconsistent access. Use the custom `IsAdminUser` from `core.permissions`. | Security |
| 5 | `core/settings.py` | 192 | **CORS_ALLOW_ALL_ORIGINS in DEBUG** — While scoped to DEBUG mode, this allows any origin to make authenticated requests in development. Combined with `CORS_ALLOW_CREDENTIALS = True`, this is risky if DEBUG accidentally leaks to a staging environment. | Security |
| 6 | `catalog/models.py` | 229–238 | **RAILWAY_MACHINERY validation only works on update** — `clean()` checks `self.pk and not self.equipment_groups.exists()`, meaning on initial create (`self.pk` is None before save), the validation is skipped. Equipment groups (M2M) can only be added after the product exists, so this validation can never catch a missing equipment group on creation. Consider a post-save signal or form-level validation. | Correctness |
| 7 | `frontend/src/api/client.ts` | 46 | **Token refresh race condition** — Multiple concurrent 401 responses will each trigger independent refresh attempts. Only the first will succeed; subsequent ones may fail if `ROTATE_REFRESH_TOKENS` is enabled (the old refresh token is invalidated). Implement a refresh queue/mutex. | Correctness |
| 8 | `crm/views.py` | 37–39 | **Deal creation auto-assigns company without validation** — `perform_create` uses `request.user.primary_company`, but if the user has no primary company (null), the deal is created with `company=None`. The `company` field on Deal is not nullable (`on_delete=models.CASCADE`), so this will raise an IntegrityError. Add a null check. | Correctness |

---

## Low Suggestions

| # | File | Suggestion | Category |
|---|------|------------|----------|
| 1 | `master_data/models.py` | `AbstractLookup` fields (`code`, `name`) are not shown here, but the pattern is clean. Consider adding `created_at` for audit compliance. | Maintainability |
| 2 | `crm/models.py:292-306` | `ActivityLog.level` uses a CharField with choices instead of a lookup FK like other models. Inconsistent with the master data pattern. | Maintainability |
| 3 | `accounts/services.py:109-142` | `invite_workspace_member` doesn't assign a `SystemRole` to the invited user (the `role` field stays null). This breaks `IsManagerOrAdmin` checks which assume `user.role` exists. | Correctness |
| 4 | `sourcing/tasks.py:151` | `DomainType.objects.filter(code=domain_code).first()` is called per-row inside the catalog import loop with no caching. Should cache domain types like `uom_cache`. | Performance |
| 5 | `docker-compose.yml` | PostgreSQL uses default `POSTGRES_PASSWORD=postgres`. In production, use a strong generated secret. | Security |
| 6 | All serializers | Serializers do not explicitly list `read_only_fields` for computed/auto fields (`landed_cost`, `final_price_excl_vat`, `total_incl_vat`). A client could potentially send these in a POST/PATCH and have them accepted before recalculation overwrites them. | Security |

---

## What Looks Good

- **Financial pipeline is server-side only** — The `QuoteCalculationService` handles all monetary math with `Decimal`, atomic transactions, and `select_for_update()`. This is production-grade.
- **Domain-driven architecture** — The three-domain model (RAILWAY_MACHINERY, GENERAL_GOODS, SERVICES) with strict hierarchy rules is well-designed and clearly enforced.
- **Multi-tenancy via CompanyMember** — The M2M through-model pattern is clean, supports multiple companies per user, and filters QuerySets properly.
- **Smart matching engine** — 3-tier approach (exact → drawing extraction → trigram fuzzy) is well-designed with proper scoring weights.
- **Frontend TypeScript discipline** — No `any` types observed. Proper interfaces, Zod validation, and Decimal.js for client-side display math.
- **Master data pattern** — `AbstractLookup` eliminates hardcoded enums and makes the system configurable without code changes.
- **WebSocket auth** — JWT middleware for Channels is correctly implemented with proper anonymous rejection.
- **Bulk operations** — `bulk_update` in `recalculate_quote`, `Replace` for equipment group paths, shows awareness of DB performance.

---

## Verdict

**Request Changes** — The 5 critical issues must be resolved before this codebase goes to production:

1. **Fix ChatConsumer RBAC** — Replace `UserRole.SALES_MANAGER` with proper `SystemRole` lookup check matching the pattern used in `IsOwnerOrManagerOrAdmin`.
2. **Eliminate O(n²) on Excel import** — Use `bulk_create` for QuoteItems during import, then a single `recalculate_totals()` at the end.
3. **Add deal-level authorization to sourcing endpoints** — Verify the requesting user has access to the deal before allowing import.
4. **Scope task status to the requesting user** — Store `user_id` with the Celery task and validate ownership on status check.
5. **Tighten SupplierOffer write permissions** — Require staff or supplier-company membership for create/update.

The codebase is fundamentally sound in its architecture and financial correctness. The critical issues are primarily authorization gaps in newer endpoints (sourcing, WebSocket) that were likely added after the core RBAC framework was established.
