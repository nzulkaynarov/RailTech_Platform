> **История.** Заменено: docs/HANDOFF.md и docs/PROGRESS.md (волна закрыта); действующие runbook'и волн — docs/runbooks/. Не используется для решений.

# Runbook: волны 3 и 4 — связка CRM ↔ ERP (FIX-30…37) и хвост M1 (FIX-40…44)

Когда применять: волна 2 закрыта (FIX-21…24 влиты, FIX-24 проверен на стенде) и контракт шва 0.2.0 (FIX-29) в `main`.
Источник задач — `docs/audits/2026-10-18-main-e0f089e.md` («Волна 3», «Волна 4»), статусы — `docs/PROGRESS.md`, правила —
`docs/ORCHESTRATOR.md` §3, §4.1, §7 и `CLAUDE.md` корня («Среда разработки, тесты и CI»).

Две волны идут параллельно, **у каждой свой лид** (ORCHESTRATOR §4.1: один лид на волну): волна 3 — сессия Claude Opus,
волна 4 — вторая сессия Claude Opus или Gemini Argon. Исполнители — субагенты Sonnet (у Argon — Flash), по одному на задачу,
каждый в своём `.claude/worktrees/<задача>`. Архитектор принимает итог обеих волн. После волны 3 размораживается M3.

Цели (аудит): волна 3 — «Передать в бэк-офис» идемпотентна, каждое событие доходит один раз и проверяется по
`events.schema.json`, бот отвечает по реальным данным; волна 4 — `erp-internal` из схемы бэкенда, курсы и настройки честные,
dev-команды безопасны.

## 0. Промпты лидов — каждый одним сообщением в своей сессии в корне репозитория

### 0.1. Лид волны 3 (`claude --model opus`)

```
Ты — лид разработки RailTech Platform (ORCHESTRATOR §4.1), ведёшь волну 3 исправлений по аудиту: FIX-30…FIX-37.
Код сам не пишешь — ставишь задачи субагентам-исполнителям, ревьюишь их PR свежим субагентом и ставишь автослияние.

Прочитай: CLAUDE.md корня (раздел «Среда разработки, тесты и CI»), docs/ORCHESTRATOR.md (§3, §4.1, §7), docs/HANDOFF.md,
docs/history/runbooks/wave3-4-agents.md (целиком: §1 факты кода, §2 рабочее место, §3 раскладка, §4 порядок, §5 промпты, §6 цикл),
docs/PROGRESS.md («Исправления по аудиту»), docs/DECISIONS.md (строки 2026-10-19), docs/architecture/CONTRACTS.md §2–§3,
packages/contracts/openapi/erp-integration.yaml и events.schema.json.

Работай по раундам §4. Перед каждым раундом создай worktree задач раунда от свежего origin/main и поставь зависимости (§2).
Исполнителей запускай Agent tool (subagent_type general-purpose, model sonnet, run_in_background true) с промптом
«§5.0 преамбула с подставленными значениями + раздел §5.x задачи». PR исполнителя ревьюй свежим субагентом по «готово,
когда» и чек-листу §6; блокеры — исполнителю одной строкой; без блокеров — `gh pr merge --auto --merge <n>`. CI не
опрашивай; перед следующим раундом один раз проверь свои PR (CLAUDE.md корня п. 4–6: красный «CI ok» или конфликт —
исполнителю чинить локально) и одним docs-PR перенеси их статусы в PROGRESS. Общий бюджет Docker с лидом волны 4 — §2. Закрытие волны: строки FIX-30…37 в PROGRESS «готово» с PR, HANDOFF §3
«волна 3 закрыта, M3 размораживается», хвосты ревью в «Что осталось», один docs-PR на автослиянии; доложи архитектору.
Контракт (packages/contracts) в волне правит только архитектор: расхождение — строка в docs/QUESTIONS.md и реализация по
контракту. Исполнитель PR не сливает; ревьюер ≠ исполнитель; платных вызовов моделей нет.
```

### 0.2. Лид волны 4 (`claude --model opus` во второй сессии, или Gemini Argon — правила те же через `GEMINI.md`)

```
Ты — лид разработки RailTech Platform (ORCHESTRATOR §4.1), ведёшь волну 4 исправлений по аудиту: FIX-40…FIX-44 (хвост M1).
Параллельно идёт волна 3 у другого лида — её файлы (integration/*, CRM) не трогай. Код сам не пишешь.

Прочитай: CLAUDE.md корня, docs/ORCHESTRATOR.md (§3, §4.1, §7), docs/HANDOFF.md, docs/history/runbooks/wave3-4-agents.md (§1, §2, §3, §4
«Волна 4», §5.0, §5.40–§5.44, §6), docs/PROGRESS.md, docs/systems/erp/CONVENTIONS.md.

Работай по раундам §4 «Волна 4»: worktree от свежего origin/main, зависимости (§2), исполнители субагентами (model sonnet;
у Gemini — flash) с промптом «§5.0 + §5.4x», ревью свежим субагентом, `gh pr merge --auto --merge <n>`, CI не опрашивать; перед раундом — одна проверка своих PR и docs-PR со статусами в
PROGRESS (CLAUDE.md корня п. 4–6).
FIX-40 — последним и только после того, как лид волны 3 закроет волну (или по его согласию в журнале PROGRESS): он включает
в CI проверку дрейфа схемы ERP, и любой открытый PR волны 3 после этого обязан перегенерировать schema.json.
Закрытие волны: строки FIX-40…44 «готово» с PR, HANDOFF §3, хвосты в «Что осталось», один docs-PR; доложи архитектору.
```

## 1. Исходное состояние (исследование архитектора, `main` после волны 2 и FIX-29)

Контракт шва 0.2.0 (FIX-29, PR #72): `DealStage` — 11 кодов шкалы CRM; `amount` сделки — сумма последнего КП, отправленного
клиенту, иначе `null` (CRM уже принимает `null`); `/clients/handoff` — поиск по ИНН и 409 `INN_CONFLICT`; статусы строк
поставки + `accepted`/`disputed`; события `delivery.line_accepted|disputed`.

**Волна 3 — факты кода** (пути от `apps/erp/backend` и `apps/crm/backend/app`):
- FIX-30. `integration/services/summary.py` читает несуществующие поля: `c.signed_at` (есть `client_signed_at`,
  `manager_signed_at`), `inv.total_amount`/`inv.paid_amount` (есть `total_incl_vat`, `amount_paid`) → 500 на любой сделке
  со счётом или договором; `exclude(stage__code__in=["won","lost"])` при кодах `CLOSED_WON`/`CLOSED_LOST`
  (`crm/constants.py`); сырой `stage.code` в ответах (`:127, :223, :317`); статусы документов `code.lower()` вне enum;
  `receivables` ищет `PARTIALLY_PAID` при коде `PARTIAL`; `next_delivery` всегда `null` (`except Exception: pass`);
  `amount = deal.total_value` — последняя версия КП в любом статусе. Функция сопоставления стадий одна —
  `integration/services/webhooks.py:map_deal_stage`, её обходят `summary.py`, `mcp/tools.py`, `handoff.py`,
  `serializers.py`. Готовые проекции статусов — `portal/projections.py` (`contract_status`, `invoice_status`, `act_status`,
  `delivery_status`). Тест `integration/tests/test_integration_api.py` сеет несуществующую стадию `quoting`. Проверки
  ответов по `erp-integration.yaml` нет; образец — `portal/tests/contract_support.py` (жёстко на `erp-portal.yaml`).
- FIX-31. `integration/services/handoff.py`: `Deal.create` раньше сопоставления → `request.created` (`signals.py`) и
  `invite.sent` (`portal/services/invitation.py`) отбрасываются в `webhooks.py` (нет сопоставления); `source=crm` нигде не
  ставится (после FIX-23 есть признак `request_origin`); стадия `code="request"` не существует → `None`; `Company.inn`
  уникален, поиска по ИНН нет → IntegrityError 500; согласие игнорируется. CRM: `services/clients.py` зовёт ERP внутри
  `session.begin()` до коммита клиента; ключ идемпотентности — случайный `uuid4` (`integrations/erp.py`).
- FIX-32. `summary.py` (ссылка на документ): URL `…/api/v1/documents/{id}/download/?token=link_{id}` на несуществующий
  маршрут, аудит — только `logger.info`, нет проверки `CrmClientMapping`, `size_bytes` выдуман (`or 1024`); тест
  `integration/tests/test_mcp.py` закрепляет заглушку (`"token=link_" in url`). Можно переиспользовать
  `GeneratedDocument.public_access_token`/`public_token_expires_at` и `portal/public_views.py:PublicDocumentView`; PDF
  договора, счёта и акта — в своих `pdf_file`. Публичный адрес ERP — `FRONTEND_URL` (настройки `ERP_BASE_URL` нет).
- FIX-33. ERP: нет `integration/admin.py`, `redeliver_event` (`integration/tasks.py`) никто не зовёт, нет задачи Beat для
  зависших `PENDING`, нет `visibility_timeout` (`core/settings/infra.py`) при повторах до 24 ч. CRM: Telegram отправляется
  внутри транзакции (`services/erp_events.py`); при сбое постановки строка навсегда `received`; нет сверки
  `client.erp_company_id` с конвертом; `deals.erp_deal_id` не уникален (`models/deals.py`); нет порядка по `occurred_at`;
  тело разбирается до проверки подписи (`api/v1/integrations.py`).
- FIX-34. CRM: `domain/backoffice.py:may_close_locally` нигде не вызывается, `services/leads.py` закрывает `won` в любом
  режиме (запрет только во фронтенде); `decide_handoff` не передаёт клиента, ставшего клиентом в режиме `local`;
  `clients.py` подставляет `consent_given_at or now` и версию `"1.0"` при наличии `lead.consent_version`; тексты бота
  по-русски в коде (`services/erp_events.py`), кнопки «Кабинет» и адреса Cabinet в настройках CRM нет.
- FIX-35. В ERP нет проверки событий по `events.schema.json` и ответов по `erp-integration.yaml`; CRM держит
  `payload: dict[str, Any]` (`schemas/erp_events.py`), модели payload объявлены, но не подключены; примеров событий 6 из 21;
  секрет вебхуков один с каждой стороны (`ERP_WEBHOOK_SECRET`, CRM `erp_webhook_secret`) — ротации нет. Адрес вебхука в
  compose уже исправлен (FIX-01).
- FIX-36. erp-mcp — самописный JSON-RPC во DRF APIView (`integration/mcp/views.py`): зашит `protocolVersion`, неизвестный
  метод → 200, текст исключения уходит модели; схемы инструментов продублированы в `mcp/tools.py`; `create_request` шлёт
  `request.created` дважды (сигнал + явный вызов); режим `prospect` не проверяет `erp_company_id is null`
  (`mcp/context.py`). CRM строит серверы на пакете `mcp` 2.3.0 (`app/mcp/common.py`: `MCPServer`,
  `streamable_http_app(stateless_http=True, json_response=True)`, отдельный uvicorn на сервер). В ERP пакета `mcp` нет
  (`requirements.txt` компилируется pip-compile со сторожем `deps-lock`), `mcp-tools.json` в образ ERP не попадает
  (контекст сборки — `apps/erp/backend`), совместимость с Daphne/lifespan не проверена. Решение владельца 2026-10-18 —
  официальный SDK.
- FIX-37. После FIX-22 строки поставки принимаются/оспариваются клиентом (`sales/models/delivery.py`,
  `portal/views.py`), но ERP событий не шлёт, CRM их не знает (`schemas/erp_events.py: EventType`).
- События ERP: 19 (+2 после FIX-37). `invoice.overdue` не шлётся никогда (статус OVERDUE не ставится), `act.returned` —
  никогда (`reject_act` ставит DRAFT), `document.created` — включая черновики, `quote.sent` читает несуществующее
  `quote.public_token` и зашитый прод-домен, `invoice.*` — ссылка на прод-домен. CRM: `external_stage` перезаписывается
  выводом из события, поэтому `eta_changed` после `paid` откатывает стадию.

**Волна 4 — факты кода** (`apps/erp`):
- FIX-40. `packages/contracts/openapi/erp-internal.yaml` написан вручную (28 путей), `backend/schema.json` — 317 путей
  (`/api/v1` 250, portal 54, integration 12, mcp 1); `erp-internal-full.json` — побайтная копия `schema.json`
  (`apps/erp/Makefile`); `generated/erp-internal.d.ts` никто не импортирует (фронтенд ERP генерирует типы из
  `backend/schema.json`), `docs/systems/erp/CONVENTIONS.md` утверждает обратное; дрейф уже есть (нет `POST /api/portal/v1/auth/magic`);
  CI (`erp`, `scripts/ci_local.sh`) выгрузку spectacular не сверяет.
- FIX-41. `sales/services/quote_fx.py`: договорной курс блокируется только при `frozen_at` (на `PENDING_APPROVAL`/
  `READY_TO_SEND` меняет цену без пересогласования); `finance/services/fx.py`: переменная окружения перебивает настройку
  компании, затем берётся первая попавшаяся `CompanySettings`; второй ручной курс — `core/models/settings.py` (12500),
  `core/views/settings.py`, `frontend/src/store/currencyStore.ts` (`DEFAULT_RATE = 12650`),
  `components/Settings/PlatformSettings.tsx`; фантомное отклонение маржи — `finance/services/margin_deviation.py`
  (округление суммы против суммы по строкам).
- FIX-42. `core/views/settings.py`: `platform_name`, `support_email`, `logo_url`, `domain` доступны на запись; «Перейти в CRM»
  ведёт на `/admin/settings` (`PlatformSettings.tsx`), SPA не получает `CRM_FRONTEND_URL`; `catalog/models/taxonomy.py` —
  `parent` с `CASCADE`; `notify_client_on_schedule_shift` никто не читает; несуществующий код `catalog.edit`
  (`frontend/src/config/settingsSections.tsx`); тестовое письмо без лимита (`notifications/views.py`).
- FIX-43. `crm/management/commands/smoke_full_cycle.py` без проверки `DEBUG`: переписывает курс USD на сегодня, реквизиты
  `own_company()`, делает smoke-менеджера суперпользователем, `--cleanup` удаляет свою компанию; `core_seed` меняет e-mail
  и пароль найденного по username аккаунта; force-эндпоинты (`force-approve`, `force-cancel`, `force_change_stage`) без
  решения.
- FIX-44. Тост «Недостаточно прав»: `frontend/src/components/CRM/QuoteApprovalChain.tsx` зовёт
  `useQuoteApprovalPreview` без проверки `quote.build`; «Maximum update depth» на 390 px —
  `components/QuoteBuilder/QuoteBuilderGrid.tsx` (подозрения: `virtualizer.measure` в эффектах, `useMediaQuery`,
  `useRailState.ts`, `hooks/use-mobile.ts`) — причина не установлена, нужно воспроизвести.

## 2. Рабочее место

Worktree — только `.claude/worktrees/<задача>` (ORCHESTRATOR §4.1); создаёт лид перед раундом от свежего `origin/main`:

```bash
cd "$(git rev-parse --show-toplevel)" && git fetch origin && git worktree prune
git worktree add .claude/worktrees/fix-30 -b fix/erp-30-integration-projections origin/main
# зависимости: make -C apps/erp install | make -C apps/crm install | make -C apps/cabinet install (что правит задача);
# cd packages/contracts && pnpm install --frozen-lockfile
```

Ветки: FIX-30 `fix/erp-30-integration-projections`, FIX-31 `fix/all-31-handoff-idempotent`, FIX-32
`fix/erp-32-signed-document-link`, FIX-33 `fix/all-33-webhook-reliability`, FIX-34 `fix/crm-34-adr0022-backend`, FIX-35
`fix/all-35-seam-contract-tests`, FIX-36 `fix/erp-36-mcp-official-sdk`, FIX-37 `fix/all-37-delivery-line-events`,
FIX-40 `fix/erp-40-internal-schema-generated`, FIX-41 `fix/erp-41-fx-rates`, FIX-42 `fix/erp-42-settings`, FIX-43
`fix/erp-43-safe-dev-commands`, FIX-44 `fix/erp-44-frontend-defects`. `ERP_TEST_NS` = имя worktree (`fix30` …).

**Бюджет Docker (12 ГБ) на обе волны вместе:** одновременно не больше **трёх** наборов тестов ERP (`ERP_TEST_NS`) при
остановленном стенде и не больше **двух** при запущенном. Стенд волнам 3–4 не нужен (проверка глазами — на гейтах),
владелец останавливает его `make down` на время волн. Лиды договариваются через журнал PROGRESS: волна 3 — до двух наборов,
волна 4 — один. Тесты CRM (`make -C apps/crm check`) Postgres не требуют; integration CRM — `scripts/ci_local.sh
crm-integration` (одноразовые контейнеры, считается как набор).

## 3. Раскладка

| Задача | Системы | Размер | Зависит от | Зоны кода | Конфликтует с |
|---|---|---|---|---|---|
| **FIX-30** проекции integration, одна функция стадий, `amount` | ERP | M–L | FIX-29 | `integration/services/{summary,stages(новый),webhooks,handoff (только стадия)}.py`, `integration/serializers.py`, `integration/tests` | 31, 32, 36 |
| **FIX-36** erp-mcp на официальном SDK + хвост FIX-12 | ERP + infra | M–L | — | `integration/mcp/*`, `requirements*.txt`, `core/asgi.py`/`urls.py`, `infra/compose` (если отдельный процесс), Dockerfile ERP (контракт в образ) | 30 (`summary.py` — только чтение) |
| **FIX-34** правила ADR-0022 на бэкенде CRM | CRM | M | — | `domain/backoffice.py`, `services/leads.py`, `services/clients.py` (только согласие и `decide_handoff`), тексты бота → `settings.texts`, `services/erp_events.py` (только тексты и кнопки) | 31, 33, 37 |
| **FIX-31** передача без потерь и дублей | ERP + CRM | M | 30 | ERP `integration/services/handoff.py`, `integration/signals.py`, `parties` (согласие на компании, миграция); CRM `services/clients.py` (порядок коммита и задача), `integrations/erp.py` (ключ) | 30, 33, 34 |
| **FIX-32** подписанная ссылка на документ | ERP | M | 30 | `integration/services/documents_link.py` (новый), публичный маршрут, `integration/tests/test_mcp.py` (снять заглушку) | 30 |
| **FIX-37** события приёмки строк поставки | ERP + CRM | S | 34 | ERP `integration/signals.py`/`webhooks.py` (генерация), CRM `schemas/erp_events.py`, `services/erp_events.py` (обработчик) | 33, 35 |
| **FIX-33** надёжность вебхуков | ERP + CRM | L | 31, 37 | ERP `integration/{admin,tasks,services/webhooks}.py`, `core/settings/infra.py`, Beat; CRM `services/erp_events.py`, `api/v1/integrations.py`, `models/deals.py` (уникальность, миграция Alembic) | 31, 35, 37 |
| **FIX-35** контрактные тесты шва, два секрета | ERP + CRM + infra | M–L | 30, 31, 33, 37 | ERP `integration/tests/contract_support.py` (обобщить портальный), CRM `schemas/erp_events.py` (дискриминированные модели), примеры 21 события, compose/settings (второй секрет) | все задачи волны 3 |
| **FIX-41** курсы | ERP | S–M | — | `sales/services/quote_fx.py`, `finance/services/{fx,margin_deviation}.py`, `core/models/settings.py`, фронтенд `currencyStore.ts`, `PlatformSettings.tsx` | 42 |
| **FIX-43** безопасные dev-команды | ERP | S | — | `crm/management/commands/smoke_full_cycle.py`, `core/management/commands/core_seed.py`, force-эндпоинты (решение — §5.43) | — |
| **FIX-44** два дефекта фронтенда | ERP фронтенд | S | — | `QuoteApprovalChain.tsx`, `QuoteBuilderGrid.tsx` и хуки | 42 (i18n) |
| **FIX-42** настройки | ERP | S | 41 | `core/views/settings.py`, `PlatformSettings.tsx`, `catalog/models/taxonomy.py` (миграция), `settingsSections.tsx`, `notifications/views.py` | 41, 44 |
| **FIX-40** `erp-internal` из схемы бэкенда, дрейф в CI | ERP + infra | M | волна 3 закрыта | `apps/erp/Makefile`, `packages/contracts` (internal), `.github/workflows/ci.yml` (только задание `erp` — по поручению этого runbook'а), `scripts/ci_local.sh`, `docs/systems/erp/CONVENTIONS.md` | все PR ERP |

## 4. Порядок

**Волна 3** (лид 0.1), по раундам; внутри раунда — параллельно:
1. Раунд 1: **FIX-30**, **FIX-36**, **FIX-34** (два набора тестов ERP + CRM без Docker).
2. Раунд 2 (после FIX-30 и FIX-34): **FIX-31**, **FIX-32**, **FIX-37**.
3. Раунд 3 (после FIX-31 и FIX-37): **FIX-33**.
4. Раунд 4 (последним): **FIX-35** — обобщает проверки на всё, что сделали остальные; включает примеры всех 21 события.

Если два готовых PR раунда конфликтуют — второй делает `git merge origin/main` в своём worktree и перегоняет затронутые
тесты (код разрешает исполнитель, не лид); конфликты только в `PROGRESS.md`/`DECISIONS.md` — стопкой (ORCHESTRATOR §4.1).

**Волна 4** (лид 0.2):
1. Раунд 1: **FIX-41**, **FIX-43**, **FIX-44** (один набор тестов ERP за раз; FIX-44 — только vitest/Playwright).
2. Раунд 2: **FIX-42** (после FIX-41).
3. Раунд 3: **FIX-40** — после закрытия волны 3 (иначе каждый PR волны 3 будет перегенерировать `schema.json`); JSON
   `schema.json` при конфликтах **не склеивать** — перегенерировать (`make -C apps/erp openapi`).

## 5. Промпты исполнителей

### 5.0. Общая преамбула (перед каждым промптом задачи)

```
Ты — исполнитель RailTech Platform (ORCHESTRATOR §4.1). Работаешь ТОЛЬКО в worktree {ПУТЬ} (все команды из него), ветка
{ВЕТКА}, одна задача: {ID}. Прочитай: CLAUDE.md корня (раздел «Среда разработки, тесты и CI» — обязателен), docs/ORCHESTRATOR.md
(§3, §7), docs/history/runbooks/wave3-4-agents.md (§1 — факты кода, §3 — твои зоны), docs/audits/2026-10-18-main-e0f089e.md
(задача {ID} и находки {НАХОДКИ}), CLAUDE.md приложений, которые правишь, docs/architecture/CONTRACTS.md и файлы контракта задачи.

Правила, которые не обсуждаются:
- main защищена; PR только из этой ветки; PR не сливаешь — после открытия PR остановись и доложи лиду ссылкой.
- Локальная проверка — основная: итерации затронутыми тестами; перед коммитом make check-<приложение> для каждого
  затронутого; перед push — make ci-local по затронутым заданиям. CI не запускай вручную, не опрашивай и не жди.
- Контракт (packages/contracts) не правишь: он уже 0.2.0 (FIX-29). Расхождение — строка в docs/QUESTIONS.md, делай по контракту.
- Один PR — одна задача; попутных рефакторингов нет. Тест-first: падающий тест на находку → правка; негативные тесты обязательны.
- Секретов нет; тестовые значения явно фейковые. Платных вызовов моделей нет. Стенд make up не трогать.
- Тесты ERP: ERP_TEST_NS={NS} make -C apps/erp test-backend args="<путь> -x -q"; CRM: make -C apps/crm check;
  integration CRM: scripts/ci_local.sh crm-integration. Зависимости уже установлены.
- Миграции: ERP — одна на задачу (makemigrations --check без изменений после неё); CRM — Alembic через skill migration,
  номер после текущей головы, downgrade проверен.
- Параллельно работают: {ПАРАЛЛЕЛЬНО}. Их файлы не трогай. docs/PROGRESS.md не правь — статус, хвосты и вопросы пиши в описание PR (PROGRESS ведёт лид).
- Коммиты: Conventional Commits на русском, суффикс ({ID}), трейлер Co-Authored-By: Claude <noreply@anthropic.com>.
- Финал: gh pr create (заголовок «{ID}: …»; тело — что, почему, как проверить, что обновлено в docs, открытые вопросы),
  ссылка на PR в ответе — и стоп.
```

### 5.30. FIX-30 (ERP) — проекции integration по контракту, одна функция стадий, `amount`

```
Задача FIX-30 (P0, находки I-2, I-3, I-19; хвост FIX-12 — amount): ответы integration и стадии — по erp-integration.yaml 0.2.0.
Готово, когда:
1. Новый модуль integration/services/stages.py — ЕДИНСТВЕННАЯ функция deal_stage(deal) → код DealStage контракта из FSM и
   документов (accepted/invoiced/paid/fulfilment/closing выводятся из КП, счетов, оплат, строк поставки, актов); таблица
   правил в docstring; параметризованный тест на каждую из 11 стадий. map_deal_stage в webhooks.py, summary.py, handoff.py,
   serializers.py используют её (grep stage.code в integration — только в stages.py). mcp/tools.py не трогать (FIX-36), но
   экспортировать функцию так, чтобы FIX-36 её взял.
2. summary.py — на настоящие поля моделей (client_signed_at/manager_signed_at, total_incl_vat, amount_paid, CLOSED_WON/LOST,
   PARTIAL); статусы договора/счёта/акта/строк поставки — через portal/projections.py (те же функции, без копий);
   next_delivery из sales.DeliveryLine без except Exception; amount = сумма последней версии КП в статусах, видимых клиенту
   (SENT, VIEWED, APPROVED/accepted), иначе None — и в ответах, и в DealRef событий (build_deal_ref).
3. Тест-сторож integration/tests/test_contract_integration.py: каждый GET integration по фикстуре «сделка с КП, договором,
   счётом, оплатой, строками поставки, актом» и по пустой сделке валидируется jsonschema по erp-integration.yaml (общий
   загрузчик — вынести из portal/tests/contract_support.py в одно место, портальный сторож не ослаблять); ключи ⊆ properties.
4. test_integration_api.py больше не сеет несуществующих стадий; 500 на сделке со счётом/договором — тест, что 200.
5. make -C apps/erp check зелёный; CRM не трогать (CRM уже принимает amount = null с FIX-29).
PR: «FIX-30: integration по контракту 0.2.0 — одна функция стадий, настоящие поля, amount без черновиков, сторож».
```

### 5.31. FIX-31 (ERP + CRM) — передача без потерь и дублей

```
Задача FIX-31 (P0, находки I-4, I-5, I-20): «Передать в бэк-офис» идемпотентна и ничего не теряет.
Готово, когда:
1. ERP handoff.py: компания ищется по crm_client_id, затем по ИНН; ИНН другой компании с другим crm_client_id → 409
   INN_CONFLICT (ничего не создаётся); CrmClientMapping создаётся ДО сделки; стадия — через stages.py (FIX-30), не code="request";
   request.created уходит с source=crm (через request_origin из FIX-23), invite.sent доходит; согласие (consent.given_at,
   consent.version) сохраняется на компании как пришло — поля и одна миграция в parties; повтор с тем же crm_client_id —
   200 с теми же id, без второй сделки и без вторых событий. Тесты на каждый пункт, включая «два параллельных handoff одного
   клиента» (select_for_update или уникальность).
2. CRM services/clients.py: клиент коммитится первым, передача — задачей Procrastinate после коммита; Idempotency-Key —
   детерминированный от crm_client_id (и версии передачи, если повторная передача по смыслу новая — обоснуй в PR);
   409 INN_CONFLICT → понятная ошибка менеджеру в карточке клиента, без автоповтора; ошибки ERP — в центр внешних сервисов.
   Тесты unit + integration (scripts/ci_local.sh crm-integration).
3. make -C apps/erp check, make -C apps/crm check зелёные; сторож FIX-30 зелёный.
Не трогать: Telegram и надёжность вебхуков (FIX-33), правила ADR-0022 (FIX-34), MCP (FIX-36).
PR: «FIX-31: передача клиента без потерь и дублей — ИНН и 409, сопоставление до сделки, коммит до передачи, ключ от crm_client_id».
```

### 5.32. FIX-32 (ERP) — настоящая подписанная ссылка на документ

```
Задача FIX-32 (P0, находки S-4, I-6): GET /api/integration/v1/documents/{id}/link — по контракту 0.2.0.
Готово, когда:
1. Ссылка ведёт на публичный маршрут ERP (на FRONTEND_URL) с подписанным токеном (подпись — django.core.signing или
   GeneratedDocument.public_access_token с expires_at), TTL 10 минут; вьюха проверяет подпись и срок, отдаёт файл потоком
   (PDF КП, договора, счёта, акта — из их pdf_file/рендера; не готов — 202 + Retry-After, как портал); size_bytes — настоящий
   или поля нет.
2. 404: компания без CrmClientMapping, черновик, внутренний документ, чужая компания; выдача ссылки и каждое скачивание —
   запись в журнале ERP (не logger) с crm_* контекстом из X-CRM-Context.
3. Тесты: подпись подделана → 403/404, срок истёк → 410 или 404 (как решишь — по контракту и в QUESTIONS), черновик → 404,
   без сопоставления → 404, журнал пишется; тест-заглушка test_mcp.py ("token=link_") заменён на проверку настоящей ссылки.
4. make -C apps/erp check зелёный; сторож FIX-30 зелёный.
PR: «FIX-32: подписанная ссылка на документ с TTL 10 минут, проверкой во вьюхе и журналом ERP».
```

### 5.33. FIX-33 (ERP + CRM) — надёжность вебхуков

```
Задача FIX-33 (P1, находки I-7, I-9, I-10, I-11, I-25).
Готово, когда:
1. ERP: журнал доставок в Django admin (integration/admin.py) с действием «Повторить» (redeliver_event); задача Beat
   подбирает зависшие PENDING старше порога и ставит повтор; visibility_timeout брокера ≥ максимального интервала повторов
   (настройка, тест на значение); неизвестная/неподписанная доставка не теряется.
2. CRM: подпись проверяется ДО разбора тела (api/v1/integrations.py); отправка в Telegram — после коммита и по ключу
   события (повтор события не шлёт второе сообщение); строки received, не поставленные в очередь, подбираются задачей;
   сверка client.erp_company_id с envelope.erp_company_id (несовпадение — отклонить и записать); уникальный deals.erp_deal_id
   (миграция Alembic с дедупликацией существующих); события применяются по occurred_at (старое после нового не откатывает
   external_stage — в т.ч. eta_changed после paid).
3. Тесты на каждый пункт (CRM — на настоящей БД через crm-integration); make -C apps/erp check, make -C apps/crm check зелёные.
PR: «FIX-33: надёжные вебхуки — журнал и повтор в ERP, подпись до разбора, Telegram после коммита, порядок по occurred_at».
```

### 5.34. FIX-34 (CRM) — правила ADR-0022 на бэкенде

```
Задача FIX-34 (P1, находки I-8, I-12, I-13, I-14).
Готово, когда:
1. Режим коннектора erp: «Сделка заключена» (won) локально запрещена на бэкенде (domain/backoffice.py:may_close_locally
   вызывается в services/leads.py), ответ 409 с понятным кодом; режим local — как было. Параметризованный тест матрицы режимов.
2. decide_handoff передаёт клиента, ставшего клиентом в режиме local, при переключении на erp (тест).
3. Согласие передаётся честно: given_at и version из лида; нет согласия — передача не выдумывает его (поле по контракту
   обязательно — тогда 422 менеджеру «нет согласия», не подстановка now/«1.0»).
4. Тексты бота по событиям ERP — в settings.texts на ru/uz/en (skill settings-key), кнопки «Открыть КП» (public_url) и
   «Кабинет» (адрес Cabinet — настройка CRM в консоли админа, без .env); тест рендера на каждую локаль.
5. make -C apps/crm check зелёный; OpenAPI CRM перегенерирован, если менялись схемы.
Не трогать: порядок коммита и передачу (FIX-31), доставку и порядок событий (FIX-33).
PR: «FIX-34: правила ADR-0022 на бэкенде CRM, честное согласие, тексты бота в настройках на трёх языках».
```

### 5.35. FIX-35 (ERP + CRM + infra) — контрактные тесты шва и два секрета

```
Задача FIX-35 (P1, находки I-15, I-16, G-5). Последняя в волне 3.
Готово, когда:
1. ERP: каждое отправляемое событие (21 тип) в тестах валидируется по events.schema.json перед отправкой (общий помощник;
   в рантайме — валидация в DEBUG/тестах, в проде — лог при несоответствии); сторож integration (FIX-30) расширен на все пути.
2. CRM: конверт разбирается дискриминированными моделями по event (payload типизирован, schemas/erp_events.py), все 21 событие
   тестируются на настоящей БД (crm-integration); неизвестное событие — 200 с записью «пропущено», не 422.
3. packages/contracts/examples/events — пример на каждое из 21 события (контракт не меняется, только примеры; ajv в make contracts).
4. Ротация секрета вебхуков без простоя: ERP подписывает текущим, CRM принимает текущий и предыдущий (настройки обеих
   сторон через запятую, как сервисные токены); compose и .env.example; тест «старым секретом — принимается до снятия».
5. make contracts, make -C apps/erp check, make -C apps/crm check зелёные.
PR: «FIX-35: контрактные тесты шва — события и ответы по схемам, дискриминированные модели в CRM, ротация секрета вебхуков».
```

### 5.36. FIX-36 (ERP + infra) — erp-mcp на официальном `mcp` SDK

```
Задача FIX-36 (P1, находки S-12, S-13 + хвост FIX-12). Решение владельца 2026-10-18: официальный SDK.
Готово, когда:
1. erp-mcp построен на пакете mcp той же версии, что CRM (2.3.0; app/mcp/common.py в CRM — образец): MCPServer,
   streamable_http (stateless, json_response); отдельный процесс в compose (как crm-mcp-*), внутренний порт, наружу не
   публикуется (FIX-03 — /mcp снаружи 404 остаётся); Django ORM доступен процессу (django.setup()); зависимость добавлена через
   pip-compile, сторож deps-lock зелёный.
2. Схемы инструментов грузятся из mcp-tools.json (копия в образ при сборке или монтирование — опиши в PR), дубля в коде нет;
   тест «инструменты сервера = mcp-tools.json».
3. X-Agent-Context — как после FIX-12 (iat/exp/jti, одноразовость, строгие типы) + prospect требует erp_company_id is null;
   неизвестный метод — ошибка протокола, а не 200; текст исключения модели не уходит (общий код ошибки).
4. Хвост FIX-12: amount в list_client_deals/get_deal_status — из функции FIX-30 (последнее КП, видимое клиенту, иначе null);
   create_request шлёт request.created один раз; стадии — stages.py (FIX-30). Если FIX-30 ещё не влит — сделай пункт 4 после
   его слияния (git merge origin/main), лид скажет.
5. Интеграционный тест через клиент SDK (mcp.Client + streamable_http_client), как CRM: initialize, list_tools, call_tool
   с валидным и невалидным контекстом. Старый APIView и маршрут /mcp/erp удалены; CRM-сторона erp-mcp не подключает (M3-CRM-07).
6. make -C apps/erp check зелёный; make ci-local infra (compose config) зелёный.
PR: «FIX-36: erp-mcp на официальном mcp SDK, схемы из mcp-tools.json, prospect без компании, amount без черновиков».
```

### 5.37. FIX-37 (ERP + CRM) — события приёмки строк поставки

```
Задача FIX-37 (S; контракт FIX-29): ERP шлёт delivery.line_accepted / delivery.line_disputed, CRM их обрабатывает.
Готово, когда:
1. ERP: при accept/dispute строки поставки (сервисы FIX-22) уходит событие по events.schema.json (DeliveryLineDecision,
   actor.type=client с именем контакта, deal — DealRef из FIX-30); тест на валидацию по схеме и на отсутствие события при
   отказе (409).
2. CRM: EventType и модели знают оба события; лента клиента/лида получает запись; при disputed — уведомление ответственному
   менеджеру (как quote.accepted) с замечанием; тесты.
3. make -C apps/erp check, make -C apps/crm check зелёные.
PR: «FIX-37: события приёмки и замечаний по строкам поставки — ERP шлёт, CRM ведёт ленту и уведомляет».
```

### 5.40. FIX-40 (ERP + infra) — `erp-internal` из схемы бэкенда, дрейф в CI

```
Задача FIX-40 (P1, находки F-1, G-4, G-13). Начинать только после закрытия волны 3 (лид скажет).
Готово, когда:
1. packages/contracts/openapi/erp-internal.yaml генерируется из drf-spectacular с фильтром /api/v1 (make -C apps/erp openapi),
   ручной файл и erp-internal-full.json удалены; portal и integration остаются ручными контрактами (их ERP сверяет
   сторожами); redocly проходит (правила redocly.yaml — исключения только обоснованные).
2. Проверка дрейфа: задание erp в .github/workflows/ci.yml и scripts/ci_local.sh перегенерирует schema.json и падает при
   diff (поручение этого runbook'а — единственная разрешённая правка CI в волне); generated/erp-internal.d.ts — либо
   используется фронтендом ERP вместо schema.json, либо удалён (одно из двух, решение в PR).
3. docs/systems/erp/CONVENTIONS.md приведён к факту; make contracts, make -C apps/erp check зелёные; ci-local erp ловит дрейф (покажи в PR).
PR: «FIX-40: erp-internal генерируется из схемы бэкенда, дрейф ловит CI».
```

### 5.41. FIX-41 (ERP) — курсы

```
Задача FIX-41 (P1, находки F-2, F-3, F-12, F-13).
Готово, когда:
1. Договорной курс меняется только в черновике КП; на согласовании и позже — 409 с понятным кодом (или явный возврат в
   черновик с пересогласованием — одно из двух, решение в DECISIONS «по рекомендации»); тесты по статусам.
2. Лимит возраста курса — из настроек своей компании (core.tenant.own_company), переменная окружения — только запасное
   значение, «первая попавшаяся CompanySettings» удалена; тест «две компании».
3. Второго ручного курса нет: SystemSetting-курс, DEFAULT_RATE 12650 и форма в PlatformSettings удалены, источник курса —
   finance.services.fx; миграция данных, если поле удаляется.
4. Отклонение маржи без фантома от округления: сравнение в одной точности (сумма по строкам против суммы по строкам);
   параметризованный тест с «копеечными» кейсами.
5. make -C apps/erp check зелёный.
PR: «FIX-41: курсы — договорной только в черновике, лимит из своей компании, один источник, отклонение без фантома».
```

### 5.42. FIX-42 (ERP) — настройки

```
Задача FIX-42 (P1, находки F-4, F-5, F-6, F-10). После FIX-41.
Готово, когда:
1. Общие для ансамбля поля (platform_name, support_email, logo_url, domain) на бэкенде только для чтения (PATCH → 400/403 с
   кодом), в SPA — только просмотр со ссылкой «Изменить в CRM» на CRM_FRONTEND_URL (отдаётся SPA через /me или настройки).
2. Удаление категории не стирает подкатегории каскадом (PROTECT + понятная ошибка, или перенос на родителя — решение в
   DECISIONS), миграция; тест.
3. notify_client_on_schedule_shift либо работает (читается при сдвиге даты поставки — после FIX-22 есть строки), либо скрыт
   из UI и помечен в DECISIONS; несуществующий код catalog.edit заменён на код каталога прав (accounts/constants.py), тест.
4. Тестовое письмо — лимит частоты (throttle scope), тест 429.
5. make -C apps/erp check зелёный; для UI — скриншоты 1440/390 в docs/screens/fix-42/.
PR: «FIX-42: настройки — общие поля только в CRM, категории без каскада, честный флаг уведомлений, лимит тестового письма».
```

### 5.43. FIX-43 (ERP) — безопасные dev-команды

```
Задача FIX-43 (P1, находки F-8, F-9, F-11).
Готово, когда:
1. smoke_full_cycle запускается только при DEBUG (иначе CommandError); не трогает реальный курс (свой источник «SMOKE» или
   откат), реквизиты own_company (создаёт свою smoke-компанию), не оставляет суперпользователя; --cleanup удаляет только
   созданное командой (по меткам), никогда — свою компанию; тесты на каждый пункт.
2. core_seed не переписывает e-mail/пароль существующих аккаунтов (создаёт недостающих, существующих пропускает с
   сообщением); тест.
3. Force-эндпоинты (force-approve, force-cancel, force_change_stage): решение «по рекомендации» в DECISIONS — оставить только
   администратору (ADMIN_ONLY) с обязательной причиной и записью в журнал; тесты матрицы ролей.
4. make -C apps/erp check зелёный.
PR: «FIX-43: dev-команды безопасны — только в DEBUG, без порчи курса, реквизитов и чужих аккаунтов; force только админу с причиной».
```

### 5.44. FIX-44 (ERP фронтенд) — два дефекта M1-ERP-08

```
Задача FIX-44 (P1, находка F-7).
Готово, когда:
1. QuoteApprovalChain не зовёт предпросмотр согласования без права quote.build (условие в enabled хука по capabilities
   /me); тест Vitest «роль без quote.build — запроса нет, тоста нет».
2. «Maximum update depth» на 390 px в QuoteBuilderGrid воспроизведён тестом (Vitest с шириной 390 или Playwright), причина
   найдена и названа в PR, исправлена; тест зелёный.
3. make -C apps/erp check зелёный; скриншот экрана КП на 390 px без ошибки в docs/screens/fix-44/.
PR: «FIX-44: предпросмотр согласования только с quote.build, без бесконечного цикла рендера на 390 px».
```

## 6. Цикл лида

1. Раунд: worktree и зависимости (§2) → исполнители субагентами с «§5.0 + §5.x» → ждать докладов.
2. Ревью PR свежим субагентом (read-only) по «готово, когда» и чек-листу: контракт не менялся (`git diff origin/main --
   packages/contracts` пуст, кроме примеров событий в FIX-35); негативные тесты; нет правок вне зон §3; `make ci-local` в
   теле PR; статус и хвосты в описании PR, PROGRESS не тронут; миграции — одна на задачу (ERP) / голова Alembic (CRM); для UI — скриншоты. Блокеры —
   исполнителю одной строкой; иначе — `gh pr merge --auto --merge <n>`.
3. CI не опрашивать. Красный CI в PR → исполнитель воспроизводит `make ci-local <задание>` и чинит.
4. После слияния — зависимым исполнителям: «влит FIX-NN, сделай git merge origin/main, перегони затронутые тесты».
5. Убирать worktree влитых задач (`git worktree remove`), ветки удаляет GitHub.
6. Закрытие волны — промпт лида §0, последний абзац.

## 7. Если что-то идёт не так

- Исполнитель «контракт не позволяет» → QUESTIONS и реализация по контракту; контракт меняет архитектор.
- Код 137 у контейнеров тестов → бюджет Docker §2; лиды сверяются через журнал PROGRESS.
- FIX-36 упирается в Daphne/ASGI → отдельный процесс (как CRM), не монтировать в Daphne; решение в PR.
- Два PR одного раунда на `summary.py`/`erp_events.py` → второй делает `git merge origin/main`; рефакторинг файла целиком — нет.
- GitHub не стартует CI («recent account payments have failed…») → владельцу, ветки не трогать.
