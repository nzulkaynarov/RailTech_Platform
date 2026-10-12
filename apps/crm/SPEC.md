# RailTech CRM — техническое задание (SPEC)

Версия 2.3 · 2026-10-09 (RustFS — ADR-0009; модели — ADR-0004; docling-serve и MCP SDK — ADR-0011; жизненный цикл без тупиков — ADR-0015; квалификация и цена по правилам — ADR-0016)

Документ описывает, *как* устроена система: архитектура, ядро, данные, агенты, интерфейсы, безопасность, стенды, связи. Порядок реализации — в `PLAN.md`; зачем всё это — в `BUSINESS.md`; правила работы для Claude Code — в `CLAUDE.md`.

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
| Модели | Внешние API. Рекомендация: диалог — Anthropic Sonnet-класс; квалификатор/judge — Anthropic Haiku-класс или Google Flash-класс; embeddings — Google Gemini Embedding (мультиязычный, узбекский) или Voyage multilingual | Конкретные идентификаторы фиксируются в `infra/litellm.config.yaml` на момент старта и в ADR-0004 |
| БД | PostgreSQL 16 + pgvector | Одна база для домена, векторов, очереди, чекпоинтов |
| Очередь и планировщик | Procrastinate | Задачи на Postgres: события квалификатора, таймеры SLA/снуз/unresponsive, ингест KB, ежедневные отчёты |
| Файлы | RustFS (S3-совместимый, Apache-2.0; ADR-0009) | Документы клиентов, исходники KB, вложения из Telegram. Код работает только по протоколу S3 |
| Ингест документов | docling: сервис `docling-serve` (CPU-образ) + `docling-core` HybridChunker в worker (ADR-0011) | PDF/DOCX/PPTX/XLSX/MD/HTML → DoclingDocument → чанки |
| Frontend | React 18 + TypeScript + Vite + **Refine** + Ant Design | Refine даёт CRUD, dataProvider, authProvider, accessControlProvider |
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
│ worker   │◄─────────►│ PostgreSQL 16 + pgvector                        │   │RustFS │
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
| `postgres` | `pgvector/pgvector:pg16` | 5432 | Все данные |
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
├── CLAUDE.md                 # оркестратор для агента
├── README.md                 # запуск за 15 минут (dev), ссылки на docs
├── BUSINESS.md  PLAN.md  SPEC.md
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
│   ├── Caddyfile.dev  Caddyfile.prod
│   └── casbin/model.conf  casbin/policy.seed.csv
├── scripts/                  # bootstrap_dev.sh, seed_demo.py, create_admin.py, kb_ingest.py, backup.sh, restore.sh, smoke_dev.sh, smoke_prod.sh
├── .claude/
│   ├── settings.json         # разрешённые команды для агента
│   └── skills/               # см. CLAUDE.md
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
users(id, email UNIQUE, password_hash, full_name, tg_user_id UNIQUE NULL, is_active, must_change_password BOOL DEFAULT true, ui_mode 'admin'|'manager', last_login_at, notify_system BOOL DEFAULT true, notify_leads BOOL DEFAULT true)  -- подписки на личные сообщения от бота (Q-010)
roles(id, name UNIQUE)                     -- admin | manager | viewer (seed)
user_roles(user_id, role_id, granted_by, granted_at)   -- PK (user_id, role_id)
casbin_rule(...)                           -- таблица адаптера Casbin
refresh_tokens(id, user_id, token_hash, expires_at, revoked_at, user_agent, ip)
audit_log(id, actor_user_id NULL, actor_type 'user'|'system'|'bot', action, entity_type, entity_id, before JSONB, after JSONB, ip, created_at)
```

Инвариант: `COUNT(user_roles WHERE role=admin AND users.is_active) >= 1` — проверяется в `UserService` перед снятием роли/деактивацией; нарушение → 409.

### 5.2. Лиды, клиенты, идентичности

```sql
leads(
  id, display_name, language 'ru'|'uz'|'en', stage, score INT, owner_mode 'bot'|'human'|'paused',
  assigned_user_id NULL, client_id NULL,            -- появляется при stage=customer или ручной привязке
  consent_given_at NULL, consent_version TEXT,
  need_summary TEXT, product_interest TEXT[], qualification JSONB,
  last_lead_msg_at, last_bot_msg_at, last_human_msg_at, snoozed_until, unresponsive_since,
  manager_notified_at NULL,                         -- троттлинг личных уведомлений менеджеру (Q-010)
  source 'telegram', notes_count INT
)
clients(id, name, inn TEXT NULL, segment TEXT, owner_user_id, is_active)
deals(                                              -- сделки клиента (Q-013, ADR-0019)
  id, client_id NULL, lead_id NULL, title, product_key NULL, amount NUMERIC(14,2) NULL,
  currency CHAR(3) DEFAULT 'UZS', stage 'open'|'won'|'lost', expected_close_date DATE NULL,
  closed_at NULL, lost_reason NULL,                 -- значение из settings.deals.lost_reasons
  owner_user_id NULL, created_at, updated_at
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
tg_updates(update_id PK, received_at)                -- идемпотентность
lead_notes(id, lead_id, user_id, text, visible_to_bot BOOL)
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
```

Документы скачиваются сотрудником через API (`GET /documents/{id}/download`, запись в журнал), клиентом — файлом от бота; RustFS наружу не публикуется.

### 5.7. Настройки

```sql
settings(key PK, value JSONB, schema_version INT, updated_by, updated_at)
```
Ключи и JSON-схемы валидируются Pydantic-моделями в `app/schemas/settings.py`:
`company`, `business_hours`, `texts` (greeting/consent/handoff/off_hours × ru/uz/en; подписи меню `menu_*`, команды клиента `docs_*`/`request_*`/`client_only`, номер `phone_*` — Q-011/Q-020, класс `ClientBotTexts`), `escalation` (триггеры, пороги, `no_progress_turns`, SLA, `price_always_to_manager`), `qualification` (критерии «Квалифицирован»: обязательные и дополнительные факты, горизонт срока, роли — ADR-0016), `kb` (`min_score` — по умолчанию 0.70, калибровка аудита 2026-10-12: бессмыслица набирала 0.60–0.68; `top_k`; `search_timeout_s` — таймаут попытки kb-mcp, 6 с), `bot` (persona, `max_words` — по умолчанию 60, `history_messages`, `rate_limit_per_minute`, `unresponsive_days`, `ask_phone` — один раз попросить номер, Q-020; `assist_enabled`, `assist_max_input_chars` — ИИ-помощь менеджеру «Черновик»/«Улучшить», `POST /leads/{id}/assist`, право `leads:assist`, Q-019), `competitors`, `stop_words`, `notifications` (`channel_id`, `duty_user_ids`), `budget` (`daily_usd`, `fallback_model_enabled`, `providers` — дневной лимит USD по провайдеру LiteLLM: `anthropic` 3, `gemini` 1, 0 — без лимита; Q-008), `deals` (`lost_reasons` — справочник причин отказа, `currency` — валюта новых сделок, UZS; ADR-0019).

### 5.8. Техническое

- Таблицы Procrastinate (`procrastinate_*`) — создаются его миграциями.
- Таблицы LangGraph `PostgresSaver` (`checkpoints`, `checkpoint_writes`, ...).
- `system_alerts(key PK, active, detail, first_seen_at, sent_at, resolved_at, updated_at)` — дедупликация системных алертов монитора (§13).
- `llm_usage(id, at, purpose, alias, provider, model, input_tokens, output_tokens, cost_usd, lead_id NULL, kind 'work'|'test')`, индекс по `at` — единый учёт каждого вызова модели (чат и эмбеддинги; стоимость — заголовок LiteLLM `x-litellm-response-cost`); `kind='test'` — `LLM_USAGE_KIND=test` в make eval/eval-quick/load-test/kb-eval. Источник для BudgetGuard, монитора и экрана «Расходы».

---

## 6. Домен

### 6.1. Жизненный цикл

`new → engaged → qualified → handoff → in_progress → won → customer`; боковая: `lost` (выход — новое сообщение лида или «Забрать»); временная: `unresponsive`. Клиент может открыть новую сделку: `customer → in_progress → won|lost → customer` (ADR-0015).

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
}
```
Квалификатор может предлагать только `engaged`, `qualified`. Всё остальное отклоняется с записью `rejected_reason`.

### 6.3. Score (`domain/scoring.py`)

Детерминированная функция от `qualification`, последнего `QualifierOutput` и флагов триггеров: потребность +25; продукт +15; таймлайн ≤3 мес +20 / ≤12 мес +10; роль ЛПР +20 / влияет +10; спросил цену/условия +15; просьба о контакте +25; негатив −10. Клиппинг 0..100. Весы — в коде с тестами, не в настройках (изменение веса = осознанное решение с ADR-заметкой).

### 6.4. Согласие (`domain/consent.py`)

До `consent_given_at` бот отвечает только приветствием + текстом согласия с кнопкой. Текст версионируется (`consent_version`); при смене версии согласие запрашивается повторно при следующем сообщении. Команда `/delete` → `LeadService.erase(lead_id)`: тексты сообщений заменяются на `[удалено по запросу]`, `telegram_identities` обезличивается, запись в `audit_log`; агрегаты для дашборда сохраняются.

---

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
- `decide` (код): `owner_mode != bot` → стоп; hard-триггер по стоп-словам/`/human` → `handoff`; документ найден однозначно → `deliver_document`; «ок/спасибо/понятно» (ru/uz/en) → короткий `texts.smalltalk_ack` без модели; KB недоступна (prospect, не smalltalk) → `fallback` (`reason=kb_unavailable`, без записи в `kb_gaps`); `best_score < min_score` и вопрос по продукту → `fallback`; потребность не ясна и стадия ≤ engaged → `answer` с флагом «один уточняющий вопрос»; иначе `answer`.
- `answer/clarify`: `dialog-model`, промпт `dialog_prospect.md` / `dialog_customer.md`, в контексте только найденные фрагменты. ≤ `bot.max_words` слов (60), без списков, максимум один вопрос. Гарантии кода поверх ответа модели: встречный вопрос в конце убирается, если бот спрашивал в одном из двух предыдущих ответов, в ответ на smalltalk и перед уведомлением о передаче менеджеру. Модель получает настоящий результат инструмента (`ok`/ошибка/`not_allowed`); `create_service_request` возвращает `request_number`, и ответ клиенту обязательно содержит «Запрос №N» (`texts.request_created`), как в `/request`. Промпт запрещает упоминать «базу знаний» и внутренние источники.
- `fallback`: честный отказ + `kb_gaps` (upsert по нормализованному вопросу, `occurrences++`).
- `deliver_document`: отправка файла из S3 (RustFS) через Telegram + `document_access_log`.
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

Запуск: задача `qualify_lead(lead_id)` на каждое сообщение лида и бота; `queueing_lock=lead_id` + отложенный старт 5 с для батчинга. Модель `qualifier-model`, structured output:

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

- Привязка: менеджер в CRM на карточке клиента «Привязать Telegram» → выбирает идентичность из лидов этого клиента или вводит `tg_user_id`/username → `verified_at`. Дополнительно бот может запросить номер телефона (`request_contact`) и сверить с `clients`-контактами — ускоряет, но не заменяет подтверждение менеджером.
- Интенты: документ, статус (заглушка в v2 → `create_service_request`), поддержка, человек.
- Все обращения к `documents` фильтруются `client_id` из контекста на уровне SQL; тесты на попытку доступа к чужому `document_id` обязательны.

### 7.4. Промпты

Хранятся в `backend/prompts/*.md`, версионируются в Langfuse Prompt Management (имя = путь файла, версия = git sha). Структура промптов — как в v1 спецификации, с добавлением `dialog_customer.md`: роль сервисного ассистента, выдача документов только найденных, никаких обещаний по срокам/условиям, при любом запросе на изменение условий — менеджер.

---

## 8. Эскалация

### 8.1. Триггеры (`domain/triggers.py`; параметры — `settings.escalation`)

| Код | Условие | Приоритет |
|---|---|---|
| `human_requested` | Интент/команда «человек, оператор, менеджер» | hot |
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
Потребность: интеграция онлайн-кассы с 1С для 3 магазинов
Интерес: pos-integration · Срок: до 3 мес. · Роль: ЛПР
Почему: Цена/условия — нет в базе; Просит звонок
Рекомендация: позвонить сегодня, уточнить число касс и версию 1С
Последнее: 👤 «Ок, пусть позвонят, лучше после 15:00»

[ Забрать ]   [ Открыть в CRM ]
```

Метки стадий, причин передачи, сроков и ролей — те же, что в CRM (один словарь канала `app/services/channel_texts.py`, термин — «Передача», Q-015); порог «бот N раз подряд не нашёл ответ» — из `settings.escalation.kb_gap_streak`.

- **Забрать** — `callback_query`; бот сопоставляет `from.id` с `users.tg_user_id`; нет совпадения → ответ «Привяжите Telegram в профиле CRM». Успех → `LeadService.take(lead_id, user)` (те же правила, что из CRM) → пост редактируется: «Забрал: Имя · 14:32», кнопка исчезает.
- **Открыть в CRM** — URL `https://<host>/leads/124`.
- Больше кнопок в канале нет. Ответы лиду — только из CRM.

### 9.2. Клиентский бот

Команды: `/start`, `/lang`, `/human`, `/delete`, `/help`; клиенту — `/docs`, `/request`, `/status`.

**Интерфейс по статусу (Q-011, Q-020; `domain/bot_menu.py`, `services/client_bot.py`, `bot/status.py`).** Меню чата (`BotCommandScopeChat`) выбирает код после каждого сообщения/кнопки лида; публикуется только при смене варианта или языка (кэш в процессе бота):

| Статус | Признак | Меню |
|---|---|---|
| prospect | нет подтверждённой привязки к клиенту | Начать · Связаться с менеджером · Сменить язык · Что умеет бот · Удалить переписку |
| with_manager | prospect и `owner_mode = human` | то же без «Связаться с менеджером» |
| client | `verified_client` (как режим customer агента) | Мои документы `/docs` · Запрос менеджеру `/request` · Статус запроса `/status` · Сменить язык · Удалить переписку |

`/docs` — до 10 видимых клиенту документов кнопками (новые первыми), `client_id` только из подтверждённой идентичности, выдача файла и журнал доступа — как у docs-mcp. `/request` — описание следующим сообщением → `service_requests` + info-эскалация `service_request`. `/status` — открытый запрос словами. Prospect на командах клиента получает `texts.client_only`. Номер телефона: один раз (флаг `leads.qualification.phone_asked_at`), когда лид квалифицирован/передан или ждёт менеджера, при `bot.ask_phone`; сохраняется только собственный контакт (`contact.user_id == from_user.id`) в `telegram_identities.phone_e164` (E.164), показывается в карточке лида, стирается по `/delete`.

Middleware: идемпотентность, rate-limit (20 сообщений/мин на пользователя, при превышении — вежливое сообщение), маскирование PII в логах, проверка согласия. Вложения лида (фото/документы) сохраняются в S3 (RustFS) и показываются в CRM; бот в v2 на вложения отвечает «передам коллеге» + триггер `info`.

---

## 10. CRM (frontend)

### 10.1. Навигация

| Раздел | Роли | Содержание |
|---|---|---|
| **Входящие** | manager, admin | Открытые эскалации (hot первыми), мои лиды, лиды без владельца, запросы клиентов (открытые сервисные запросы, кто ждёт дольше — первым: `GET /api/v1/service-requests?status=open`, право `clients:read`; в карточке лида-клиента — ссылка по `open_service_request_id`, Q-017); счётчики в сайдбаре; live через SSE `/api/v1/stream` |
| **Лиды** | manager, admin, viewer(ro) | Таблица с фильтрами (стадия, владелец, score, период, язык), сохранённые фильтры |
| **Карточка лида** | manager, admin, viewer(ro) | Слева: шапка (стадия, score, владелец, язык, согласие), резюме, квалификация, причина эскалации, заметки. Центр: `ChatThread` — переписка с ролями, поле ответа (только `owner_mode=human` и владелец/админ), кнопки: Забрать · Вернуть боту (с заметкой, лид получает `texts.returned_to_bot`) · Отложить · Сделка заключена · Закрыть отказом · Сделать клиентом · Передать коллеге (`actions/assign`) · Новая сделка (для клиента, `actions/new_deal`) — ADR-0015. Владелец показывается по имени (`assigned_user_name`; справочник команды `GET /team` — всем ролям). Справа: «Почему система так решила» — последние `qualifier_runs` и `stage_transitions` в человекочитаемом виде |
| **Клиенты** | manager, admin, viewer(ro) | Карточка клиента: контакты, привязанные Telegram-идентичности (с подтверждением), документы, связанные лиды/диалоги, сервисные запросы |
| **Сделки** | manager, admin, viewer(ro) | `/deals`: таблица (название, клиент, сумма с валютой, стадия, ожидаемое закрытие, ответственный, причина отказа), фильтры стадия/ответственный (`?stage=won`), создание и правка в модальном окне; на карточке клиента — блок «Сделки» с «Новая сделка». Закрытие лида «Сделка заключена»/«Отказ» закрывает его открытую сделку в той же транзакции (ADR-0019). API: `GET/POST /api/v1/deals`, `GET/PATCH /api/v1/deals/{id}`, `GET /api/v1/deals/summary?days=`, `GET /api/v1/deals/options`; права `deals:read` (все роли), `deals:write` (manager, admin) |
| **Документы** | manager, admin | Загрузка документов клиенту (тип, номер, дата), видимость клиенту, журнал доступа |
| **База знаний** | admin | Документы KB, ингест, активность, просмотр чанков, тестовый поиск («что найдёт бот на этот вопрос») |
| **Пробелы KB** | admin | Вопросы без ответа: частота, язык, примеры диалогов, действия: «Создать документ», «Привязать к документу», «Игнорировать» |
| **Настройки** | admin | Формы по ключам `settings` с валидацией; предпросмотр текстов на 3 языках; редактор правил эскалации |
| **Пользователи** | admin | Список, роли, создание с временным паролем (обязательная смена при первом входе, `users.must_change_password`), сброс пароля админом, деактивация (с передачей лидов в работе и клиентов коллеге — иначе 409 `user_has_active_leads`, ADR-0015), привязка Telegram; защита «последний админ». Email-приглашения — в расширениях (§15) |
| **Дашборд** | все | Сделки за период (выиграно числом и суммой по валютам, отказы по причинам; плитка «Сделок» ведёт в `/deals?stage=won`), воронка, эскалации по причинам, время до «Забрать», доля fallback, стоимость моделей (из Langfuse API), пробелы KB |
| **Аудит** | admin | `audit_log` с фильтрами |

### 10.2. Переключатель режима

В шапке у пользователей с ролью `admin` — переключатель **Админ / Менеджер** (`users.ui_mode`, сохраняется). В режиме «Менеджер» скрыты: База знаний, Пробелы KB, Настройки, Пользователи, Аудит. Переключатель не меняет права на бэке — только навигацию.

### 10.3. Технические требования к фронту

Refine с кастомным `dataProvider` (REST `/api/v1`), `authProvider` (cookie JWT), `accessControlProvider` (матрица прав приходит с бэка `GET /api/v1/me/permissions`, фронт только скрывает/блокирует; истина — на бэке). Клиент API генерируется из OpenAPI (orval) в CI; ручные типы запрещены. Ошибки API — единое тело `ErrorOut {code, message, details}` для доменных ошибок, валидации запроса и 404: `code` — класс ошибки, `details.reason` — стабильный подкод случая (`Reason`, ADR-0017), `details.field` — поле формы; текст пользователю фронт берёт из i18n по `details.reason ?? code`, `message` — только для логов. Адаптивная вёрстка до 390 px (менеджер с телефона может читать и отвечать).

---

## 11. Безопасность

| Область | Требование |
|---|---|
| Секреты | Только в `.env` на стенде и GitHub Secrets; в репозитории — `.env.example`. Ключи провайдеров моделей знает только `litellm`. pre-commit с `gitleaks` |
| Аутентификация | argon2id; JWT access 15 мин в памяти, refresh в httpOnly/SameSite=Strict cookie с ротацией; logout отзывает refresh; блокировка после 10 неудачных входов на 15 мин |
| Авторизация | Casbin на каждом REST-эндпоинте через зависимость `require(action, resource)`; объектные проверки (владелец лида) — в сервисах. MCP-инструменты — только внутренняя сеть + HMAC-контекст |
| Данные клиентов | Все запросы к `documents`/`clients` из бота — с обязательным `client_id` из верифицированной идентичности; интеграционные тесты на cross-tenant доступ |
| Telegram | Webhook `secret_token`; allow-list `update` типов; `tg_updates` идемпотентность; rate-limit |
| PII | Маскирование телефонов/email/ИНН в логах и Langfuse (`security/pii.py` как processor structlog и Langfuse mask-функция) |
| Инъекции в промпт | Пользовательский текст и фрагменты KB — в отдельных XML-блоках; системные правила запрещают раскрытие инструкций; eval-кейсы на injection; инструменты не принимают идентификаторов от модели |
| Аудит | Все мутации через REST и кнопку в канале — `audit_log` (before/after) |
| Транспорт | TLS на Caddy (ACME), HSTS; Langfuse и консоль RustFS на prod — только с IP allow-list |
| Зависимости | `uv lock`, `pnpm lock`, Dependabot, `pip-audit`/`npm audit` в CI |
| Бэкапы | Ежедневно, проверка восстановления раз в месяц по runbook |
| Бюджет моделей | Три уровня (ADR-0014): `settings.budget.daily_usd` — при превышении диалог → `fallback-model`, квалификатор продолжает; LiteLLM `provider_budget_config` — жёсткий суточный потолок по провайдеру; лимиты в консолях провайдеров |

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
- Метрики здоровья: `GET /health` (liveness), `GET /ready` (БД, S3/RustFS, LiteLLM); ежедневный отчёт в канал (General-пост): новых лидов, эскалаций, открытых пробелов KB, стоимость.
- Алерты (личным сообщением от бота активным админам с `notify_system` и привязанным Telegram; если никому не доставлено — в канал; префикс ⚠️): задача в `failed` после 3 ретраев; LiteLLM недоступен > 2 мин; очередь > 100 задач; бюджет > 80 %; у провайдера модели закончились кредиты/квота или отклонён ключ — проба раз в час запросом в 1 токен к `dialog-model` (Anthropic) и `fallback-model` (Gemini) с `disable_fallbacks` (иначе сбой Claude скрыт ответом Gemini), ключ алерта `model:<alias>`, снятие — только по успешной пробе. Монитор — периодическая задача `system_monitor` (раз в минуту, `domain/alerts.py`); дедупликация в таблице `system_alerts(key PK, active, detail, first_seen_at, sent_at, resolved_at, updated_at)`: пост на переходе в проблему, повтор не чаще 6 ч, снятие постом «✅ … в норме». Итоги дня — `daily_report` в 18:05 Asia/Tashkent (пн–пт).
- Экран «Состояние системы» (`/system`, admin; `GET /api/v1/system/status`): БД, S3, LiteLLM (проверки `/ready`), модели — по последней пробе монитора (`system_alerts` `model:*`, без вызовов моделей), бюджет, очередь (ожидание, зависшие > 15 мин, упавшие за час), канал, бот, бэкап (`unknown`: бэкапы в томе сервера), наличие обязательных секретов (только имена). Статусы `ok|warn|fail|unknown` с причиной и временем проверки.
- Личные уведомления (Q-010): сообщение лида в режиме `human` → задача `notify_lead_message` → личка ответственному менеджеру (`notify_leads`, без кнопок, ссылка на карточку `company.crm_base_url`/leads/{id}), не чаще `notifications.manager_dm_throttle_minutes`. В CRM — звук и уведомление браузера по SSE `message.created` (`assigned_user_id` = текущий пользователь), включается в профиле.
- BudgetGuard: расход за сутки (Asia/Tashkent) = сумма `llm_usage.cost_usd` (работа и тесты; кэш 60 с). Мягкий бюджет: при ≥ 100 % `budget.daily_usd` и `fallback_model_enabled` диалог идёт на `fallback-model`, квалификатор продолжает; `daily_usd = 0` — без лимита. Лимит провайдера `budget.providers` (проверка до вызова): провайдер за лимитом → диалог на `fallback-model`, если провайдер резерва в лимите, иначе `LlmUnavailableError` (бот честно передаёт человеку); квалификатор — отказ. Провайдер алиаса — из LiteLLM `GET /model/info` (`model_info.litellm_provider` или префикс `litellm_params.model`), кэш 5 мин; неизвестен → лимит провайдера не применяется. Потолок `provider_budget_config` LiteLLM — аварийный, выше настроек.
- Runbooks: деплой, откат, бэкап/восстановление, ротация ключей, «бот молчит», «эскалации не приходят», «стоимость выросла», «откат промпта», eval-gate, «переезд dev → prod».

---

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

Переезд dev → prod — `docs/runbooks/promote-to-prod.md`: чек-лист из `PLAN.md` фазы 9.

---

## 15. Интеграционные точки на будущее

- Внешняя CRM/ERP/документооборот — через новые MCP-серверы (`erp-mcp`) и/или вебхуки `settings.integrations`; данные CRM остаются источником истины для диалога.
- Календарь — `calendar-mcp` (Cal.com self-hosted или таблица слотов).
- Другие каналы — адаптеры в `app/bot/` с общим интерфейсом `InboundMessage`/`OutboundMessage`; агент не знает о канале.
- Telegram Mini App для менеджеров — отдельный Vite-entry на тех же компонентах и API.
- Переход на Keycloak — замена `authProvider` и `security/auth.py` (ADR-0005).
- Email-приглашения и самостоятельный сброс пароля — требуют SMTP; добавляются без изменения модели пользователей.

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
