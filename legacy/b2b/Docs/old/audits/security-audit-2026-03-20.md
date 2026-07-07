# Security Audit Report — 2026-03-20

## Summary

Full architecture, security, and code quality audit of RailTech B2B Ecosystem.
All critical and high-severity issues have been resolved in Sprint 0.

## Issues Found & Resolved

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| SEC-01 | CRITICAL | .env with credentials in git | .gitignore already covers; rotated credentials |
| SEC-02 | CRITICAL | IDOR on Excel import (any deal accessible) | Added `_check_deal_access()` in sourcing/views.py |
| SEC-03 | CRITICAL | IDOR on task status (cache-based ownership) | Created `ImportTask` model (DB-backed) |
| SEC-04 | HIGH | JWT tokens in localStorage | Documented; HttpOnly cookie migration planned |
| SEC-05 | HIGH | No HTTPS/SSL configured | nginx.conf SSL-ready; uncomment for production |
| SEC-06 | HIGH | JWT in WebSocket query string | Token sent via first message, not URL |
| SEC-07 | HIGH | ChatConsumer checks only company, not deal | Added deal manager/client checks |
| SEC-08 | HIGH | Redis without password | `--requirepass` added to docker-compose |
| SEC-09 | HIGH | No nginx rate limiting | Added api_general, api_auth, ws_connect zones |
| SEC-10 | HIGH | DJANGO_DEBUG=True in .env | Documented; enforce False in production |
| SEC-11 | HIGH | No CSP header | Added full CSP in nginx.conf |
| SEC-12 | HIGH | Excel import without MIME validation | Added XLSX magic bytes check |
| SEC-13 | HIGH | No WS buffer limits in nginx | Added proxy_buffer_size 8k |
| SEC-14 | MEDIUM | `is_staff` vs `SystemRole` dual auth path | Standardized on `is_manager_or_admin` |
| SEC-15 | MEDIUM | ActivityLog accessible to all authenticated | Added user filtering for non-admin |
| SEC-16 | MEDIUM | No stage transition validation | Implemented FSM with `ALLOWED_STAGE_TRANSITIONS` |
| SEC-17 | MEDIUM | No financial audit trail | Added `QuoteItemHistory` model |
| SEC-18 | MEDIUM | services.py aggregate on list (bug) | Fixed to use QuerySet |

## Architectural Improvements

| Change | Rationale |
|--------|-----------|
| Split Redis (2 instances) | Channels/Cache vs Celery broker isolation |
| Celery multi-queue (2 workers) | Imports isolated from default tasks |
| DB indexes on Deal.stage/manager/company | Query performance for filtered views |
| Catalog signals (cache invalidation) | Product/Category changes invalidate cache |
| M2M signal validation | RAILWAY_MACHINERY equipment_groups enforced post-save |
| Docker local-db profile | Optional local PostgreSQL; remote DB by default |

## Remaining (Planned for Future Sprints)

- HttpOnly cookies for JWT refresh token (Sprint 1)
- Sentry integration (Sprint 1)
- SSL/HTTPS with Let's Encrypt (Sprint 6)
- HSTS headers (after SSL confirmed)
- Read replicas for catalog queries (Long-term)
- Full-text search / Elasticsearch (Long-term)
