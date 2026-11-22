# AREA 2: DOCUMENT A («Knowledge-First») checked against the repository

Repo: fresh main at `` (paths below are relative to it). I only read code and docs. Nothing was run. "(inference)" marks a conclusion I drew from code but did not see working.

## 0. Short answer

- **Large parts of the five layers already exist** in some form: the outbox/inbox bus with retries and DLQ, S3 storage, a files registry with versions and sha256, Docling, pgvector plus tsvector hybrid search, the Tiptap editor, stateless Streamable-HTTP MCP servers, LiteLLM and Langfuse, AI call logs with a "human decided" field, and prompt-injection fencing.
- **The core architectural thesis contradicts accepted decisions.** Document A wants "one PostgreSQL engine and one database, isolated by RLS", plus JSONB custom properties, a Notion-style canvas or Markdown note on every entity, and a TS/NestJS backend. Each of these hits an invariant or an owner decision:
  - ORCHESTRATOR §3 inv. 2 and 16
  - ADR-0019 п. 5 (pool with RLS only at stage H)
  - DECISIONS 2026-11-18 «Не берём: … холст, пользовательские поля»
  - ADR-0031 п. 4
  - ADR-0013 п. 1
- **What is genuinely new:**
  - an entity link graph with backlinks and `[[links]]` (only the planned `@mentions` exist)
  - a generic `files.doc_type/status/metadata` registry across domains
  - an "extracted.md" companion for every file, plus OCR of scans
  - a remote MCP for employees or external agents (OAuth 2.1, per-user identity, write tools with human confirmation)
  - real-time co-editing (Yjs)
  - outbound webhooks to third parties
- **It is written for the client Cabinet, and its premise about Cabinet is out of date.** Its assumption "ваше ТЗ уже заложен Notion-UX (Database Views Канбан/Таблица/Документы)" is wrong for main: the Cabinet kanban and `ViewSwitcher` were removed on 2026-10-31. Cabinet has no backend (ADR-0004), so every layer it proposes "for Cabinet" would really be built in the ERP portal API.

## 1. Facts by topic

### 1.1 Storage, domain boundaries, multi-tenancy

| Claim in A | Verdict | Evidence |
|---|---|---|
| One PostgreSQL 16+ engine «в одной базе данных», strict and flexible contours in one DB | **Contradicts** | ORCHESTRATOR §3 inv. 2 (line 53): «Общих таблиц нет. `crm`, `erp`, `eds` — разные базы». Inv. 16 (line 67): one owner per field, foreign data only as projections. Inv. 14 (line 65): integrations only through the bus. One Postgres *server* is true: `infra/compose/base.yml:139` uses image `pgvector/pgvector:0.8.7-pg17` (PG 17, not 16), but each service has its own database. |
| Tenant isolation by RLS on `tenant_id` | **Contradicts / not applicable** | ADR-0019 lines 6 and 11: silo model, «одна компания — одна установка»; «pool с RLS — только по решению этапа H». The `tenant` field exists only in the event envelope (`packages/contracts/events/envelope.v1.json:15,60`). There is no `ENABLE ROW LEVEL SECURITY`, `CREATE POLICY` or `tenant_id` anywhere in `apps/` or `infra/`. |
| Isolation of "B2B clients" from each other | **Exists, in application code** | Cabinet → ERP portal: `apps/erp/backend/portal/authentication.py:14-30` binds `request.portal_company`, `portal_contact`, `portal_roles` (`client`, `partner`) and `portal_modules` from the session cookie. `portal/permissions.py:21` `HasPortalModule`. ADR-0004 line 11: «Все ответы отфильтрованы по компании сессии; негативные тесты на каждый эндпоинт». Inv. 5 (line 56): the client sees only the projection. For agents, the company comes only from the signed context (inv. 4, line 55). |
| Roles «client_admin, manager, supplier» / «Покупатель / Поставщик / Партнёр» | **Partly** | The portal knows two roles, `client` and `partner` (with a supplier relationship, ADR-0022), plus the per-contact right «решает» (`CanAct`, `permissions.py:44`). There is no «Покупатель» role (inference from `apps/cabinet/src/i18n/locales/ru.json:200,1044`). |
| ERP «companies» as tenants | **No** | `parties.Company` holds counterparties. The issuer `company` on `documents/models/sequences.py:53-61` is legacy B2B multi-issuer numbering, not tenancy. |

### 1.2 Editor, versions, Markdown

| Claim | Verdict | Evidence |
|---|---|---|
| Tiptap (ProseMirror) recommended | **Already chosen for Platform** | `apps/platform/web/package.json:38-41` has `@tiptap/react`, `starter-kit`, `extension-table`, `pm` 3.32.0. Shared `shared/ui/BodyEditor/BodyEditor.tsx`, used in letters, documents and letter templates. Owner decision 2026-11-12. Plan ДОК-9 «Один редактор» and ДОК-10 «Шаблон — документ из редактора» (`docs/runbooks/plan-2026-11-12.md:167-168`). Cabinet has **no** editor (`apps/cabinet/package.json` has no tiptap). |
| Store `content_md` + `content_ast`/`yjs_state` | **Partly / contradicts** | The body is stored as a ProseMirror tree in JSONB under contract `documents/body.schema.json`: `apps/eds/app/models/documents.py` (`body` JSONB), DocumentVersion `body` JSONB. There is no `content_md`. The flexible-UI assessment §2.5 says «Содержимое редактора в JSONB. Уже так… документы остаются структурными (решение 2026-11-12)». |
| Real-time co-editing Yjs + Hocuspocus | **Missing** | No yjs, hocuspocus or collab in either front end. New service (a Node server) — conflicts with ADR-0013 п. 1 (new server code is Python/FastAPI). |
| Note version history and rollback | **Partly** | EDS `document_versions` snapshots the body when it goes to approval (`documents.py`, class `DocumentVersion` ~line 111). `files` + `file_versions` carry sha256. There is no rollback "in one click" and no versioning of free notes. |
| Markdown anywhere | **Yes, but not for business entities** | Help articles: `docs/kb/help` → `apps/platform/web/src/features/help/Markdown.tsx` (own minimal parser). Company articles are stored in CRM (`apps/platform/bff/app/api/company_articles.py:1-8`). The bot KB accepts only `.md` with YAML front matter (`docs/kb/FORMAT.md:17`; `apps/crm/backend/app/services/kb/markdown_convert.py`). Notable: the "Markdown + YAML frontmatter" convention already exists, but only for the KB. |

### 1.3 Notes, discussion, links

| Claim | Verdict | Evidence |
|---|---|---|
| Every entity has a Markdown note | **Missing; contradicts the 18.11 decision on the canvas** | Today there are only text fields:<br>• ERP `sales/models/deals.py:92` `notes` («Внутренние заметки, видны только сотрудникам»)<br>• `sales/models/quotes.py:212`<br>• `finance/models/billing.py:92,424`<br>• CRM `lead_notes` table (`apps/crm/backend/app/models/leads.py:199-200`) and `clients.notes` (`clients.py:55`)<br>The 2026-11-18 assessment §2.3 says the canvas is «Не берём… противоречит второму условию запуска: свободный текст вместо записи — только временное состояние». DECISIONS line 349 lists «холст» among «Не берём». |
| «Обсуждение» | **Declared, not built** | `apps/platform/web/src/modules/types.ts:63-80`: `RECORD_TABS.chat` is in the standard set (ЕД-7, DECISIONS line 364). No screen fills `PanelPortal tab="chat"`: the grep found tabs card, facts, history, journal, resolution, role, step and task, but no chat. Report §9.3 plans «Обсуждения на объектах» for February (L). |
| `[[wiki-links]]`, `entity_links`, backlinks | **Missing** | No link graph in any domain. The closest pieces:<br>• Planned «Упоминания `@человек` и `@документ`» (plan line 260; assessment п. 4, 2 PR)<br>• the `EntityCell` reference chip<br>• ⌘K search (`apps/platform/bff/app/api/search.py`), which fans out to the domain APIs; there is no own index.<br>A cross-domain edge table would break inv. 2: links between a CRM lead, an ERP deal and an EDS document would have to live in one owner or be projections (inference). |

### 1.4 Files, OCR, vectors

| Claim | Verdict | Evidence |
|---|---|---|
| S3/MinIO | **S3 yes, MinIO rejected** | RustFS: `infra/compose/base.yml:247-248`. Buckets per service (`base.yml:278`): `kb-sources client-documents tg-attachments erp-private erp-public erp-temp eds-private …`. «MinIO … отклонено, не возвращаемся» (`docs/research/2026-11-22-connectors/README.md:57`). |
| Key `{tenant_id}/{entity_type}/{entity_id}/…` | **Not applicable** | Silo model, a bucket per service. |
| `files` registry with sha256 | **Exists in EDS** | `apps/eds/app/models/files.py:12-42`: `files` (owner is one of letter, document or instruction) and `file_versions` (`sha256`, `s3_key`, size, content_type). CRM `documents` with `extracted_text` and tsvector (`apps/crm/backend/app/models/clients.py:105,135,31`) plus `document_access_log`. |
| `doc_type` / `status` / `metadata_jsonb` / `linked_entities` on files | **Partly, by design typed per domain** | Types and statuses live on the *document*, not the file:<br>• EDS `documents.kind` (memo, application, report, letter_out) and `status` CHECK (`documents.py:33-36`)<br>• `project_documents.kind` (contract, invoice, act) as an ERP projection<br>• ERP `GeneratedDocument` + `GeneratedDocumentStatus` lookup<br>A generic «certificate / customs_gtd / expiry» metadata registry is missing. |
| File → `extracted.md` + vector chunks | **Partly** | Docling container: `base.yml:347-348` (`docling-serve-cpu:v1.36.0`). Called from:<br>• CRM `app/integrations/docling.py`, `services/documents.py`, `tasks/documents.py`, which extracts client-document text for bot search (procrastinate, 3 retries)<br>• KB ingest + `HybridChunker`<br>• ERP `ai/services/payloads.py:25-44,65`: **docx only** via Docling; PDF and images go to the model as a file. That is debt B-CAT1-3 against the 2026-11-11 rule «в модель — только текст» (connectors README §0).<br>OCR of scans: «позже» (connectors README §1). |
| pgvector + tsvector hybrid | **Exists for the bot KB only** | `apps/crm/backend/app/models/kb.py:5,20-31,81-97`: HNSW, Vector(`EMBEDDING_DIMENSIONS`), tsvector ru/en. The embedding is **gemini-embedding-2, 1536 dims** (`app/domain/embedding_profile.py:3,27,32`; alias `embed-model`, `infra/ai/litellm.models.yaml:64-66`). **It is not bge-m3**: the brief's hint is wrong. EDS and ERP have no vectors. |

### 1.5 Custom fields, saved views, configurable data

The 2026-11-18 assessment (`docs/research/2026-11-18-flexible-ui-assessment.md` §3) was adopted in DECISIONS line 349: «До запуска — сортировка… после запуска — строка итогов, сохранённые виды и настройки таблиц на сервере в профиле сотрудника CRM, упоминания… Не берём: группировку, холст, пользовательские поля, свою сетку и блочный редактор, shadcn в Платформе, настраиваемую «Главную»».

| Item | Decision | Plan row |
|---|---|---|
| Custom fields in JSONB | **не берём** (§2.5: «поле в JSONB не попадёт никуда без отдельной работы и обойдёт правило «контракт раньше кода»»). Reconfirmed by ADR-0031 п. 4 and DECISIONS line 360 (5): «пользовательские поля остаются «не берём»». | — |
| Saved views | **берём**, stored server-side in the CRM employee profile, not as `user_views` next to business data | plan line 259, 2–3 PR |
| Column settings «Столбцы» | exist, in localStorage | `apps/platform/web/src/shared/ui/DataTable/tableSettings.ts:5,53` |
| Kanban | **позже**, «по этапам» without drag, only on request | plan line 92. Report §9.3: read-only board in January |
| Inline edit | narrow, later | plan line 87 |
| Calendar / timeline / gallery views | not assessed; no such views exist | — |
| Grouping | не берём | — |
| Sorting | before launch | Х-15, plan line 233 |
| Totals row | after launch | plan line 258 |

The configurable data that does exist: dictionaries (BFF `app/api/dictionaries.py`; EDS `models/dictionaries.py`; ERP lookups) and processes as data (ADR-0031: versioned JSON owned by the domain, «Формул, скриптов и вебхуков в обход «Подключений» в описании нет», line 36). A's `formula` property type directly contradicts the latter.

### 1.6 Integration gateway

| Claim | Verdict | Evidence |
|---|---|---|
| Transactional outbox + bus | **Exists** | `packages/rt-bus`; tables `rt_bus_outbox/delivery/inbox/subscriber_state` (`docs/architecture/rt-bus.md:54-56`). 86 event schemas in `packages/contracts/events/{crm,eds,erp,identity}`, AsyncAPI 3.0, CloudEvents envelope, subscriptions `packages/contracts/bus/subscriptions.yaml`. |
| NATS JetStream | **Planned as v2 (stage F)** | ORCHESTRATOR line 40-41; ADR-0014 line 19. Kafka and RabbitMQ are not considered. |
| HMAC, retries, DLQ | **Exists (internal)** | HMAC v2 delivery to subscribers. Retries 30 s → 24 h, 6 retries then `dead`, 4xx straight to `dead`, circuit breaker, «повторить все dead» (`rt-bus.md:12-15,186-208,304`). Inbox dedup by event id (`rt-bus.md:244`). |
| Idempotency-Key | **Exists** | ERP `core/idempotency.py`, `integration/idempotency.py`, portal middleware; BFF `api/eds_documents.py`; EDS `models/idempotency.py`; 19 mentions in OpenAPI. |
| Outbound webhooks to third parties / webhook builder | **Missing** | Only the inbound Telegram webhook (`apps/crm/backend/app/domain/telegram_webhook.py`, `api/telegram.py`). Connectors are «снаружи ядра, каждый со своей очередью (этап F)» (ORCHESTRATOR line 44-45, inv. 14). |
| Connectors | **Partly** | Working:<br>• Telegram bot, Cabinet as Mini App (`apps/cabinet/src/telegram/webapp.ts:64`)<br>• Yandex 360 mail in and out<br>• CBU exchange rates<br>• tarif.customs.uz / tasnif without an official API<br>• site forms → lead<br>• «Подключения» with checks<br>Planned: ЭДО Didox + E-IMZO after launch (step 8); 1C as the bookkeeper's system (decided; exchange is a question) (connectors README §1). There is **no EDO operator integration today**: the brief's «EDO operator mark» is a misreading, since `shared/ui/OperatorMark.tsx` is the company logo. |
| Smart Import | **Exists** | Supplier price import (`apps/platform/bff/app/api/erp_price_import.py:1-13`: async, check then apply, AI rows). Calculation from the request file via `intake-model` (`apps/erp/backend/crm/services/calculation.py:1734-1735`, formats docx, xlsx, pdf, images, csv). Cabinet has file attachment on requests (`apps/cabinet/src/pages/requests.tsx`, `components/FileField.tsx`). «Excel/PDF/Email → черновик Markdown-заметки» is missing and contradicts the canvas decision. |
| Automation engines | **Rejected** | ADR-0031 lines 19, 23, 42-43: Camunda, Operaton, Flowable, Temporal, n8n and Windmill are rejected. Connectors README line 57: «отклонено, не возвращаемся». |

### 1.7 MCP and AI

| Server | Tools | Called by | Auth | Transport |
|---|---|---|---|---|
| `crm-mcp-kb` (:8101) | `search_kb`, `list_products` | CRM client dialog agent (`apps/crm/backend/app/agents/mcp_client.py:13-35`) | HMAC-signed `X-Agent-Context` per call (`apps/crm/backend/app/mcp/common.py:23-28`) | `streamable_http_app(stateless_http=True, json_response=True)`; allowed hosts are internal only, «наружу порт не публикуется» (`common.py:31-38`) |
| `crm-mcp-crm` (:8102) | `get_lead_context`, `update_qualification`, `request_callback`, `create_service_request` (`crm_server.py:62-134`) | same | same | same |
| `crm-mcp-docs` (:8103) | `search_documents`, `get_document_link` (10 min) | same | same | same |
| `erp-mcp` (:8104, `/mcp/erp`) | 7 tools in `packages/contracts/mcp-tools.json`: `list_client_deals`, `get_deal_status`, `get_delivery_status`, `list_client_documents`, `get_document_link`, `search_catalog`, `create_request` | CRM agent (`agents/erp_mcp.py`) | HMAC context, 60 s TTL, one-time `jti`, rate limit per company, args validated against input_schema (`mcp-tools.json:7-19`; `apps/erp/backend/integration/mcp/gate.py:1-13`; `context.py`) | streamable-http |

- **SDK:** `mcp` 2.3.0 in both CRM (`apps/crm/backend/uv.lock:1201-1202`) and ERP (`requirements.txt:1128`).
- **All MCP is for the client bot.** There is no MCP for employees or external agents (Claude Desktop, Cursor), no OAuth 2.1/PKCE and no per-employee identity. The report already notes this (§9.4).
- **AI gateway:** LiteLLM with 9 aliases (`infra/ai/litellm.models.yaml:15-119`): dialog, qualifier, judge, fallback, embed, intake, match, draft, enrich. EDS uses intake, draft and fallback (`apps/eds/app/ai/gateway.py:27-35`). Langfuse traces from CRM, ERP and EDS (`base.yml:668-684,792-806`).
- **AI audit already in place:**
  - CRM `llm_usage` (`models/system.py:47`)
  - ERP `AICall` (`apps/erp/backend/ai/models.py:129`, metadata only, texts in Langfuse)
  - EDS `ai_suggestions` with `decision accepted/edited/manual`, which is the human-in-the-loop record (`apps/eds/app/models/ai.py:26-48`)
  - a daily budget per service
  - There is no `diff_before_after` and no rollback of AI edits.
- **Invariant and assistant rules:**
  - Inv. 4 (line 55) «Код решает, модель предлагает»; ADR-0005 lines 11-14: «Cabinet своего ИИ не имеет».
  - Assistant plan (`docs/research/2026-11-12-create-and-assistant.md` §C6-C7): «Ничего не записывает сам», «Своего доступа к доменам у помощника нет», «Не даём помощнику действовать самому: создавать, отправлять, подписывать». Plan line 254: after launch.
- **Prompt-injection fencing already exists:** `apps/crm/backend/prompts/dialog_customer.md:35`, `mail_assist.md:12`, `assist_draft.md:14`, `qualifier.md:15`, `apps/eds/app/ai/prompts/letter_intake.md:6` («данные, а не инструкции»). ERP treats LLM output as untrusted and checks it in code (`apps/erp/backend/ai/services/documents.py:12,188`).

**MCP spec claim.** «MCP 2026-07-28: stateless JSON-RPC 2.0 поверх Streamable HTTP» is **confirmed externally**. The 2026-07-28 revision removes sessions and the initialize handshake, adds `Mcp-Method`/`Mcp-Name` headers and drops ping ([MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/), [Claude blog](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude), [WorkOS](https://workos.com/blog/mcp-stateless-spec-2026-07-28), [Cloudflare](https://blog.cloudflare.com/mcp-v2/), [The Register](https://www.theregister.com/a/5276722)).

Our `erp-mcp` gate explicitly relies on `initialize`, `ping` and `tools/list` arriving before `tools/call` (`gate.py:8-9`; `mcp-tools.json:9`). (inference) Moving to the new revision would mean reworking the `jti` logic and the SDK version. Whether `mcp` 2.3.0 speaks 2026-07-28: cannot verify.

### 1.8 Analytics

- **ClickHouse:** in compose under `profiles: [observability]` (`base.yml:849-853`). Used only by Langfuse (`CLICKHOUSE_MIGRATION_URL`, `base.yml:890`). No app code touches ClickHouse or DuckDB.
- **Materialized views:** only CRM bot stats, `mv_daily_stats` and `mv_escalation_reasons` (`apps/crm/backend/alembic/versions/20261008_1621_dashboard_materialized_view.py:24,77`), refreshed in `services/dashboard.py:27`.
- **«Сводка»:** an empty section (Х-9, plan line 227). The director's «Сводка по компании» is ГЛ-3 (plan line 149).
- **Dashboard and Главная:** BFF aggregation from the domain APIs (`apps/platform/bff/app/api/dashboard.py`), no warehouse. BFF «не владеет данными. Нет своей базы» (`docs/architecture/platform-bff.md:38`).
- **BI:** «свой BI-сервер» is not connected. Reports go to Excel/Power Query first; DataLens or Metabase later, only with a separate server (connectors README lines 29, 111-112, 219).

## 2. Gap table: DOCUMENT A against the repository

S = 1–2 PR, M = 3–6, L = 8–15, XL = >15 or a new service (the report's scale).

| A element | State | Conflicting decision (quote) | What adopting it touches | Size |
|---|---|---|---|---|
| One DB / one engine for SoR + knowledge | contradicts | inv. 2 «Общих таблиц нет… разные базы»; inv. 16 | all domains, the bus, contracts | XL (new architecture) |
| RLS tenant isolation | contradicts / not needed | ADR-0019 п. 5 «pool с RLS — только по решению этапа H»; isolation is in portal code plus negative tests (ADR-0004) | ERP portal, all queries | XL |
| Markdown note on every entity with YAML frontmatter projection | missing; contradicts | 18.11: «холст… Не берём… свободный текст вместо записи — только временное состояние» | owner domain per entity; BFF; editor | L–XL |
| Tiptap editor | **exists** (Platform) | — | Cabinet would need a second editor stack on shadcn | — / M for Cabinet |
| Slash commands `/задача /таблица /файл` | partly (Markdown shortcuts in BodyEditor) | blocks «/спецификация» rejected 18.11 | BodyEditor | S–M |
| Yjs + Hocuspocus co-editing | missing | ADR-0013 п. 1 (Python for new server code); 12.11 «не встраиваем офисный редактор… отдельный сервер» (assistant research C7) | new Node service, auth, storage | XL |
| `[[wiki-links]]` + `entity_links` + backlinks | missing; `@mentions` planned | cross-domain edge table vs inv. 2 | contracts, every domain or a projection owner | L (M if limited to `@mentions` and links in EDS, ERP and CRM text fields) |
| Hybrid search tsvector + pgvector | **exists** for the bot KB and CRM client docs; ⌘K fans out to the APIs | — | extending to EDS and ERP documents | M–L |
| Files registry with sha256 and versions | **exists** (EDS `files`/`file_versions`; CRM `documents`) | — | — | — |
| File `doc_type`/`status`/`metadata_jsonb`/expiry, `linked_entities` | partly (typed documents per domain) | 18.11 custom fields «не берём»; one owner per field | EDS/ERP models, contracts | M |
| `extracted.md` companion + chunks for every file + OCR | partly (CRM client docs, KB; ERP docx only) | 11.11 «в модель — только текст» argues *for* extending Docling | ERP payloads (B-CAT1-3), EDS files, worker | M |
| `property_definitions` + `custom_props JSONB` + formula | contradicts | 18.11 and ADR-0031 п. 4 «пользовательские поля» не берём; «Формул, скриптов… нет» | — | — (L–XL if reversed) |
| Saved views (table, kanban, calendar, timeline, gallery) as JSON configs + one query engine | partly decided: saved views in the CRM profile (plan line 259); kanban read-only later | 18.11 «Канбан… этап меняется действием с проверками»; group-by not taken; no generic query engine (BFF owns no data) | CRM profile, DataTable, BFF | M for saved views; L–XL for a query engine |
| Generated columns + MVs for funnel and overdue | partly (CRM bot MVs) | — | ГЛ-3 «Сводка» sources | M |
| ClickHouse/DuckDB BI via CDC | missing for business; ClickHouse is Langfuse-only | «свой BI-сервер» not connected; Excel first | infra, a new server | L |
| Outbox + bus | **exists** | — | — | — |
| NATS/Kafka/RabbitMQ | NATS planned (stage F) | ADR-0014 | — | already planned |
| Webhooks HMAC, Idempotency-Key, retries, DLQ | **exist internally**; outbound third-party webhooks missing | inv. 14 «только коннекторами со своей очередью и контейнером» | connector framework (report §9.4 «не оценивалось») | M–L |
| 1C / EDO connectors | planned (Didox after launch; 1C pending the bookkeeper) | connectors README §1 | ERP plus a connector | L each (inference) |
| Telegram Mini App + approve buttons in chat | Mini App code ready; Telegram for decisions decided 22.11 (Главная п. 4) | — | CRM bot, Cabinet | S–M |
| Smart Import (price list, request file) | **exists** | Markdown-note output contradicts the canvas decision | — | — |
| Remote MCP for employees and external agents, 8–15 tools, Resources, Prompts | missing; 4 internal bot servers exist, 13 tools | inv. 4; assistant rules «не даём помощнику действовать самому»; ADR-0005 «Cabinet своего ИИ не имеет» | new service or BFF tier, contracts `mcp-tools.json`, per-user auth | L (read-only) / XL (write) |
| OAuth 2.1 + PKCE + RFC 8707 | missing (HMAC service context) | — (no decision yet) | identity in CRM (ADR-0003), Caddy | L |
| HITL via MCP Elicitation / draft | principle **exists** (EDS `ai_suggestions.decision`, «Похоже:» 20.11, «ничего не записывает сам») | — | — | — |
| Indirect prompt-injection fencing | **exists** in the prompts | — | — | — |
| Audit log of AI calls | **exists** (llm_usage, AICall, ai_suggestions); no diff or rollback | — | — | S–M for diff |
| A2A | missing; no need found | — | — | — |
| Backend in TS (NestJS/Fastify) | contradicts | ADR-0013 п. 1-2: Python/FastAPI, Django in ERP | — | — |
| Next.js front end | wrong for us | ADR-0013 п. 3: Vite SPAs | — | — |
| «100% реализуемо», 4 phases × 4–6 weeks | cannot verify; (inference) underestimates | the report's pace is 3–3.5 PR/day and Q1 is almost full with «Процессы как данные» (52–57 PR) plus the Organizer path (45–100 PR) | — | — |

## 3. Which parts of A target Cabinet, and do they fit

A names `apps/cabinet` as its context (line 3) and puts Tiptap in «Web B2B Cabinet» (line 31, phase 1 line 188: «Встроить редактор Tiptap внутрь карточки сделки (`apps/cabinet`)… команда и клиенты уже получают «магию Notion»»). It also expects the tenant roles client_admin and supplier, the Telegram Mini App, and «Database Views Канбан/Таблица/Документы» in Cabinet.

**Does it fit Cabinet as built? Mostly no.**

1. **Premise outdated.** DECISIONS line 243 (2026-10-31) removed «`SidePeek`, `DealCard`, канбан и `ViewSwitcher`». `docs/systems/cabinet/README.md:89,138`: «Канбана и переключателя видов нет; `?view=…` ведёт на список». The «Legal Eminence» palette and the «сделка = Проект» framing are real (same line).
2. **No backend.** ADR-0004 lines 9-17: Cabinet has none, and its own DB was rejected. «Перевод бэкенда на гибридное MD + JSONB + MCP ядро» therefore means changing the ERP portal API and `portal` app. Cabinet would only get screens.
3. **Client-written notes visible to the team** clash with three things (inference):
   - inv. 5: the client sees only a projection
   - ERP deal `notes` is explicitly «видны только сотрудникам»
   - the client↔company channel already exists as chat (ADR-0023, `portal/messages_views.py`)
   A shared client/staff Markdown note would need a new visibility model per paragraph.
4. **No AI in Cabinet** (ADR-0005 line 13). Client questions go to the CRM agent, which already uses MCP with company-scoped signed context. That is the existing «AI-ready» path for clients.
5. **Isolation already enforced** by the portal session plus negative tests. RLS would add little on one installation and would contradict ADR-0019.

**Parts that do fit Cabinet cheaply:**

| Element | Size |
|---|---|
| Documents tab with typed file metadata such as certificate expiry (via the portal API) | M |
| Telegram approve buttons for ActionRequired | S–M |
| A read-only «по этапам» board, only if clients ask | S |

## 4. What is genuinely worth extracting (for the final version)

Each of these is compatible with the decisions:

- Extend Docling text extraction to PDFs and scans in ERP and EDS (closes B-CAT1-3), with search over document text.
- `@mentions` and object links (already planned, 2 PR) as the minimal «graph». Backlinks could follow later as a CRM- or Platform-owned projection fed by events.
- Saved views on the server (planned).
- Typed metadata on certificates and contracts (expiry date) as contract fields, not JSONB.
- A future employee-facing read-only MCP that runs with the employee's own token through the BFF. It would need an ADR (identity, OAuth, audit) and stay within «код решает, модель предлагает».

Everything else in A either already exists or reverses a recorded owner decision. Each reversal would need an ADR under inv. 10.
