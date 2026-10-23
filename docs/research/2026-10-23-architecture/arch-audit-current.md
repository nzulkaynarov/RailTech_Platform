# Аудит текущей технической архитектуры RailTech Platform (as-is)

Дата: 2026-10-22 · Срез: `main` @ 5bace3d4 · Режим: только чтение (код, compose, документы; стенд не поднимался).
Назначение: исходный материал для целевой архитектуры с интеграционной шиной.
Все пути — от корня репозитория; `file:line` указывают на место факта. Где строка приблизительная — помечено `~`.

Сокращения: CRM = `apps/crm/backend/app`, ERP = `apps/erp/backend`, BFF = `apps/platform/bff/app`,
WEB = `apps/platform/web/src`, C = `packages/contracts`, IC = `infra/compose`.

---

## 0. Короткий итог

- Топология: **два сервера**. VPS1 — все приложения, Caddy, Redis, RustFS, LiteLLM; VPS2 — один PostgreSQL 17
  (базы `crm`, `erp`, `litellm`, `langfuse`) и контейнер бэкапов (`IC/prod.yml:1-8`, `IC/db.yml`, `infra/deploy/db-up.sh:1-48`).
- Шов CRM↔ERP — **точка-точка**: вебхуки ERP→CRM (журнал в БД ERP + Celery, HMAC v2), REST CRM→ERP
  (`/api/integration/v1`, Bearer), MCP CRM-бот→`erp-mcp`, SSO-JWT HS256 на общем секрете. Шины нет; Redis Streams
  для Платформы — только в ADR-0011 п.5 (фаза P4), в коде отсутствует.
- Получатель событий ERP **один и задан строкой окружения** `CRM_WEBHOOK_URL` — подписок, fan-out и секретов на
  получателя нет. Это главный блокер для «шины».
- Надёжность доставки ERP→CRM приличная (журнал, ретраи 6 шагов до 24 ч, инбокс с дедупом в CRM), но **эмиссия
  события теряется молча**: обработчики сигналов глотают исключения.
- Данные клиента после передачи (`handoff`) **не синхронизируются** ни в одну сторону; бренд, SMTP, бюджет ИИ,
  адреса фронтендов настраиваются в двух местах.
- **Файлы ERP лежат на локальном томе `erp_media`**, не в RustFS, и не попадают в бэкапы; бакеты RustFS тоже не
  бэкапятся.
- Наблюдаемость минимальна: JSON-логи есть, но нет метрик, нет Sentry в проде, нет сквозного request-id через
  CRM→ERP/вебхуки/очереди, у Caddy нет access-логов.

---

## 1. Карта компонентов и связей

### 1.1. Сервисы compose (prod = `base.yml` + `prod.yml`)

| Сервис | Где | Образ / команда | Память (prod) | Зависит (prod) | Примечание |
|---|---|---|---|---|---|
| `caddy` | VPS1 | caddy:2.11.7 | 64M | crm-api, crm-web, erp-backend, erp-web, cabinet-web — `service_healthy`; platform-* — `service_started` (`IC/base.yml:577-596`) | единственный вход 80/443 (`IC/prod.yml:328`), 4 домена |
| `crm-migrate` | VPS1 | `alembic upgrade head` (`IC/base.yml:228-235`) | 384M | — | одноразовый |
| `crm-api` | VPS1 | `python -m app api` | 512M | crm-migrate, s3-init, litellm, litellm-seed (`IC/prod.yml:143-151`) | **в том же процессе** Telegram-бот (lifespan `CRM/main.py:80-95`) |
| `crm-worker` | VPS1 | Procrastinate worker | 512M | то же | очереди в PG |
| `crm-mcp-kb/crm/docs` | VPS1 | `python -m app mcp <x>` :8101-8103 | 3×256M | то же | MCP для агента CRM |
| `crm-web` | VPS1 | статика Refine/AntD | 64M | — | будет отключён на T4 (ADR-0011 п.6) |
| `erp-backend` | VPS1 | daphne ASGI :8000 (`IC/base.yml:352`) | 768M | redis (`IC/prod.yml:229-231`) | REST internal/portal/integration, WebSocket, admin |
| `erp-mcp` | VPS1 | `python -m integration.mcp` :8104, профиль `mcp` (`IC/prod.yml:242-254`) | 256M | — | ORM в процессе |
| `erp-worker` | VPS1 | celery `-Q default,pdf,imports` (`IC/base.yml:445`) | 512M | — | |
| `erp-worker-ai` | VPS1 | celery `-Q ai --concurrency=2` (`IC/base.yml:462`) | 384M | — | |
| `erp-beat` | VPS1 | celery beat, DatabaseScheduler (`IC/base.yml:479`) | 192M | — | **без healthcheck** |
| `erp-ai-gateway` | VPS1 | `manage.py ai_gateway_sync`, одноразовый (`IC/base.yml:489-499`) | 256M | — | регистрирует ключ ERP в LiteLLM |
| `erp-web` | VPS1 | статика shadcn | 64M | — | будет отключён на T4 |
| `cabinet-web` | VPS1 | nginx-статика | 64M | — | API — ERP `/api/portal/*` через Caddy |
| `platform-bff` | VPS1 | FastAPI, без БД | 256M | redis (`IC/base.yml:552-554`) | Redis DB 3 — сессии |
| `platform-web` | VPS1 | статика AntD | 64M | — | |
| `redis` | VPS1 | redis 7.4, `--maxmemory 100mb --maxmemory-policy noeviction` (`IC/prod.yml:91`) | 128M | — | DB0 Langfuse, DB1 Celery, DB2 Channels+cache ERP, DB3 BFF (`IC/base.yml:105-107`) |
| `rustfs` + `s3-init` | VPS1 | rustfs 1.0.1, порт на `APP_INTERNAL_IP:9000` (`IC/prod.yml:97`) | 512M | — | бакеты `langfuse kb-sources client-documents tg-attachments erp backups` (`IC/prod.yml:102`) |
| `litellm` + `litellm-seed` | VPS1 | свой образ rt-litellm; БД `litellm` на VPS2 (`IC/prod.yml:104-120`) | 768M | — | единый ИИ-шлюз по алиасам |
| `docling` | VPS1 | профиль `kb-ingest` (`IC/prod.yml:122-125`) | 1536M | — | в проде выключен (`DOCLING_URL: ""`, `IC/prod.yml:37`) |
| `clickhouse`, `langfuse-web/worker` | VPS1 | профиль `observability` | 768/768/512M | — | в проде по умолчанию выключены (`infra/.env.prod.example:22` → `RT_PROFILES=mcp`) |
| `postgres` | VPS2 | pgvector-pg17, TLS самоподписанный, pg_hba только IP VPS1 (`infra/deploy/db-up.sh:23-33`) | — | — | в prod-compose VPS1 под профилем `local-db` (не стартует, `IC/prod.yml:83-86`) |
| `backup` | VPS2 | `infra/db/Dockerfile.backup` + `backup.sh` | — | — | ежедневно 22:00 UTC |

### 1.2. Схема

```
                          Интернет (браузер сотрудника, клиент, Telegram, SMTP-релей, CBU)
                                               │ 80/443
                                       ┌───────▼────────┐  без access-логов, без X-Request-ID
                                       │     Caddy      │  crm.* / erp.* / cabinet.* / platform.*
                                       └┬────┬────┬────┬┘
          crm.*: /api,/telegram/webhook │    │    │    │ platform.*: /api → bff, остальное → platform-web
                  ┌─────────────────────┘    │    │    └──────────────────────────────┐
                  ▼                 erp.*: /api,/admin,/ws,/media                     ▼
        ┌──────────────────┐        cabinet.*: /api/portal,/media      ┌───────────────────────┐
        │ crm-api (+бот)   │◄─────────────┐  │                         │ platform-bff (без БД) │
        │ FastAPI          │  (6) HTTP    │  ▼                         │ сессия → Redis DB3    │
        └─┬──┬──┬──┬──┬──┬─┘  sync, 3 c   ┌────────────────────┐      └───┬──────────┬────────┘
          │  │  │  │  │  │ ◄──────────────┤ erp-backend daphne │◄─────────┘ (6) HTTP   │
   (1)    │  │  │  │  │  │   токен сотр.  │ DRF + Channels     │   sync 3 c, токен      │
 Procrast.│  │  │  │  │  └──────┐         └─┬───────▲──────┬───┘   сотрудника (SSO)   │
  в PG    │  │  │  │  │ (8) LLM │ (2) REST  │       │ (3)  │ ORM                       │
          ▼  │  │  │  │ OpenAI  │ Bearer,   │ Celery│ вебхук│                          │
 ┌────────────┐ │  │  │ API     │ 10 c,     │ Redis │ HMAC  ▼                          │
 │ crm-worker │─┘  │  │         │ из очереди│ DB1   │ v2  ┌──────────┐                 │
 │ handoff,   │────┼──┼─────────┼──────────►│       │     │ erp-mcp  │◄── (4) MCP      │
 │ provision, │    │  │         │           ▼       │     │ :8104    │   HMAC-контекст │
 │ events,    │    │  │         │  ┌──────────────┐ │     └──────────┘   из crm-api    │
 │ email      │    │  │         │  │ erp-worker   │─┘                                  │
 └────────────┘    │  │         │  │ erp-worker-ai│──── SMTP (sync в задаче/запросе)   │
   │SMTP(CRM)      │  │         │  │ erp-beat     │──── CBU (курсы), ТН ВЭД            │
   ▼               │  │         │  └──────────────┘                                    │
 SMTP-релей        │  │         ▼                                                      │
 (настроен в БД    │  │  ┌─────────────┐   (8) LLM алиасы intake/match/draft/enrich      │
  CRM)             │  │  │  LiteLLM    │◄── erp-worker-ai / erp-backend                │
                   │  │  └──────┬──────┘                                               │
 Telegram API ◄────┘  │         │ ключи/бюджеты                                        │
 (5) polling/webhook  │         ▼                                                      │
                      │  ════════════ VPS2 ═══════════════════════════════════════     │
                      └─►║ PostgreSQL 17: crm │ erp │ litellm │ langfuse ║◄───────────┘ (BFF в БД не ходит)
                         ║ backup → локально 14 дн → RustFS VPS1 → внешн.S3 (выкл) ║
                         ═════════════════════════════════════════════════════════
 RustFS (VPS1): kb-sources, client-documents, tg-attachments, backups, langfuse ← только CRM/Langfuse/бэкап;
                бакет `erp` создаётся, но ERP пишет файлы в локальный том erp_media (!)
 Redis (VPS1, 100 МБ noeviction): DB1 Celery broker+results, DB2 Channels+Django cache, DB3 BFF-сессии, DB0 Langfuse
```

### 1.3. Матрица вызовов

| # | Откуда → куда | Механизм | Синхр./асинхр. | Повтор | Таймаут | Источник |
|---|---|---|---|---|---|---|
| 1 | CRM-API → crm-worker | Procrastinate (таблицы в PG `crm`) | асинхр. | `RetryStrategy` на задачу (handoff/provision: 6 попыток, линейно 30 с) | — | `CRM/tasks/erp_handoff.py:17`, `CRM/tasks/erp_users.py:11-33` |
| 2a | crm-worker → ERP `/clients/handoff` | REST, Bearer, `Idempotency-Key` = uuid5(client, hash тела) | асинхр. (задача после коммита, `CRM/services/clients.py:208`) | 6 попыток, 429 → `Retry-After` (`CRM/tasks/erp_retry.py:17-29`) | 10 с | `CRM/integrations/erp.py:481-563`, `CRM/domain/erp_handoff.py:25-37` |
| 2b | crm-worker → ERP `/users/provision`, `DELETE /users/{id}/sessions` | REST, Bearer | асинхр. | 6 попыток; ключ идемпотентности — **новый uuid4 на вызов** (`CRM/integrations/erp_users.py:67`) | 10 с | `CRM/integrations/erp_users.py:52-90` |
| 2c | CRM-API → ERP `/companies/{id}/summary` (дебиторка в карточке) | REST | **синхр. в запросе пользователя**, деградирует в «недоступно» | нет | 10 с | `CRM/api/v1/clients.py:115` → `CRM/services/erp_client_card.py:48`, `CRM/integrations/erp_company.py:55` |
| 2d | CRM-API → ERP pairing accept/rotate, externals switch, health | REST | синхр. | нет | 10 с / 5 с | `CRM/integrations/erp_pairing.py:130-216`, `CRM/integrations/erp_externals.py`, `CRM/integrations/erp.py:301-317` |
| 3 | ERP → CRM `POST /api/v1/integrations/erp/events` | вебхук, HMAC v2 | асинхр. (журнал + Celery `on_commit`) | 60 с, 5 мин, 30 мин, 2 ч, 6 ч, 24 ч → FAILED (`ERP/integration/tasks.py:38`); Beat-подбор зависших каждые 300 с (`ERP/core/settings/infra.py:53-59`) | 10 с (`ERP/integration/tasks.py:131`) | `ERP/integration/services/webhooks.py:289-362` |
| 3' | CRM приём → crm-worker `process_erp_event` | инбокс `erp_incoming_events` + Procrastinate | асинхр. (кроме `quote.acceptance_code_requested` — синхронно, `CRM/services/erp_events.py:364-372`) | 3 попытки задачи + sweep каждую минуту, `MAX_ATTEMPTS=5` → `failed` (`CRM/services/erp_events.py:165,501-513`) | — | `CRM/tasks/erp_events.py:9-36` |
| 4 | crm-api (бот) → erp-mcp | MCP streamable HTTP, `X-Agent-Context` HMAC, TTL 60 с, одноразовый `jti` | синхр. в диалоге | 401 → 1 повтор; 429 → ≤2 повтора (≤5 с) | 10 с | `CRM/agents/erp_mcp.py:4-9,83,141-160`, `CRM/security/erp_agent_context.py:21-60` |
| 5 | crm-api ↔ Telegram Bot API | aiogram, polling (по умолч.) или webhook | вход — фон. задача `asyncio` в процессе API (`CRM/bot/runtime.py:163-173`), выход — синхр. | нет (уведомления по событиям ERP — at-most-once, `CRM/services/erp_events.py:745`) | 10 с на send | `CRM/config.py:65` |
| 6 | BFF → CRM `/api/v1/*`, ERP `/api/v1/*` | REST с токеном сотрудника, `X-Request-Id` | синхр.; агрегаты — параллельно с частичными ответами (`sources`) | нет; только refresh токена под Redis-блокировкой | 3 с (`BFF/clients/base.py:17`) | `BFF/auth.py:120-189,307-335`, `BFF/feeds/feed.py:1-30` |
| 7 | Cabinet SPA → ERP `/api/portal/v1` | cookie `portal_session`; вход Telegram `initData` или magic link | синхр. | — | — | `ERP/portal/authentication.py:13-39`, `ERP/portal/services/telegram_auth.py:21-64` |
| 8 | CRM, ERP → LiteLLM | OpenAI API по алиасам | синхр. (бот), асинхр. (ERP — очередь `ai`) | CRM: 1 ретрай клиента + `fallback-model` через тот же LiteLLM (`CRM/agents/llm.py:3,105-118`) | 20 с (CRM) | `infra/ai/litellm.models.yaml`, `ERP/ai/services/gateway.py:45` |
| 9 | SSO CRM → ERP | JWT HS256 на `PLATFORM_SSO_SECRET`, ≤60 с, одноразовый `jti` | синхр. | — | — | `C/sso-token.md:7-8`, `CRM/services/sso.py:50-92`, `ERP/accounts/services/sso.py:147-198` |
| 10 | ERP → SMTP | Django `get_connection`, **без `EMAIL_TIMEOUT`** (grep по `ERP/core/settings` пуст) | синхр. в задаче или в запросе (приглашение в handoff) | нет | ОС-дефолт | `ERP/notifications/emails.py:153-~230` |
| 11 | CRM → SMTP | задача `send_email` (Procrastinate) | асинхр. | по стратегии задачи | — | `CRM/integrations/smtp.py`, таблица `email_log` |
| 12 | ERP-beat → CBU | HTTP | асинхр. | Celery | — | `ERP/finance/services/fx.py:28`, `ERP/core/seeds/beat.py:24` |
| 13 | backup (VPS2) → RustFS (VPS1) → внешний S3 | rclone | асинхр., раз в сутки / неделю | — | — | `infra/db/backup.sh:44-67` |

---

## 2. Дублирование и конфликты между CRM и ERP

| Предмет | CRM | ERP | Источник истины | Синхронизация | Где возможны расхождения |
|---|---|---|---|---|---|
| Пользователи / сотрудники | `User` (`CRM/models/auth.py:31`; `platform_access` :78, `erp_role_codes` :84, `platform_roles` :87, `erp_sync_error` :94) | `CustomUser` (`ERP/accounts/models/users.py:13`) + `CrmUserMapping` (`ERP/integration/models.py:85`) | CRM (ADR-0003, ADR-0010) | CRM→ERP провижининг (`CRM/tasks/erp_users.py:18,24` → `ERP/integration/services/provision.py:67,177`) | `position`, `language` не передаются; имя после первой синхронизации принадлежит ERP (`provision.py:111-113`); у ERP остаются свои пароль/сброс/2FA (`ERP/core/urls.py:177-209`, `ERP/accounts/services/auth.py:68` не проверяет `CrmUserMapping`) — против ADR-0010 §3; ERP-only сотрудники создаются мастером (`ERP/accounts/wizard.py:262`) |
| Роли | `CRM/domain/erp_roles.py:18`, CHECK в `CRM/models/auth.py:41-45`, `platform_roles_generated.py`, casbin | `Permission`/`BackofficeRoleCode`/`ROLE_TEMPLATES` (`ERP/accounts/constants.py:27,96,110`), `CompanyMember.crm_granted_roles` | `C/platform-rbac.yaml` (генерация в CRM и BFF `BFF/rbac_generated.py`) | `role_codes` в провижининге | роли, выданные вручную в ERP «Команда», CRM не видит и не снимает (`provision.py:47-55`); каталог ролей ERP скопирован в 4 места (кортеж CRM, CHECK БД, OpenAPI, константы ERP) |
| Клиент / компания | `Client` (`CRM/models/clients.py:35`, `erp_company_id` :51) | `Company` (`ERP/parties/models/core.py:59`) + `CrmClientMapping` (`ERP/integration/models.py:20`) | CRM до передачи; после — **никто** | однократный `POST /clients/handoff`, сопоставление по ИНН (`ERP/integration/services/handoff.py:100-110`) | эндпоинта обновления компании нет: смена названия/ИНН ни туда, ни обратно |
| Контакты | `ClientContact` (`CRM/models/clients.py:132`) | `Contact` (`ERP/parties/models/contacts.py:8`) + `CrmContactMapping` (`ERP/integration/models.py:58`) | CRM | только при handoff; `PUT /contacts/{crm_contact_id}` в ERP есть (`ERP/integration/views.py:94-97`), **CRM его не вызывает** | правки/удаления контактов в CRM не доходят; контакт ERP = учётная запись Cabinet |
| Сделка / заявка | `Deal` (`CRM/models/deals.py:24`, `erp_deal_id` :48, `external_stage` :49) + `Lead.erp_request_id` (`CRM/models/leads.py:61`) | `Deal` (`ERP/sales/models/deals.py:17`), `DealStage` | ERP после передачи; CRM — зеркало | события ERP → инбокс CRM → зеркало, порядок по `occurred_at` (`CRM/services/erp_events.py:180-185,671-725`) | три словаря стадий (CRM open/won/lost, `external_stage`, `DealStage`); две ссылки на одну заявку (`Lead.erp_request_id`, `Deal.erp_deal_id`); потерянное событие (см. §4.1) = зеркало застывает без сигнала |
| Документы и индекс | `Document` (`CRM/models/clients.py:60`, `erp_document_id` :97), `DocumentAccessLog` :100 | `GeneratedDocument` (`ERP/documents/models/documents.py:94`), PDF КП/договоров/счетов/актов | ERP (файл); CRM — индекс без файла (`storage_key=None`, `CRM/services/erp_event_handlers.py:190-229`) | `document.created` → upsert; ссылка по запросу `GET /documents/{id}/link` (10 мин) | нет `document.deleted/cancelled` — аннулированные остаются в CRM, ссылка 404 |
| Уведомления | Telegram команде/клиенту (`CRM/services/notifications.py`, `staff_notifier.py`, `erp_bot_messages.py`), `system_alerts` | in-app `Notification` + Channels (`ERP/core/models/notifications.py:19`, `ERP/notifications/consumers.py:15`), письма Celery | каждый своё | события ERP порождают Telegram в CRM | клиент получает одно и то же дважды (письмо ERP + Telegram CRM) разными текстами; `crm.send_payment_reminders` нигде не запланирован |
| Бренд / реквизиты | `settings.company` в БД (`CRM/schemas/settings.py:29-51`) | `SystemSetting.platform_name/support_email/logo_url/domain` (`ERP/core/models/settings.py:50-65`), `CompanyDocumentProfile` (логотип, реквизиты печати) | заявлено CRM: ERP помечает поля `SHARED_FIELDS` «managed in CRM» и отвергает запись (`ERP/core/views/settings.py:16-17`) | **нет** (в CRM даже нет этих полей) | `PLATFORM_NAME` не передан ни одному контейнеру ERP → в письмах «ERP» (`ERP/notifications/emails.py:~181`); Django admin правит `platform_name` в обход (`ERP/core/admin.py:32`); `cabinet_url` — в БД CRM и в env ERP `CABINET_URL` |
| Почта / SMTP | раздел `integrations.smtp` в БД + `integration_secrets` (`CRM/schemas/settings.py:346-359`), шаблоны-файлы, `email_log` | env `EMAIL_*`/`EMAIL_<CH>_*` из `SMTP_*` (`IC/prod.yml:63-68`, `ERP/core/settings/observability.py:22-50`), файлы + `EmailTemplate` в БД, `EmailLog` | каждый своё | нет | один релей настраивается дважды (UI CRM и `.env.prod`); письма приглашения/сброса пароля есть в обеих системах |
| Курсы валют | нет (валюта сделки без пересчёта) | `ExchangeRate`/`Currency` (`ERP/core/models/master_data.py:57,116`), beat из CBU | ERP | — | внутри ERP срок годности курса дважды: env `FX_RATE_MAX_AGE_DAYS` и `CompanySettings.fx_rate_max_age_days` |
| Очереди | Procrastinate в PG (handoff, provision, events, email, эскалации, отчёты; periodic каждые 1–15 мин) | Celery на Redis DB1 + DatabaseScheduler (вебхуки, письма, PDF, ИИ, FX) | каждый своё | — | два разных рантайма, две модели ретраев, две админки; Celery зависит от Redis 100 МБ |
| Файлы | RustFS: `kb-sources`, `client-documents`, `tg-attachments`, `backups` (`CRM/config.py:40-48`) | `MINIO_*` → `erp-public/private/temp` (`ERP/core/settings/project.py:65-76`), но **`MINIO_ENDPOINT` нигде не задан** → `FileSystemStorage` на томе `erp_media` (`IC/prod.yml:225-227`) | — | — | бакет `erp` создаётся и не используется; файлы ERP вне RustFS и вне бэкапа |
| Аудит / журналы | `audit_log` (`CRM/models/auth.py:131`), `document_access_log`, `stage_transitions`, `erp_incoming_events` | `ActivityLog` (`ERP/sales/models/deals.py:135`), pghistory, `IntegrationWebhookEvent` | каждый своё | — | нет общего correlation-id; межсистемное действие (provision, handoff) не связать |
| ИИ | алиасы dialog/qualifier/judge/fallback/embed, `llm_usage`, бюджеты в БД (`CRM/schemas/settings.py:333-340`) | алиасы intake/match/draft/enrich (`ERP/core/settings/ai.py:11`), `AICall`, бюджет из env `AI_DAILY_BUDGET_USD` | шлюз LiteLLM общий | CRM читает `GET /ai-usage` | бюджет ERP дважды: `budget.erp_daily_usd` в CRM (только отображение, `CRM/services/ai_spend.py:134`) и env (`IC/base.yml:375`), реально действует env |
| Выключатели внешних сервисов | `ExternalServiceSwitch` (`CRM/models/external_services.py:80`) | `ERP/core/models/external_services.py:5` | CRM | `PUT /externals/{code}/switch`, синхронно | рассинхрон при сбое вызова или ручной правке в ERP |
| Товары / цены | `products` в БЗ (`CRM/models/kb.py:37`), цены бота из текста БЗ | каталог (`ERP/catalog/models/products.py:22`), НДС, маржа | ERP де-факто | нет | бот может назвать цену, отличную от каталога/КП |
| Тексты статусов клиента | `settings.texts` (БД, редактируемо) | шаблоны писем ERP | `C/client-statuses.yaml` | тесты сверяют ключи | формулировки расходятся после правки в админке CRM |

---

## 3. Отказоустойчивость

### 3.1. Компонент → отказ → последствия → защита сейчас

| Компонент | Отказ | Последствия для бизнеса | Защита сейчас |
|---|---|---|---|
| **CRM API** (`crm-api`) | процесс упал / 5xx | Бот молчит (бот в том же процессе); веб-форма «Я новый клиент» в Cabinet не работает; **вход в Платформу невозможен** (`BFF/auth.py:120-189` → `backend_unavailable("crm")`); SSO в ERP невозможен; приём вебхуков ERP → события копятся в журнале ERP | ERP: ретраи до ~32,6 ч, затем FAILED + ручной replay суперпользователем (`ERP/integration/admin.py:56-72`); Telegram хранит апдейты ~24 ч; прямой вход в ERP по паролю остаётся (ADR-0010) |
| **crm-worker** | стоп | Handoff, провижининг, обработка событий ERP, письма, эскалации, отчёты стоят; данных не теряется (всё в PG) | Procrastinate-задачи в PG; sweep инбокса; `procrastinate healthchecks` в compose |
| **ERP backend** | упал / 5xx | ERP и **Cabinet полностью недоступны** (Cabinet — только фронтенд над ERP); Платформа — сессия открывается с `erp_state="unavailable"`, экраны с частичными данными (`BFF/auth.py:41,183-188`); карточка клиента CRM без дебиторки; бот без данных ERP («не могу проверить»); **handoff** — 6 попыток с линейной паузой ≈ 7,5 мин, затем `failed`, повтор вручную | частичная деградация BFF (`sources`); идемпотентность handoff; Caddy не перезапускается при падении ERP, **но при холодном старте не поднимется**, пока ERP не healthy (`IC/base.yml:577-586`) |
| **erp-worker / erp-beat** | стоп | Вебхуки в CRM не уходят (PENDING в журнале), PDF и письма ERP стоят, курсы не обновляются; при стопе beat не подбираются зависшие события | журнал в PG + `requeue_stuck_webhook_events` (если beat жив); у `erp-beat` **нет healthcheck** (`IC/base.yml:476`) |
| **Redis** (VPS1, 100 МБ, noeviction) | падение или заполнение | ERP: кэш Django на Redis без игнорирования ошибок (`ERP/core/settings/infra.py:8-14`) → throttling, SSO-`jti`, health-кэш падают → массовые 5xx; Celery-брокер и результаты; Channels (живые уведомления); **все сессии Платформы** (DB3) — разлогин; Langfuse-очередь. CRM не затронута | только healthcheck; volume `redis_data` (RDB по умолчанию); при noeviction переполнение = отказ записи, а не вытеснение |
| **PostgreSQL VPS2** | недоступен | **Остановка всего**: CRM (и её очереди Procrastinate), ERP (и журнал вебхуков), LiteLLM (ключи/бюджеты), Langfuse; Платформа не войдёт (CRM) | бэкап раз в сутки + дамп перед деплоем; реплики/standby нет; RPO до 24 ч |
| **RustFS** | недоступен | CRM: загрузка/выдача документов клиента, вложения Telegram, БЗ; ежедневная копия бэкапа не ляжет; Langfuse. ERP не затронут (файлы на локальном томе) | нет; бакеты не бэкапятся (`docs/runbooks/deploy.md:184`) |
| **LiteLLM** | недоступен | Бот: `LlmUnavailableError` → честно передаёт человеку (`CRM/services/budget.py:5`); `fallback-model` идёт **через тот же шлюз** — от отказа шлюза не спасает; ИИ-импорт ERP (очередь `ai`) падает | таймаут 20 с + 1 ретрай; бюджеты |
| **Telegram API** | недоступен | Клиенты не получают сообщения бота; уведомления по событиям ERP **теряются** (отметка `notified_at` ставится до отправки, `CRM/services/erp_events.py:745`, осознанный at-most-once) | лог `erp_event_telegram_failed`; таймаут 10 с |
| **SMTP** | недоступен / висит | ERP: приглашение в Cabinet отправляется **синхронно внутри `transaction.atomic()` handoff** (`ERP/integration/services/handoff.py:233,265-270` → `ERP/portal/services/invitation.py:48`); без `EMAIL_TIMEOUT` зависание SMTP держит транзакцию и advisory-lock, CRM получает таймаут 10 с и повторяет; ошибка доставки не роняет handoff (`handoff.py:198-207`). Письма КП/счетов — в Celery | журнал `EmailLog`; выключатель «mail» из CRM |
| **Caddy** | упал | Всё внешнее недоступно: 4 домена, Telegram webhook (если режим webhook), Cabinet, вебформа | `restart: unless-stopped`; один экземпляр |
| **BFF** | упал | Только Платформа (502); CRM/ERP/Cabinet работают (`IC/base.yml:587-592`, INF-P1-0) | изоляция в Caddy |
| **erp-mcp** | упал / профиль выкл. | Бот отвечает «не могу проверить» по заказам/документам | `ERP_MCP_ENABLED`, деградация в CRM |
| **VPS1 целиком** | сбой хоста | Всё, кроме БД; файлы ERP (`erp_media`) и RustFS — **единственная копия** на этом хосте | нет |

### 3.2. Где синхронная зависимость ломает пользовательский путь

1. **Вход в Платформу без CRM** — невозможен: логин, `/me` и выдача SSO-токена идут в CRM синхронно (`BFF/auth.py:120-189`).
   Это следствие ADR-0011 п.3 («вход один — через CRM»), но и CRM-API, и бот, и IdP — один процесс.
2. **Передача лида без ERP** — асинхронна (задача после коммита), но окно повторов короткое (≈7,5 мин,
   `CRM/tasks/erp_handoff.py:17`); дальше `failed` и ручной повтор. Отложенной до-доставки (часы) нет.
3. **Cabinet без ERP** — полностью неработоспособен по конструкции (ADR-0004).
4. **Карточка клиента CRM** — синхронный вызов ERP в запросе (`CRM/services/erp_client_card.py:48`), до 10 с ожидания.
5. **Platform-экраны** — все данные тянутся синхронно с таймаутом 3 с, опрос каждые 30 с (`BFF/feeds/feed.py:22-27`);
   событийного канала (Redis Streams, ADR-0011 п.5) нет.
6. **Handoff в ERP** — синхронный SMTP внутри транзакции (см. 3.1).
7. **Выключатели внешних сервисов** — синхронный `PUT` в ERP из CRM без повтора.

### 3.3. Механизмы надёжности — что есть

| Механизм | Есть? | Где |
|---|---|---|
| Outbox (ERP → CRM) | частично: строка журнала пишется в `post_save`, задача — `on_commit`; атомарна с бизнес-изменением только если вызывающий код в `atomic()` (`ATOMIC_REQUESTS` нет) | `ERP/integration/services/webhooks.py:289-362`; хороший пример — `ERP/sales/services/delivery_lines.py:179` |
| Outbox (CRM → ERP) | нет: задача Procrastinate ставится **после** коммита клиента (`CRM/services/clients.py:208`), хотя очередь в той же БД | — |
| Inbox / дедуп | CRM: `erp_incoming_events` (PK `event_id`) + дедуп по sha256 тела (`CRM/models/integrations.py:54-110`, `CRM/services/erp_events.py:404-420`) | — |
| Идемпотентность входа ERP | `handle_idempotency` на handoff и provision; ключ обязателен, тело хэшируется, 7 дней; **без блокировки/insert-first** — параллельные одинаковые запросы оба исполняются (handoff защищён `pg_advisory_xact_lock`) | `ERP/integration/idempotency.py:25-76`, `ERP/integration/services/handoff.py:49-54` |
| DLQ | нет отдельной; статус `FAILED` в журнале ERP и `failed` в инбоксе CRM; replay только в ERP admin; в CRM replay `failed/rejected` нет | `ERP/integration/tasks.py:46-64,213-227` |
| Circuit breaker | **нет нигде** (grep `circuit|breaker` по CRM/ERP/BFF — только комментарии) | — |
| Таймауты | CRM→ERP 10 с, health 5 с; ERP→CRM 10 с; BFF 3 с; MCP 10 с; LLM 20 с; SMTP ERP — нет | см. §1.3 |
| Пул соединений | CRM создаёт новый `httpx.AsyncClient` на каждый вызов (`CRM/integrations/erp_http.py:25-90`); BFF — общий клиент на бэкенд | — |
| Rate limit | ERP integration 300/мин на токен (`ERP/integration/views.py:67-73`); BFF логин 10/мин; MCP-гейт 429 | — |

---

## 4. Текущие интеграционные механизмы

### 4.1. Вебхуки ERP → CRM

- **Эмиссия**: `pre_save/post_save` на 6 моделях (Deal, Quote, Contract, Invoice, Act, Fulfillment) —
  `ERP/integration/signals.py:402-423`, документы — `:431-492`; часть событий — из сервисов. Каталог —
  `VALID_EVENT_TYPES`, 22 типа (`ERP/integration/services/webhooks.py:34-57`).
- **Тихая потеря**: каждый обработчик обёрнут в `except Exception: logger.error` (`ERP/integration/signals.py:134-135`,
  также `:188,247,290,340`) — бизнес-изменение коммитится, события нет, сигнала тревоги нет.
- **Журнал** `IntegrationWebhookEvent` (`ERP/integration/models.py:163-251`): `event_id` UUID, `target_url` на строке,
  `payload`, `headers`, `status` PENDING/SENT/FAILED, `attempts`, `next_attempt_at`, `last_error`.
- **Доставка**: Celery `deliver_webhook_event` (`ERP/integration/tasks.py:67-210`), ретраи `[60,300,1800,7200,21600,86400]`
  (`:38`), `visibility_timeout` Redis 25 ч (`ERP/core/settings/infra.py:50`), подбор зависших каждые 300 с, допуск 10 мин.
  Нет секрета — событие ждёт PENDING без счёта попыток (`tasks.py:83-88`). Код акцепта — маска в журнале, значение в
  кэше 20 мин; истёк — FAILED `SECRET_EXPIRED` (`webhooks.py:116-162`).
- **Подпись v2**: `X-Event-Id`, `X-Event-Type`, `X-Timestamp`, `X-Signature: sha256=HMAC(secret, "{id}.{ts}.{body}")`
  (`webhooks.py:85-92`), переподпись на каждой попытке (`tasks.py:111-119`). Секрет — из сопряжения (БД) или
  `ERP_WEBHOOK_SECRET` (список через запятую, подписывает первый; `webhooks.py:60-68`).
- **Приём в CRM**: `POST /api/v1/integrations/erp/events` (`CRM/api/v1/integrations.py:235-262`): подпись по текущему и
  предыдущему секрету → окно ±300 с → Pydantic → инбокс → задача. **`ERP_WEBHOOK_SIGN_LEGACY=true` по умолчанию**
  (`CRM/config.py:99`, `IC/base.yml:59`, и в `infra/.env.prod.example:143`) — принимается подпись v1 «только тело»,
  защита от повтора тогда держится лишь на дедупе по хэшу.
- **Обработка**: зеркало сделки, заметка лида, Telegram-outbox в строке события (`CRM/services/erp_events.py:515-659`).

### 4.2. Integration API ERP (`/api/integration/v1`)

- 15 эндпоинтов (`ERP/integration/urls.py:26-42`): handoff, contacts, company summary/deals, deal и его документы,
  ссылка на документ, поиск по каталогу, users provision/sessions, ai-usage, health, pairing accept/rotate, externals switch.
- Аутентификация — `Bearer` сервисного токена, до двух активных с часом перекрытия при ротации; токены в
  `ServiceCredential` (Fernet, ключ производный от `DJANGO_SECRET_KEY`, `ERP/integration/services/credentials.py:36-38`),
  env — запасной путь (`ERP/integration/authentication.py:18-43`, `ERP/integration/models.py:306-345`).
- Публикуется наружу: Caddy отдаёт весь `/api/*` домена ERP в `erp-backend` (`infra/caddy/Caddyfile.prod:61-63`) — то
  есть машинный API доступен из интернета (как и `/admin`). CRM при этом ходит к ERP по внутренней сети.
- Слот `ERP_TO_CRM` генерируется и хранится, но **ничем не проверяется** (`ERP/integration/models.py:309`); env
  `SERVICE_TOKEN_ERP_TO_CRM` в примерах окружения есть, в коде не читается.

### 4.3. MCP

- `erp-mcp` — отдельный процесс, порт 8104, путь `/mcp/erp`, вызывает ORM в процессе (`ERP/integration/mcp/tools.py:18-37`),
  гейт: контекст (401), rate limit (429), одноразовый `jti`, проверка аргументов (400). Инструменты: `list_client_deals`,
  `get_deal_status`, `get_delivery_status`, `list_client_documents`, `get_document_link`, `search_catalog`, `create_request`.
- Схемы — из `C/mcp-tools.json` (смонтирован read-only, `IC/prod.yml:249-253`); нет файла — сервис не стартует.
  Версия `0.1.0` только парсится (`ERP/integration/mcp/contract.py:84`), согласования версий нет; CRM сверяет схемы
  аргументов тестом (`apps/crm/backend/tests/unit/agents/test_erp_tools_contract.py`).
- Собственные MCP CRM (kb, crm, docs) — `CRM/mcp/{kb,crm,docs}_server.py`, наружу закрыты (`Caddyfile.prod:21-26`).

### 4.4. SSO и провижининг

- SSO: CRM выпускает JWT HS256 (`iss`, `aud`, `sub`=crm_user_id, `exp−iat ≤ 60`, `jti`) только если у пользователя
  есть `erp` в `platform_access` (`CRM/services/sso.py:50-92`); ERP проверяет и хранит `jti` в кэше Redis 10 мин
  (`ERP/accounts/services/sso.py:147-198`). Не JWKS: общий симметричный секрет в двух сервисах.
- Провижининг: CRM → `POST /users/provision`, `DELETE /users/{id}/sessions` (`ERP/integration/services/provision.py:67,177`).
  Payload: email, имя, роль, права, `is_active`, `role_codes`. Ошибки — в `User.erp_sync_error`.

### 4.5. Сопряжение (pairing, ADR-0009)

- Одноразовый код 12 символов, TTL 15 мин, хранится хэш; CRM генерирует 3 секрета (токен CRM→ERP, токен ERP→CRM,
  секрет вебхуков); первое сопряжение — `X-Pairing-Proof` (HKDF от `PLATFORM_SSO_SECRET`)
  (`ERP/integration/services/pairing.py:95-189`, `ERP/integration/views.py:301-345`). Модель слотов — жёстко «CRM».

### 4.6. Портал (Cabinet)

- `/api/portal/v1`, cookie `portal_session` или заголовок, хэш сессии в `PortalSession` (`ERP/portal/authentication.py:13-39`).
- Вход: Telegram `initData` (HMAC по токену бота, окно 300 с, сопоставление по `Contact.telegram_user_id`) или magic link.
- «Пользователи» кабинета — это `parties.Contact`, созданные handoff-ом (`ERP/integration/services/handoff.py:135-208`).

### 4.7. Версионирование и схема-проверки

| Контракт | Версия | Проверка в рантайме |
|---|---|---|
| `C/openapi/erp-integration.yaml` | `info.version 0.6.1` | нет (путь `/v1`) |
| `C/openapi/erp-portal.yaml` | 0.3.0 | нет |
| `C/openapi/erp-internal.yaml` | 1.0.0 (сгенерирован из ERP) | нет |
| `C/openapi/platform-bff.yaml` | 0.2.4 | тесты BFF по схеме |
| `C/events.schema.json` | `version: const 1`, `additionalProperties: false` (`:7-18`) | ERP — jsonschema, режим `log` в проде (`ERP/core/settings/api.py:196`); CRM — **ручная копия** на Pydantic с `version: Literal[1]` (`CRM/schemas/erp_events.py:229`), неизвестный тип → `skipped`, `version: 2` → `rejected` |
| `C/mcp-tools.json` | 0.1.0 | ERP парсит, CRM — тест |
| `C/platform-rbac.yaml`, `C/client-statuses.yaml` | `version: 1` | генерация + тесты |

Политика (`docs/architecture/CONTRACTS.md:199-203`): префикс `v1`, несовместимое — новый префикс; события — поле `version`, новые
поля без смены версии. Общие примеры событий `C/examples/events/` проверяются тестами обеих сторон. **OpenAPI CRM в
`packages/contracts` нет** (лежит в `apps/crm/docs/api/openapi.json`), хотя BFF его потребляет.

### 4.8. Что пришлось бы менять для нового потребителя событий (BFF Платформы, коннектор 1С)

Сейчас получатель — одна строка `CRM_WEBHOOK_URL` (`ERP/core/settings/api.py:186-189`), копируемая в `target_url`
каждой строки журнала (`ERP/integration/services/webhooks.py:326`). Секрет один; события по компаниям без
`CrmClientMapping` отбрасываются (`webhooks.py:253-261`). Для второго потребителя нужно:

1. Модель подписки (URL, секрет, фильтр типов, версия схемы, состояние) и UI/админка.
2. Fan-out в `emit_event`: по строке журнала на подписчика; ретраи и replay на подписчика.
3. Секреты и сопряжение на подписчика (сейчас слоты `CRM_TO_ERP/ERP_TO_CRM/WEBHOOK` — `ERP/integration/models.py:306-310`).
4. Убрать требование `CrmClientMapping` для эмиссии (1С интересны все контрагенты).
5. Для обратного направления (CRM → 1С/BFF) — **источника событий в CRM нет вообще**: CRM ничего не публикует.
6. Для BFF — ещё канал доставки в браузер (сейчас опрос каждые 30 с).
7. Схема-реестр: сейчас CRM держит ручную копию схемы; второй потребитель — третья копия.

Вывод: текущий механизм — «надёжный вебхук на одного адресата», не шина. Журнал ERP — хорошая основа outbox,
если сделать запись атомарной и вынести маршрутизацию в отдельный слой.

---

## 5. Конфигурация и секреты

### 5.1. Где что настраивается

| Слой | CRM | ERP | BFF |
|---|---|---|---|
| `.env` (один файл на ансамбль: `.env.example` — 64 переменные, `infra/.env.prod.example` — 81; генерация `IC/make-env.sh`, `infra/deploy/make-env-prod.sh`) | `CRM/config.py` (pydantic-settings); в контейнер — только перечисленное в `x-crm-backend` (`IC/base.yml:13-64`) | `ERP/core/settings/*.py` через `os.environ` | `BFF/config.py:13-20` |
| БД, key/value | таблица `settings` JSONB (`CRM/models/leads.py:159`, схема `AppSettings` `CRM/schemas/settings.py:417`): компания, часы, тексты, эскалации, БЗ, бот, бюджет, интеграции (URL ERP, SMTP) | `SystemSetting` синглтон (`ERP/core/models/settings.py:25`), `CompanySettings` (`ERP/parties/models/company_settings.py:10`), `django_celery_beat` | — |
| БД, секреты | `integration_secrets` (Fernet, `SECRETS_KEY`) — токен CRM→ERP, секрет вебхуков, SMTP | `ServiceCredential` (Fernet от `DJANGO_SECRET_KEY`), TOTP | — |
| Файлы-контракты в рантайме | casbin, `litellm.models.yaml` | `events.schema.json`, `mcp-tools.json` (bind из релиза, `IC/prod.yml:74-79`) | `rbac_generated.py` (сгенерирован) |

### 5.2. Дубли и ловушки

- `erp_base_url`: env (`CRM/config.py:93`) и БД (`CRM/schemas/settings.py:369`, БД побеждает). SMTP в CRM — так же.
- `WEBHOOK_SECRET(_PREVIOUS)`, `SERVICE_TOKEN_CRM_TO_ERP`: у ERP — env или БД; у CRM — только БД («Подключения»).
  Смена `.env` CRM не обновляет; первичное равенство даёт только генератор env.
- Ротация `ERP_SECRET_KEY` молча делает нечитаемыми `ServiceCredential` и TOTP (`ERP/integration/services/credentials.py:36-38`) → откат на env.
- `PLATFORM_SSO_SECRET` в двух сервисах (`IC/base.yml:57,383`) — ротация одновременно; `ERP_MCP_CONTEXT_KEY`
  обязателен у ERP (`:?`, `IC/base.yml:382`) и необязателен у CRM (`:-`, `IC/base.yml:54`).
- `LITELLM_MASTER_KEY` CRM использует **как рабочий ключ** (`IC/base.yml:33`), ERP — как запасной (`IC/base.yml:373`);
  ключи Langfuse ERP падают на ключи CRM (`IC/base.yml:496-497`).
- `S3_ACCESS_KEY/SECRET` — один ключ на RustFS, s3-init, CRM и бэкап (`infra/deploy/make-env-prod.sh:46-47`): нет
  разделения прав по бакетам.
- `REDIS_PASSWORD` — один на ERP (Celery, Channels, кэш), BFF, Langfuse.
- `TELEGRAM_BOT_TOKEN` — в CRM и ERP (`IC/base.yml:39,396`).
- Фронтенд-адреса: `ERP_FRONTEND_URL` (CRM) и `FRONTEND_URL` (ERP); `CRM_FRONTEND_URL` (ERP env) против
  `settings.company.crm_base_url` (БД CRM); `CABINET_URL` (ERP env) против `settings.company.cabinet_url` (БД CRM).
- `PLATFORM_NAME` есть в `.env.example:98`, но не передан в ERP; `SUPPORT_EMAIL` передан, но объявлен «управляемым CRM».
- Внутри ERP: НДС (`SystemSetting.vat_rate` и `CompanySettings.default_vat_rate`), маржа — дважды.
- Флаги поведения в env, а не в БД: `ERP_WEBHOOK_SIGN_LEGACY`, `PLATFORM_SSO_ENABLED`, `ERP_MCP_ENABLED`, `AI_DAILY_BUDGET_USD`.

---

## 6. Темы и токены дизайна

### 6.1. Как устроено

- Источник — `packages/ui-tokens/tokens.json` v0.2.0: `color{primary, info, success, warning, error, text, surface, tag}`,
  `font`, `radius`, `density`, `antdComponents`. **Палитра одна, светлая**; тёмного набора нет.
- `packages/ui-tokens/build.mjs` (`:2-5,208-232`) выпускает: `dist/tokens.css` (`--rt-*`), `dist/shadcn.css` (`:root` +
  Tailwind 4 `@theme inline`, комментарий «.dark задаёт приложение», `:83`), `dist/antd.ts` (`RT_TOKENS`,
  `RT_COMPONENTS`) с копиями в CRM, ERP и Cabinet. Копию для Платформы делает не `build.mjs`, а
  `apps/platform/Makefile:41-52` (`tokens`, `tokens-check`).
- Платформа: `WEB/app/theme.ts:40-90` — `cssVar: true`, `...RT_TOKENS`, затем переопределение захардкоженными
  `PF_COLORS` и `TAG_TEXT` (`WEB/app/theme.ts:19-38`); **нет `algorithm`**; `ConfigProvider theme={appTheme}` статичен
  (`WEB/app/providers.tsx:20`). `RT_TOKENS` сам фиксирует светлые `colorBgContainer #ffffff`, `colorText #1f1f1f`
  (`WEB/app/tokens.generated.ts:17,42-46`).
- ERP: `apps/erp/frontend/src/index.css` импортирует `shadcn.css`, имеет custom variant `dark` и **полный рукописный
  блок `.dark`** (`:50-88`); переключатель `store/themeStore.ts:17,25` по настройке пользователя.
- Cabinet: частичный `.dark` (только статусы, `apps/cabinet/src/index.css:21-34`), включается по `colorScheme` Telegram.
- CRM: `apps/crm/frontend/src/app/theme.ts:20-33` — `cssVar`, `RT_TOKENS`, без `algorithm`; CSS чистый (102 `var(--ant-*)`).

### 6.2. Можно ли переключать тему без правки компонентов

| Приложение | Светлая/тёмная | «Как в ERP» (палитра shadcn) | Что мешает |
|---|---|---|---|
| ERP | да | да (правкой `tokens.json`/`index.css`) | `.dark` рукописный, не из токенов |
| Cabinet | частично | да | `.dark` только статусы, база — от Telegram |
| CRM | почти | почти | нет `algorithm`; светлые значения `RT_TOKENS` перебьют `darkAlgorithm` |
| **Платформа** | **нет** | **нет** | (1) нет тёмной палитры в `tokens.json`/`build.mjs`; (2) нет `algorithm` и состояния темы; (3) **183 hex-литерала в 25 файлах** (`shared/ui/ui.css` 46, `shared/ui/shell.css` 38, `app/theme.ts` 12, `modules/admin/org/org.css` 11, `features/notifications/notifications.css` 9, `shared/lib/statuses.ts:19-25` 7…), в CSS Платформы **ноль** ссылок на `var(--ant-*)`/`--rt-*`; (4) `PF_COLORS`/`TAG_TEXT`/`statuses.ts` дублируют токены; (5) меню прибиты `theme="light"` (`ModuleMenu.tsx:122`, `ContextPanel.tsx:77`, `ModuleRail.tsx:66`); (6) inline-цвета `AvatarMenu.tsx:77`, `ContextPanel.tsx:78`, `ModuleMenu.tsx:124`, `ModuleRail.tsx:68`, `ActivityPanel.tsx:37` |

Общий разрыв: AntD-выход и shadcn-выход не имеют общего тёмного источника; семантических токенов
(surface/elevated/border-subtle и т. п.) нет — только «сырые» цвета палитры.

---

## 7. Наблюдаемость и эксплуатация

### 7.1. Логи

- CRM: structlog, JSON по умолчанию (`CRM/log.py:58-102`, `CRM/config.py:32`), маскирование секретов/PII (`CRM/log.py:51-52`).
- ERP: свой `JSONFormatter` (`ERP/core/logging.py:64-~85`), в проде `DJANGO_LOG_FORMAT=json` (`IC/prod.yml:50`);
  access-лог Daphne выключен, его роль — `AccessLogMiddleware` (`ERP/core/settings/web.py:25`).
- BFF: structlog JSON (`BFF/logging.py:9-22`).
- Caddy: **директивы `log` нет** — access-логов входа нет (`infra/caddy/Caddyfile.prod`).
- Docker: `json-file` 20m×5 (`IC/prod.yml:10-14`). Сбора логов (Loki/ELK/Vector) нет.

### 7.2. Сквозной request-id

| Участок | Есть? | Где |
|---|---|---|
| Caddy генерирует/прокидывает | нет | `Caddyfile.prod` без `header_up` |
| CRM вход | да (`asgi-correlation-id`, `X-Request-ID`) | `CRM/main.py:121` |
| ERP вход | да (`RequestIDMiddleware`) | `ERP/core/logging.py:88-111` |
| BFF вход и исходящие в CRM/ERP | да (единственное место) | `BFF/request_id.py:17-39`, `BFF/clients/base.py:39-42,76` |
| CRM → ERP | **нет** (только Authorization, Idempotency-Key) | `CRM/integrations/erp.py:311,511-516` |
| ERP вебхук → CRM | **нет** (`event_id` есть, но не как correlation) | `ERP/integration/tasks.py:113-120` |
| Celery / Procrastinate задачи | **нет** | — |

### 7.3. Метрики, health, ошибки

- Prometheus/`/metrics` — нет нигде.
- Health: CRM `/health` и `/ready` (503 с деталями, `CRM/api/health.py:29-49`); ERP `/health/` (только БД, кэш 10 с);
  BFF `/api/v1/health` (всегда 200, `degraded`); compose-healthchecks у всех, кроме `erp-beat` и одноразовых.
- Sentry: ERP backend — код есть (`ERP/core/settings/observability.py:72-93`), но `SENTRY_DSN` нет ни в compose, ни в
  `.env.prod.example` → в проде выключен; ERP frontend — `VITE_SENTRY_DSN` не передаётся в сборку
  (`.github/workflows/deploy.yml:119-121`); CRM, BFF, Cabinet, Платформа — нет.
- Алертинг: только Telegram-алерты CRM (`system_monitor` каждую минуту, `daily_report`) и healthcheck бэкапа (26 ч).
- Langfuse — профиль `observability`, в проде по умолчанию выключен.

### 7.4. Бэкапы

- `infra/db/backup.sh`: ежедневно 22:00 UTC, базы `crm erp litellm langfuse` (`:17`), проверка дампа (`:31-42`),
  локально 14 дней (`:15,82`), копия в бакет `backups` **RustFS на VPS1** без шифрования (`:44-50`), еженедельно — во
  внешний S3 с AES-256 и 60 днями (`:52-67`), но только если заданы `BACKUP_EXT_*` (по умолчанию пусто, `IC/db.yml:102-109`).
- Перед деплоем — `predeploy-dump.sh` (custom-формат, `pg_restore -l`, SHA256SUMS, 5 штук, `:16-42`).
- Проверка восстановления — ручная (`infra/db/restore-check.sh:17-42`).
- **Не бэкапятся**: том RustFS `s3_data` (`docs/runbooks/deploy.md:184`), том `erp_media` (все файлы ERP), Redis.
- WAL-архивации/PITR нет → RPO до 24 ч.

### 7.5. Деплой, миграции, откат

- `.github/workflows/deploy.yml` (ручной запуск): сборка 8 образов → GHCR (тег = sha) → `release.tgz` по SSH →
  `infra/deploy/deploy.sh`.
- `deploy.sh`: проверка env → pull → CPU-baseline → pg_dump-гейт (`:37`) → миграции CRM, затем ERP (`:39-41`) →
  `up_stack` (`infra/deploy/lib.sh:54-64`, `docker compose up -d`, Платформа отдельно) → smoke (`:53-55`).
- **Не zero-downtime**: контейнеры пересоздаются на месте; миграции идут, пока работает старый код; политики
  expand/contract нет — только оговорка в `docs/runbooks/deploy.md:160`.
- Миграции CRM и ERP не атомарны вместе: падение миграции ERP после успешной CRM оставляет схему CRM впереди кода.
- `infra/deploy/rollback.sh` откатывает образы и релиз, **не откатывает миграции** (`:3-4,40`); данные — вручную.
- Один экземпляр каждого сервиса, масштабирования нет; бот в режиме polling не допускает второй реплики `crm-api`.

---

## 8. Архитектурные проблемы и риски

| # | Приоритет | Проблема | Пути |
|---|---|---|---|
| 1 | **P0** | Файлы ERP (PDF КП/договоров/счетов/актов, загрузки) на локальном томе `erp_media` VPS1: не в RustFS, не в бэкапе; бакет `erp` создаётся впустую; при потере VPS1 документы утрачены безвозвратно | `ERP/core/settings/project.py:63-76`, `ERP/core/storage.py:52-53`, `IC/prod.yml:102,225-227` |
| 2 | **P0** | Объекты RustFS (документы клиентов CRM, вложения Telegram, БЗ) не бэкапятся; «ежедневная копия» дампов лежит на том же VPS1; внешний бэкап по умолчанию выключен; нет PITR | `docs/runbooks/deploy.md:184`, `infra/db/backup.sh:44-67`, `IC/db.yml:102-109` |
| 3 | **P0** | Тихая потеря событий: сигналы ERP глотают исключения; запись журнала атомарна с бизнес-изменением только внутри `atomic()` (`ATOMIC_REQUESTS` нет) — зеркало CRM и уведомления клиенту расходятся без сигнала | `ERP/integration/signals.py:134-135,188,247,290,340`, `ERP/integration/services/webhooks.py:289-362` |
| 4 | **P0** (для целевой) | Нет механизма подписок: один `CRM_WEBHOOK_URL`, один секрет, `target_url` в строке, фильтр по `CrmClientMapping` — подключение BFF/1С невозможно без переделки | `ERP/core/settings/api.py:186-189`, `ERP/integration/services/webhooks.py:253-261,326`, `ERP/integration/models.py:306-310` |
| 5 | P1 | CRM не публикует событий вообще (клиент, контакт, пользователь, лид): обратный поток только синхронными REST-вызовами; добавить потребителя данных CRM нельзя | `CRM/services/clients.py:208`, `CRM/tasks/*` |
| 6 | P1 | Данные клиента после handoff не синхронизируются: нет обновления компании; `PUT /contacts` в ERP не вызывается CRM | `ERP/integration/views.py:94-97`, `ERP/integration/services/handoff.py:100-110` |
| 7 | P1 | Единая точка отказа CRM-API: IdP Платформы, бот, приём вебхуков и вебформа — в одном процессе; вход в Платформу без CRM невозможен | `CRM/main.py:80-95`, `BFF/auth.py:120-189` |
| 8 | P1 | Redis 100 МБ `noeviction` общий для Celery (broker+results с отложенными задачами до 24 ч), кэша/Channels ERP, сессий BFF, Langfuse; кэш ERP без игнорирования ошибок → отказ Redis = отказ ERP и разлогин Платформы | `IC/prod.yml:91`, `IC/base.yml:105-110`, `ERP/core/settings/infra.py:8-14,50` |
| 9 | P1 | Одна PostgreSQL на 4 базы без реплики; RPO до 24 ч; отказ VPS2 = остановка всего | `IC/db.yml`, `infra/db/backup.sh:10-17` |
| 10 | P1 | Подпись вебхуков v1 (только тело) по умолчанию принимается и в проде | `CRM/config.py:99`, `IC/base.yml:59`, `infra/.env.prod.example:143` |
| 11 | P1 | Синхронный SMTP без `EMAIL_TIMEOUT` внутри транзакции handoff (и под advisory-lock) | `ERP/integration/services/handoff.py:233,265-270`, `ERP/portal/services/invitation.py:48`, `ERP/notifications/emails.py:~214` |
| 12 | P1 | Нет сквозного correlation-id через CRM→ERP, вебхуки, Celery, Procrastinate; Caddy не ставит `X-Request-ID` и не пишет access-лог | `CRM/integrations/erp.py:311,511-516`, `ERP/integration/tasks.py:113-120`, `infra/caddy/Caddyfile.prod` |
| 13 | P1 | Нет метрик и трекинга ошибок в проде (Sentry не подключён нигде), алертинг — только Telegram CRM | `ERP/core/settings/observability.py:72-93`, `.github/workflows/deploy.yml:119-121` |
| 14 | P1 | ERP допускает свой пароль/сброс/2FA для провижиненных пользователей (против ADR-0010 §3); роли, выданные вручную в ERP, не видны CRM/BFF | `ERP/core/urls.py:177-209`, `ERP/accounts/services/auth.py:68`, `ERP/integration/services/provision.py:47-55` |
| 15 | P1 | BFF завязан на внутренние API старых фронтов (`erp-internal`, CRM `/api/v1` без контракта в `packages/contracts`) — T5 «удаление эндпоинтов старых фронтов» сломает Платформу | `BFF/feeds/snapshot.py:18-69`, `BFF/feeds/search.py:123-149`, `apps/crm/docs/api/openapi.json` |
| 16 | P1 | Деплой без zero-downtime и без политики expand/contract; откат не откатывает миграции; миграции CRM и ERP не согласованы | `infra/deploy/deploy.sh:39-44`, `infra/deploy/lib.sh:54-64`, `infra/deploy/rollback.sh:3-4` |
| 17 | P1 | Секреты шва живут в двух местах (env и БД каждой системы); ротация `ERP_SECRET_KEY` молча ломает `ServiceCredential`/TOTP | `ERP/integration/services/credentials.py:36-38,112-139`, `CRM/models/integrations.py:25` |
| 18 | P2 | Схема событий в CRM — ручная Pydantic-копия; `version: Literal[1]` — событие v2 будет `rejected`; в проде ERP проверяет схему в режиме `log` | `CRM/schemas/erp_events.py:229`, `ERP/core/settings/api.py:196` |
| 19 | P2 | Нет replay для `failed/rejected` во входящем журнале CRM; DLQ нет; replay в ERP — только суперпользователь в admin | `CRM/services/erp_events.py:165,501-513`, `ERP/integration/admin.py:56-72` |
| 20 | P2 | Идемпотентность integration API без блокировки (insert-first); provision шлёт новый uuid4 на каждый вызов | `ERP/integration/idempotency.py:25-76`, `CRM/integrations/erp_users.py:67` |
| 21 | P2 | Нет circuit breaker; CRM создаёт `httpx.AsyncClient` на каждый вызов; окно повторов handoff ≈7,5 мин | `CRM/integrations/erp_http.py:25-90`, `CRM/tasks/erp_handoff.py:17` |
| 22 | P2 | Telegram-уведомления по событиям ERP — at-most-once (`notified_at` до отправки) | `CRM/services/erp_events.py:745-781` |
| 23 | P2 | Бренд «управляется CRM», но синхронизации нет; `PLATFORM_NAME` не передан в ERP; SMTP, бюджет ИИ ERP, адреса фронтендов — по два места | `ERP/core/views/settings.py:16-17`, `ERP/core/admin.py:32`, `IC/prod.yml:63-68`, `IC/base.yml:375`, `CRM/services/ai_spend.py:134` |
| 24 | P2 | Двойные уведомления клиенту (письмо ERP + Telegram CRM); нет `document.deleted/cancelled`; `send_payment_reminders` не запланирован | `ERP/crm/tasks.py:314,404,467`, `CRM/services/erp_event_handlers.py:190-229` |
| 25 | P2 | Caddy при холодном старте ждёт `erp-backend` healthy — сбой ERP при деплое/перезапуске хоста блокирует и CRM, и Cabinet-статику | `IC/base.yml:577-586` |
| 26 | P2 | Машинный API ERP (`/api/integration/v1`) и Django `/admin` опубликованы в интернет через Caddy, хотя CRM ходит по внутренней сети | `infra/caddy/Caddyfile.prod:61-63` |
| 27 | P2 | TLS к PostgreSQL без проверки цепочки (`sslmode=require`, `accept_invalid_certs`); один S3-ключ на всех; общий `LITELLM_MASTER_KEY` как рабочий ключ CRM | `IC/prod.yml:34,109`, `IC/base.yml:30-33` |
| 28 | P2 | `erp-beat` без healthcheck — остановка тихо отключает подбор зависших вебхуков и курсы | `IC/base.yml:476-488` |
| 29 | P2 | Тема Платформы не переключаема: нет тёмных токенов и `algorithm`, 183 hex-литерала, CSS без переменных; копия токенов Платформы вне `build.mjs` | `WEB/app/theme.ts:19-90`, `packages/ui-tokens/build.mjs:83,208-232`, `apps/platform/Makefile:41-52` |
| 30 | P2 | Мёртвые/расходящиеся настройки: `SERVICE_TOKEN_ERP_TO_CRM` и слот `ERP_TO_CRM` не проверяются; `ERP_MCP_CONTEXT_KEY` обязателен в ERP и опционален в CRM | `ERP/integration/models.py:309`, `IC/base.yml:54,382` |

---

## 9. Что из этого следует для целевой архитектуры с шиной (тезисы, не решение)

1. Основа уже есть в ERP: журнал `IntegrationWebhookEvent` = зачаток transactional outbox. Нужны: запись строго в
   той же транзакции (сервисный слой вместо сигналов, без `except Exception`), маршрутизация на подписчиков,
   per-subscriber ретраи/replay/DLQ.
2. CRM нужен симметричный outbox (Procrastinate уже в той же БД — можно ставить событие в транзакции).
3. Реестр схем — `packages/contracts/events.schema.json` как единственный источник; генерация моделей для CRM, BFF и
   коннекторов вместо ручных копий; версия схемы в подписке.
4. Канал для BFF (ADR-0011 п.5, Redis Streams) и шина для систем (1С, ЭСФ) — решить, один это механизм или два;
   текущий Redis (100 МБ, noeviction, общий) для этого не годится без выделения ресурса и персистентности.
5. Сквозной correlation-id и единый формат конверта (уже есть `event_id`, `occurred_at`, `actor`) — первым шагом.
6. Разрешить дубли: компания/контакт (события изменения из CRM), бренд и SMTP (один владелец, раздача событием или
   конфиг-сервисом), роли (запрет ручной выдачи в ERP для `managed_by_crm`).
7. Перед шиной — закрыть P0 по данным: файлы ERP в RustFS, бэкап бакетов вне VPS1, PITR.
