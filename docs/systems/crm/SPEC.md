# RailTech CRM — техническое задание (SPEC)
Статус: действует для бэкенда CRM; при расхождении права docs/product/ и стратегия · Владелец: лид · Обновлено: 2026-10-28

Версия 2.8 · 2026-10-14 (центр внешних сервисов — §13.2, M3-CRM-12, ADR-0024; расходы на ИИ по ансамблю из журнала LiteLLM — §13.1, M3-CRM-09; RustFS — ADR-0009; модели — ADR-0004; docling-serve и MCP SDK — ADR-0011; жизненный цикл без тупиков — ADR-0015; квалификация и цена по правилам — ADR-0016; передача в бэк-офис и итог из ERP — ADR-0022; коннектор «ERP» в «Подключениях» — M3-CRM-02; коннектор «Почта» и журнал писем — ADR-0023, M3-CRM-08: решение Q-010 «SMTP нет» пересмотрено — SMTP появляется как коннектор, ручной временный пароль остаётся)

Документ описывает, *как* устроена система: архитектура, ядро, данные, агенты, интерфейсы, безопасность, стенды, связи. Порядок реализации — в `docs/history/crm/PLAN.md`; зачем всё это — в `docs/systems/crm/BUSINESS.md`; правила работы для Claude Code — в `docs/systems/crm/CONVENTIONS.md`.

Нумерация разделов стабильна: другие документы ссылаются на неё как `SPEC §7.2`.

---

## 1. Принципы (архитектурные инварианты)

1. **Диалог — центральная сущность.** Лид, клиент, документы, стадии — всё привязано к диалогу и видно из него.
2. **Два агента, две роли.** Диалоговый агент — синхронный, в контексте разговора, на сильной модели. Квалификатор — асинхронный, по событию, на дешёвой модели, со структурированным выводом. Больше агентов в v2 нет.
3. **Решения принимает код, модель предлагает.** Стадия, оценка, эскалация, доступ к данным — детерминированная логика. Модель даёт сигналы.
4. **Нулевая галлюцинация фактов о продукте.** Ответы по продукту только из найденных фрагментов базы знаний; иначе честный отказ и регистрация пробела.
5. **Идентичность клиента подставляет код, не LLM.** Любой инструмент, читающий данные клиента, получает `client_id` из аутентифицированного контекста выполнения, а не из аргументов, сгенерированных моделью.
6. **Один шлюз к моделям.** Весь доступ к LLM и embeddings — через LiteLLM по алиасам. Провайдер меняется конфигом.
7. **Готовое вместо кастомного.** Очередь, RBAC, админ-UI, хранилище файлов, трейсинг — готовые решения. Кастомный код — только доменная логика и экраны.
8. **Всё наблюдаемо и воспроизводимо.** Каждый вызов модели трассируется; каждое решение квалификатора журналируется; каждое действие пользователя — в audit log.
9. **Единый веб-интерфейс команды.** Telegram-канал — только уведомления и одна быстрая кнопка. Все действия — в CRM.

---

## 2. Стек

| Слой | Решение | Версия/заметки |
|---|---|---|
| Язык backend | Python | 3.12, менеджер пакетов `uv` |
| Web/API | FastAPI + Pydantic v2 + SQLAlchemy 2 (async) + Alembic | OpenAPI как контракт для фронта |
| Telegram | aiogram 3 | Dev — long polling; prod — webhook с `secret_token` |
| Оркестрация агентов | LangGraph | `PostgresSaver` для чекпоинтов |
| Инструменты агентов | MCP-серверы на официальном Python SDK `mcp` (`MCPServer`, бывший FastMCP), транспорт streamable HTTP (stateless, JSON); клиент — `mcp.Client` (ADR-0011) | Три сервера: `kb-mcp`, `crm-mcp`, `docs-mcp` |
| Шлюз моделей | LiteLLM Proxy (self-hosted) | Алиасы: `dialog-model`, `qualifier-model`, `judge-model`, `embed-model`, `fallback-model` |
| Модели | Внешние API. Рекомендация: диалог — Anthropic Sonnet-класс; квалификатор/judge — Anthropic Haiku-класс или Google Flash-класс; embeddings — Google Gemini Embedding (мультиязычный, узбекский) или Voyage multilingual | Значения по умолчанию — `infra/litellm.models.yaml` (ADR-0004); текущие модели и ключи ролей — в БД LiteLLM, меняет админ в CRM без рестарта (ADR-0020) |
| БД | PostgreSQL 17 + pgvector | Одна база для домена, векторов, очереди, чекпоинтов |
| Очередь и планировщик | Procrastinate | Задачи на Postgres: события квалификатора, таймеры SLA/снуз/unresponsive, ингест KB, ежедневные отчёты |
| Файлы | RustFS (S3-совместимый, Apache-2.0; ADR-0009) | Документы клиентов, исходники KB, вложения из Telegram. Код работает только по протоколу S3 |
| Ингест документов | docling: сервис `docling-serve` (CPU-образ) + `docling-core` HybridChunker в worker (ADR-0011) | PDF/DOCX/PPTX/XLSX/MD/HTML → DoclingDocument → чанки |
| Frontend | React 18 + TypeScript + Vite + **Refine** + Ant Design + TanStack Query | Refine — оболочка: authProvider, accessControlProvider, раскладка, уведомления; данные — хуки TanStack Query из orval (ADR-0021) |
| Авторизация | JWT (access 15 мин + refresh 30 дней, httpOnly cookie), пароли argon2id | Провайдер заменяем на Keycloak (OIDC) без смены фронта — Refine authProvider |
| RBAC | Casbin (`pycasbin`, модель RBAC с доменами на будущее) | Политики в БД, кэш в памяти, инвалидация по событию |
| Observability | Langfuse (self-hosted) — трейсы LLM, стоимость, датасеты, judge | Логи приложений — structlog JSON → stdout → `docker logs`/Loki (опционально) |
| Evals | pytest (`-m eval`) + Langfuse datasets + promptfoo | §12 |
| Качество кода | ruff (lint+format), mypy (strict на домене), pre-commit, pytest, ESLint + Prettier, Vitest + Playwright (smoke) | |
| Инфра | Docker Compose (base + `dev` + `prod` overrides), Caddy (TLS/роутинг), GitHub Actions | |
| Бэкапы | `pg_dump` 16 ежедневно + копия S3-бакетов RustFS (`python -m app s3-mirror`, ADR-0013) в контейнере `backup` → том `backups`, ротация 14 дней | prod |

Явно **не используем**: локальные модели (Ollama), Redis/RabbitMQ в приложении (Redis есть только внутри профиля Langfuse), отдельную векторную БД, готовые CRM как ядро (ADR-0002), Keycloak на старте (ADR-0005), ORM-магию в агентах (агенты ходят в данные только через MCP).

---

## 3. Архитектура

### 3.1. Контекст

```
┌─────────────┐   Telegram Bot API   ┌──────────────────────────────────────────┐
│ Лид/Клиент  │◄────────────────────►│ api  (FastAPI)                            │
│ (Telegram)  │                      │  ├─ bot: aiogram router                   │
└─────────────┘                      │  ├─ dialog agent (LangGraph)              │
                                     │  ├─ REST /api/v1/* для CRM                │
┌─────────────┐  уведомления+кнопка  │  └─ auth, rbac, audit                     │
│ Канал       │◄─────────────────────┤                                           │
│ команды     │                      └──────┬──────────┬──────────┬──────────────┘
└─────────────┘                             │          │          │  MCP (HTTP, внутр. сеть)
                                            ▼          ▼          ▼
┌─────────────┐   HTTPS   ┌──────┐     ┌────────┐ ┌────────┐ ┌─────────┐
│ Менеджер /  │◄─────────►│ web  │     │ kb-mcp │ │crm-mcp │ │docs-mcp │
│ Админ       │           │React │     └───┬────┘ └───┬────┘ └────┬────┘
└─────────────┘           └──────┘         │          │           │
                                           ▼          ▼           ▼
┌──────────┐  задачи   ┌─────────────────────────────────────────────────┐   ┌───────┐
│ worker   │◄─────────►│ PostgreSQL 17 + pgvector                        │   │RustFS │
│Procrast. │           │ домен · векторы · очередь · чекпоинты · casbin  │   └───────┘
│ +qualif. │           └─────────────────────────────────────────────────┘
└──────────┘
      │  все вызовы моделей
      ▼
┌──────────┐  HTTPS  ┌────────────────────────┐        ┌──────────┐
│ litellm  │────────►│ Anthropic / Google / … │        │ langfuse │◄── трейсы от api, worker
└──────────┘         └────────────────────────┘        └──────────┘
```

### 3.2. Сервисы (Docker Compose)

| Сервис | Образ/код | Порты (внутр.) | Назначение |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg17` | 5432 | Все данные |
| `rustfs` (+ `s3-init` — создание бакетов) | `rustfs/rustfs` | 9000/9001 | Файлы (S3) |
| `litellm` | `ghcr.io/berriai/litellm` | 4000 | Шлюз моделей, ключи провайдеров только здесь |
| `langfuse` (+ ClickHouse, Redis — внутренние зависимости Langfuse по официальному compose) | `langfuse/langfuse` v4 | 3000 | Трейсинг; на prod — поддомен `langfuse.<домен>` с IP allow-list |
| `api` | `./backend` | 8000 | FastAPI: бот, агент, REST, auth |
| `worker` | `./backend` (entrypoint worker) | — | Procrastinate: квалификатор, таймеры, ингест |
| `docling` | `docling-serve-cpu` | 5001 | Конвертация документов KB и клиентов (ADR-0011) |
| `kb-mcp`, `crm-mcp`, `docs-mcp` | `./backend` (entrypoint mcp:<name>) | 8101/8102/8103 | Инструменты агентов |
| `web` | `./frontend` → статика | — | Раздаётся Caddy |
| `caddy` | `caddy:2` | 80/443 | TLS, роутинг `/api`, `/`; поддомен Langfuse (prod, по IP-allowlist) |

Наружу (prod) открыты только `caddy:443` (и 80 для ACME). MCP, Postgres, RustFS, LiteLLM — только во внутренней сети compose.

### 3.3. Потоки

**Входящее сообщение лида**
1. Telegram → `api` (webhook/polling) → проверка `secret_token`, идемпотентность по `update_id` (таблица `tg_updates`).
2. `api` сохраняет `messages(role=lead)`, обновляет `leads.last_lead_msg_at`.
3. Если `leads.owner_mode = bot` → запуск диалогового агента (§7.1) → ответ лиду → `messages(role=bot)`.
   Если `owner_mode = human` → сообщение попадает в CRM в реальном времени (SSE), бот молчит: агент не запускается вовсе (ни MCP, ни извинений при сбое), менеджер получает уведомление.
   Если `owner_mode = paused` → модель не вызывается (ждёт менеджера); код отвечает `texts.waiting_for_manager` не чаще раза в 30 мин, `/human` и стоп-слова поднимают приоритет открытой эскалации до `hot` (ADR-0015).
4. `api` ставит задачу Procrastinate `qualify_lead(lead_id)` с дедупликацией (`queueing_lock = lead_id`, если уже в очереди — не дублируется).

**Квалификация**
1. `worker` берёт задачу, загружает контекст, запускает квалификатор (§7.2).
2. Применяет state machine (§6.2), пересчитывает score (§6.3), прогоняет триггеры (§8.1).
3. Пишет `qualifier_runs`. При эскалации → `escalations` + уведомление в канал (§9) + `leads.owner_mode = paused` (кроме `info`, ADR-0015).

**Действие менеджера в CRM** (Забрать / Ответить / Вернуть боту / Закрыть)
1. REST `POST /api/v1/leads/{id}/actions/{action}` → RBAC → доменный сервис → `audit_log`.
2. Побочные эффекты: сообщение лиду через бота, редактирование поста в канале, постановка/отмена таймеров.

**Клиентский режим** (§7.3) — тот же входящий поток, но агент получает другой профиль инструментов и промпт; `client_id` подставляется из `telegram_identities`.

---

## 4. Репозиторий

```
railtech-crm/
├── docs/systems/crm/CONVENTIONS.md                 # оркестратор для агента
├── README.md                 # запуск за 15 минут (dev), ссылки на docs
├── docs/systems/crm/BUSINESS.md  docs/history/crm/PLAN.md  docs/systems/crm/SPEC.md
├── docs/
│   ├── adr/                  # MADR: 0001-..., шаблон 0000-template.md
│   ├── runbooks/             # эксплуатация: деплой, бэкап/восстановление, ротация ключей, инциденты
│   ├── api/                  # экспорт OpenAPI (генерируется)
│   └── diagrams/             # Mermaid-исходники
├── backend/
│   ├── pyproject.toml  uv.lock
│   ├── alembic/              # миграции
│   ├── app/
│   │   ├── main.py           # FastAPI app factory
│   │   ├── config.py         # pydantic-settings, единственное место чтения env
│   │   ├── api/v1/           # роутеры REST: leads, clients, documents, kb, settings, users, dashboard, auth
│   │   ├── bot/              # aiogram: handlers, middlewares (idempotency, consent, rate-limit)
│   │   ├── agents/
│   │   │   ├── dialog/       # graph.py, nodes.py, tools.py (MCP client)
│   │   │   └── qualifier/    # graph.py, schema.py
│   │   ├── domain/           # чистая логика: stage_machine.py, scoring.py, triggers.py, escalation.py, consent.py
│   │   ├── services/         # use-cases над репозиториями: LeadService, ClientService, KbService, DocumentService, UserService, NotificationService
│   │   ├── repositories/     # доступ к БД
│   │   ├── models/           # SQLAlchemy
│   │   ├── schemas/          # Pydantic DTO
│   │   ├── security/         # auth.py (JWT), rbac.py (casbin), audit.py, pii.py (маскирование)
│   │   ├── integrations/     # telegram.py, litellm.py, langfuse.py, s3.py
│   │   ├── tasks/            # Procrastinate: qualify.py, timers.py, ingest.py, reports.py
│   │   └── mcp/              # kb_server.py, crm_server.py, docs_server.py (FastMCP)
│   ├── prompts/              # dialog_prospect.md, dialog_customer.md, qualifier.md, judge_faithfulness.md
│   ├── tests/
│   │   ├── unit/             # домен, схемы, промпт-шаблоны — без внешних сервисов
│   │   ├── integration/      # с Postgres/RustFS (testcontainers или CI services), помечены @integration
│   │   └── e2e/              # сценарии через Telegram-эмуляцию + REST, помечены @e2e
│   └── evals/
│       ├── golden/*.yaml  fixtures/kb/*  test_eval.py  promptfooconfig.yaml
├── frontend/
│   ├── package.json  vite.config.ts  tsconfig.json
│   └── src/
│       ├── app/              # providers: auth, access-control (casbin-js enforcement по данным с бэка), data (REST)
│       ├── pages/            # inbox, leads, lead-detail, clients, client-detail, documents, kb, kb-gaps, settings, users, dashboard, audit
│       ├── components/       # ChatThread, LeadCard, StageBadge, ModeSwitch (Админ/Менеджер), EscalationReason
│       └── api/              # сгенерированный клиент из OpenAPI (orval)
├── infra/
│   ├── docker-compose.yml  docker-compose.dev.yml  docker-compose.prod.yml
│   ├── litellm.config.yaml
│   ├── litellm.models.yaml
│   ├── Caddyfile.dev  Caddyfile.prod
│   └── casbin/model.conf  casbin/policy.seed.csv
├── scripts/                  # bootstrap_dev.sh, seed_demo.py, create_admin.py, kb_ingest.py, backup.sh, restore.sh, smoke_dev.sh, smoke_prod.sh
├── .claude/
│   ├── settings.json         # разрешённые команды для агента
│   └── skills/               # см. docs/systems/crm/CONVENTIONS.md
├── .github/
│   ├── workflows/ci.yml  deploy-prod.yml
│   └── PULL_REQUEST_TEMPLATE.md
├── .env.example  .pre-commit-config.yaml  Makefile
```

---

## 5. Модель данных

Все таблицы — `created_at`, `updated_at` (триггер). Денежные/персональные поля не хранятся сверх необходимого.

### 5.1. Пользователи и доступ

```sql
users(id, email UNIQUE, password_hash, full_name, tg_user_id UNIQUE NULL, is_active, must_change_password BOOL DEFAULT true, ui_mode 'admin'|'manager', last_login_at, notify_system BOOL DEFAULT true, notify_leads BOOL DEFAULT true, platform_access JSONB DEFAULT '["crm"]', erp_role_codes JSONB DEFAULT '[]', position VARCHAR(120) NULL, erp_sync_error TEXT NULL)  -- подписки на личные сообщения от бота (Q-010); `platform_access` — куда можно (`["crm"]` | `["crm","erp"]`, CHECK: всегда с `crm`, других систем нет; FIX-11, миграция `0026_user_platform_access`), `erp_role_codes` — системные роли бэк-офиса ERP, выданные админом (`CALCULATION|CATALOG_SUPPLY|FULFILLMENT|FINANCE|HEAD|VIEWER`, CHECK по каталогу `domain/erp_roles.py`; FIX-63, миграция `0031_user_erp_role_codes`), роли Платформы — с R-1 (ADR-0012) данные в `platform_roles`/`user_platform_roles` (столбец `users.platform_roles` удалён миграцией `0036`): права CRM сотрудника — политики casbin его ролей `pr:<id>` (у системной «Администратор» — раздел `admin` каталога, не `admin` CRM `*:*`: лиды, клиенты, сделки — 403, R3-D-2), провижининг ERP — вычисленные `permissions` и `role_codes = []`; выдача — `PATCH`/`POST /users` с `platform_role_ids` (только admin; пустой набор — 422 `roles_required`, закрыть доступ — `is_active = false`, R3-D-1); первый админ из `/setup` и `create-admin` получает системную роль «Администратор»; `position` — должность текстом (SPEC-v3 §4.3, `""` очищает); `erp_sync_error` — последняя ошибка синхронизации с ERP (читает центр внешних сервисов, пользователю не показывается)
roles(id, name UNIQUE)                     -- admin | manager | viewer (seed)
user_roles(user_id, role_id, granted_by, granted_at)   -- PK (user_id, role_id)
platform_roles(id, code UNIQUE NULL, name, description, is_system, access JSONB, restricted_fields JSONB, version INT DEFAULT 1, created_by, updated_by) -- роли Платформы как данные (ADR-0012): code есть у системных ADMIN/DIRECTOR и шаблонов tpl:MANAGER...; access — раздел -> full|read; version растёт при каждом изменении, `PATCH /platform-roles/{id}` требует её (409 `role_version_conflict`, R-1b)
user_platform_roles(user_id, role_id, granted_by, granted_at)   -- PK (user_id, role_id); роль с сотрудниками не удаляется
casbin_rule(...)                           -- таблица адаптера Casbin
refresh_tokens(id, user_id, token_hash, expires_at, revoked_at, user_agent, ip)
audit_log(id, actor_user_id NULL, actor_type 'user'|'system'|'bot', action, entity_type, entity_id, before JSONB, after JSONB, ip, created_at)
```

**Профиль сотрудника (W15-H6, миграция `0042_staff_profile`).** В `users` — поля, которые сотрудник правит сам (должность и роли — только админ): `phone` (7–15 цифр, `+` и цифры), `timezone` (IANA, по умолчанию `Asia/Tashkent`), `email_signature` (≤ 1000 символов, в аудит не пишется), `tg_username` (ник при самостоятельной привязке; сбрасывается, когда админ меняет или снимает `tg_user_id`), фото `avatar_key` + `avatar_updated_at` (объект `staff-avatars/<id>/<случайное>.<png|jpg|webp>` в бакете `client-documents`, до 1 МБ, тип по содержимому; отдаёт только API `GET /staff/{id}/avatar`, публичных ссылок на S3 нет) и замещение `deputy_user_id`, `deputy_from`, `deputy_to` (CHECK: все три или ни одного, период не пуст, не сам себе). Ещё в `users`: `tg_linked_at` (когда Telegram привязал сам сотрудник; администратор и старые привязки — NULL) и `password_changed_at` (когда пароль сброшен ссылкой, админом или приглашением: выпущенные раньше access-токены перестают приниматься — claim `pwv` (микросекунды `password_changed_at`, 0 — пароль не менялся) сверяется с текущим значением сотрудника в `get_principal`, а refresh-токены, выпущенные раньше, отклоняются в `AuthService.refresh` с отзывом семейства; сессии сотрудника, в том числе живые в BFF, закрываются сразу, а не через 15 минут. Смена пароля самим сотрудником (`POST /auth/change-password`, W15-H8b) закрывает **другие** сессии так же, а текущую продолжает: ответ 200 `TokenResponse` с новой парой токенов и refresh-cookie вместо прежнего 204, BFF выполняет смену под блокировкой сессии (вторая вкладка ждёт и идёт на новой паре, а не убивает сессию по закрытому refresh-токену) и подменяет пару в своей Redis-сессии, снимает `must_change_password`; сбой записи в Redis после ответа CRM оставляет пароль сменённым, а сессию закрытой — сотрудник входит заново; после выкладки массового разлога нет (`pwv = 0` у ранее выпущенных токенов совпадает с `password_changed_at IS NULL`); момент смены берётся по часам приложения, не БД, чтобы токены сравнивались точно). Замещение: заместитель может стать NULL при заполненных датах (FK `ON DELETE SET NULL`, CHECK это допускает) — это «замещения нет». Таблицы `staff_telegram_links(user_id, code_hash UNIQUE, expires_at, used_at)` — код привязки Telegram, 10 минут, одноразовый, хеш sha256 — и `password_reset_tokens(user_id, token_hash UNIQUE, channel 'email'|'telegram', expires_at, used_at)` — ссылка сброса пароля, 60 минут. Правила значений — `domain/staff_profile.py`, `domain/staff_telegram.py`, `domain/password_reset.py` (тесты без БД); сервисы — `StaffProfileService`, `StaffTelegramLinkService`, `StaffDeputyService`, `PasswordResetService`. REST (только про себя, `user_id` из токена): `PATCH /me` (атомарно: всё тело проверяется до первого изменения; только после смены временного пароля; `extra=forbid`: должность, роли и чужой id — 422), `PUT|DELETE /me/avatar` (тело читается потоком и обрывается на 1 МБ + запас на multipart: 413 `payload_too_large`; Caddy Платформы дополнительно ограничивает `request_body max_size`), `POST|DELETE /me/telegram-link`, `GET /me/deputy-candidates`, `PUT|DELETE /me/deputy`, `GET /me/covering`, `GET /staff/{id}/avatar`, `GET /inbox?on_behalf_of=<id>` (очередь замещаемого, пока период идёт и вызывающий назначен заместителем, иначе 403 `not_a_deputy`; права на лиды — вызывающего), публично `POST /auth/forgot-password` (202 одинаков для любой учётной записи) и `POST /auth/reset-password`. Имя меняется через `UserService.update` (аудит, событие шины `identity.user.updated`, синхронизация ERP).

**Обращения сотрудников к администратору и колокольчик сотрудника (W15-H7, миграция `0045_staff_tickets`).** Сотрудник пишет администратору с экрана «Нет доступа» Платформы и из «Помощи»; решения и данные — в CRM (ADR-0015), Платформа ничего не хранит. Таблицы: `staff_tickets(id, author_id → users ON DELETE CASCADE, subject 'access'|'notification'|'template'|'error'|'other', body, page ≤ 300, author_role ≤ 120, status 'new'|'in_progress'|'resolved', created_at, updated_at, resolved_at)` (CHECK по темам и статусам, индексы `(author_id, created_at)` и `(status, updated_at)`), `staff_ticket_messages(id, ticket_id → ON DELETE CASCADE, author_id → users ON DELETE SET NULL, body, created_at)` — ответы администратора (первое сообщение — сам `body`), и `staff_notifications(id, user_id → ON DELETE CASCADE, kind, tab 'decisions'|'clients'|'system', title ≤ 200, subtitle, object_kind, object_id, object_number, created_at, read_at)` — **общий механизм «событие CRM → колокольчик Платформы»**: любой сервис CRM кладёт строку `StaffNotificationService.add(...)`, BFF сливает их с лентой ERP (id `crm:<id>`, `platform-bff.md` §3.4). В `users` — `onboarding_done_at` (приветствие и тур первого входа закрыты: «Больше не показывать» или «Готово»; у существовавших сотрудников миграция ставит `now()`, чтобы им карточка не показывалась). Правила — `domain/staff_tickets.py` (чистые функции, тесты без БД): темы и статусы; текст ≤ 4000 символов после обрезки пробелов (пустой — 422 `ticket_text_empty`, длиннее — `ticket_text_too_long`); страница — только внутренний путь Платформы (`/…`, не `//`; иначе `ticket_page_invalid`), длиннее 300 символов — обрезается, а не отклоняется; Платформа присылает путь без query; ответ ≤ 4000 (`ticket_reply_empty|too_long`); переходы статуса `new → in_progress | resolved`, `in_progress → resolved`, `resolved → in_progress` (иначе 409 `ticket_status_transition`); **не больше 5 обращений в час на сотрудника** (429 `ticket_rate_limited`, `Retry-After`); номер обращения — `ОБР-0012` (`number_of(id)`), числовой id наружу в Платформу не отдаётся. REST: сотрудник — `POST|GET /api/v1/me/tickets`, `GET /api/v1/me/tickets/{id}` (только свои; чужой id — 404, не 403); администратор — `GET /api/v1/staff-tickets` (фильтры `status`, `subject`, страницы; счётчики по статусам), `GET /api/v1/staff-tickets/{id}`, `POST …/{id}/reply` (ответ; первый ответ на «Новое» берёт обращение «В работу»; необязательное `status` — «Ответить и отметить решённым»), `POST …/{id}/status`; права — раздел каталога `tickets` (`tickets:read` — администратор и директор, `tickets:write` — только администратор; роль ADMIN получает их из раздела `admin` Платформы). Эффекты: новое обращение — строка колокольчика каждому администратору (кроме автора) и алерт в личку подписанным администраторам с Telegram (`StaffNotifier.alert_admins`, как остальные оповещения команды; ссылка на экран — по `PLATFORM_PUBLIC_URL`); ответ — строка «Ответ на обращение ОБР-…» и личное сообщение в Telegram автору, если он привязан и активен (`StaffNotifier.direct`; нет Telegram — только колокольчик; строка «Открыть: …» — только если задан `PLATFORM_PUBLIC_URL`); «Решено» — строка «Обращение … решено» (на «Решено» из ответа отдельная строка не дублируется). Всё в аудите (`staff_ticket.create|reply|status`). Колокольчик сотрудника: `GET /api/v1/me/notifications`, `POST /api/v1/me/notifications/{id}/read` и `/read-all` (только свои).

**«Что нового» Платформы (W-REL, миграция `9362ca08ba13`).** В `users` — `whats_new_shown` и `whats_new_read` (`String(10)`, дата записи «Что нового» `ГГГГ-ММ-ДД`): до какой записи сотруднику показано окно «Платформа обновлена» и до какой он открыл раздел «Что нового» (пока меньше новой записи — отметка «Новое» у «?»). NULL — ничего не видел, поэтому существующие сотрудники увидят окно один раз. Пишет только сам сотрудник: `PATCH /api/v1/me {whats_new_shown|whats_new_read}` (формат — дата, иначе 422); отметки только растут, открытие раздела закрывает и окно той же записи; без аудита (как прочтение колокольчика). Читается в `GET /api/v1/me` (только `MeOut`).

Инвариант: `COUNT(user_roles WHERE role=admin AND users.is_active) >= 1` — проверяется в `UserService` перед снятием роли/деактивацией; нарушение → 409. Роли Платформы: всегда есть активный сотрудник с системной ролью `ADMIN` и (если директор уже был) с `DIRECTOR` — иначе 409 `last_admin`/`last_director`; правила casbin роли — субъект `pr:<id>` (`casbin_rule`), права ERP считает провижининг из матриц ролей (`role_codes = []`). **Права EDS (волна 12, E4)** — вычисляются тем же механизмом из `backend.eds` каталога (`EDS_BACKEND`, `eds_permissions_of`): несколько ролей — объединение, уровень раздела — максимум, `full` включает `read`, неактивный сотрудник — пусто; матрица системной роли берётся из каталога. Снимок `identity.user.*` несёт `permissions.eds` (сортированный список; пустой — доступа нет), а любое изменение, меняющее права EDS (назначение и снятие ролей, правка матрицы роли — событие каждому держателю с изменившимися правами, активация), публикует `identity.user.updated` с `changed_fields` ⊇ `["permissions"]` в той же транзакции (outbox rt_bus); роль с держателями не удаляется, поэтому удаление роли права не меняет. `POST /api/v1/auth/sso/token` принимает необязательное тело `{"aud": "erp" | "eds"}` (по умолчанию `erp`; иное значение — 422): для `eds` выдаётся токен сотрудника по `docs/architecture/sso-token.md` («Токен сотрудника для EDS») активному сотруднику с непустым `permissions.eds`, иначе 403 `eds_access_denied`; `redirect_url` в ответе пуст (у EDS нет внешнего маршрута).

### 5.2. Лиды, клиенты, идентичности

```sql
leads(
  id, display_name, language 'ru'|'uz'|'en', stage, score INT, owner_mode 'bot'|'human'|'paused',
  assigned_user_id NULL, client_id NULL,            -- появляется при stage=customer или ручной привязке
  consent_given_at NULL, consent_version TEXT,
  consent_method NULL 'phone'|'email'|'paper',      -- как получено согласие, если его отметил сотрудник (FIX-57, D-8)
  erp_request_id NULL,                              -- заявка ERP, созданная передачей этого лида (FIX-57, D-10)
  need_summary TEXT, product_interest TEXT[], qualification JSONB,
  last_lead_msg_at, last_bot_msg_at, last_human_msg_at, snoozed_until, unresponsive_since,
  manager_notified_at NULL,                         -- троттлинг личных уведомлений менеджеру (Q-010)
  source 'telegram'|'web'|'phone'|'email'|'referral'|'sandbox', notes_count INT,
  phone_e164 NULL, email NULL, company_name NULL   -- контакты лида без Telegram (M3-CRM-05); индекс по phone_e164
)
clients(id, name, inn TEXT NULL, segment TEXT, owner_user_id, is_active)
deals(                                              -- сделки клиента (Q-013, ADR-0019)
  id, client_id NULL, lead_id NULL, title, product_key NULL, amount NUMERIC(14,2) NULL,
  currency CHAR(3) DEFAULT 'UZS', stage 'open'|'won'|'lost', expected_close_date DATE NULL,
  closed_at NULL, lost_reason NULL,                 -- значение из settings.deals.lost_reasons
  owner_user_id NULL, created_at, updated_at,
  erp_deal_id UNIQUE NULL, external_stage NULL, external_stage_at NULL,  -- зеркало заявки ERP (FIX-33)
  erp_number NULL,                                  -- ЗВ/ПР-ГГГГ-NNN из ERP (ERP-09, события)
  request_key UUID UNIQUE NULL,                     -- ключ формы «Создать заявку» (идемпотентность)
  request_summary NULL, request_urgency 'normal'|'urgent' NULL,           -- «Создать заявку» (W16-D1-2, CRM-03):
  request_contact_id → client_contacts NULL, request_letter_file_id UUID NULL, --   суть, срочность, контакт, файл EDS
  erp_request_status 'pending'|'done'|'failed' NULL, erp_request_error NULL, -- передача заявки в ERP задачей
  invoice_issued_at NULL                            -- первый счёт ERP по сделке (erp/invoice.*): зона переписки «Счета и оплаты», B-D18-1
)
telegram_identities(
  id, tg_user_id UNIQUE, tg_username, tg_first_name, lead_id NULL, client_id NULL,
  phone_e164 NULL, verified_by_user_id NULL, verified_at NULL, is_blocked BOOL
)
client_contacts(                                    -- контактные лица клиента (Q-011)
  id, client_id → clients ON DELETE CASCADE, full_name, position NULL,
  phone_e164 NULL,                                  -- тот же нормализатор E.164, что и номер из бота
  email NULL,                                       -- нижний регистр, проверка формата
  telegram_identity_id NULL → telegram_identities ON DELETE SET NULL,
  is_primary BOOL,                                  -- частичный UNIQUE (client_id) WHERE is_primary
  note NULL, created_at, updated_at
)
```

Правило: доступ к данным клиента из бота возможен только если `telegram_identities.client_id IS NOT NULL AND verified_at IS NOT NULL`.

Контакты клиента: «Добавить из Telegram» предлагает подтверждённые идентичности клиента с `phone_e164`,
которых ещё нет среди контактов (по `telegram_identity_id` или номеру); связать контакт можно только с
подтверждённой идентичностью этого же клиента. Телефон основного контакта показывается в карточке лида
этого клиента (`LeadDetail.client_phone_e164`).

### 5.3. Диалог

```sql
conversations(id, lead_id, channel 'telegram', tg_chat_id, is_open)
messages(
  id, conversation_id, role 'lead'|'bot'|'manager'|'system', text, attachments JSONB,
  tg_message_id NULL, sent_by_user_id NULL,         -- для role=manager
  meta JSONB    -- {kb_hits:[{chunk_id,score}], trace_id, model, tokens_in, tokens_out, latency_ms, mode:'prospect'|'customer'}
)
-- индексы: (conversation_id, id); частичный ix_messages_bot_created_at (created_at) WHERE role='bot' — строка «Ответы ИИ» (0043)
tg_updates(update_id PK, received_at)                -- идемпотентность
lead_notes(id, lead_id, user_id, text, visible_to_bot BOOL)
reply_templates(id, title VARCHAR(120), text JSONB {ru,uz,en}, created_by NULL, created_at, updated_at)
                                                     -- шаблоны быстрых ответов менеджера (0018), подстановки {name}/{manager}
```

### 5.4. Квалификация и эскалации

```sql
qualifier_runs(id, lead_id, trigger_message_id, output JSONB, proposed_stage, applied_stage, rejected_reason NULL,
               triggers_fired TEXT[], score_before, score_after, escalated BOOL, trace_id, model, cost_usd)
escalations(id, lead_id, reason_codes TEXT[], reason_text, priority 'hot'|'warm'|'info', status 'open'|'taken'|'snoozed'|'returned'|'closed',
            taken_by_user_id NULL, taken_at NULL, channel_message_id NULL, resolved_at NULL, outcome NULL)
stage_transitions(id, lead_id, from_stage, to_stage, source 'qualifier'|'trigger'|'user'|'timer', actor_user_id NULL, reason)
```

### 5.5. База знаний

```sql
kb_documents(id, title, product_key NULL, language, source_type 'file'|'url'|'manual', storage_key NULL, version, is_active, uploaded_by, ingest_status 'pending'|'done'|'failed', ingest_error)
kb_chunks(id, document_id, heading_path, content, embedding vector(N), tsv tsvector GENERATED, position, token_count)
kb_gaps(id, lead_id NULL, question, language, best_score REAL, occurrences INT, status 'open'|'resolved'|'ignored', resolved_document_id NULL, resolved_by)
products(key PK, name, description, is_active)
```

`N` — размерность выбранной embedding-модели (ADR-0004). Индексы: HNSW cosine по `embedding`, GIN по `tsv`.

### 5.6. Документы клиентов

```sql
documents(id, client_id, type 'contract'|'proposal'|'letter'|'invoice'|'act'|'other', title, number TEXT NULL, doc_date DATE NULL,
          storage_key, mime, size_bytes, extracted_text TEXT, tsv GENERATED, uploaded_by, is_visible_to_client BOOL DEFAULT true)
document_access_log(id, document_id, accessed_by_type 'bot'|'user', accessed_by_id, tg_user_id NULL, created_at)
service_requests(id, client_id, lead_id NULL, summary, status 'open'|'closed', closed_by NULL,
                 resolution TEXT NULL, closed_at NULL)   -- создаёт инструмент create_service_request; закрытие — с ответом клиенту (ADR-0015)
-- Связи с эскалацией нет: закрытие запроса закрывает open/snoozed info-эскалацию лида, все причины
-- которой — service_request, и только когда у лида не осталось других открытых запросов.
```

Документы скачиваются сотрудником через API (`GET /documents/{id}/download`, запись в журнал), клиентом — файлом от бота; RustFS наружу не публикуется.

### 5.7. Настройки

```sql
settings(key PK, value JSONB, schema_version INT, updated_by, updated_at)
```
Ключи и JSON-схемы валидируются Pydantic-моделями в `app/schemas/settings.py`:
`company` (`name`, `crm_base_url` — по умолчанию из окружения `CRM_PUBLIC_URL`/`CRM_DOMAIN`, заводское `http://localhost` подменяется на чтении (`get()`), форма «Настройки» (`raw()`) видит сохранённое значение, поэтому сохранение секции не фиксирует выведенный адрес; заданное админом остаётся (W15-H8a), `phone`/`site`/`address` — ответ бота на «дайте контакты», Q-023; `cabinet_url` — адрес кабинета клиента для кнопки «Кабинет» под сообщениями бота о событиях ERP, пусто — кнопки нет, FIX-34), `business_hours`, `texts` (greeting/consent/handoff/off_hours × ru/uz/en, плейсхолдеры `{sla}`, `{next}`, `{hours}`; подписи меню `menu_*`, команды клиента `docs_*`/`request_*`/`client_only`, номер `phone_*` — Q-011/Q-020, события ERP клиенту `erp_*` (КП, счёт, оплата, поставка, акт, кнопки) и сотруднику `erp_staff_*`, FIX-34; приёмка и замечания по строкам поставки — запись в ленту лида `erp_note_delivery_line_*` и сообщение ответственному `erp_staff_delivery_line_disputed`, клиенту бот молчит, FIX-37; класс `ClientBotTexts`), `escalation` (триггеры, пороги, `no_progress_turns`, SLA, `price_always_to_manager`, `require_phone_for_human_request` — просьба лида о менеджере только после номера, решение владельца 2026-10-12, §8.2), `qualification` (критерии «Квалифицирован»: обязательные и дополнительные факты, горизонт срока, роли — ADR-0016), `kb` (`min_score` — по умолчанию 0.70, калибровка аудита 2026-10-12: бессмыслица набирала 0.60–0.68; `top_k`; `search_timeout_s` — таймаут попытки kb-mcp, 6 с), `bot` (persona, `max_words` — по умолчанию 60, `history_messages`, `rate_limit_per_minute`, `unresponsive_days`, `ask_phone` — один раз попросить номер, Q-020; `assist_enabled`, `assist_max_input_chars` — ИИ-помощь менеджеру «Черновик»/«Улучшить», `POST /leads/{id}/assist`, право `leads:assist`, Q-019), `competitors`, `stop_words`, `notifications` (`channel_id`, `duty_user_ids`), `budget` (`daily_usd`, `erp_daily_usd` — бюджет ERP на день, $1, только показ на «Расходах» и «Состоянии системы», M3-CRM-09, §13.1; `fallback_model_enabled`, `providers` — дневной лимит USD по провайдеру LiteLLM: `anthropic` 3, `gemini` 1, 0 — без лимита; Q-008), `deals` (`lost_reasons` — справочник причин отказа, `currency` — валюта новых сделок, UZS; ADR-0019), `bot_profile` (`name` ≤ 64, `description` ≤ 512 — «Что умеет бот» до /start, `short_description` ≤ 120, каждое × ru/uz/en; правится и публикуется в «Подключениях» через `setMyName`/`setMyDescription`/`setMyShortDescription` — русский без `language_code`, пустой русский не трогает BotFather; публикуются только отличия, при сохранении и старте бота; на экране «Настройки» не показывается — ADR-0018), `integrations` (`erp_base_url` — корень ERP без пути `/api/integration/v1`; правится в «Подключениях» → «ERP», на экране «Настройки» не показывается; секреты коннектора — в `integration_secrets`, M3-CRM-02; `smtp` — коннектор «Почта», M3-CRM-08, ADR-0023: `host`, `port` 587, `security` starttls|ssl|none, `from_email`, `from_name`; правится в «Подключениях» → «Почта», логин и пароль — `integration_secrets`, запасной источник — `.env` `SMTP_*`).
`company` (`name`, `crm_base_url`, `phone`/`site`/`address` — ответ бота на «дайте контакты», Q-023), `business_hours`, `texts` (greeting/consent/handoff/off_hours × ru/uz/en, плейсхолдеры `{sla}`, `{next}`, `{hours}`; подписи меню `menu_*`, команды клиента `docs_*`/`request_*`/`client_only`, номер `phone_*` — Q-011/Q-020, класс `ClientBotTexts`), `escalation` (триггеры, пороги, `no_progress_turns`, SLA, `price_always_to_manager`, `require_phone_for_human_request` — просьба лида о менеджере только после номера, решение владельца 2026-10-12, §8.2), `qualification` (критерии «Квалифицирован»: обязательные и дополнительные факты, горизонт срока, роли — ADR-0016), `kb` (`min_score` — по умолчанию 0.70, калибровка аудита 2026-10-12: бессмыслица набирала 0.60–0.68; `top_k`; `search_timeout_s` — таймаут попытки kb-mcp, 6 с), `bot` (persona, `max_words` — по умолчанию 60, `history_messages`, `rate_limit_per_minute`, `unresponsive_days`, `ask_phone` — один раз попросить номер, Q-020; `assist_enabled`, `assist_max_input_chars` — ИИ-помощь менеджеру «Черновик»/«Улучшить», `POST /leads/{id}/assist`, право `leads:assist`, Q-019), `competitors`, `stop_words`, `notifications` (`channel_id`, `duty_user_ids`), `budget` (`daily_usd`, `erp_daily_usd` — бюджет ERP на день, $1, только показ на «Расходах» и «Состоянии системы», M3-CRM-09, §13.1; `fallback_model_enabled`, `providers` — дневной лимит USD по провайдеру LiteLLM: `anthropic` 3, `gemini` 1, 0 — без лимита; Q-008), `deals` (`lost_reasons` — справочник причин отказа, `currency` — валюта новых сделок, UZS; ADR-0019), `bot_profile` (`name` ≤ 64, `description` ≤ 512 — «Что умеет бот» до /start, `short_description` ≤ 120, каждое × ru/uz/en; правится и публикуется в «Подключениях» через `setMyName`/`setMyDescription`/`setMyShortDescription` — русский без `language_code`, пустой русский не трогает BotFather; публикуются только отличия, при сохранении и старте бота; на экране «Настройки» не показывается — ADR-0018), `integrations` (`erp_base_url` — корень ERP без пути `/api/integration/v1`; правится в «Подключениях» → «ERP», на экране «Настройки» не показывается; секреты коннектора — в `integration_secrets`, M3-CRM-02), `web_form` (антиспам публичной формы «Запрос», M3-CRM-05: `min_fill_seconds` 3, `token_ttl_minutes` 60, `rate_limit_per_hour` 5 на IP, `max_text_chars` 4000, `first_response_sla_minutes` 15 — рабочих минут на первый ответ человека на запрос с сайта (D1-9, §6.5); раздел «Правила передачи» в «Настройках»).

Ключ `service_alerts` (центр внешних сервисов, §13.2): `telegram_admins` (личное сообщение админам с подпиской), `telegram_channel` (`fallback` — в канал, если в личку никому не доставлено | `always` | `never`), `email_admins`, `extra_emails` (до 10), `repeat_minutes` (устарело, не используется: оповещения идут по правилам §13.2 — «Сломано» после 15 минут непрерывного сбоя, не больше одного в сутки на причину, «Восстановлено» после 5 минут непрерывного `ok`). Текст `texts.maintenance` (ru/uz/en) — ответ клиенту, пока Telegram выключен вручную.

### 5.8. Техническое

- Таблицы Procrastinate (`procrastinate_*`) — создаются его миграциями.
- Таблицы LangGraph `PostgresSaver` (`checkpoints`, `checkpoint_writes`, ...).
- `system_alerts(key PK, active, detail, first_seen_at, sent_at, resolved_at, updated_at)` — дедупликация системных алертов монитора (§13).
- `bot_runtime(id PK=1, running, mode, source, username, last_error, profile jsonb, heartbeat_at, started_at, restart_requested_at, restart_applied_at, updated_at)` — единственная строка: состояние процесса `crm-bot` (пишет он) и запрос на перезапуск при смене токена (пишет `crm-api`); токена в таблице нет (S0-4, `docs/runbooks/crm-bot.md`).
- `integration_secrets(key PK, ciphertext, last4, updated_by FK users, updated_at)` — секреты интеграций, введённые админом в CRM (`telegram_bot_token`; `erp_service_token`, `erp_webhook_secret` — коннектор ERP, M3-CRM-02; `smtp_username`, `smtp_password` — коннектор «Почта», M3-CRM-08); шифр Fernet с ключом из `SECRETS_KEY`, значение не возвращается API и не пишется в логи (ADR-0018).
- `client_notices(id, kind 'web_confirmation'|'request_accepted'|'portal_invite', lead_id FK leads NULL, client_id FK clients NULL, contact_id FK client_contacts NULL, channel 'telegram'|'email'|'both'|'none', status 'queued'|'sent'|'failed'|'skipped', error NULL — код причины (`domain/notice_errors.py`), detail jsonb (`sent_via`, `telegram` pending|sent|failed), attempts, email_log_id FK email_log NULL, sent_at NULL, requested_by_user_id FK users NULL, dedupe_key UNIQUE NULL, created_at, updated_at)`, индексы `(lead_id, kind)`, `(client_id, kind)` — сообщения клиенту от системы и их итог для карточек лида и клиента (D1-9, миграция `0044_client_notices`); адресов и телефонов в строке нет, обезличивание лида удаляет её вместе с письмом в `email_log`. Колонки `leads.first_response_due_at`, `leads.first_response_notified_at` (срок первого ответа на запрос с сайта) и `client_contacts.preferred_channel 'telegram'|'email'|'both'|NULL` (канал приглашения в кабинет) — там же.
- `email_log(id, to_email text, subject, template, lang, status 'queued'|'sent'|'failed'|'skipped_no_smtp', error NULL, attempts, body_ciphertext NULL, user_id FK users NULL, requested_by FK users NULL, sent_at NULL, created_at, updated_at, source 'crm'|'erp'|'eds' DEFAULT 'crm', purpose NULL, request_key NULL, bus_event_id NULL, ref_kind NULL, ref_id NULL, reply_to NULL, notify bool, html_ciphertext NULL, links_ciphertext NULL, attachments jsonb NULL)`, индексы по `created_at`, UNIQUE (`source`, `request_key`) где ключ задан, по `bus_event_id` — журнал доставки почты ансамбля (M3-CRM-08, ADR-0023, миграция `0021_email_log`; один отправитель — W18A-P1, ревизия `ac71231f330f`, CONTRACTS §9.9): свои письма CRM и письма, которые ERP и EDS просят отправить по шине (`source`, `purpose` — код шаблона отправителя, `request_key` — ключ идемпотентности отправителя, `ref` — его объект, `notify` — публиковать ли итог `crm.mail.sent|failed`). Тело, HTML и ссылки на вложения — только шифртекстом Fernet (`SECRETS_KEY`) и только до отправки или последней из 3 попыток; после — `NULL`; у вложений в строке — только метаданные (имя, тип, размер, sha256). Отправка — задача Procrastinate `send_email` (очередь `notify`, блокировка по строке), не в пути запроса; временная ошибка SMTP оставляет `queued` с причиной, постоянная (5xx) — сразу `failed`; сборщик `email_queue_sweep` (раз в 2 мин) ставит потерянные; `skipped_no_smtp` — коннектор не настроен, письмо не ставилось.
- `external_service_checks(id, service_key, checked_at, tier 'cheap'|'heavy'|'manual', status 'ok'|'warn'|'fail'|'unknown'|'off', latency_ms NULL, summary, error NULL, hint NULL, metrics JSONB)`, индексы `(service_key, checked_at)` и `checked_at` — строка на проверку внешнего сервиса, хранится 8 дней; `external_service_incidents(id, service_key, started_at, ended_at NULL, last_error NULL, summary, alerted_at NULL, recovery_alerted_at NULL)`, уникальный открытый инцидент на сервис (частичный индекс `ended_at IS NULL`), хранится 90 дней; `external_service_switches(service_key PK, disabled, reason NULL, state JSONB, changed_by FK users NULL, changed_at)` — выключатели; миграция `0022_external_services` (центр внешних сервисов, §13.2, ADR-0024). `external_cause_alerts(id, cause_key, started_at, ended_at NULL, alerted_at NULL, recovery_alerted_at NULL, suppressed_at NULL, headline, service_keys JSONB)` — журнал причин «Сломано» (общий корень нескольких сервисов) и отметки оповещений, частичный уникальный индекс открытой записи на причину (`ended_at IS NULL`) — дедупликация оповещений переживает рестарт; миграция `0041_external_cause_alerts` (+ частичные индексы `external_service_checks` по `ok`, не-`ok`, не-`fail` для «с какого времени» и полосы сбоя без квадратичного чтения) (W15-H3, §13.2).
- `telegram_chat_candidates(chat_id PK, title, kind, detected_at)` — каналы и группы, куда бота добавили администратором (событие `my_chat_member`); из них админ выбирает канал команды (ADR-0018).
- `llm_usage(id, at, purpose, alias, provider, model, input_tokens, output_tokens, cost_usd, lead_id NULL, kind 'work'|'test')`, индекс по `at` — единый учёт каждого вызова модели (чат и эмбеддинги; стоимость — заголовок LiteLLM `x-litellm-response-cost`); `kind='test'` — `LLM_USAGE_KIND=test` в make eval/eval-quick/load-test/kb-eval, а для песочницы «Проверить бота» — на вызов (`kind_scope('test')`, §10.1). Источник для BudgetGuard, монитора и вкладки «CRM подробно» экрана «Расходы» (вкладка «Ансамбль» — журнал LiteLLM, §13.1).

---

## 6. Домен

### 6.1. Жизненный цикл

`new → engaged → qualified → handoff → in_progress → won → customer`; боковая: `lost` (выход — новое сообщение лида или «Забрать»); временная: `unresponsive`. Клиент может открыть новую сделку: `customer → in_progress → won|lost → customer` (ADR-0015).

**Ансамбль CRM ↔ ERP (ADR-0022, proposed).** «Передан в бэк-офис» = стадия `customer`. Режим определяет код по факту «коннектор ERP настроен» (`integrations/erp.erp_connector_configured`, `domain/backoffice.py`): без коннектора (`local`) — поведение выше без изменений («Сделать клиентом» из `won`, итог сделки — действия CRM); с коннектором (`erp`) — «Передать в бэк-офис» (та же операция `make_customer`) из `in_progress` | `won` | `customer` с вызовом `POST /clients/handoff` (M3-CRM-03), итог сделки приходит событиями ERP `deal.won`/`deal.lost` в зеркало `deals` (`domain/deals.plan_erp_outcome`), **стадия лида событиями ERP не меняется**; в CRM из `in_progress` остаётся только «Закрыть отказом» (`may_close_locally`). Повторная передача тому же клиенту — идемпотентна (ничего не меняет, ERP не вызывается). Зеркальная сделка (`deals.erp_deal_id`) — копия заявки ERP: название, сумму, валюту, стадию и причину отказа ведёт бэк-офис (приёмник событий перезаписывает их), `PATCH /deals/{id}` с изменением этих полей — 409 `deal_owned_by_erp` (`details.fields`); ответственный, срок и продукт правятся в CRM (FIX-57, I-26). Номер заявки в карточке лида — `leads.erp_request_id`, результат передачи этого лида, а не последняя сделка (поздние заявки клиента из Cabinet привязываются к тому же лиду, D-10).

**«Создать заявку» (CRM-03, W16-D1-2; SPEC-v3 §3.1 шаг 2).** `POST /leads/{id}/actions/create_request` из любой активной
стадии лида (кроме `lost`; переход в `customer` — действием менеджера, `domain/stage_machine.py`) и `POST /clients/{id}/actions/create_request`
из карточки клиента: клиент (выбранный или новая компания с ИНН), контакт с хотя бы одним каналом (телефон, e-mail или Telegram
лида; e-mail не обязателен — 422 `contact_channel_required`), суть, срочность, id файла письма директору в EDS; согласие
обязательно (бот или отметка сотрудника `consent` — 422 `handoff_no_consent`). В одной транзакции: лид → клиент, менеджер —
ответственный за переписку, диалог ведёт бот, активная передача закрывается (`request_created`), заявка — строка `deals` со
`erp_request_status = pending`. В ERP — задачей `erp_create_request` после коммита (`services/erp_requests.py`): клиента нет в
ERP — передача без заявки, затем `POST /clients/{crm_client_id}/requests` шва 0.9.0; итог — `erp_request_status`,
`erp_deal_id`, `erp_number`. Без коннектора ERP — 409 `erp_not_configured`. Идемпотентность — `request_key` формы (UUID от клиента): повтор — 200 с той
же заявкой без новой строки и задачи (блокировка лида или клиента, UNIQUE `deals.request_key`); ключ заявки другого лида —
409 `request_key_reused`; ERP ответила 409 `IDEMPOTENCY_CONFLICT` (тело изменилось) — заявка `failed`, `erp_request_conflict`. Статус лида для Платформы (CRM-02) —
`platform_status` в ответе лида и фильтры `GET /leads?platform_status=&overdue=` (`domain/client_requests.py`).

### 6.2. State machine (`domain/stage_machine.py`)

```python
ALLOWED = {
  ("new","engaged"):      {"qualifier"},
  ("engaged","qualified"):{"qualifier"},
  ("*","handoff"):        {"trigger"},            # из new|engaged|qualified|unresponsive
  ("handoff","in_progress"): {"user"},            # Забрать
  ("new"|"engaged"|"qualified"|"unresponsive","in_progress"): {"user"},  # Забрать из CRM без эскалации (ADR-0012)
  ("handoff","engaged"|"qualified"): {"user"},    # Вернуть боту → в стадию до handoff
  ("in_progress","won"|"lost"): {"user"},
  ("in_progress","engaged"|"qualified"): {"user"},# Вернуть боту из работы
  ("won","customer"):     {"user","system"},      # при привязке к client; system — итог повторной сделки
  ("lost","customer"):    {"system"},             # отказ по повторной сделке клиента (ADR-0015)
  ("*","unresponsive"):   {"timer"},              # из new|engaged|qualified; не handoff — там ждёт лид (ADR-0015)
  ("unresponsive"|"lost","engaged"): {"system"},  # новое сообщение лида
  ("lost","in_progress"): {"user"},               # Забрать вернувшегося (ADR-0015)
  ("customer","in_progress"): {"user"},           # Новая сделка с клиентом (ADR-0015)
  ("customer","won"|"engaged"): {"user"},         # отвязан последний подтверждённый Telegram: в won, если клиентом стал из won, иначе engaged
}
```
Квалификатор может предлагать только `engaged`, `qualified`. Всё остальное отклоняется с записью `rejected_reason`.

Источник `erp` (`TransitionSource.ERP`, ADR-0022) не имеет ни одного ребра: `decide()` отклоняет любой переход из события ERP до обращения к таблице, в `stage_transitions` он не записывается. Из каких стадий разрешена передача в бэк-офис по режиму — `domain/backoffice.HANDOFF_FROM` (`local`: `won`, `customer`; `erp`: `in_progress`, `won`, `customer`), целевая стадия всегда `customer`.

### 6.3. Score (`domain/scoring.py`)

Детерминированная функция от `qualification`, последнего `QualifierOutput` и флагов триггеров: потребность +25; продукт +15; таймлайн ≤3 мес +20 / ≤12 мес +10; роль ЛПР +20 / влияет +10; спросил цену/условия +15; просьба о контакте +25; негатив −10. Клиппинг 0..100. Весы — в коде с тестами, не в настройках (изменение веса = осознанное решение с ADR-заметкой).

### 6.4. Согласие (`domain/consent.py`)

**Согласие за лида, заведённого вручную (FIX-57, D-8).** Лид из звонка, письма или рекомендации (`source` ∈ `phone|email|referral`) боту не пишет, а «Передать в бэк-офис» без согласия — 422 `handoff_no_consent`. Сотрудник отмечает согласие действием «Согласие получено» (`POST /leads/{id}/actions/record_consent`, способ `phone|email|paper` + комментарий ≤ 500): право `clients:write`, чужого лида — только админ (403 `not_lead_owner`); пишется `consent_given_at` = сейчас, `consent_version = "manual"`, `consent_method`; аудит `lead.consent_recorded` (кто, когда, способ, комментарий) и заметка в ленте лида. Повторная отметка идемпотентна (`recorded: false`, первое согласие не меняется); согласие, данное лидом самим (бот, форма), не перезаписывается; лид из Telegram соглашается в боте — 409 `consent_via_bot`. Как и после формы «Запрос», версия не равна версии текста бота: бот при первом сообщении лида спросит своё согласие. В ERP уходит `consent {given_at, version: "manual"}` как есть; способ остаётся в CRM. Отзыва согласия в CRM нет.

До `consent_given_at` бот отвечает только приветствием + текстом согласия с кнопкой. Текст версионируется (`consent_version`); при смене версии согласие запрашивается повторно при следующем сообщении. Команда `/delete` → `LeadService.erase(lead_id)`: тексты сообщений заменяются на `[удалено по запросу]`, `telegram_identities` обезличивается, запись в `audit_log`; агрегаты для дашборда сохраняются.

---

### 6.5. Источники лидов и склейка по номеру (`domain/lead_sources.py`, M3-CRM-05)

Три входа клиента (ARCHITECTURE §17) при одном жизненном цикле §6.1:

| Источник | Как появляется | Стадия / ведущий при создании | Где во «Входящих» |
|---|---|---|---|
| `telegram` | первое сообщение боту | `new`, бот | как прежде (передачи по §8) |
| `web` | `POST /api/v1/leads/web` — форма «Запрос» на странице входа Cabinet, без аутентификации | `new`, `owner_mode=paused`, без ответственного; бот ему не пишет (Telegram-идентичности нет) | «Без ответственного» |
| `phone` / `email` / `referral` | `POST /api/v1/leads` (`leads:create`, admin/manager) — «Новый лид» во «Входящих» | `in_progress` (переход `new → in_progress`, `user`, «created manually»), ведёт создавший | «Мои» |

Контакты лида без Telegram — `leads.phone_e164` (E.164, `normalize_phone_e164`: 9 цифр Узбекистана → `+998…`), `leads.email`, `leads.company_name`; в карточке — «Источник», компания, почта, телефон (`LeadDetail.phone_e164` — из карточки, иначе из Telegram).

**Антиспам формы** (`domain/web_form.py`, без внешних сервисов): honeypot-поле `website` (заполнено → 202 с `lead_id: null`, лид не создаётся), подписанный токен формы `GET /api/v1/leads/web/token` (HMAC по `JWT_SECRET`, минимальное время заполнения и срок жизни — `settings.web_form`), скользящее окно по IP в памяти процесса api (`rate_limit_per_hour`, 429 `rate_limited`; Q-13), лимит длины полей. Ошибки — ADR-0017: `consent_required` | `form_token_invalid` | `form_too_fast` | `form_token_expired` | `contact_required` | `invalid_phone` | `invalid_email`. CORS — только для `/api/v1/leads/web*` и только origin из `CABINET_ORIGIN` (`api/cors.py`). Повторный запрос известного контакта (тот же номер или почта) — заметка `[web] …` в существующей карточке, не вторая. Аудит: `lead.create_web`, `lead.web_request` (actor `system`, IP).

**Путь нового клиента (D1-9, SPEC-v3 §3.1 шаг 1 и §8).** В транзакции приёма запроса (`services/lead_intake.py`) заводятся: срок первого ответа `leads.first_response_due_at` (`settings.web_form.first_response_sla_minutes` рабочих минут, `services/web_lead_sla.py`) и строка подтверждения клиенту `client_notices` (`kind=web_confirmation`: Telegram, если у лида есть чат с ботом — повторный запрос известного клиента; иначе письмо; только телефон — `skipped`/`no_channel`, менеджер видит «позвоните»). После коммита `on_web_lead` ставит задачи очереди (`tasks/client_notices.py`): `deliver_client_notice` (отправка с повтором; бот заблокирован — письмо), `notify_web_lead` (личное сообщение менеджерам и админам с `notify_leads` и привязанным Telegram; повторный запрос — только ответственному за лида, нет ответственного — никому) и `web_lead_sla_check` в срок: никто не взял — одно напоминание (`first_response_notified_at`); периодический `web_lead_sla_sweep` (5 мин) подхватывает срок, перенесённый склейкой карточек на выжившую. Запрос виден в «Моей очереди» (`GET /inbox` → `unassigned`; BFF обновляет её по `lead.created`). Итоги — `GET /leads/{id}`: `confirmation`, `first_response_due_at`, `first_response_overdue`. Тексты клиенту — один файл на трёх языках `domain/client_texts.py`; причины сбоя словами — `domain/notice_errors.py`. Письмо (без цитаты запроса: оно уходит на любой указанный адрес) несёт подписанную ссылку на бота `https://t.me/<бот>?start=lead_<id>_<срок>_<подпись>` (14 дней): `/start` с ней склеивает чат с запросом (`services/start_links.py`, `merge_with_lead`), один раз.

**Согласие на обработку ПДн** (DECISIONS Q-12, M2-CAB-03): поле `consent` обязательно `true`; `false` или нет поля — 422 `consent_required` (`details.field=consent`), проверка сразу после honeypot и до антиспама (забытая галочка не расходует окно по IP). Новый лид получает `consent_given_at` = время запроса и `consent_version = "web-form"` — это не версия текста бота (`settings.texts.consent_version`), поэтому бот при первом сообщении всё равно спросит своё согласие (оно шире: обработка диалога ИИ). У существующей карточки (повторный запрос) согласие **не** перезаписывается — иначе у Telegram-лида без согласия бота открылась бы обработка диалога квалификатором; факт согласия формы — в аудите (`consent_given_at`, `consent_version` в `after` у `lead.create_web` и `lead.web_request`). Вложений форма не принимает — файлы клиент загружает в Cabinet после приглашения.

**Ручное создание**: для `phone` обязателен телефон, для `email` — почта, для `referral` — любой контакт (`contact_required`). Совпадение телефона/почты с живым лидом → 409 `lead_exists` (`lead_id`, `display_name`), телефона с контактом активного клиента → 409 `client_exists` (`client_id`, `client_name`): фронт предлагает открыть найденного, дубль не создаётся. Аудит `lead.create`.

**Склейка** (`merge_plan`, `services/lead_merge.py`): лид с номером (`web`/`phone`/`email`/`referral`) позже пишет в бот и делится тем же номером (`ClientBotService.save_phone`) — две карточки становятся одной в той же транзакции. Правило (параметризованные тесты `tests/unit/domain/test_lead_sources.py`): остаётся более ранняя карточка и её **источник**; стадия — дальняя по воронке (`STAGE_RANK`, не понижается; `lost` + новое сообщение → `engaged`, `customer` остаётся клиентом), ведущий `human > paused > bot`, ответственный — у кого есть; оценка — максимум, согласие — самое раннее, интересы — объединение, квалификация дополняется, подтверждённый язык важнее автоматического; имя/потребность/компания/почта/телефон — у выжившего, иначе у второго. Переносятся все строки с FK на лида (идентичности, диалоги, заметки, передачи, переходы, прогоны квалификатора, сделки, запросы, пробелы KB) и `llm_usage`; при двух открытых передачах закрывается передача поглощённого (`outcome='merged'`, индекс «одна открытая на лида»); смена стадии — `stage_transitions` (`system`, «merged with lead #N»); поглощённая строка удаляется, её снимок — в аудите `lead.merge`; карточки передач в канале перерисовываются. Обратный случай (Telegram-лид есть, потом ручной с тем же номером) — 409 `lead_exists`, см. выше.

## 7. Агенты

### 7.1. Диалоговый агент (LangGraph)

```
load_context → detect_language → guard_consent → select_mode(prospect|customer)
  → retrieve(kb | docs) → decide → {answer | clarify | fallback | handoff | deliver_document} → persist → enqueue_qualify
```

- `load_context`: лид, идентичность, последние 20 сообщений, заметки с `visible_to_bot`, стадия, `need_summary`, `qualification`, настройки.
- `detect_language`: по тексту; фиксируется после 2 совпадающих сообщений; команда `/lang` для смены.
- `select_mode`: `customer`, если идентичность верифицирована и привязана к `client_id`; иначе `prospect`.
- `retrieve`: `kb-mcp.search_kb` (prospect и customer) и `docs-mcp.search_documents` (только customer). Гибридный поиск: вектор (cosine) + BM25 (`ts_rank_cd`) → RRF → top-6 → порог `kb.min_score`. Попытка поиска ограничена `kb.search_timeout_s`; при сбое — одна повторная, затем ход продолжается с пометкой «KB недоступна» (ход не падает).
- `decide` (код): `owner_mode != bot` → стоп; hard-триггер по стоп-словам/`/human` → `handoff`; документ найден однозначно → `deliver_document`; несколько документов → `choose_document` (кнопки, BOT-07); ни одного → `handoff` (`document_not_found`); «ок/спасибо/понятно» (ru/uz/en) → короткий `texts.smalltalk_ack` без модели; KB недоступна (prospect, не smalltalk) → `fallback` (`reason=kb_unavailable`, без записи в `kb_gaps`); `best_score < min_score` и вопрос по продукту → `fallback`; потребность не ясна и стадия ≤ engaged → `answer` с флагом «один уточняющий вопрос»; иначе `answer`.
- `answer/clarify`: `dialog-model`, промпт `dialog_prospect.md` / `dialog_customer.md`, в контексте только найденные фрагменты. ≤ `bot.max_words` слов (60), без списков, максимум один вопрос. Гарантии кода поверх ответа модели: встречный вопрос в конце убирается, если бот спрашивал в одном из двух предыдущих ответов, в ответ на smalltalk и перед уведомлением о передаче менеджеру. Модель получает настоящий результат инструмента (`ok`/ошибка/`not_allowed`); `create_service_request` возвращает `request_number`, и ответ клиенту обязательно содержит «Запрос №N» (`texts.request_created`), как в `/request`. Промпт запрещает упоминать «базу знаний» и внутренние источники.
- `fallback`: честный отказ + `kb_gaps` (upsert по нормализованному вопросу, `occurrences++`).
- `deliver_document`: отправка файла из S3 (RustFS) через Telegram + `document_access_log`.
- `choose_document` (BOT-07): клиент просит документ, docs-mcp нашёл несколько — без модели `texts.docs_choose` и до 10 кнопок «название · дата» (`doc:<id>`, как у `/docs`); id — только из ответа docs-mcp по клиенту из подписанного контекста, при нажатии принадлежность проверяется заново (`documents.client_id` подтверждённой привязки); чужой id → `texts.document_failed`.
- Таймаут вызова модели 20 с, один ретрай, затем `fallback-model`; при недоступности — служебное сообщение лиду, событие сохраняется.

Инструменты по режимам:

| Инструмент | prospect | customer |
|---|---|---|
| `kb-mcp.search_kb(query, product_key?, top_k)` | ✓ | ✓ |
| `kb-mcp.list_products()` | ✓ | ✓ |
| `crm-mcp.get_lead_context()` | ✓ | ✓ |
| `crm-mcp.update_qualification(patch)` | ✓ | — |
| `crm-mcp.request_callback(preferred_time?)` | ✓ | ✓ |
| `crm-mcp.create_service_request(summary)` | — | ✓ |
| `docs-mcp.search_documents(query, type?, date_from?, date_to?)` | — | ✓ |
| `docs-mcp.get_document_link(document_id)` | — | ✓ |

Ни один инструмент не принимает `lead_id`/`client_id` аргументом — они берутся из контекста вызова (заголовок `X-Agent-Context`, подписанный HMAC ключом из env, живёт 60 с). MCP-сервер проверяет подпись и срок.

### 7.2. Квалификатор (Procrastinate task → LangGraph)

Запуск: задача `qualify_lead(lead_id)` на каждое сообщение лида и бота; `queueing_lock=lead_id` + отложенный старт 5 с для батчинга. Модель `qualifier-model`, structured output (`response_format` json_schema strict), `max_tokens=4096` — рассуждение модели (`reasoning_effort`) расходует тот же лимит, при 1024 длинная карточка обрывалась; ответ с `finish_reason=length` не разбирается, а повторяется (всего 2 попытки, каждая — строка в `llm_usage`), затем честный отказ `qualifier_runs.error`:

```python
class Qualification(BaseModel):
    budget_hint: str | None; timeline: Literal["<1m","<3m","<12m",">12m"] | None
    decision_role: Literal["decision_maker","influencer","researcher"] | None
    company: str | None; company_size: str | None; region: str | None

class QualifierOutput(BaseModel):
    need_summary: str | None
    product_interest: list[str]
    intent: Literal["info","compare","pricing","request_contact","complaint","service","document","smalltalk","other"]
    sentiment: Literal["positive","neutral","negative"]
    qualification: Qualification
    proposed_stage: Literal["new","engaged","qualified"]
    recommend_escalation: bool
    escalation_reason: str | None
    confidence: float = Field(ge=0, le=1)
    next_best_action: str
```

Пост-обработка в коде: стадия `qualified` — по критериям `settings.qualification` из извлечённых фактов (`domain/qualification_rules.py`, ADR-0016; модель предлагает только `new`/`engaged`) → state machine → score → триггеры → `qualifier_runs` → при эскалации §8.2. Запись `cost_usd` из ответа LiteLLM.

### 7.3. Клиентский режим

- Привязка: менеджер в CRM на карточке клиента «Привязать Telegram» → выбирает идентичность из лидов этого клиента или вводит `tg_user_id`/username → `verified_at`. «Отвязать» последний подтверждённый Telegram лида очищает `leads.client_id`, а лида в стадии `customer` возвращает в `won` (если клиентом он стал из «Выиграна»), иначе в `engaged` (`stage_machine.stage_after_unlink`, аудит `client.unlink_telegram`). Дополнительно бот может запросить номер телефона (`request_contact`) и сверить с `clients`-контактами — ускоряет, но не заменяет подтверждение менеджером.
- Интенты: документ, статус (заглушка в v2 → `create_service_request`), поддержка, человек.
- Все обращения к `documents` фильтруются `client_id` из контекста на уровне SQL; тесты на попытку доступа к чужому `document_id` обязательны.

### 7.4. Промпты

Хранятся в `backend/prompts/*.md`, версионируются в Langfuse Prompt Management (имя = путь файла, версия = git sha). Структура промптов — как в v1 спецификации, с добавлением `dialog_customer.md`: роль сервисного ассистента, выдача документов только найденных, никаких обещаний по срокам/условиям, при любом запросе на изменение условий — менеджер.

---

## 8. Эскалация

### 8.1. Триггеры (`domain/triggers.py`; параметры — `settings.escalation`)

| Код | Условие | Приоритет |
|---|---|---|
| `human_requested` | Интент/команда «человек, оператор, менеджер»; без номера телефона — сначала номер (§8.2, п. 0) | hot |
| `callback_requested` | Интент `request_contact` или вызов `request_callback` | hot |
| `price_or_contract_asked` | Интент `pricing` и цена не названа из базы (`price_quoted`, `domain/pricing.py`) — бот обещал расчёт менеджера; флаг `escalation.price_always_to_manager` — любой ценовой вопрос (ADR-0016) | hot |
| `negative_sentiment` | `sentiment=negative` или стоп-слова | hot |
| `complaint` | Интент `complaint` | hot |
| `kb_gap_streak` | 2 подряд fallback | warm |
| `no_progress` | ≥ N ходов бота без смены стадии и роста score | warm |
| `competitor_mentioned` | Словарь конкурентов | warm |
| `high_score` | `score ≥ 70` | warm |
| `qualifier_recommend` | `recommend_escalation ∧ confidence ≥ 0.7` | warm |
| `document_not_found` (customer) | Запрос документа без результата | warm |
| `service_request` (customer) | Интент `service` | info |
| `agent_unavailable` | Сбой диалогового агента (лиду — `texts.service_unavailable` с кнопкой «Позвать менеджера»; сбой считается в `consecutive_fallbacks`, повторный подряд → `kb_gap_streak` warm: лиду одно «передаю менеджеру», без второго извинения) | info |
| `delivery_failed` | Бот не смог отправить файл документа | info |

Триггер → эскалация всегда. Одна открытая эскалация на лида: новые триггеры дописываются, приоритет повышается, в канале редактируется существующий пост.

### 8.2. Процедура

0. **Номер перед передачей по просьбе лида** (решение владельца 2026-10-12; `domain/handoff_gate.py: needs_phone_first`, `services/client_bot.py: hold_handoff_for_phone`, `bot/phone_gate.py`). Лид сам просит менеджера (меню «Связаться с менеджером»/`/human`, слова `escalation.human_request_terms`, «Да» на предложение позвать менеджера), флаг `escalation.require_phone_for_human_request` включён (по умолчанию), у лида нет `telegram_identities.phone_e164`, он не подтверждённый клиент, согласие дано и лида ведёт бот (`owner_mode=bot`) → эскалация **не создаётся**: лиду `texts.phone_before_manager` с одноразовой клавиатурой «Поделиться номером / Не сейчас» (`PhoneForm.pending`), в `leads.qualification` — `handoff_pending_phone_at` (и `phone_asked_at`, чтобы Q-020 не спросил второй раз). Свой контакт при пометке → номер сохраняется и передача идёт тем же путём, что `/human` (`ConversationService.handle_message(human_requested=True)`: эскалация, пост в канал, `texts.handoff`/`off_hours`); «Не сейчас» → `texts.phone_declined_manager`, пометка снимается, бот отвечает дальше, следующая просьба снова спрашивает номер. Передачи по сигналам системы (стоп-слова, негатив, цена, квалификатор, вложения, сбой ИИ), лид на паузе или у менеджера, клиенты и лиды с номером — без изменений; в карточке канала строка «Номер: …» / «Номер: не указан».
1. Для `hot`/`warm`: `stage=handoff` (если применимо), `owner_mode=paused`, лиду — текст `texts.handoff` (вне рабочих часов — `texts.off_hours`). Эскалация `info` — только сведения для команды (пост в канал), бот продолжает отвечать; при повышении до `warm`/`hot` выполняется этот пункт (ADR-0015).
2. Пост в канал (§9.1). `escalations.channel_message_id`.
3. Таймер SLA (Procrastinate, `escalation.sla_minutes`, по умолчанию 15, только в рабочие часы): если `status=open` — редактировать пост с пометкой ⏰ и упомянуть `duty_user_ids`.
4. Таймер повторного напоминания через 60 мин, затем ежедневно в 09:05 сводка открытых.

---

## 9. Telegram

### 9.1. Канал команды

Бот — администратор приватного канала (`settings.notifications.channel_id`). Пост-карточка:

```
🔥 Лид #124 · Азиз · RU · Оценка 75 · Квалифицирован
Номер: +998901234567
Потребность: интеграция онлайн-кассы с 1С для 3 магазинов
Интерес: Интеграция касс · Срок: до 3 мес. · Роль: ЛПР
Почему: Цена/условия — нет в базе; Просит звонок
Рекомендация: позвонить сегодня, уточнить число касс и версию 1С
Последнее: 👤 «Ок, пусть позвонят, лучше после 15:00»
⏳ ждёт 12 мин · с 14:20

[ Забрать ]   [ Открыть в CRM ]
```

Метки стадий, причин передачи, сроков и ролей — те же, что в CRM (один словарь канала `app/services/channel_texts.py`, термин — «Передача», Q-015); порог «бот N раз подряд не нашёл ответ» — из `settings.escalation.kb_gap_streak`.

- **Забрать** — `callback_query`; бот сопоставляет `from.id` с `users.tg_user_id`; нет совпадения → ответ «Привяжите Telegram в профиле CRM». Успех → `LeadService.take(lead_id, user)` (те же правила, что из CRM) → пост редактируется: «Забрал: Имя · 14:32», кнопка исчезает.
- Кнопка несёт id передачи: `take:e<escalation_id>`. Передача уже не открыта/не отложена (или старая кнопка `take:<lead_id>`) → «Карточка устарела», пост пересинхронизируется. Лида ведёт другой сотрудник → ответ «Лида ведёт Имя…» — кнопка не перехватывает лида даже у админа (передача — только «Передать коллеге» в CRM).
- Карточка без сырых кодов: продукты — названиями из `products` (неизвестные ключи и `company` не показываются), время — в `business_hours.timezone`; «Забрал: Имя · 14:32» (не сегодня — «пн 14:32»); «⏳ ждёт N · с HH:MM» (больше суток — «2 д 3 ч»); «💤 Отложено до 15:00 · Имя».
- Пост запоминает `escalations.channel_chat_id` (смена канала в настройках не ломает старые посты) и `posted_priority`. Telegram ответил «message to edit not found»/«chat not found»/Forbidden → `channel_message_id` очищается; передачу можно забрать → карточка публикуется заново в текущий канал, иначе молча завершается.
- Срок реакции и упоминания — только для `warm`/`hot`; `info` — сигнал без SLA (бот продолжает отвечать). Передача из-за сбоя ИИ (`agent_unavailable`) — такая же рабочая карточка в канал, менеджер забирает клиента; системный сигнал о сбое — строка «Ответы ИИ клиентам» центра внешних сервисов (§13.2: `messages` бота за 5 минут, общая политика оповещений), прежний алерт монитора `ai_failures` снят.
- Стал горячим → ответ на пост «🔺 Стал горячим», срок реакции заново (`reset_sla`), новая проверка SLA; конец «Отложить» → ответ «⏰ Снова открыт после «Отложить»» и тоже новый срок. Дежурных нет → SLA-напоминание упоминает активных менеджеров с Telegram (до 5).
- «Передать коллеге» → передача переписывается на нового ответственного (карточка обновляется), ему — личное сообщение «Вам передан лид #N …». Отказ Telegram в личке → `users.tg_dm_failed_at` (виден в профиле, снимается успешной отправкой); окно тишины `manager_notified_at` ставится только после доставки.
- Ссылки в уведомлениях — всегда `<a href>`; кнопка-ссылка — только для https. **Ссылки ведут в Платформу** (W15-H8b, B-009): одна карта маршрутов — `domain/platform_links.py::notification_link` (лид → `/crm/leads?lead=L-0042&panel=open&tab=card`, итоги дня → `/dashboard/summary`, «Подключения» → `/admin/integrations`, журнал обмена → `/admin/bus`); маршрут объекта без настоящего экрана ведёт в раздел Платформы с мостом H1 («Открыть в …»), после волны 16 тот же маршрут открывает экран. База — `PLATFORM_PUBLIC_URL` (`SettingsService.links()`); не задан — прежняя ссылка в старую CRM (`company.crm_base_url` + `/leads/{id}`, `/dashboard`; у «Подключений» запасной ссылки нет) и предупреждение в строке «Адреса для ссылок» «Состояния системы» (адрес CRM проверяется, только пока адреса Платформы нет). Потребители: личные сообщения лиду/менеджеру (`StaffNotifier`), карточка, напоминания и сводка в канале (`notification_data`), итоги дня (`MonitorService`), оповещения «Внешних сервисов» («Открыть: Платформа → Admin → Подключения» — ссылка в Telegram и адрес в письме). Тест `test_platform_links` сверяет маршруты с разделами Платформы (`modules/*/module.ts`). `company.crm_base_url` принимает только `http(s)://…` (валидатор схемы, как `cabinet_url`); `domain/crm_url.py::crm_url_problem` — проверка адреса CRM (не https / localhost) для «Состояния», когда он остаётся запасным.
- Сводка 09:05: горячие → тёплые → инфо, имя, причина, сколько ждёт; больше 30 — «…и ещё N».
- **Открыть в CRM** — URL `https://<host>/leads/124`.
- Больше кнопок в канале нет. Ответы лиду — только из CRM.

### 9.2. Клиентский бот

Команды: `/start`, `/lang`, `/human`, `/delete`, `/help`; клиенту — `/docs`, `/request`, `/status`.

**Интерфейс по статусу (Q-011, Q-020; `domain/bot_menu.py`, `services/client_bot.py`, `bot/status.py`).** Меню чата (`BotCommandScopeChat`) выбирает код после каждого сообщения/кнопки лида; публикуется только при смене варианта или языка (кэш в процессе бота). Действие в CRM, меняющее вариант (`owner_mode` лида изменился — «Забрать», «Вернуть боту», итог сделки, «Новая сделка»; «Сделать клиентом», привязка/отвязка Telegram, (де)активация клиента), после коммита ставит задачу `refresh_chat_menu(tg_user_id)` (очередь `notify`, `queueing_lock=menu-<tg_user_id>`): статус считается при выполнении, повтор безвреден, сбой Telegram и недоступная очередь — в лог, действие CRM не отменяется:

| Статус | Признак | Меню |
|---|---|---|
| prospect | нет подтверждённой привязки к клиенту | Начать · Связаться с менеджером · Сменить язык · Что умеет бот · Удалить переписку |
| with_manager | prospect и `owner_mode = human` | то же без «Связаться с менеджером» |
| client | `verified_client` (как режим customer агента) | Мои документы `/docs` · Запрос менеджеру `/request` · Статус запроса `/status` · Связаться с менеджером `/human` · Сменить язык · Что умеет бот `/help` · Удалить переписку |

**Привязка Telegram сотрудником (W15-H6; `bot/staff_link.py`, `services/staff_telegram_link.py`).** В профиле Платформы «Привязать Telegram» выпускает одноразовую ссылку `https://t.me/<бот>?start=staff_<код>` (код 16 символов `A-Za-z0-9_-`, 10 минут; новая ссылка гасит прежнюю; нужен запущенный бот — иначе 409 `bot_not_configured`/`bot_not_running`). Бот по `/start staff_<код>` в личном чате привязывает `users.tg_user_id` и ник тому, кто выпустил код, и отвечает подтверждением на языке сотрудника; просроченный, использованный или чужой код — «ссылка недействительна»; Telegram, уже привязанный к другому сотруднику, — отказ. После привязки владелец получает письмо «К профилю привязан Telegram» (`StaffLinkNotice`, если коннектор «Почта» настроен) и ответ бота с подсказкой «если это не вы — отвяжите»; самопривязанный Telegram моложе 24 часов (`TRUST_AFTER`) ссылку сброса пароля не получает. Роутер подключён раньше клиентских и перехватывает только `/start` с аргументом `staff_<16 символов>`: `/start` без аргумента и клиентские deep-link'и идут прежним путём (`handlers.on_start`). Привязку админом в карточке сотрудника это не заменяет и не ломает: хранение общее (`users.tg_user_id`, его читает `StaffNotifier`).

`/help` — по статусу: `texts.help` (prospect), `texts.help_with_manager`, `texts.help_client`; каждый перечисляет ровно команды своего меню (кроме `/start` и `/help`; тест `test_help_lists_exactly_the_menu`). Когда менеджер делает лида клиентом (`make_customer`), бот один раз пишет `texts.client_access_granted` (доступны `/docs`, `/request`). `client_only` подсказывает: договор уже есть — `/human`, менеджер подключит доступ.

**Язык (Q-022; `domain/language.py`).** Первое сообщение новому собеседнику — `texts.language_first` сразу на трёх языках с кнопками «Oʻzbekcha / Русский / English»; приветствие и согласие — после выбора, на выбранном языке (вопрос, заданный до согласия, получает ответ сразу после согласия). Явная просьба («по-русски», «oʻzbekcha», «in English», ≤ 5 слов) — `requested_language` → `set_language` + `texts.language_set` без модели. Язык зафиксирован, а два сообщения подряд на другом — один раз кнопки языка (`leads.qualification.language_mismatch_streak`/`language_offered_at`). Узбекская кириллица без ўқғҳ определяется по словарю частых слов (нима, керак, канча, рахмат…).

**Без модели (код решает, SPEC §1.3).** Просьба о человеке — `escalation.human_request_terms` (основы `менеджер*`, `operator*`, `menejer*`, фразы «живой человек», «real person»; «человек»/«odam»/«person» — только формами и фразами, чтобы «нас 5 человек» и «personal data» не передавали менеджеру). «Дайте телефон/адрес/сайт» (`contact_request`, ≤ 8 слов, не про номер договора/запроса, просьба о менеджере важнее) — ответ из `company.phone/site/address` (`texts.contacts`, `texts.contact_labels`); пусто — `texts.contacts_missing` с кнопками менеджера. Ответ на «Не нужно» — `texts.handoff_offer_declined`. Передача менеджеру: в рабочее время `texts.handoff` с `{sla}` (`texts.sla_promise`, `{minutes}` = `escalation.sla_minutes`), вне — `texts.off_hours` с `{next}` — ближайшее рабочее время с учётом праздников («завтра с 9:00», «в понедельник с 9:00»). Текст вместо кнопки «Поделиться номером» — обычный ответ и `ReplyKeyboardRemove`. Просьба лида о менеджере без номера — сначала `texts.phone_before_manager` и клавиатура номера, передача сразу после своего контакта; «Не сейчас» — `texts.phone_declined_manager` (§8.2, п. 0; все ответы пишутся в переписку). Файл/голос во время `/request` — `texts.request_text_only` (ожидание описания не сбрасывается). Закрытый запрос называет номер (`service_request_closed`, `{number}`).

`/docs` — до 10 видимых клиенту документов кнопками (новые первыми), `client_id` только из подтверждённой идентичности, выдача файла и журнал доступа — как у docs-mcp. `/request` — описание следующим сообщением → `service_requests` + info-эскалация `service_request`. `/status` — открытый запрос словами. Prospect на командах клиента получает `texts.client_only`. Номер телефона: один раз (флаг `leads.qualification.phone_asked_at`), когда лид квалифицирован/передан или ждёт менеджера, при `bot.ask_phone`; сохраняется только собственный контакт (`contact.user_id == from_user.id`) в `telegram_identities.phone_e164` (E.164), показывается в карточке лида, стирается по `/delete`.

Middleware: идемпотентность, rate-limit (20 сообщений/мин на пользователя, при превышении — вежливое сообщение не чаще раза в минуту; сообщение лида всё равно сохраняется в переписку с `meta.rate_limited`, бот на него не отвечает), маскирование PII в логах, проверка согласия. Вложения лида (фото/документы) сохраняются в S3 (RustFS) и показываются в CRM; бот в v2 на вложения отвечает «передам коллеге» + триггер `info`. До согласия файл в S3 не загружается: в переписке остаётся пометка `{stored: false, note: «файл получен до согласия»}`. Файл больше 20 МБ (лимит Bot API) не скачивается: бот отвечает `texts.attachment_too_large` («Файл больше 20 МБ — пришлите ссылку или сожмите»), без «передам» и без триггера; сообщение с пометкой `too_large` видно в CRM. Ответы обработчиков без модели (контакты компании Q-023, подтверждение смены языка, «пришлите текстом», «Не нужно» под предложением менеджера) записываются в переписку с ролью `bot` вместе с сообщением лида — менеджер видит в CRM всё, что видел клиент.

---

## 10. CRM (frontend)

### 10.1. Навигация

| Раздел | Роли | Содержание |
|---|---|---|
| **Входящие** | manager, admin; `GET /inbox` читает и viewer (D1-1: директор Платформы видит «Ждут ответа» без действий; запись `handoff_note` — записка передачи, CRM-06) | Кнопка «Новый лид» (право `leads:create`, M3-CRM-05, §6.5): звонок / письмо / рекомендация, форма с валидацией, 409 — ссылка на найденного лида/клиента; после создания — карточка. Открытые эскалации (hot первыми), мои лиды, лиды без владельца (сюда же попадают лиды с сайта), запросы клиентов (открытые сервисные запросы, кто ждёт дольше — первым: `GET /api/v1/service-requests?status=open`, право `clients:read`; в карточке лида-клиента — ссылка по `open_service_request_id`, Q-017); счётчики в сайдбаре; live через SSE `/api/v1/stream` |
| **Лиды** | manager, admin, viewer(ro) | Таблица с фильтрами (стадия, владелец, score, период, язык), сохранённые фильтры |
| **Карточка лида** | manager, admin, viewer(ro) | Слева: шапка (стадия, score, владелец, телефон, язык, источник — `leadSourceLabel`, §6.5), резюме (компания и почта лида без Telegram), резюме, квалификация, причина эскалации, заметки. Центр: `ChatThread` — переписка с ролями, поле ответа (только `owner_mode=human` и владелец/админ), кнопки: Принято к сведению (информационная передача у бота: `actions/acknowledge`, закрывает эскалацию без смены стадии и владельца) · Забрать · Вернуть боту (повторная сделка клиента возвращается в «Клиент») (с заметкой, лид получает `texts.returned_to_bot`) · Отложить · Вернуть из отложенных (`actions/unsnooze`: права как у «Отложить», передача снова `open`, срок реакции заново `reset_sla`, пост в канале и новая проверка SLA, аудит `lead.unsnooze`, SSE) · Сделка заключена · Закрыть отказом · Сделать клиентом · Передать коллеге (`actions/assign`) · Новая сделка (для клиента, `actions/new_deal`) — ADR-0015. Владелец показывается по имени (`assigned_user_name`; справочник команды `GET /team` — всем ролям). Справа: «Почему система так решила» — последние `qualifier_runs` и `stage_transitions` в человекочитаемом виде |
| **Клиенты** | manager, admin, viewer(ro) | Карточка клиента: контакты, привязанные Telegram-идентичности (с подтверждением), документы, связанные лиды/диалоги, сервисные запросы |
| **Сделки** | manager, admin, viewer(ro) | `/deals`: таблица (название, клиент, сумма с валютой, стадия, ожидаемое закрытие, ответственный, причина отказа), фильтры стадия/ответственный (`?stage=won`), создание и правка в модальном окне; на карточке клиента — блок «Сделки» с «Новая сделка». Открытую сделку создаёт код при входе лида в «Квалифицирован» и при «Новая сделка» (одна открытая на лида, название «Клиент — продукт»); закрытие лида «Сделка заключена»/«Отказ» закрывает её в той же транзакции, отказ без открытой сделки создаёт проигранную с причиной; выигранную сделку правит только админ (Q-021, ADR-0019). API: `GET/POST /api/v1/deals`, `GET/PATCH /api/v1/deals/{id}`, `GET /api/v1/deals/summary?days=`, `GET /api/v1/deals/options`; права `deals:read` (все роли), `deals:write` (manager, admin) |
| **Документы** | manager, admin | Загрузка документов клиенту (тип, номер, дата), видимость клиенту, журнал доступа |
| **База знаний** | admin, manager(ro) | Документы KB (менеджер — только просмотр и тестовый поиск, право `kb:read`; правка — `kb:write`, admin), ингест, активность, просмотр чанков, тестовый поиск («что найдёт бот на этот вопрос») |
| **Пробелы KB** | admin | Вопросы без ответа: частота, язык, примеры диалогов, действия: «Создать документ», «Привязать к документу», «Игнорировать» |
| **Проверить бота** | admin | `/sandbox` (меню «Бот»): админ пишет боту как клиент без Telegram — ход идёт через тот же `ConversationService.handle_message` (агент, MCP, триггеры, эскалация), выбор языка ru/uz/en, «Начать заново», под ответом свёрнутое «Почему так» (решение, причина, совпадение и документы KB, сработавшие правила передачи). Лид песочницы — `leads.source='sandbox'`, согласие дано автоматически, служебная идентичность `tg_user_id = −user_id`; без хуков: квалификатор, канал и уведомления не задействуются, передача показывается в ответе и сразу снимается. Такие лиды исключены из «Лидов», «Входящих», воронки и `mv_daily_stats`/`mv_escalation_reasons` (миграция `0018_sandbox_dashboard`), таймера «нет ответа» и ежедневного отчёта. Вызовы моделей — в «Расходах» как `kind='test'` (`kind_scope`). API: `POST /api/v1/sandbox/messages`, `POST /api/v1/sandbox/reset`; право `sandbox:use` (admin); аудит `sandbox.message`/`sandbox.reset` без текстов |
| **Настройки** | admin | Формы по ключам `settings` с валидацией; предпросмотр текстов на 3 языках; редактор правил эскалации |
| **Пользователи** | admin | Список, роли, создание с временным паролем (обязательная смена при первом входе, `users.must_change_password`), сброс пароля админом, деактивация и снятие роли менеджера (с передачей лидов в работе и клиентов коллеге — иначе 409 `user_has_active_leads`, ADR-0015; диалог тогда показывает выбор «Передать лидов и сделки коллеге» и отправляет изменение ещё раз с `transfer_to_user_id`), привязка Telegram; защита «последний админ». Столбец **«Доступ к ERP»** (FIX-11, M3-CRM-06): переключатель `PATCH /api/v1/users/{id}` с `platform_access` — выдача ставит задачу Procrastinate `erp_provision_user` (`POST /api/integration/v1/users/provision`, идемпотентно по `crm_user_id`, повторы), снятие (после подтверждения) — `erp_revoke_sessions` (`DELETE …/users/{crm_user_id}/sessions`); так же при деактивации и смене ролей, имени или ролей ERP у пользователя с доступом. **Роли ERP (FIX-63, Q-FIX50-1 (1))**: включение переключателя открывает окно «Выдать доступ к ERP» с мультивыбором системных ролей бэк-офиса (названия ru/uz/en в `frontend/src/domain/erpRoles.ts`, права ведёт ERP), доступ и роли уходят одним `PATCH` (`platform_access` + `erp_role_codes`); в карточке пользователя с доступом роли меняются там же — изменение набора ставит повторный провижининг с `role_codes` (поле `[]` — снять выданные из CRM). У `admin` CRM роли ERP не нужны (суперпользователь). ERP снимает только роли, выданные из CRM; ручные не трогает. Аудит `platform_access.granted` / `platform_access.revoked`. Ошибки ERP в ответ админу не попадают: строка «Синхронизация с ERP» в «Внешних сервисах» (§13.2). Кнопка «В бэк-офис (ERP)» в шапке — только при `erp` в `platform_access` (`/me.platform_access`) и включённом SSO; `POST /api/v1/auth/sso/token` без доступа — 403 `platform_access_denied`. Права в ERP — по карте «роль CRM → каталог прав ERP» (`domain/erp_permissions.py`, `docs/architecture/sso-token.md`) Письма через коннектор «Почта» (M3-CRM-08, ADR-0023): «Отправить приглашение по почте» (в меню строки и в окне временного пароля после создания) и «Сбросить пароль и отправить по почте» — `POST /api/v1/users/{id}/invite`, `POST /api/v1/users/{id}/reset-password/email`: сначала проверка коннектора, затем новый временный пароль, отзыв сессий, письмо в журнал и очередь; аудит `user.invite` / `user.reset_password_email`. Без коннектора — 409 `smtp_not_configured` («Настройте коннектор «Почта»»), пароль не меняется, ручной временный пароль (Q-010) остаётся рабочим путём. Ссылка «Вход» в письме — `<адрес Платформы>/login` (`PLATFORM_PUBLIC_URL`, иначе из `PLATFORM_DOMAIN`); адреса нет — 409 без смены пароля (W15-H8a) |
| **Дашборд** | все | Графики `@ant-design/plots` (UX волна 4; модуль грузится лениво). Сверху вниз: KPI с трендом к прошлому периоду той же длины (`previous`, до 90 дней) — новые лиды · забрали менеджеры · выиграно (число и сумма по валютам; ведёт в `/deals?stage=won`) · среднее время до «Забрать» · стоимость моделей (только `spend:read`); операционные плитки (открытые передачи, передачи, пробелы KB — только `kb:write`); «Поток лидов» `Line` по дням (новые, передачи, забрали, выиграно — `daily`); «Воронка» `Funnel` (все стадии, включая нулевые, и итог); «Почему передаём» `Bar` (`escalation_reasons`); «Сделки» `Column` выиграно/проиграно по дням (`/deals/summary.daily`) + кольцевой `Pie` отказов по причинам (только `deals:read`); «Работа бота» `Gauge` доли без ответа (`fallback_share`) + `Column` ответы бота/передачи по дням; «Менеджеры за период» — забрал, медиана до «Забрать», выиграл сделок, ведёт сейчас (`managers`) и доля передач, забранных до `sla_due_at` (`sla`: в знаменателе — забранные и просроченные); таблица по дням — свёрнута. Лиды песочницы (`source='sandbox'`) не считаются. Каждый график — `role="img"` с `aria-label` из ключевых чисел и пустое состояние при нулях |
| **Аудит** | admin | `audit_log` с фильтрами |
| **Расходы** | admin | `/spend`, период 7/30/90 дней; вкладки «Ансамбль: CRM и ERP» — журнал шлюза LiteLLM по системам, функциям и моделям с бюджетом на день по системе и деградациями (M3-CRM-09, §13.1, `GET /api/v1/admin/ai-spend`) и «CRM подробно» — учёт `llm_usage`: лимиты провайдеров, работа/тесты, назначения, дорогие лиды (`GET /api/v1/spend`); право `spend:read` |
| **Шаблоны ответов** | admin (правка), manager (выбор) | `/templates`: название и текст на ru/uz/en с подстановками `{name}` (имя лида), `{manager}` (имя менеджера). В карточке лида у поля ответа — «Шаблоны» (выбор с поиском): текст на языке лида (пусто → русский) вставляется в поле, отправляет менеджер. API: `GET/POST /api/v1/reply-templates`, `PUT/DELETE /api/v1/reply-templates/{id}`; права `reply_templates:read` (manager, admin), `reply_templates:write` (admin); аудит `reply_template.*` |
| **Подключения** | admin | Токен бота, канал команды (ADR-0018), профиль бота (имя, описание, краткое описание × ru/uz/en, статус «Опубликовано в Telegram» или причина словами): `GET/PUT /api/v1/integrations/telegram/profile` Вкладка **ERP** (M3-CRM-02, ADR-0018, ADR-0022): адрес ERP (`settings.integrations.erp_base_url`, иначе `ERP_BASE_URL`), сервисный токен CRM→ERP и секрет вебхуков ERP→CRM (ключи `erp_service_token`, `erp_webhook_secret` в `integration_secrets`, иначе `.env`) — только на запись, в ответах «задан» + `last4`; сохранение после пароля админа, аудит `integrations.erp` без значений; «Проверить связь» — `GET {erp_base_url}/api/integration/v1/health` с `Authorization: Bearer`, таймаут 5 с, ответ по схеме `Health` контракта или ошибка ADR-0017 (`erp_not_configured` 409, `erp_invalid_url` 422, `erp_unauthorized`/`erp_unavailable`/`erp_bad_response` 502). API: `GET/PUT /api/v1/integrations/erp`, `POST /api/v1/integrations/erp/check`; права `integrations:read/write` (admin). Коннектор «настроен» = адрес + токен → режим жизненного цикла `erp` (`Container.backoffice_mode`); на «Состоянии системы» строка «ERP (бэк-офис)» по той же пробе с кэшем 30 с: не настроен — «нет данных» без ошибки, сбой связи/токена — `fail`, деградация/миграции/очередь — `warn`. Вкладка **Почта** (M3-CRM-08, ADR-0023, ARCHITECTURE §18; с W18A-P1 — один отправитель ансамбля, CONTRACTS §9.9): SMTP-релей для всей исходящей почты — письма сотрудникам (приглашение, сброс пароля), клиентам (D1-9) и письма, которые ERP и EDS просят отправить по шине (КП, документы, вход и приглашение в кабинет, письма EDS) — хост, порт, шифрование, отправитель (`settings.integrations.smtp`, иначе `SMTP_*`), логин и пароль (`smtp_username`, `smtp_password` в `integration_secrets`, пароль только на запись, `last4`); сохранение после пароля админа, аудит `integrations.smtp` без значений; «Проверить связь» — соединение + EHLO + STARTTLS/SMTPS + AUTH без отправки, 10 с (ошибки `smtp_not_configured` 409, `smtp_invalid_host` 422, `smtp_unavailable`/`smtp_tls_failed`/`smtp_auth_failed`/`smtp_rejected` 502); «Отправить тестовое письмо себе» — через журнал и очередь. Ниже — журнал писем (последние 50, фильтр по статусу, тел писем нет). API: `GET/PUT /api/v1/integrations/smtp`, `POST …/smtp/check`, `POST …/smtp/test-send`, `GET …/smtp/log?status=&limit=`; права `integrations:read/write` (admin). Шаблоны — `backend/templates/email/<invite|password_reset|test>.<ru|uz|en>.md` (`Subject:` первой строкой, подстановка `string.Template`; язык сотрудника — пока всегда ru, Q-012; нет словаря — ru) |
| **Внешние сервисы** | admin | `/external-services` (меню «Администрирование», §13.2, ADR-0024): сводка (сбой / внимание / в норме / нет данных / не подключено / выключено вручную), баннер «выключено вручную» с причиной и «Включить», карточки по группам «Требуют внимания» → «Выключены вручную» → «Работают» → «Не подключены или нет данных» → «Сервисы ERP»: статус, что сейчас, «Что сделать» с кнопкой «Исправить» (путь к коннектору), главные метрики, доступность за 24 ч, «Проверить сейчас», выключатель с паролем. `/external-services/:key`: состояние, показатели, 7 дней, проверки за 24 ч, инциденты за 30 дней. На телефоне — списки вместо таблиц |
| **Экспорт CSV** | admin | Кнопка «Экспорт CSV» на «Лидах», «Клиентах», «Сделках» с текущими фильтрами: `GET /api/v1/export/{leads,clients,deals}.csv`, право `export:read` и чтение выгружаемого (`leads|clients|deals:read`, R3-D-2), аудит `export.<entity>` с числом строк, до 10 000 строк. Формат под Excel ru-локали: UTF-8 с BOM, разделитель `;`, дробные с запятой, даты `ДД.ММ.ГГГГ ЧЧ:ММ` по Ташкенту, ячейки с `= + - @` в начале экранируются апострофом (CSV-инъекция); колонки — те же данные, что в списках |

### 10.2. Переключатель режима

В шапке у пользователей с ролью `admin` — переключатель **Админ / Менеджер** (`users.ui_mode`, сохраняется). В режиме «Менеджер» скрыты: База знаний, Пробелы KB, Настройки, Пользователи, Аудит. Переключатель не меняет права на бэке — только навигацию.

### 10.3. Технические требования к фронту

Refine — оболочка: `authProvider` (cookie JWT), `accessControlProvider` (матрица прав приходит с бэка `GET /api/v1/me/permissions`, фронт только скрывает/блокирует; истина — на бэке), раскладка, уведомления, предупреждение о несохранённых изменениях. Данные — хуки TanStack Query, которые orval генерирует из OpenAPI (ADR-0021); SSE обновляет экраны сбросом их ключей кэша; ручные типы и хуки-дубли запрещены. Ошибки API — единое тело `ErrorOut {code, message, details}` для доменных ошибок, валидации запроса и 404: `code` — класс ошибки, `details.reason` — стабильный подкод случая (`Reason`, ADR-0017), `details.field` — поле формы; текст пользователю фронт берёт из i18n по `details.reason ?? code`, `message` — только для логов. Адаптивная вёрстка до 390 px (менеджер с телефона может читать и отвечать).

---

## 11. Безопасность

| Область | Требование |
|---|---|
| Секреты | Инфраструктурные — только в `.env` на стенде и GitHub Secrets; секреты интеграций, которые админ вводит в CRM (токен бота, сервисный токен и секрет вебхуков ERP), — в `integration_secrets` зашифрованными ключом `SECRETS_KEY` из `.env` (ADR-0018), поле только на запись, смена — с повторным паролем и аудитом без значения; в репозитории — `.env.example`. Ключи провайдеров моделей знает только `litellm`. pre-commit с `gitleaks` |
| Аутентификация | argon2id; JWT access 15 мин в памяти, refresh в httpOnly/SameSite=Strict cookie с ротацией; logout отзывает refresh; блокировка после 10 неудачных входов на 15 мин |
| Авторизация | Casbin на каждом REST-эндпоинте через зависимость `require(action, resource)`; объектные проверки (владелец лида) — в сервисах. MCP-инструменты — только внутренняя сеть + HMAC-контекст. Переписка отдельно от реестра лидов (B-D18-1): очередь, список, карточка и решения лида — `leads:*`; сообщения, вложения и заметки лида, ответ и заметка — `leads:<действие>` или `chats:<действие>` с объектной проверкой диалога (`app/api/dialog_access.py`, правило — `domain/chat_access.py`: участник — ответственный за лида, клиента или сделку, автор ответа; зона `chats:invoiced` — сделка клиента со счётом); чужой диалог держателю `chats:*` — 404; список открытых диалогов — `GET /chats` |
| Данные клиентов | Все запросы к `documents`/`clients` из бота — с обязательным `client_id` из верифицированной идентичности; интеграционные тесты на cross-tenant доступ |
| Telegram | Webhook `secret_token`; allow-list `update` типов; `tg_updates` идемпотентность; rate-limit |
| Сброс пароля по ссылке (W15-H6) | `POST /auth/forgot-password` без аутентификации: ответ 202 одинаков для существующей, отключённой и несуществующей учётной записи (не перечисляем сотрудников), в журнал — причина без адреса; ссылка на Платформу (`PLATFORM_PUBLIC_URL`) уходит на почту (коннектор «Почта») или в Telegram, нет канала — ничего; токен 256 бит, в БД хеш, живёт 60 минут, одноразовый, лимит — 3 ссылки в час на учётную запись (CRM) и 5 запросов в час на IP и адрес (BFF); `POST /auth/reset-password` проверяет политику пароля до погашения токена, после успеха гасит все токены учётной записи и её refresh-токены |
| Публичная форма «Запрос» | `POST /api/v1/leads/web` без аутентификации (M3-CRM-05, §6.5): обязательное согласие на обработку ПДн (`consent: true`, Q-12), honeypot, подписанный токен формы (минимальное время заполнения, срок жизни), окно запросов по IP (429), лимиты длины полей, CORS только для origin Cabinet (`CABINET_ORIGIN`) и только на `/leads/web*`; в ответе — только `lead_id`; аудит с IP |
| PII | Маскирование телефонов/email/ИНН в логах и Langfuse (`security/pii.py` как processor structlog и Langfuse mask-функция) |
| Инъекции в промпт | Пользовательский текст и фрагменты KB — в отдельных XML-блоках; системные правила запрещают раскрытие инструкций; eval-кейсы на injection; инструменты не принимают идентификаторов от модели |
| Аудит | Все мутации через REST и кнопку в канале — `audit_log` (before/after) |
| Транспорт | TLS на Caddy (ACME), HSTS; Langfuse и консоль RustFS на prod — только с IP allow-list |
| Зависимости | `uv lock`, `pnpm lock`, Dependabot, `pip-audit`/`npm audit` в CI |
| Бэкапы | Ежедневно, проверка восстановления раз в месяц по runbook |
| Бюджет моделей | Бюджет ERP на день `settings.budget.erp_daily_usd` — только показ (§13.1). Три уровня (ADR-0014): `settings.budget.daily_usd` — при превышении диалог → `fallback-model`, квалификатор продолжает; LiteLLM `provider_budget_config` — жёсткий суточный потолок по провайдеру; лимиты в консолях провайдеров |

---

## 12. Качество ИИ (evals)

- `evals/golden/*.yaml` — ≥ 40 кейсов на старте по категориям: ответ есть в KB (ru/uz/en), нет в KB, просьба о человеке, негатив, конкурент, smalltalk, injection, нет прогресса, возврат из unresponsive, customer: документ найден / не найден / чужой документ.
- Метрики и пороги релиза: faithfulness (judge) ≥ 0.95; выдуманные числа = 0; escalation precision ≥ 0.85, recall ≥ 0.95; stage accuracy ≥ 0.85; language match = 1.0; injection resistance = 1.0; cross-tenant leaks = 0; latency p95 ≤ 6 с.
- Запуск: `make eval` (pytest `-m eval`, результаты в Langfuse dataset run с тегом git sha); `make promptfoo` для матрицы промпт × модель.
- Процесс: любое изменение промптов, моделей, триггеров, порогов — PR с отчётом eval; еженедельная разметка 20 реальных диалогов → пополнение golden.

---

## 13. Наблюдаемость и эксплуатация

- Трейсы: каждый ход диалога и каждый запуск квалификатора — Langfuse trace с `lead_id`, `mode`, `stage`; стоимость агрегируется.
- Логи: structlog JSON, `request_id`, `lead_id`; уровни по env.
- Метрики здоровья: `GET /health` (liveness), `GET /ready` (БД, S3/RustFS, LiteLLM); ежедневный отчёт в канал (General-пост): новых лидов, передач, просрочек срока реакции, медиана до «Забрать», кто сколько забрал, открытых пробелов KB и топ-3 вопросов, ссылка на дашборд; стоимость моделей — только админам в личку.
- Алерты (личным сообщением от бота активным админам с `notify_system` и привязанным Telegram; если никому не доставлено — в канал; префикс ⚠️): задача в `failed` после 3 ретраев; очередь > 100 задач (недоступность шлюза моделей и сбои ответов ИИ монитор не шлёт: это строки «Шлюз моделей» и провайдеров центра внешних сервисов, §13.2, по той же политике оповещений; прежние `litellm_down` и `ai_failures` закрываются молча); бюджет > 80 %; у провайдера модели закончились кредиты/квота или отклонён ключ — проба раз в час запросом в 1 токен к `dialog-model` (Anthropic) и `fallback-model` (Gemini) с `disable_fallbacks` (иначе сбой Claude скрыт ответом Gemini), ключ алерта `model:<alias>`, снятие — только по успешной пробе. Каждая проба — строка `llm_usage` (`purpose='probe'`, `kind='work'`: системная работа прода, как кнопка «Проверить» в «Моделях ИИ»; `test` — только evals/нагрузка/песочница) и проходит BudgetGuard: провайдер сверх дневного лимита не проверяется (состояние алерта не меняется). Монитор — периодическая задача `system_monitor` (раз в минуту, `domain/alerts.py`); дедупликация в таблице `system_alerts(key PK, active, detail, first_seen_at, sent_at, resolved_at, updated_at)`: пост на переходе в проблему, повтор не чаще 6 ч, снятие постом «✅ … в норме». Состояние решается и сохраняется в транзакции, отправка (таймаут Bot API 10 с, ошибки Telegram ловятся) — после коммита; недоставленный алерт остаётся без `sent_at` и уходит следующим проходом. Алерт задачи снимается только успешным запуском этой задачи после сбоя (не опустевшим окном); у алерта задачи — человеческое название и «Что делать» (`channel_texts.TASKS`). Строка `model:<alias>` пишется и для исправной модели (`updated_at` = время пробы). Итоги дня — `daily_report` в 18:05 Asia/Tashkent (пн–пт).
- Экран «Состояние системы» (`/system`, admin; `GET /api/v1/system/status`): БД, S3, LiteLLM (проверки `/ready`), модели — по последней пробе монитора (`system_alerts` `model:*`, без вызовов моделей), бюджет, очередь (ожидание, зависшие > 15 мин, упавшие за час), канал, бот, бэкап (`unknown`: том бэкапов не подключён; `warn` «Резервное копирование не запущено на этом сервере» — файла `heartbeat` нет вовсе, демон не развёрнут, напр. dev; `fail` — heartbeat был и устарел > 2 мин или успешных копий нет), наличие обязательных секретов (только имена), «Адреса для ссылок» (`crm_url`: адрес CRM из «Настроек» и адрес Платформы из окружения; `warn` — адрес пуст, `localhost` или без https; адрес Платформы не задан вовсе или на проде указывает на localhost — «Это настраивает хостинг: PLATFORM_DOMAIN», без ссылки на «Настройки» в тексте, W15-H8a). Статусы `ok|warn|fail|unknown` с причиной и временем проверки. Источники собираются вместе, каждый с пределом 2 с (`SOURCE_TIMEOUT_S`): медленный или упавший источник (ERP, журнал расходов, сводка внешних сервисов, данные из БД, бакет копий) даёт строку «Не проверено: … не ответил в срок», а не задержку всей карточки (W15b-1). Текст «N задач выполняются / упали» согласуется по числу (`domain/plural.py`).
- Личные уведомления (Q-010): сообщение лида в режиме `human` → задача `notify_lead_message` → личка ответственному менеджеру (`notify_leads`, без кнопок, ссылка на карточку лида в Платформе, см. «Ссылки в уведомлениях»), не чаще `notifications.manager_dm_throttle_minutes`. В CRM — звук и уведомление браузера по SSE `message.created` (`assigned_user_id` = текущий пользователь), включается в профиле.
- BudgetGuard: расход за сутки (Asia/Tashkent) = сумма `llm_usage.cost_usd` (работа и тесты; кэш 60 с). Мягкий бюджет: при ≥ 100 % `budget.daily_usd` и `fallback_model_enabled` диалог идёт на `fallback-model`, квалификатор продолжает; `daily_usd = 0` — без лимита. Лимит провайдера `budget.providers` (проверка до вызова): провайдер за лимитом → диалог на `fallback-model`, если провайдер резерва в лимите, иначе `LlmUnavailableError` (бот честно передаёт человеку); квалификатор — отказ. Провайдер алиаса — из LiteLLM `GET /model/info` (`model_info.litellm_provider` или префикс `litellm_params.model`), кэш 5 мин; неизвестен → лимит провайдера не применяется. Потолок `provider_budget_config` LiteLLM — аварийный, выше настроек.
- Строка «Бюджет ИИ сегодня» на «Состоянии системы» (`ai_budget`): «CRM x/y USD, ERP x/y USD» из журнала LiteLLM (§13.1, кэш 60 с, таймаут 5 с); превышение любой системы — `warn`, журнал недоступен — `unknown`; ссылка — на «Расходы».
- Runbooks: деплой, откат, бэкап/восстановление, ротация ключей, «бот молчит», «эскалации не приходят», «стоимость выросла», «откат промпта», eval-gate, «переезд dev → prod».

---

### 13.1. Расходы на ИИ по ансамблю (M3-CRM-09)

«Биллинг» владельца — один дашборд затрат на ИИ для CRM и ERP (ARCHITECTURE §8). Источник истины — журнал расходов шлюза LiteLLM (`LiteLLM_SpendLogs`, строка на вызов), а не `llm_usage` CRM: цифры совпадают с журналом прокси до вызова.

- **Теги вызова.** Каждый вызов модели из CRM (чат `ChatModel`, эмбеддинги `Embedder`, пробы `models_status.ping`) несёт в теле запроса `metadata.tags = ["system=crm", "feature=<функция>", "model=<алиас>"]` (`integrations/llm_usage.gateway_body`). Функции — по местам вызова (`FEATURE_BY_PURPOSE`): `dialog`, `qualifier`, `judge`, `kb-search` (эмбеддинг запроса), `kb-ingest` (индексация), `probe` (монитор и «Проверить»), `assist-draft`, `assist-improve`, `test`. ERP пишет `system=erp` и свои функции (M1-ERP-06). Unit-сторож `test_gateway_tags.py` падает на вызове модели без `extra_body`.
- **Чтение.** `AiSpendService` → `GET {LITELLM_BASE_URL}/spend/logs/v2` с мастер-ключом (`LITELLM_API_KEY`): окно по UTC, страницы по 1000, сортировка по `startTime`; при `total_is_capped` (потолок 10 000 строк) окно делится пополам до минуты, иначе отчёт помечается `truncated`. Поля: `request_id`, `startTime`, `spend`, `prompt_tokens`, `completion_tokens`, `model_group`, `request_tags`, `status`. Свёртка в коде (`domain/ai_spend.py`): сутки по `business_hours.timezone`, повторы по `request_id` один раз, «день × система × функция × модель» — вызовы (включая неуспешные), ошибки, токены, USD. `/spend/tags` и `/global/spend/tags` не годятся: один тег за раз и `spend` округлён. Модель — `model_group` (фактический алиас), без него — тег `model`. Вызов без тегов — система и функция `other` («Без тега»). Период ≤ 90 дней, не в будущем; кэш 60 с на период.
- **Деградация** — успешный вызов, обслуженный `fallback-model` (BudgetGuard CRM или `router_settings.fallbacks` прокси); пробы (`feature=probe`) не считаются.
- **Бюджет на день по системе:** CRM — `settings.budget.daily_usd`, ERP — `settings.budget.erp_daily_usd` (CRM расход ERP не ограничивает — показывает); превышение — расход ≥ бюджета (0 — без лимита). Ответ отдаёт превышение сегодня и дни превышения за период.
- **API:** `GET /api/v1/admin/ai-spend?from=&to=&group=day|system|feature|model` (admin, `spend:read`): `rows` по `group` (по дням — каждый день периода, с разбивкой по системам), `totals`, `systems` (бюджет, сегодня, период, деградации, `connected`), `overruns`, `erp_connected`, `truncated`; ошибки ADR-0017 — `422 ai_spend_period`, `502 litellm_unavailable`.
- **Экран:** «Расходы» → «Ансамбль: CRM и ERP»: плитки «Всего за период» и по системам (сегодня x из y, превышение — красный тег, `role="status"`), дни превышения, таблица по дням (CRM, ERP, всего, вызовы, токены, деградации), разрезы по системе/функции/модели; ERP без строк в журнале — «ERP ещё не подключена к шлюзу»; шлюз недоступен — понятная причина и «Повторить».

### 13.2. Центр внешних сервисов (M3-CRM-12, ADR-0024)

Требование владельца (ORCHESTRATOR §3.13): админ видит и контролирует все внешние сервисы ансамбля — всё, что интегрировано помимо CRM и ERP. Новый внешний сервис принимается в код только со строкой в реестре.

- **Реестр** (`domain/external_registry.py`): ключ, название и назначение по-русски, кто пользуется (`crm`/`erp`/`ensemble`), кто проверяет (`crm` — CRM сама, `erp` — передаст ERP), способ и частота проверки, путь в CRM, где это исправляется, вид выключателя. Сервисы CRM: `telegram`, `litellm`, `vendor.<провайдер>` (по одному на провайдера из алиасов LiteLLM `/model/info`, при недоступности шлюза — из `litellm.models.yaml`), `langfuse`, `mail`, `s3`, `docling`, `backup`, `erp_sync` (синхронизация сотрудников с ERP: итог задач провижининга и отзыва сессий из `users.erp_sync_error`, FIX-11), `tls.crm|erp|cabinet`. Сервисы ERP — `erp.cbu_rates`, `erp.customs_tariff`, `erp.mail`, `erp.litellm`, `erp.s3`, `erp.sentry` (M3-ERP-06): состояние из `externals[]` ответа ERP на `GET /health` (`domain/external_erp_reported.py`; `degraded` → `warn`, `fail` → `fail` с инцидентом и оповещением, `disabled` → `off`; ERP не отвечает — `unknown` без инцидентов); выключатель (кроме Sentry) — `PUT /externals/{code}/switch` в ERP (`integrations/erp_externals.py`).
- **Проверки без платных вызовов** (`services/external_services/collector.py`, `integrations/external_probes.py`): Telegram — `getMe` + `getWebhookInfo` (токен не принят → `fail`; вебхук не установлен или чужой → `fail`; ошибка доставки за 15 мин или > 100 ждущих обновлений → `warn`); LiteLLM — `/health/liveliness` + `/health/readiness` (`/health` не используется — он вызывает модели); вендор — журнал `/spend/logs/v2` за 15 мин (≥ 3 вызовов и ≥ 50 % ошибок или отказ ключа последним вызовом → `fail`, ≥ 20 % или последний вызов с ошибкой → `warn`) и `/provider/budgets` (≥ 100 % потолка → `fail`, ≥ 80 % → `warn`), за 24 ч — вызовы, ошибки, p95, USD, ушедшие на запасную модель; Langfuse — `/api/public/health` + `/api/public/projects` с ключами (без ключей — `off`); почта — `email_log` за 24 ч и раз в 15 мин EHLO/STARTTLS/AUTH без отправки; S3 — `/health`, раз в 15 мин место по бакетам; docling — `/health`; бэкапы — правило §13 (ADR-0013); TLS — рукопожатие с проверкой цепочки, ≤ 7 дней — `fail`, ≤ 21 — `warn`, http/localhost — `off`. Статусы `ok|warn|fail|unknown|off`; у не-`ok` — «что сделать» (`hint`) и путь (`fix_path`). Задачи Procrastinate `external_checks_cheap` (`* * * * *`), `external_checks_recheck` (`* * * * *`, затухание повторов сломанного) и `external_checks_heavy` (`*/15 * * * *`, + чистка); дешёвый проход несёт итог последнего тяжёлого. Последняя проверка старше 5 мин (тяжёлой — 45 мин, сломанного — 20 мин) — `unknown` «фоновые проверки не идут», хостингу передаётся «Запустить crm-worker вместе с ансамблем».
- **Инциденты** (`domain/external_incidents.py`, `services/external_services/checks.py`): непрерывный `fail` не короче 15 мин открывает инцидент сервиса (начало — начало полосы `fail`; короткие провалы — дребезг, инцидента нет), непрерывный `ok` не короче 5 мин закрывает (`ended_at` — начало `ok`); `warn`/`unknown`/`off` не меняют. Это журнал «с … по …» (у восстановившегося сервиса в «Подключениях» — «Восстановлено в {время}», `last_recovered_at`). Запись проверок и переходы — под advisory-блокировкой. Оповещения идут по **причине** — см. ниже.
- **Причина, кто исправляет, действие** (W15-H3; `domain/external_cause.py`, чистые функции — код решает, интерфейс показывает). Каждое правило статуса несёт машинный код причины (`CheckResult.cause`, хранится в метриках проверки как `_cause`). `diagnose` даёт сервису: **состояние словом** — `ok`, `broken` «Сломано» (непрерывный `fail` ≥ 15 мин), `unstable` «Нестабильно» (жёлтое: `fail` короче 15 мин или ≥ 3 провалов за 3 часа при текущем `ok`; без писем и Telegram, «провалов за сутки: N» — `flaps_24h`), `degraded` «Работает с перебоями», `not_configured` «Не настроено», `disabled` «Выключено намеренно» (выключатель админа, необязательный сервис без настройки — Langfuse, docling без `DOCLING_URL`), `expected` «Ожидаемо на стенде», `not_checked` «Не проверено — нажмите «Проверить»» (проверки не было или фоновые проверки стоят); **кто исправляет** — `admin` (Вы, администратор), `owner` (владелец компании: ключ и оплата провайдера), `hosting` (хостинг: сервер, тот, кто разворачивал Платформу), `provider` (сбой на стороне провайдера, ждём); **главное действие и запасные** — `enter_key` «Ввести новый ключ», `enter_token`, `recheck` «Проверить снова», `reconnect` «Переподключить», `open_settings`, `write_owner` «Написать владельцу», `write_hosting` «Передать хостингу», `disable_provider` «Выключить провайдера». Таблица причин → (кто, действие) — `ROUTES` в модуле; ключ провайдера отклонён → владелец, `enter_key`; квота/кредиты → владелец, `write_owner`; сбой на стороне провайдера → провайдер, `recheck`; сервис не запущен на сервере → хостинг, `write_hosting`. **Тексты для хостинга** — вместо «Обратитесь к администратору сервера…» каждое правило пишет «что случилось. Это настраивает тот, кто разворачивал Платформу (хостинг). Отправьте ему: «что сделать»» (`hosting_hint`, `domain/system_status.py`); для владельца и хостинга CRM собирает готовый текст (`message`) — пользователь копирует его или открывает в почте/Telegram, **ничего не отправляется за него**. **«Ожидаемо на стенде»**: настройка окружения CRM `APP_ENV=dev` (`Settings.is_stand`; у прода `prod`, у тестов `test`); на стенде сбой, который чинит хостинг или владелец (ключи, оплата, сервер), и «не настроено» получают состояние `expected` — серые, без оповещений, не в «Требует внимания», не в сводке «Состояния системы»; сбой, который чинит админ (пароль SMTP), остаётся «Сломано». Компоненты «Состояния системы» `secrets`, `crm_url`, `bot`, `channel` на стенде приходят с `expected_on_stand: true`.
- **Группировка по корню** (`build_groups`): одна причина — одна строка. Ключ группы (`cause_key`) — «область:причина» (`vendor.anthropic:key_rejected`; у «ERP не подключена» область общая — `erp:erp_not_connected` для `erp_sync`, `erp_handoff`, `erp.*`). Группа несёт заголовок («Ключ Anthropic отклонён»), список затронутого («диалог с клиентом, запасная модель, поиск по базе знаний» — роли провайдера из алиасов LiteLLM, `ALIAS_FUNCTIONS`), «с {время}» (у «Сломано» — начало полосы `fail` (не позже открытого инцидента), у перебоев и «не настроено» — первая не-`ok` проверка), кто исправляет, действия, `message` и `technical` — сырой текст проверки, **замаскированный** `security/log_mask.mask_secrets`; BFF и интерфейс показывают его только свёрнутым под «Технические подробности» с «Скопировать для поддержки». Тот же `mask_secrets` применяется к `health_detail` ролей моделей и к `detail` пробы модели.
- **Самовосстановление** (`checks.py`, `external_cause.recheck_due`): сломанное (`fail`) перепроверяется с затуханием — после 1-го, 2-го, 3-го, 4-го и далее сбоя подряд через 1, 2, 5, 7 мин, дальше раз в 7 мин (допуск 10 с): проверки сбоя идут на 0, 1, 3, 8 и 15-й минутах полосы, поэтому «непрерывные 15 минут» (`fail_for` = последняя − первая проверка полосы) не набираются четырьмя провалами за 8 минут. Минутный проход пропускает дешёвые сервисы, которым срок ещё не подошёл; сервисы только тяжёлого уровня (`tls.*`) перепроверяет задача `external_checks_recheck` (`* * * * *`): сломанные по затуханию, а после сбоя — раз в минуту, пока «Восстановлено» ждёт 5 минут `ok`. «Проверить» вручную и явный список ключей затухание не учитывают. Проверка прошла — строка и инцидент снимаются сами; пауза между проверками сломанного (до 20 мин) не считается «фоновые проверки не идут». Начало полосы `ok` для «Восстановлено» (`ok_run_start`) не сбрасывается коротким провалом или `warn` между двумя `ok` с промежутком до 3 минут. Устаревшая проверка («фоновые проверки не идут»: воркер или периодика CRM) — одна причина `worker:checks_stale` на все такие сервисы, одна строка «Требует внимания» со списком сервисов (W15b-1).
- **Оповещения** (`external_cause.plan_alerts`, `services/external_services/alerts.py`; политика — ADR-0024, дополнение 2026-10-27): одни правила для всех каналов. «Сломано» (состояние `broken`, не `expected`, не `disabled`) — **одно** сообщение «⚠️ Сломано: {заголовок}» на причину, когда сбой идёт непрерывно ≥ 15 минут (кто исправляет, что не работает, что сделать; сырого ответа в нём нет); «✅ Восстановлено» — одно, когда `ok` идёт непрерывно ≥ 5 минут, и только если «Сломано» отправляли; не больше одного «Сломано» на причину за 24 часа (повтор в те же сутки — `suppressed_at` в записи, письма нет, в «Здоровье» — «Нестабильно»; когда сутки с прошлого «Сломано» прошли, а повторный сбой всё ещё непрерывный, приходит **одно** «Сломано» со сводкой «Нестабилен: N провалов с прошлого сообщения (… назад)», затем одно «Восстановлено»). Начало `ok` для «Восстановлено» — `ok_run_start` (короткий провал между двумя `ok` с промежутком до 3 минут не сбрасывает отсчёт); восстановление идёт по `ok` проверки, а не по «Нестабильно». Дедупликация — запись `external_cause_alerts` (одна открытая на причину, `alerted_at` ставится в транзакции до отправки: параллельный проход и рестарт процесса не дублируют; не дошло ни в Telegram, ни на почту — отметка снимается, следующий проход повторит; «Восстановлено» повторяется до 6 ч после возврата). Сбой короче 15 минут, «нестабильно», «ожидаемо на стенде» и «выключено намеренно» не оповещают; «не проверено» и «перебои» запись не закрывают. Каналы — настройка `service_alerts` (§5.7): личные сообщения админам с подпиской на системные уведомления (владелец — админ), канал команды (`fallback` | `always` | `never`), письмо активным админам и `extra_emails` (шаблон `service_alert`).
- **Проверка и повтор** (`services/external_services/collector.py`): таймаут запроса к внешнему сервису 12 с (проход — 30 с на попытку); транзиентный `fail` (сеть, сервис не ответил, сбой самой пробы) и сбой пробы повторяются один раз внутри проверки, и только второй результат идёт в журнал.
- **Ключ провайдера для всех ролей** (W15-H3): `PUT /api/v1/models/providers/{provider}/key` (`models:write`, пароль админа) — `ModelsAdminService.change_provider_key`: один пароль, один аудит `model.provider_key`, новые deployment всех ролей создаются первыми, прежние удаляются, когда все созданы, сбой посередине откатывает созданное; затем провайдер сразу проверяется (`vendor.<провайдер>`). Модели ролей не меняются. Порядок: новые deployment всех ролей → аудит и маски → удаление прежних (одна повторная попытка с паузой, остальные роли досчитываются; не удалившееся — предупреждение `provider_key_old_deployments_left` в журнале, ответ — успех). Прежние проблемы часовой пробы этих ролей снимаются (новую найдёт проба или трафик).
- **Ответы ИИ клиентам и часовая проба моделей** (W15-H3b): строка реестра `ai_replies` (`domain/external_ai_replies.py`) — ответы бота за 5 минут из `messages` (сбой агента — `meta.error = agent_unavailable`, ответ агента — `meta.action`): последний ответ бота за сутки — сбой, свежее окна, — `fail` (причина `ai_unavailable`); последний ответ успешный — `ok` (в том числе когда обращений ночью нет: «Восстановлено» по общей политике приходит и без трафика); `unknown` (ни сбой, ни восстановление) — только когда за сутки нет ни одного ответа бота или после старого сбоя ответов не было; общая политика оповещений; запросы строки идут по частичному индексу `ix_messages_bot_created_at` (`messages(created_at) WHERE role = 'bot'`, миграция `0043_messages_bot_created_idx`, создаётся `CONCURRENTLY`); прежний алерт монитора `ai_failures` снят. Передача клиента менеджеру из-за сбоя ИИ — рабочая карточка в канал (§9.1). Часовая проба моделей монитора (`model:<alias>`) оповещений не шлёт: её активная проблема (кредиты/квота, отклонённый ключ) — причина провайдера `vendor.<провайдер>` в центре (`key_rejected` / `quota`, одна на провайдера), состояние в `system_alerts` остаётся для «Состояния системы» и чек-листа.
- **Редкие проверки неизлечимых причин:** ключ отклонён, квота, токен бота, пароль/шифрование/адрес SMTP (`SLOW_CAUSES`) перепроверяются раз в 15 минут — неудачными входами не блокируем ящик провайдера почты; сетевые и дешёвые — по затуханию 1, 2, 5, 7. «Сломано» на 15-й минуте полосы верно для дешёвых сервисов; сервисы только тяжёлого уровня (`tls.*`, часть почты) — 15–21 минута, восстановление вендора по журналу шлюза — до ~20 минут.
- **Архив WAL, Redis, шина, права EDS** (W15-H8b; `domain/external_infra.py`, строки реестра `ensemble`, общая политика H3: «Сломано» после 15 минут, одно «Сломано»/«Восстановлено» на причину). `wal_archive` — возраст последнего сегмента (`pg17/wal_005/`, ok ≤ 10 мин, warn ≤ 30, fail > 30) и базовой копии (warn > 26 ч, fail > 50 ч) по списку бакета `wal` (только список: политика `crm` в `infra/s3/init.sh` даёт `ListBucket` без `GetObject` — содержимое сегментов CRM не читает; политика применяется шагом `s3-init` каждого деплоя; список инкрементальный — `StartAfter` последнего ключа, базовые копии перечитываются тяжёлым проходом); аварийный выключатель `rt-archive-off` лежит на VPS 2 внутри контейнера PostgreSQL и CRM его не видит — виден только эффект (сегменты перестали приходить), подсказка говорит об этом честно. `redis_broker`, `redis_cache` — собственный клиент RESP (`integrations/redis_probe.py`: AUTH, PING, `INFO memory/persistence`, таймаут 5 с, пароль в журнал и ответ не попадает; ходит отдельным пользователем Redis `crm-probe` с правами только `PING` и `INFO` (ключей не видит, полных паролей Redis у CRM нет); пароль `REDIS_PROBE_PASSWORD` создаёт деплой, адреса `REDIS_BROKER_URL`, `REDIS_CACHE_URL` собирает compose, пустой — «не проверено»): память ≥ 80 % — warn, брокер ≥ 95 % (политика `noeviction`) — fail, кэш по памяти только warn; `aof_last_write_status=err` — fail, `rdb_last_bgsave_status=err` — warn, RDB кэша старше часа — warn. Причина WAL и Redis — `server_down` (хостинг). `bus_dlq` — «Шина: не доставлено N»: доставки `dead` (подписчик не ERP) и необработанные принятые `failed` (издатель не ERP) за 7 суток; ERP исключён — его недоставленное уже строка `erp_events`; причина `bus_dlq` → админ, действие `open_bus` «Открыть журнал обмена» (`/admin/bus`), запасное — «Проверить снова». `eds_rights` — «Права сотрудников в EDS» (B-005): записанный отпечаток каталога (`identity_catalog_state`) против действующего (`eds_catalog_fingerprint`, в него входят и шаблоны ролей `tpl:*`); расхождение — сбой автопереопубликации прав при старте воркера больше не остаётся строкой лога: проверка сама повторяет публикацию (`ensure_eds_rights_published`, не чаще раза в 5 минут; тяжёлый проход и «Проверить снова» — сразу), успех — `ok`, неудача — `fail`, причина `eds_rights` → хостинг («выполнить `python -m app republish-identity`»), текст ошибки в строку и в журнал не попадает (только класс исключения). Отдельной таблицы флага сбоя нет: расхождение отпечатков и есть состояние «не опубликовано».
- **Внешняя копия бэкапов** (OPS-GDRIVE; `domain/external_offsite.py`, `services/external_services/offsite.py`, строка реестра `offsite_backup`, группа `ensemble`, общая политика H3). Источник — `status.json` в бакете `offsite`, его пишет сервис `offsite-backup` (VPS 1, `infra/offsite/gdrive-sync.sh`) после каждой попытки копирования архива WAL-G на корпоративный Google Drive; ключ CRM видит список бакета и читает только этот объект (политика по объекту; ни архив, ни Drive). `ok` — последняя успешная копия моложе 26 ч; `warn` — ≥ 80 % предела `OFFSITE_MAX_GB` (`offsite_quota`); `fail` — старше 26 ч (сервис стоит, `server_down`) или последняя попытка с ошибкой (причина по `reason`: `access`/`not_shared_drive` → `offsite_access`, `quota` → `offsite_quota` — исправляет владелец; сеть и прочее — `server_down`, хостинг); `off` — нет ключа, ID папки или отметки (`offsite_not_configured`, «не настроено», владелец, текст «Кто исправляет: владелец» с шагами); нет бакета или прав — `unknown`. Runbook — `docs/runbooks/offsite-gdrive.md`.
- **Внешняя копия: настройка в интерфейсе** (OPS-GDRIVE-2; `services/offsite_connector.py`, `domain/gdrive.py`, `integrations/gdrive.py`). `GET /api/v1/integrations/offsite` (`integrations:read`) — папка, адрес сервисного аккаунта, `key_suffix` (последние 4 символа ID ключа), `delivered_at`, `last_check`; ключ не возвращается. `PUT` (`integrations:write`, пароль админа): `key_json` (JSON-ключ сервисного аккаунта Google, `null` — прежний) и `folder_id` (ID или адрес папки) → доставка в бакет `offsite-config` (у ключа `crm` только `PutObject`) → проверка у Google → секрет `offsite_gdrive_key` в `integration_secrets`, несекретное — `settings.integrations.offsite_gdrive`, аудит `integrations.offsite_gdrive` без значений. Не доставлено — 502 `offsite_delivery_failed`, ничего не сохранено. `POST …/offsite/check` — JWT RS256 сервисного аккаунта → токен (`drive.readonly`) → `GET drive/v3/files/<папка>`: итог `ok`, `key_rejected`, `drive_api_disabled`, `folder_not_found`, `not_folder`, `not_shared_drive`, `read_only`, `network`; ничего не пишет на Drive.
- **Выключатели** (`services/external_services/switches.py`, пароль админа, аудит `external_service.disable|enable`, баннер): вендор — алиасы-чаты → `fallback-model` через `model_group_alias` (`POST /config/update`, применяется сразу, хранится в БД прокси), эмбеддинги вендора — `/model/block`; вендора запасной модели выключить нельзя (`409 service_not_switchable`); минутная проверка сверяет `model_group_alias` с выключателями. Langfuse — `client()` no-op; почта — пауза очереди (`queued` ждут, «Включить» ставит их в очередь); Telegram — клиенту `texts.maintenance` (не чаще раза в 10 мин на чат, сообщение сохраняется), исходящие воркера пропускаются, «Ответить» из CRM — `409 telegram_paused`. Процессы читают выключатели через `SwitchBoard` (кэш 10 с).
- **API** (admin, право `external_services:read|write`): `GET /api/v1/admin/external-services` (сводка, сервисы с `state`, `cause_key`, `owner`, `action`, `more_actions`, `since`, `last_recovered_at`, `groups[]` — не-`ok` сервисы, свёрнутые по причине, `stand`; агрегаты 24 ч / 7 дней, выключатель, открытый инцидент; кэш 15 с; счётчики сводки считают «ожидаемо» и «не настроено» как «не подключено», а не сбой), `GET …/{key}` (проверки за 24 ч, дни за 7 дней, инциденты за 30 дней), `POST …/{key}/check`, `POST …/{key}/disable` (`password`, `reason`), `POST …/{key}/enable` (`password`).
- **«Состояние системы»** — одна строка «Внешние сервисы» (сбой / внимание с названиями, «в норме N», «выключено вручную N») со ссылкой на `/external-services`.

## 14. Стенды

| Параметр | dev (локальный компьютер) | prod (VPS) |
|---|---|---|
| Запуск | `make up` → `docker compose -f base -f dev` | `make up-prod` на сервере, через `deploy-prod.yml` (ssh) |
| Telegram | long polling (без публичного URL), отдельный dev-бот и dev-канал | webhook, prod-бот и prod-канал |
| TLS | нет, `http://localhost` | Caddy + ACME |
| Модели | те же внешние, отдельные ключи с низким бюджетом | prod-ключи, бюджеты |
| Langfuse | опциональный профиль `--profile observability` | всегда |
| Данные | `scripts/seed_demo.py` (демо-KB, демо-лиды, тестовые пользователи) | пусто + `create_admin.py` |
| Хот-релоад | да (uvicorn `--reload`, vite dev) | нет, собранные образы |
| Бэкапы | нет | ежедневно |
| Доступ к Langfuse/консоли RustFS | открыт | IP allow-list |

Переезд dev → prod — `docs/runbooks/crm/promote-to-prod.md`: чек-лист из `docs/history/crm/PLAN.md` фазы 9.

---

## 15. Интеграционные точки на будущее

- Внешняя CRM/ERP/документооборот — через новые MCP-серверы (`erp-mcp`) и/или вебхуки `settings.integrations`; данные CRM остаются источником истины для диалога.
- Календарь — `calendar-mcp` (Cal.com self-hosted или таблица слотов).
- Другие каналы — адаптеры в `app/bot/` с общим интерфейсом `InboundMessage`/`OutboundMessage`; агент не знает о канале.
- Telegram Mini App для менеджеров — отдельный Vite-entry на тех же компонентах и API.
- Переход на Keycloak — замена `authProvider` и `security/auth.py` (ADR-0005).
- Email-приглашения и сброс пароля админом по почте — сделаны (коннектор «Почта», M3-CRM-08, ADR-0023). Самостоятельный сброс пароля по ссылке и 2FA-уведомления — позже, на том же `MailService` без изменения модели пользователей; SMTP у ERP больше нет: письма ERP и EDS отправляет этот же сервис по запросу с шины (W18A-P1, CONTRACTS §9.9).

---

## 16. Открытые решения (фиксируются ADR до соответствующей фазы)

| ADR | Решение | Фаза |
|---|---|---|
| 0001 | Архитектура «два агента + код принимает решения» | 0 |
| 0002 | Собственный CRM на Refine, а не Twenty/Odoo как ядро | 0 |
| 0003 | Один клиентский бот + канал уведомлений вместо менеджерского бота | 0 |
| 0004 | Выбор внешних моделей и embedding-размерности | 1 |
| 0005 | JWT + Casbin на старте, Keycloak позже | 0 |
| 0006 | Procrastinate как очередь и планировщик на Postgres | 0 |
| 0007 | Гибридный поиск RRF и пороги | 1 |
| 0008 | HMAC-контекст для MCP вместо передачи идентификаторов моделью | 2 |
| 0009 | S3-хранилище: RustFS вместо MinIO (community-сборки MinIO прекращены) | 0 |
| 0010 | psycopg 3 — единственный драйвер PostgreSQL | 0 |
| 0022 | Передача в бэк-офис = `customer`; итог сделки из ERP — в зеркало сделок; без коннектора — прежнее поведение | M3 (ансамбль) |
| 0023 | Коннектор «Почта»: `smtplib` в потоке + очередь, журнал `email_log`, тело письма шифртекстом до отправки | M3 (ансамбль) |
| 0024 | Центр внешних сервисов: реестр, фоновые проверки без платных вызовов, инциденты, оповещения, выключатели (вендор — `model_group_alias` LiteLLM) | M3 (ансамбль) |
