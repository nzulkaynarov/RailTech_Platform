# Волна 8 — Платформа, фаза P1 (F0): каркас, вход через CRM, роли Платформы

Архитектор, 2026-10-22. Основание: SPEC-v3 §5–§6, §10.1, §11.1 F0; ADR-0011; `docs/history/platform/05-plan.md` P1.
Старт — после гейта P0 (волна 7: каркас `web`/`bff`, токены 0.2.0, стенд, CI влиты). Контракт BFF 0.2.0 (смена пароля,
Admin · Оргструктура) — в PR этого runbook'а.

## 0. Промпт лида — одним сообщением

```
Ты — лид разработки RailTech Platform (ORCHESTRATOR §4.1), ведёшь волну 8 «Платформа, фаза P1» по
docs/history/runbooks/wave8-platform-p1.md. Код сам не пишешь. Прочитай: CLAUDE.md корня, docs/ORCHESTRATOR.md (§3, §4.1, §6 «MP», §7),
docs/HANDOFF.md, этот runbook целиком, docs/systems/platform/CONVENTIONS.md, docs/product/SPEC-v3.md (§4–§6, §10.1, §11),
docs/architecture/platform-bff.md, docs/architecture/platform-frontend.md, docs/architecture/integration-map.md (§1.1, §4), docs/architecture/CONTRACTS.md §8, docs/systems/crm/CONVENTIONS.md.
Работай по раундам §2: worktree .claude/worktrees/<задача> от свежего origin/main, зависимости — до запуска исполнителя,
исполнители — субагенты (model sonnet, run_in_background=false) с промптом «преамбула wave7 §3 + раздел §4.x этого runbook'а»,
не больше двух параллельно. Ревью — свежий субагент ≠ исполнитель, по «готово, когда»; экраны — ещё и по чек-листу
docs/architecture/platform-frontend.md §10 (скриншоты рядом с артбордами v3). Перед автослиянием — merge origin/main в ветку,
повтор проверок, для CRM — голова Alembic одна; затем gh pr merge --auto --merge <n>. Перед раундом — одна проверка своих PR
(gh pr view --json state,mergeable,mergeStateStatus,statusCheckRollup, без логов). Общий стенд rt-platform пересобираешь только
ты и только между раундами, если владелец снял заморозку стенда; иначе — проверки в своих проектах compose.
Закрытие: PROGRESS (веха MP) и HANDOFF одним docs-PR; отчёт архитектору — гейт P1: что владелец проверяет сам.
```

## 1. Исходное состояние

- `apps/platform/web` и `apps/platform/bff` — каркасы волны 7; `make check-platform` в CI; `platform.localhost` на стенде.
- Контракт BFF 0.2.0 (`packages/contracts/openapi/platform-bff.yaml`): сессия и смена пароля, `/me`, `/health`, `/menu-counters`,
  `/queue`, `/queue/cards`, `/activity/today`, `/notifications*`, `/search`, `/admin/users*`. Ролевая матрица `packages/contracts/platform-rbac.yaml`.
- CRM: вход `POST /api/v1/auth/login` (access в теле, refresh — cookie `rt_refresh`), `POST /api/v1/auth/refresh`,
  `POST /api/v1/auth/logout`, `GET /api/v1/me`, `POST /api/v1/auth/sso/token` (токен для ERP), `POST /api/v1/auth/change-password`,
  `GET/PATCH /api/v1/users*`, `roles` и `platform_access` у пользователя, `erp_role_codes` (FIX-63).
- ERP: `POST /api/v1/auth/sso/exchange/` (access в теле, refresh — cookie), `POST /api/v1/auth/token/refresh/`,
  `POST /api/v1/auth/logout/`, `GET /api/v1/notifications/`, `PATCH …/mark_read/`, `…/mark_all_read/`,
  `GET /api/v1/crm/quotes/my-approval-queue/`, `GET /api/v1/crm/analytics/search-documents/`, `GET /api/v1/crm/deals/`.

## 2. Раунды

| Раунд | Задачи | Ветки |
|---|---|---|
| 0 | **INF-P1-0** Caddy без зависимости от здоровья Платформы, smoke отката на 4 домена ∥ **W7-T1** хвосты волны 7 (ERP: частичный повтор ротации 422; CRM: `clean_env` в `apps/crm/scripts/ci_local.sh` как в CI) | `mp/inf-p1-0-caddy-decouple`, `mp/w7-t1-tails` |
| 1 | **CRM-01** роли Платформы в CRM ∥ **PLT-12** каркас AppShell на MSW | `mp/crm-01-platform-roles`, `mp/plt-12-app-shell` |
| 2 | **PLT-10** BFF: вход и сессия + **PLT-11** RBAC (один исполнитель, один PR) ∥ **PLT-13** общие компоненты | `mp/plt-10-bff-session`, `mp/plt-13-shared-ui` |
| 3 | **PLT-14** уведомления, поиск, очередь, счётчики (BFF + web) ∥ **PLT-15** Admin · Оргструктура (выдача ролей) | `mp/plt-14-dashboard-feed`, `mp/plt-15-org` |
| 4 | **QA-P1** прогон гейта | `qa/plt-p1-gate` |

## 3. Задачи («готово, когда»)

### 3.0. INF-P1-0 — прод не зависит от здоровья Платформы (срочно, до первого деплоя Платформы)

Зоны: `infra/compose/base.yml`, `infra/compose/prod.yml`, `.github/workflows/deploy.yml` (разрешено владельцем), `infra/deploy/*`.
Caddy зависит от `platform-bff` и `platform-web` по `condition: service_started`, а не `service_healthy` (сбой образа Платформы
даёт 502 только на её домене, CRM, ERP и Cabinet живут); smoke задания отката проверяет те же четыре домена, что и деплой.
Готово, когда: `make deploy-check` зелёный; проверка в проекте compose `-p rt-p1-0`: `platform-bff` с намеренно битой командой
запуска — Caddy поднят, `crm.localhost`/`erp.localhost`/`cabinet.localhost` отвечают, `platform.localhost/api/*` — 502 (вывод в PR).

### 3.0a. W7-T1 — хвосты волны 7

(1) ERP: ротация сопряжения по контракту 0.6.1 — частичное совпадение тройки с действующими значениями → 422
`PAIRING_PARTIAL_REPEAT`, точный повтор последней применённой — 200; тесты на обе ветки. (2) `apps/crm/scripts/ci_local.sh`
`clean_env` (стадии crm-e2e, crm-audit): окружение как в CI (`TELEGRAM_MODE` и прочие переопределения — сверить с `ci.yml`), как
сделано в #146 для integration. Готово, когда: `make check-erp` (ERP_TEST_NS=w7-t1), `scripts/ci_local.sh crm-e2e` зелёные.

### 3.1. CRM-01 — роли Платформы в CRM

Зоны: `apps/crm/backend/**` (модель пользователя, миграция, сервис пользователей, провижининг ERP, `/me`, `/users`), генератор
ролей из контракта, `apps/crm/docs/api/openapi.json` и сгенерированный клиент CRM (как требует `make check-crm`). Фронтенд CRM
**не меняется** (заморожен), кроме перегенерации клиента.

- `users.platform_roles` — массив кодов `MANAGER|DIRECTOR|SUPPLY|ENGINEER|ACCOUNTANT|ADMIN`, уникальные, по умолчанию пусто;
  `users.position` — должность текстом (≤ 120 символов, SPEC-v3 §4.3); одна миграция Alembic.
- Модуль `app/domain/platform_roles_generated.py` генерируется скриптом из `packages/contracts/platform-rbac.yaml`
  (`make -C apps/crm platform-roles`); тест равенства «сгенерированное = контракт».
- Правило: если `platform_roles` не пусто — базовая роль CRM `roles` вычисляется как старшая из `crm_base_role` ролей
  (`admin` > `manager` > `viewer`), `platform_access = ["crm","erp"]`, провижининг ERP получает `role_codes` = объединение
  `erp_role_codes` ролей и права = объединение `erp_extra_permissions` (поверх шаблонов ролей ERP). Пустой список — старое
  поведение (ручные `roles` и `erp_role_codes`).
- API: `PATCH /api/v1/users/{id}` принимает `platform_roles` и `position` (только `admin`), `POST /users` — тоже; `GET /users`,
  `GET /users/{id}`, `GET /me` отдают `platform_roles` и `position`; инвариант «≥ 1 активный admin» учитывает вычисленную роль; аудит изменения ролей.
- Первый администратор из `/setup` получает `platform_roles = [ADMIN]`.

Готово, когда: тесты на каждую роль (базовая роль CRM, `role_codes` и права в провижининге — по таблице контракта), на
объединение двух ролей, на снятие ролей, на «последнего админа»; `make check-crm` и `ci_local.sh crm-integration` зелёные;
голова Alembic одна.

### 3.2. PLT-12 — AppShell и вход (web, на MSW)

Зоны: `apps/platform/web/src/app/**`, `src/shared/ui/` (части каркаса), `src/modules/*/` (заглушки страниц), i18n, e2e.

- Каркас строго по `docs/architecture/platform-frontend.md` §4: рейл 64, подменю 208 со сворачиванием до 0, шапка 56 (крошки, поиск 380 с ⌘K,
  колокольчик, «Скрыть панель / Панель»), основное окно, боковое окно 360 со сворачиванием; состояние панелей по
  пользователю и маршруту в Zustand + `localStorage` (обёрнуто в try/catch) + `?panel=&tab=`; узкие экраны (< 1200 —
  `Drawer` справа, < 768 — нижняя панель модулей и `Drawer` подменю).
- Меню модулей дословно SPEC-v3 §6.2, главные действия модулей — кнопки (пока без действия, `disabled` с подсказкой «появится в
  фазе P2»); маршруты SPEC-v3 §6.3 — страницы-заглушки с `EmptyState` и текстами SPEC-v3 §7.
- Вход: страница «Вход» (e-mail, пароль, ошибки по `Error.code`), смена обязательного пароля (`must_change_password`),
  выход из меню аватара; меню аватара — профиль, смена активной роли, язык ru/uz/en.
- `RequireAccess` по `Me.resources` и `Me.modules`; модули вне роли не рендерятся в рейле; прямой URL — `Forbidden`.
- Данные — сгенерированные хуки и MSW-моки (`GET /me` с ролями из фикстур на каждую из 6 ролей).

Готово, когда: e2e на MSW: вход → `/dashboard/queue`; сворачивание обеих панелей и восстановление после перезагрузки; смена роли
скрывает модули по матрице (на каждую роль); прямой URL скрытого раздела → `Forbidden`; 390 — нижняя панель; axe без нарушений
на 1440, 1280, 390; скриншоты рядом с артбордами «0. Каркас» и «v3 · 1. Dashboard» в PR; `make check-platform` зелёный.

### 3.3. PLT-10 + PLT-11 — BFF: вход, сессия, RBAC (один PR)

Зоны: `apps/platform/bff/**`, генератор RBAC для web (`apps/platform/web/src/app/rbac.generated.ts`).

- Сессия по `docs/architecture/platform-bff.md` §3: `POST /auth/login` → CRM login (refresh-cookie CRM перехватывается и хранится в сессии), CRM
  `/me`, при `platform_access ∋ erp` — CRM `sso/token` → ERP `sso/exchange` (refresh ERP — в сессии); Redis
  `session:<sid>` с TTL `PLATFORM_SESSION_TTL_HOURS`; cookie `rt_pf_session` (HttpOnly, Secure, SameSite=Lax) и `rt_pf_csrf`;
  проверка `X-CSRF-Token` на мутациях; обновление access CRM и ERP по истечении (одна попытка, под блокировкой сессии);
  провал обновления → удаление сессии и 401 `SESSION_EXPIRED`; `POST /auth/logout` гасит обе сессии бэкендов.
- `must_change_password` из CRM — в `Session`; смена пароля — `POST /auth/change-password` BFF → CRM (контракт 0.2.0).
- `GET /me`: профиль CRM + `platform_roles` (CRM-01) → `roles`, `modules`, `resources`, `restricted_fields` по
  `platform-rbac.yaml`; сотрудник без ролей Платформы → 403 `NO_PLATFORM_ROLE` при входе.
- RBAC: генератор из `platform-rbac.yaml` → `app/rbac_generated.py` и `web/src/app/rbac.generated.ts`; зависимость FastAPI
  `require(resource, level)`; утилита вырезания полей с ограничением; **тест на каждую ячейку матрицы** (6 ролей × 15
  разделов) и на объединение ролей; тест «сгенерированное = контракт» для обоих языков.
- Лимиты входа (10 в минуту на IP и e-mail) — Redis; формат ошибок `Error` с `source`; `X-Request-Id` проходит в CRM и ERP.

Готово, когда: тесты с `respx` на вход, обновление токенов, отключённого сотрудника (CRM refresh 401 → 401 `SESSION_EXPIRED`),
CSRF, лимит, сотрудника без ERP-доступа (`sources.erp = not_applicable`); ответы проверяются по схемам `platform-bff.yaml`;
живая проверка: BFF локально (`uv run`) против CRM и ERP стенда — вход тестовым администратором стенда, `GET /me`, выход
(вывод без токенов в PR); `make check-platform` зелёный.

### 3.4. PLT-13 — общие компоненты (web)

Зоны: `apps/platform/web/src/shared/ui/**`, `src/shared/lib/**`.

Компоненты `docs/architecture/platform-frontend.md` §5: `RequestSteps`, `StatusTag` (+ карты статусов SPEC-v3 §2.4 для всех документов),
`ContextPanel`, `Consequence`, `EmptyState`, `QueueList`, `CounterCard`, `History`, `Checklist`, `DocRow`, `DefinitionList`,
`MoneyText`, `SourceBanner`, `Forbidden`; форматирование сумм (`1 234 567 сум`), дат (часовой пояс компании), номеров.

Готово, когда: юнит-тесты на каждый компонент (состояния, `aria`-атрибуты, текст статуса не только цветом); страница-витрина
`/dev/ui` (только в dev-сборке) со всеми компонентами; скриншоты витрины 1440 и 390 в PR; axe без нарушений; размеры и цвета —
по таблицам §4–§5 `docs/architecture/platform-frontend.md` (отличия — списком в PR).

### 3.5. PLT-14 — уведомления, поиск, очередь, счётчики (BFF + web)

Зоны: `apps/platform/bff/app/api/{notifications,search,dashboard}.py` и клиенты, `apps/platform/web/src/modules/dashboard/**`,
`src/features/notifications`, `src/shared/ui` (подключение).

- BFF по `docs/architecture/integration-map.md` §1.1–§1.2, только из существующих источников: уведомления — ERP (`erp:<id>`), CRM-лента пуста
  до CRM-04; поиск — CRM лиды и клиенты, ERP сделки и документы; очередь — MANAGER: CRM `/inbox`; DIRECTOR: ERP
  `my-approval-queue`; остальные роли — пусто; карточки и лента «Сегодня» — из тех же источников и ERP `activity-logs`.
  Частичные данные — `sources`.
- web: Dashboard · Моя очередь (карточки, «Что сделать сейчас», боковое окно «Сегодня · Уведомления»), центр уведомлений
  (popover 400, вкладки, «Отметить все прочитанными»), поиск ⌘K с группами; опрос 30 с и при фокусе.

Готово, когда: тесты BFF на объединение источников и недоступный бэкенд; e2e на MSW: уведомление открывает объект и вкладку
бокового окна; пустая очередь — текст SPEC-v3 §7.1; скриншоты рядом с артбордом «v3 · 1. Dashboard»; axe без нарушений.

### 3.6. PLT-15 — Admin · Оргструктура: сотрудники и выдача ролей

Зависит от CRM-01; контракт — `/admin/users*` BFF 0.2.0. Зоны: `apps/platform/bff/app/api/admin_users.py`,
`apps/platform/web/src/modules/admin/org/**`, `src/features/{invite-employee,assign-role}`.

- Список сотрудников (имя, должность — текст, роли, доступ CRM/ERP, Telegram для уведомлений, статус), карточка сотрудника в
  боковом окне, выдача ролей (несколько), отключение, приглашение по почте (CRM `/users` + `/invite`); только `ADMIN`
  (DIRECTOR — чтение).
- Блок «Что произойдёт» у «Сохранить роли»: «Сотрудник увидит модули …; в ERP получит роли …» (из матрицы).

Готово, когда: e2e: админ выдаёт роль SUPPLY → сотрудник после входа видит только свои модули; снятие последней роли ADMIN у
себя запрещено с понятным текстом; axe; скриншоты 1440/390.

### 3.7. QA-P1 — прогон гейта

На стенде (после пересборки лидом) или на проекте compose с CRM и ERP: вход тремя сотрудниками с разными ролями, каркас,
сворачивание панелей, `Forbidden`, уведомление из ERP, поиск по номеру сделки, Admin · Оргструктура; 1280/1440 без горизонтальной
прокрутки; axe. Отчёт `docs/runbooks/plt_p1_gate_report.md` со скриншотами `docs/screens/plt-p1/`; дефекты одной волной.
