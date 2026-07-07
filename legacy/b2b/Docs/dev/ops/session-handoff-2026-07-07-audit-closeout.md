# Session Handoff — 2026-07-07 — Audit 2026-07-02 close-out

**HEAD:** `937b3a4` (after PR #237). Working tree clean, all feature branches pruned.

## What shipped (PR #230–#237)

The entire **architecture + security backlog of audit 2026-07-02** (`docs/audit-2026-07-02-security-arch-ux.md`) is now **closed in code**.

| PR | Item | Summary |
|---|---|---|
| #230 | Docs | Full CLAUDE.md/README/ROADMAP refresh to HEAD; `docker-compose.override.yml.example` template; `make seed`→`core_seed` fix; `docs/audits/*`→`Docs/audits/*` path normalization; dead `JWT_*` removed from `.env.example` |
| #231 | Eyes-on UX | Admin breadcrumbs i18n map (`admin-entitlements`/`-access-log`/`-email-templates`); `useMySubscription` gated on SELLER context (post-login 403 race); nameless-account avatar/name fallbacks |
| #232 | ARCH-03 | Authenticated document PDFs (КП generate/download, deal export-pdf, contract/invoice/act) → 202 + `render_document_pdf` + `crm/views/_pdf.py`; guards stay sync (409); frontend `lib/download.ts` polls the 202 window |
| #233 | ARCH-01 | ALL 8 request-path LLM calls → Celery queue `ai` (dedicated `celery-worker-ai`), 202 + `AIJob` IDOR guard + `ai-status` polling; single-attempt task; extract-document stages files in `default_storage` (not the broker); adversarially verified — 11 findings fixed incl. CRITICAL serializer crash + Redis-broker DoS |
| #234 | Tests | Frontend component tests: AdminDataTable 14 / DealsKanban 7 / GenerateQuoteDialog 6 / DashboardWidgets 9; shared `renderWithProviders` (real ru.json). Node≥23 localStorage polyfill un-broke 16 chronic store tests. Suite 93/93 |
| #235 | Prod fix | `celery-worker` mounts `backend_media_prod` — async-rendered PDFs were landing in a volume the backend couldn't read (would 404-poll forever after #232) |
| #236 | Security tail | SEC-09 (secure-cookie warning if `PRODUCTION` unset), SEC-10 (`init_superadmin` keys on email, no unconditional reset, `--reset-password` flag), SEC-12 (reset_password won't resurrect deactivated accounts), ARCH-09 (audit log → `is_platform_admin`), ARCH-07 (all 14 bare `except Exception` triaged: 2 narrowed, 9 documented barriers, no silent swallows) |
| #237 | ARCH-05 | Unified API error shape `{"detail": CODE}` (81 sites swept, codes byte-identical); frontend detail-first readers; regression guard `core/tests/test_error_shape.py` |

Test counts after merge: backend ~679, frontend 93. Migration heads: `accounts/0033`, `crm/0053`, `sourcing/0007` (AIJob).

## New architecture facts for the next session

- **Two Celery workers now:** `celery-worker` (`-Q default,pdf,imports`) + `celery-worker-ai` (`-Q ai` only). BOTH must mount the backend's media volume (prod: `backend_media_prod`) because pdf/ai tasks write files the backend streams. `core/celery.py` has `autodiscover_tasks(related_name="tasks_ai")`.
- **No LLM call runs in an HTTP handler.** New interactive AI features go through `enqueue_ai_job(feature, payload, user)` (`sourcing/ai_jobs.py`) + a handler in `sourcing/tasks_ai.py` FEATURE_HANDLERS + `frontend/src/lib/aiJob.ts` polling.
- **API errors are always `{"detail": "<CODE>"}`** — guarded by `core/tests/test_error_shape.py`. Celery task result payloads (`result.error`) and WS payloads are a separate contract (excluded).
- `init_superadmin` no longer mutates an existing account — rotation needs `--reset-password`.

## ⚠️ Blocked on the owner

1. **GitHub Actions billing** is failing ("payments failed / spending limit") since ~2026-07-06 13:00 → the CI gates (lint/tests/api-contract/security) and nightly Playwright e2e are DOWN. PRs #231–#237 were validated LOCALLY and merged without CI. The self-hosted deploy runner is unaffected (prod deploys succeeded). **Re-run CI on `main` once billing is restored.**
2. **INF-12** (make the `security` job a required status check) is meaningless until CI runs again.

## What's next

Detailed spec for the remaining work: **`spec-remaining-2026-07-07.md`** (this directory). Ranked: INF-04 backup-gate (highest infra risk) → INF-01 Caddy rate-limit → dependency pinning → staging → product tracks (Client base, AI F6, ADR reconciliation).
