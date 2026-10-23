# Волна 9 — настраиваемые роли Платформы (ADR-0012)

Архитектор, 2026-10-23. Основание: ADR-0012 (роли — данные), решение владельца 2026-10-22 «роли начинать параллельно со
стратегией». Гейт P1 принят владельцем 2026-10-22. Остальная часть P2 (путь заявки) ждёт утверждения стратегии и целевой
архитектуры (шина, отдельный сервис EDS) — в этой волне её не начинаем.

## 0. Промпт лида — одним сообщением

```
Ты — лид разработки RailTech Platform (ORCHESTRATOR §4.1), ведёшь волну 9 «Настраиваемые роли» по docs/runbooks/wave9-roles.md.
Код сам не пишешь. Прочитай: CLAUDE.md корня, docs/ORCHESTRATOR.md (§3, §4.1, §7), docs/HANDOFF.md, docs/adr/0012-configurable-platform-roles.md,
этот runbook целиком, docs/systems/platform/CONVENTIONS.md, docs/architecture/platform-bff.md §6, docs/architecture/integration-map.md §4, docs/architecture/CONTRACTS.md §8,
packages/contracts/platform-rbac.yaml (v1), packages/contracts/openapi/platform-bff.yaml (0.2.4), docs/systems/crm/CONVENTIONS.md.
Порядок: R-1 → R-2 → R-3 (§2). Исполнители — субагенты, worktree .claude/worktrees/<задача> от свежего origin/main, зависимости ставишь ты;
R-1 и R-3 — model "sonnet", R-2 — model "opus" (меняет контракт на обе стороны). Преамбула исполнителя — docs/ORCHESTRATOR.md §4.2 (прежде — wave7 §3)
с подставленными значениями; исключение для R-2: контракт (platform-rbac.yaml v2, platform-bff.yaml 0.3.0) он правит сам по §3.2 этого runbook'а.
Ревью — свежий субагент ≠ исполнитель, по «готово, когда»; экраны — ещё по docs/architecture/platform-frontend.md §10. Перед автослиянием — merge
origin/main, повтор проверок, одна голова Alembic CRM; затем gh pr merge --auto --merge <n>. CI не опрашиваешь, логи CI не читаешь; перед шагом —
одна проверка своих PR (gh pr view --json state,mergeable,mergeStateStatus,statusCheckRollup). После слияния PR — сразу останови исполнителя
(TaskStop), удали worktree, ветку и тестовые контейнеры задачи. Прод не деплоится. Вопросы вне задачи — архитектору сообщением.
Закрытие: docs-PR (PROGRESS — «Веха MP — Платформа», HANDOFF п. 12) и отчёт архитектору: PR, итог R-3, хвосты.
```

## 1. Исходное состояние

- Роли Платформы сейчас — коды: `users.platform_roles` в CRM (JSON-массив `MANAGER|DIRECTOR|SUPPLY|ENGINEER|ACCOUNTANT|ADMIN`,
  миграции 0032–0034), генераторы из `platform-rbac.yaml` v1 в CRM (`app/domain/platform_roles_generated.py`), BFF
  (`app/rbac_generated.py`) и web (`src/app/rbac.generated.ts`), провижининг ERP по `role_codes` + `permissions` (CRM-01).
- Матрица SPEC-v3 §4.2 и пункты меню — `platform-rbac.yaml` v1 (`resources`, `menu`, `restricted_fields`, `roles`).
- Admin · Оргструктура (PLT-15) выдаёт роли кодами; Admin · Ролевая матрица — только просмотр (заглушка P1).

## 2. Задачи и порядок

| Задача | Что | Модель | Ветка |
|---|---|---|---|
| **R-1** | CRM: роли как данные, вычисление прав, API ролей, миграция кодов в данные, провижининг ERP вычисленными правами | sonnet | `mp/r1-crm-roles-data` |
| **R-2** | Контракты (`platform-rbac.yaml` v2, BFF 0.3.0) + BFF + web: RBAC по ролям из CRM, Admin · Ролевая матрица — редактор, Оргструктура — роли из списка | opus | `mp/r2-platform-roles` |
| **R-3** | QA: прогон «роль-универсал» на чистом стенде | sonnet | `qa/r3-roles` |

R-2 начинается после слияния R-1 (берёт API ролей CRM). Если R-1 затягивается, R-2 может начать контракт и web на MSW.

## 3. Задачи («готово, когда»)

### 3.1. R-1 — CRM: роли как данные

Зоны: `apps/crm/backend/**` (модели, миграции, сервисы пользователей и ролей, провижининг ERP, casbin), генератор каталога из
`platform-rbac.yaml` v2 (файл v2 вносит R-2; до его слияния R-1 работает от черновика §3.2, положив его в
`packages/contracts/platform-rbac.yaml` **в своём PR** вместе с генератором CRM — тогда R-2 берёт файл уже из main и обновляет
генераторы BFF и web; согласуй с лидом, кто первым вносит файл, — один PR, не два). Фронтенд CRM заморожен — только перегенерация клиента.

- Таблица `platform_roles`: `id`, `code` (только у системных и созданных из шаблона — `ADMIN`, `DIRECTOR`, `tpl:MANAGER` и т. п.; у
  новых — пусто), `name`, `description`, `is_system`, `access` (JSON: раздел → `full|read`; скрытые не хранятся),
  `restricted_fields` (JSON-массив), `created_by`, `updated_by`, `updated_at`. Связь `user_platform_roles` (многие ко многим).
- Миграция данных: системные роли «Администратор» и «Директор» (матрица — из каталога, неизменна); роли из шаблонов «Менеджер»,
  «Снабженец», «Гл. инженер», «Бухгалтер» (матрица — из шаблонов v2); пользователи с кодами в `users.platform_roles` получают
  соответствующие роли; столбец `users.platform_roles` удаляется второй миграцией после переноса (expand → migrate → contract).
- Вычисление прав сотрудника: объединение `access` всех его ролей (максимум по разделу) и `restricted_fields`. Из каталога v2:
  права CRM (casbin) — по `backend.crm` раздела и уровня; права ERP — по `backend.erp` и `restricted_fields.*.erp`. CRM пишет
  политики casbin на роль (субъект `pr:<id>`) и связи пользователя; базовые роли `admin|manager|viewer` для сотрудников Платформы
  больше не используются (остаются для совместимости старого фронта до T4: вычисляются как раньше — максимум `crm_base` по ролям).
- Провижининг ERP: `permissions` = вычисленный набор, `role_codes = []` для сотрудников с ролями Платформы; пересчёт — задача
  очереди на каждого затронутого сотрудника при изменении роли или выдаче ролей; итог — `erp_sync` в пользователе.
- API (только `admin`): `GET/POST /api/v1/platform-roles`, `GET/PATCH/DELETE /api/v1/platform-roles/{id}`,
  `POST /api/v1/platform-roles/preview` (черновик роли или изменения → сотрудники, разделы получат/потеряют); выдача ролей —
  `PATCH /api/v1/users/{id}` с `platform_role_ids`. Ошибки: системную роль изменить/удалить — 409 `ROLE_SYSTEM`; роль с
  сотрудниками удалить — 409 `ROLE_IN_USE` (с числом); снять последнего администратора или директора — 409 `LAST_ADMIN` /
  `LAST_DIRECTOR`; неизвестный раздел или уровень вне `levels` раздела — 422.
- `users:read` (CRM-01c) — по возможности «Admin · Оргструктура» (`admin` read) из вычисленных прав, а не по коду DIRECTOR.
- Аудит: `platform_role.create|update|delete` с «до/после», выдача ролей — `user.update`.

Готово, когда: тест на каждый элемент каталога (раздел × уровень → ожидаемые права CRM и ERP), на объединение двух ролей, на
миграцию кодов в роли (пользователь с `[MANAGER, ACCOUNTANT]` → две роли, те же права, что до миграции), на 409-ограничения, на
пересчёт провижининга при изменении роли; `make check-crm` и `ci_local.sh crm-integration` (с `ITEST_NS`) зелёные; одна голова Alembic.

### 3.2. Каталог v2 — нормативный черновик (`packages/contracts/platform-rbac.yaml`, version: 2)

Структура (схема `platform-rbac.schema.json` обновляется вместе):

```yaml
version: 2
system_roles:            # неизменны, в интерфейсе не редактируются
  ADMIN:    {name: {ru: Администратор, uz: Administrator, en: Administrator}, access: {admin: full, dashboard.queue: full, chats.internal: full, eds.memo.create: full}, restricted_fields: []}
  DIRECTOR: {name: {ru: Директор, uz: Direktor, en: Director}, access: "<все разделы full, admin: read>", restricted_fields: [cost_margin, supplier_prices]}
templates:               # создаются при первом запуске как обычные роли; дальше — данные
  MANAGER:    {name: {ru: Менеджер, …}, access: <строка MANAGER матрицы v1>, restricted_fields: []}
  SUPPLY:     {name: {ru: Снабженец, …}, access: <SUPPLY v1> + {erp.calc.goods: full}, restricted_fields: [cost_margin, supplier_prices]}
  ENGINEER:   {name: {ru: Гл. инженер, …}, access: <ENGINEER v1> + {erp.calc.services: full}, restricted_fields: []}
  ACCOUNTANT: {name: {ru: Бухгалтер, …}, access: <ACCOUNTANT v1>, restricted_fields: [totals_only, supplier_prices]}
resources:               # ключи v1 сохраняются; добавлены erp.calc.goods и erp.calc.services
  - key: crm.leads
    module: crm
    levels: [read, full]
    label: {…}
    backend:
      crm: {read: [leads:read, stream:read, dashboard:read, kb:read],
            full: [leads:read, leads:take, leads:work, leads:reply, leads:note, leads:assist, leads:create,
                   stream:read, dashboard:read, kb:read, reply_templates:read]}
      erp: {}
  - key: crm.clients
    backend:
      crm: {read: [clients:read, deals:read, documents:read], full: [clients:read, clients:write, deals:read, deals:write, documents:read, documents:write]}
      erp: {full: [deal.manage]}            # «Создать заявку» — передача в ERP
  - key: chats.external
    backend: {crm: {read: [leads:read], full: [leads:read, leads:reply, leads:note, leads:assist]}, erp: {}}
  - key: admin
    backend:
      crm: {read: [users:read, integrations:read, system:read, external_services:read, audit:read],
            full: [users:read, users:write, settings:read, settings:write, integrations:read, integrations:write, models:read,
                   models:test, models:write, system:read, external_services:read, external_services:write, backups:read,
                   backups:write, audit:read, spend:read, kb:read, kb:write, reply_templates:read, reply_templates:write,
                   sandbox:use, export:read]}
      erp: {full: [team.manage, settings.edit, settings.charge_templates]}
  - key: dashboard.summary
    backend: {crm: {read: [dashboard:read, spend:read]}, erp: {full: [data.export]}}
  - key: eds.inbox                          # резолюция
    backend: {crm: {}, erp: {full: [deal.assign]}}
  - key: eds.drafts                         # одобрение КП
    backend: {crm: {}, erp: {full: [quote.review, quote.approve_final, quote.send]}}
  - key: eds.projects
    backend: {crm: {}, erp: {full: [contract.manage, contract.sign, fulfillment.act]}}
  - key: eds.payments
    backend: {crm: {}, erp: {full: [finance.invoice, finance.payment, finance.rates]}}
  - key: erp.calc
    backend: {crm: {}, erp: {full: [deal.manage, quote.build, quote.edit_pricing]}}
  - key: erp.calc.goods                     # виза по товарам и складу (вместо роли SUPPLY в процессе)
    levels: [full]
    backend: {crm: {}, erp: {full: [quote.build, quote.edit_pricing]}}
  - key: erp.calc.services                  # виза по услугам (вместо роли ENGINEER в процессе)
    levels: [full]
    backend: {crm: {}, erp: {full: [quote.build]}}
  - key: erp.stock
    backend: {crm: {}, erp: {full: [catalog.manage, catalog.publish, supply.manage, fulfillment.manage]}}
  # dashboard.queue, eds.memo.create, eds.memo.approve, chats.internal — права бэкендов не нужны до P3 (EDS/чаты — новый сервис)
restricted_fields:
  cost_margin:     {description: {…}, backend: {erp: [quote.view_cost_margin]}}
  supplier_prices: {description: {…}, backend: {erp: []}}     # скрытие — в BFF
  totals_only:     {description: {…}, backend: {erp: []}}
menu: <как v1>
queue:                                      # вид работы → что нужно сотруднику
  answer_lead: {resource: crm.leads, level: full}
  create_request: {resource: crm.clients, level: full}
  resolve_letter: {resource: eds.inbox, level: full}
  approve_quote: {resource: eds.drafts, level: full}
  approve_memo: {resource: eds.memo.approve, level: full}
  calc_task: {resource: erp.calc, level: full}
  confirm_payment: {resource: eds.payments, level: full}
  ticket: {resource: admin, level: full}
  # …остальные виды из QueueItemKind — по тому же правилу
```

Уточнение R-1b (2026-10-23): у `system_roles.DIRECTOR` разделы `crm.leads` и `chats.external` — `read` (остальные бизнес-разделы `full`,
`admin` — `read`); версия роли (`version`) — оптимистическая блокировка PATCH (ADR-0012 п. 2, DECISIONS 2026-10-23).

Правила: каждый код права ERP — из `ErpPermission` контракта шва, каждое право CRM — из каталога `apps/crm/backend/app/security/rbac.py`
(тест в CRM и в contracts); у раздела `levels` по умолчанию `[read, full]`; `system_roles.DIRECTOR` — все разделы `full`, `admin` — `read`.
Исполнитель R-1/R-2 может уточнять отображения, если найдёт расхождение с фактическими проверками прав бэкендов, — с пометкой в PR.

### 3.3. R-2 — контракты, BFF и web

Зоны: `packages/contracts/**` (v2 и 0.3.0), `apps/platform/bff/**`, `apps/platform/web/**`.

- **BFF 0.3.0** (ломающее, до 1.0 допустимо, версия и журнал в описании файла): роль — `RoleRef {id, name, system, code?}`;
  `Me.roles: RoleRef[]`, `Me.active_role: id|null`; `Employee.roles`, `EmployeeInvite.role_ids`, `EmployeeUpdate.role_ids`;
  `/admin/roles` — `GET` (системные и созданные, число сотрудников), `POST`, `GET/PATCH/DELETE /admin/roles/{id}`,
  `POST /admin/roles/preview`; хвосты Q-PLT-15-1 п. 2–5: `POST /admin/users/{id}/invite` (повтор письма без смены пароля),
  `EmployeeUpdate.transfer_to_user_id`, `409 CONFLICT` с `details` (`invite=not_sent`, `user_has_active_leads`, `ROLE_IN_USE`,
  `ROLE_SYSTEM`, `LAST_ADMIN`, `LAST_DIRECTOR`). `QueueItem.role` → `role_id`.
- **BFF**: доступ сотрудника = вычисленные из ролей CRM разделы и поля (не коды); «вид» по активной роли — как в 0.2.2; генератор
  каталога v2 (разделы, меню, очередь, поля) вместо ролей; очередь — по `queue` каталога.
- **web**: Admin · Ролевая матрица — редактор: строки — разделы по модулям, столбцы — роли (системные — только чтение с замком и
  подписью «системная роль»), ячейка — полный / чтение / скрыто (иконки с легендой, «—» цвета `#6e6e6e`), поля с ограничением —
  флажки; «Создать роль» (с нуля или из шаблона), переименование, удаление (только без сотрудников); перед сохранением —
  `Consequence` из `preview`: «N сотрудников получат: …, потеряют: …»; Оргструктура — выбор ролей из списка, названия из данных.

Готово, когда: `make contracts`, `make check-platform` зелёные; тест BFF «права = объединение ролей» и «активная роль — вид»; e2e:
админ создаёт роль «Менеджер и бухгалтер» (CRM-лиды full + Счета и оплаты full), выдаёт сотруднику, тот после входа видит ровно
эти модули и разделы; удаление роли с сотрудниками — понятный отказ; системные роли не редактируются; скриншоты матрицы 1440/1280/390;
axe 0.

### 3.4. R-3 — QA «роль-универсал»

Чистый стенд (`docker compose -p rt-r3`), первый запуск: администратор — роли «Администратор»; создаёт себе «Директор», роль
«Менеджер и бухгалтер», приглашает двух сотрудников; проверка видимости в Платформе, прав в CRM (`/me/permissions`) и ERP (члены
роли «CRM Sync» и её права), изменение роли — пересчёт у обоих сотрудников, удаление роли с сотрудниками — отказ. Отчёт
`docs/runbooks/r3_roles_report.md`, скриншоты `docs/screens/r3-roles/`.
