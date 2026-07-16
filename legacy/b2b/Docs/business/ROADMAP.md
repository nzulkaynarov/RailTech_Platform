# RailTech B2B — Roadmap

**Последняя актуализация:** 2026-07-16 (треки-статусы сверены с кодом; закрыты CRM-книга контрагентов, деприкация WorkspaceRole, чистка мёртвого кода)

> **Живой канон планирования** — актуальное ТЗ `Docs/dev/specs/spec-remaining-2026-07-07.md`, последний хендофф `Docs/dev/ops/session-handoff-2026-07-15-quote-builder-wave2.md`, `Docs/dev/ops/stability-program.md`. Историческое (роадмапы, session-handoff'ы, аудиты) — в `Docs/old/`. Этот файл — верхнеуровневый индекс: что сделано по периодам и какие треки открыты. Полная карта документации — `Docs/README.md`.

---

## Где проект сейчас

Продакшн живёт на `b2b.railtech.uz` (app-VPS + Caddy edge, БД на отдельном DB-VPS через приватную сеть хостера; Neon выведен 2026-06-19). Деплой — self-hosted runner (`deploy-b2b.yml`), Sentry на бэке и SPA, CI c жёсткими security-гейтами (pip-audit + npm audit, SHA-pinned Actions). Архитектурный канон — ADR-0001…0006 (`Docs/dev/adr/`).

Ядро продукта (ADR-0006 «клин»): **заявка → КП → контракт** с AI-ускорением как монетизируемым преимуществом. Реализованы: multi-seller routing (DealSellerRouting, скрытая конкуренция), entitlement-слой (FeatureKey: `quote.send`/`quote.export`/`ai.*`/`roles.custom`, DEMO-водяной знак), KYC-пол (без L2 — только просмотр и черновики), AI-разбор заявок + автопривязка каталога в черновике КП, публичная ссылка на КП (202+Celery PDF), дашборд «Operations Inbox».

**Весь архитектурный и security-бэклог аудита 2026-07-02 закрыт в коде** (PR #230–237). ⚠️ Биллинг GitHub Actions сломан с ~2026-07-06 — CI-гейты и nightly e2e не работают; мержи #231–237 валидированы локально, деплой (self-hosted runner) не затронут.

---

## Хроника (сводно)

| Период | Что сделано |
|---|---|
| 2026-03-20…04-17 | Sprint 0–0.8: security hardening, миграция на shadcn/ui, UI/UX-аудит, enterprise hardening (pghistory, Swagger, ADR-0001), единый AppShell |
| 2026-04…05 | Ядро сделок: КП-движок (unit-economics, каскадные charges, цепочка согласования), PDF/Excel/CSV экспорт, email-каналы (EmailLog), WS-уведомления |
| 2026-06-02…19 | Прод-деплой на VPS, миграция БД Neon → DB-VPS (WireGuard), AI-импорт заявок (Claude, prod-live), стабилизационная программа |
| 2026-06-24…30 | ADR-0003/0004: три админ-плоскости, operator sub-roles (SUPPORT/KYC_OFFICER/…), break-glass, CompanyRole-матрица доступа, DocumentProfile + нумерация документов; ADR-0005: единая capability-навигация (T0/T1/T2, page-derived context); ADR-0006 Moves 0–4: целостность цикла, cuts, routing+claim, AI-moat (pricing-assist, AI-draft КП), монетизация (CompanyEntitlement, TTFK-метрика, DEMO-watermark) |
| 2026-07-01…02 | CI-восстановление, tenant-изоляция (React-Query cache), E2E-аудит жизненного цикла F1–F8 (UZS-канонизация валюты, реальный продавец в договоре), Security Horizon-1 (NUM_PROXIES, SHA-pin, enforcing CSP на SPA) |
| 2026-07-03…04 | PR #207–229: SEC-06 lockout, SEC-08 magic-bytes, CSP enforcing (Django+Caddy), ARCH-03 публичный PDF → 202+Celery, ARCH-04 aggregate(), Move 3 детерминированный+fuzzy автоматч, Phase E KYC-пол продавца, UX-аудит полностью (Operations Inbox, адаптивный КП-билдер, deep-link уведомлений), npm audit hard gate, тесты fulfillment+messaging |
| 2026-07-06…07 | **Аудит 2026-07-02 полностью закрыт в коде** (PR #230–237): полный рефреш документации (CLAUDE.md/README/ROADMAP), eyes-on фиксы, **ARCH-03** авторизованные PDF → 202+Celery, **ARCH-01** все 8 request-path LLM-вызовов → Celery-очередь `ai` с выделенным воркером (202+polling, AIJob IDOR-guard, адверсариально верифицирован), компонентные тесты фронтенда (93/93), фикс прод-тома `celery-worker`, security-хвост (**SEC-09/10/12, ARCH-09, ARCH-07**), **ARCH-05** единый формат ошибок `{"detail": CODE}` (81 сайт + guard-тест) |

---

## Открытые треки (приоритет ↓)

> Подробное ТЗ на пункты ниже — **[spec-remaining-2026-07-07.md](../dev/specs/spec-remaining-2026-07-07.md)** (задачи, критерии приёмки, файлы, риски).

### На стороне владельца (не код)
- [ ] Починить биллинг GitHub Actions — CI-гейты и nightly e2e не работают с ~2026-07-06
- [ ] INF-12: сделать CI-job `security` обязательным status-check в branch protection (после биллинга)

### Инфраструктура (аудит 2026-07-02, ещё открыто)
- [ ] INF-04: backup-gate (pg_dump) перед авто-`migrate --noinput` в `entrypoint.sh` — наивысший инфра-риск
- [ ] INF-01: edge rate-limit в Caddy для `/api/v1/auth/*` и `/admin/` (сейчас только DRF app-throttle)
- [ ] INF-05/09: пиннинг зависимостей (`>=` → lock) + уход с psycopg2-binary
- [ ] INF-07: пиннинг minio/minio + minio/mc образов (`:latest`)
- [ ] INF-08: проверить/сбросить наследование `./backend:/app` bind-mount в прод-compose
- [ ] Staging-окружение (DNS + GitHub environment + Caddy block) → активировать deploy-staging.yml; тогда nightly e2e перестанет ходить в прод

### Продукт
- [x] **CRM-слой «книга контрагентов с историей»** (главная продуктовая ценность) — **ПОСТРОЕН**: `CounterpartyRelationship`-ребро (`crm/models/relationships.py`, миграция `crm/0056`) + `RelationshipViewSet` (`crm/views/relationships.py`) + книга «Контрагенты» на фронте (`CounterpartiesPage.tsx`, nav Клиенты/Поставщики); идентичность по ИНН + слияние + CB-auto-populate (`accounts/services/merge.py`: `merge_companies`, `auto_populate_history`); rollup-пересчёт (`recompute_relationship_rollups` cmd). Хвост: калибровка invite-петли на реальных данных.
- [ ] AI: калибровка `AI_DRAFT_MATCH_CONFIDENCE` на реальных данных (все 8 F6-фич уже реализованы — см. spec)
- [x] ADR-0006 амендмент: Leads = **KEEP** — `AdminLeadsPage` жив (`#admin-leads`, `useLeads`); orphan `CRMAnalyticsView` удалён (grep пусто)
- [x] ADR-0005 Phase E U3: деприкация WorkspaceRole **ЗАКРЫТА** (PR #255) — authz ветвится только на `member_has_permission` (CompanyRole), в коде не осталось ветвлений на `has_workspace_role`/`WorkspaceRoleCode`. Остаётся: ADR-0004 G5/G6
- [ ] post-deploy-todos: join-existing-company (COMPANY_INN_TAKEN тупик), строгая INN-валидация, внешний S3, owner-UI для can_sell/can_buy, DMARC p=none→quarantine
- [ ] Решения владельца: orphan-эндпоинты `crm/status-choices/` + `sourcing/requests/` (removal pass — за владельцем)

### Качество / хвост
- [ ] Follow-up ARCH-03: `quotes export?format=pdf` ещё рендерит синхронно — нужен дизайн инвалидации устаревшего PDF
- [ ] Backend coverage держится ~78% (гейт 30%) — поднять гейт после стабилизации
- [ ] F4.x структурный долг: onNavigate prop-drilling, userStore↔authStore
- [ ] Docs hygiene: master-system-document.md частично устарел. (Сделано: dead-config `nginx/nginx.conf` удалён — остался только placeholder `nginx/.gitkeep`; unused `react-router-dom` убран из `frontend/package.json`; мёртвые методы `supportApi.deleteTicket` / `accountsApi.getCompanyTypes` удалены — все без call-sites.)

### P0 коммерческие блокеры (сознательно отложены владельцем — master-scope §2)
- [ ] Платёжный провайдер (Click/Payme) + идемпотентность платежей (UniqueConstraint(invoice, reference))
- [ ] E-IMZO квалифицированная э-подпись
- [ ] Перепроверить ЗРУ-547 (локализация данных) — БД уже на собственном VPS

---

## Deployment Pipeline (факт)

```text
Local Dev
  ↓ .env + docker-compose.override.yml (локальный postgres:17)
  ↓ make up / make migrate / make seed / init_superadmin
  ↓
CI (GitHub Actions): lint, tests, migration-check, api-contract, security (HARD), docker-build
  ↓ merge в main
  ↓
Production (staging пока НЕТ)
  ↓ self-hosted runner → deploy-b2b.yml (prod .env из secrets-heredoc)
  ↓ Caddy edge (TLS, CSP, XFF) — конфиг применяется вручную
  ↓ Sentry (backend + SPA), nightly Playwright e2e (prod-safe)
```

---

## См. также

- `../dev/specs/spec-remaining-2026-07-07.md` — актуальное ТЗ на оставшуюся работу
- `../dev/adr/0001…0006` — действующие архитектурные решения
- `../dev/architecture/master-system-document.md` — архитектура (частично устарел — сверяйтесь с ADR)
- `../old/audits/` — закрытые аудиты (статусы находок); `../old/handoffs/` — session-handoff'ы; `../old/roadmaps/` — прежние роадмапы
- `../README.md` — полная карта документации
