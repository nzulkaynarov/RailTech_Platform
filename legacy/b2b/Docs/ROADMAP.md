# RailTech B2B — Roadmap

**Последняя актуализация:** 2026-07-06 (HEAD `c6cb04f`, после PR #229)

> **Живой канон планирования** — `Docs/ops/`: датированные `session-handoff-*.md` (последний: `session-handoff-2026-07-02-horizon1-security.md`), `roadmap-2026-06-19.md` (фазы F0–F7), `master-scope-2026-06-24.md` (P0-блокеры и клиентская база), `ai-features-roadmap-2026-06-18.md` (F6 #1–#8), `stability-program.md`. Этот файл — верхнеуровневый индекс: что сделано по периодам и какие треки открыты.

---

## Где проект сейчас

Продакшн живёт на `b2b.railtech.uz` (app-VPS + Caddy edge, БД на отдельном DB-VPS через WireGuard; Neon выведен 2026-06-19). Деплой — self-hosted runner (`deploy-b2b.yml`), Sentry на бэке и SPA, CI c жёсткими security-гейтами (pip-audit + npm audit, SHA-pinned Actions). Архитектурный канон — ADR-0001…0006 (`Docs/adr/`).

Ядро продукта (ADR-0006 «клин»): **заявка → КП → контракт** с AI-ускорением как монетизируемым преимуществом. Реализованы: multi-seller routing (DealSellerRouting, скрытая конкуренция), entitlement-слой (FeatureKey: `quote.send`/`quote.export`/`ai.*`/`roles.custom`, DEMO-водяной знак), KYC-пол (без L2 — только просмотр и черновики), AI-разбор заявок + автопривязка каталога в черновике КП, публичная ссылка на КП (202+Celery PDF), дашборд «Operations Inbox».

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

---

## Открытые треки (приоритет ↓)

### Безопасность / инфраструктура
- [ ] INF-12: сделать CI-job `security` обязательным status-check в branch protection (настройка владельца GitHub)
- [ ] ARCH-01 (остаток, High): увести request-path LLM-вызовы из sync HTTP-хендлеров (AsyncAnthropic или Celery) — сейчас ограничены 1×60s, но пиннят ASGI-воркеры
- [ ] ARCH-03 (остаток): авторизованные generate-pdf/download — ещё синхронный WeasyPrint (202-паттерн только на публичном КП)
- [ ] ARCH-05: единый формат ошибок API (`error` vs `detail`, вариант — RFC 9457 на уровне exception handler)
- [ ] Хвост: SEC-09 (secure-cookies только при PRODUCTION=true), SEC-10 (init_superadmin get_or_create + безусловный сброс пароля), SEC-12 (reset_password реактивирует аккаунт), ARCH-07 (14 bare except), ARCH-09 (is_superuser в ActivityLogViewSet)
- [ ] INF-01 edge rate-limit в Caddy; INF-04 backup-gate перед `migrate --noinput`; INF-05/09 пиннинг зависимостей + уход с psycopg2-binary; INF-07 пиннинг minio-образов; INF-08 `volumes: !reset` для /app в прод-compose
- [ ] Staging-окружение (DNS + GitHub environment + Caddy block) — тогда nightly e2e перестанет ходить в прод

### Продукт
- [ ] Клиентская база: CB-send (КП офлайн-контакту), CB-public-link, CB-invite, CB-deal-for-offline, CB-auto-populate (разблокирован MS-routing), инструмент слияния компаний
- [ ] AI F6 (порядок из ai-features-roadmap): #5 билингв-нормализация → #1 семантический матч → #3 КП-vs-заявка diff → #7 pre-flight → #4 reply-assist → #6 PDF-extract → #2 PIM-enrich → #8 conversational; калибровка `AI_DRAFT_MATCH_CONFIDENCE` на реальных данных
- [ ] ADR-0005 Phase E/F: U3 (CompanyRole как единственный источник прав, деприкация WorkspaceRole), ContactViewSet, unified document direction-view, глобальная «+Создать»
- [ ] ADR-0004 G5 (designated primary admin) + G6 (логирование доступа инженера)
- [ ] Сверка cut-list ADR-0006 с кодом: Leads (бэкенд) и Fulfillment живы — амендмент ADR или завершение cut
- [ ] post-deploy-todos: join-existing-company (COMPANY_INN_TAKEN тупик), строгая INN-валидация, внешний S3, owner-UI для can_sell/can_buy, DMARC p=none→quarantine
- [ ] Решения владельца: orphan-эндпоинты `crm/status-choices/` + `sourcing/requests/` (removal pass), supportApi.deleteTicket (не подключён). ReassignProductDialog уже переподключён (a8e8a21, 2026-07-01) — снят с повестки

### Качество
- [ ] Компонентные тесты фронтенда: AdminDataTable / DealsKanban / GenerateQuoteDialog / Operations Inbox (сейчас только stores/hooks/utils, 9 файлов)
- [ ] Backend coverage держится ~78% (гейт 30%) — поднять гейт после стабилизации
- [ ] F4.x структурный долг: onNavigate prop-drilling, userStore↔authStore

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

- [master-system-document.md](master-system-document.md) — архитектура (частично устарел — сверяйтесь с ADR)
- `Docs/adr/0001…0006` — действующие архитектурные решения
- [audit-2026-07-02-security-arch-ux.md](audit-2026-07-02-security-arch-ux.md) + [audit-2026-07-03-ux-ui-eyes-on.md](audit-2026-07-03-ux-ui-eyes-on.md) — последние аудиты (статусы находок)
- `Docs/ops/` — session handoffs, оперативные роадмапы, smoke-чеклисты
