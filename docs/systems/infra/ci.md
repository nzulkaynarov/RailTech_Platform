# CI ансамбля — пояснения к `.github/workflows/ci.yml`
Статус: действует · Владелец: лид · Обновлено: 2026-10-28 (D-DOC1: задание rt-docs)

Workflow ансамбля — `.github/workflows/ci.yml` (GitHub читает только корневой `.github/`). Здесь — пояснения. Цель волны 14 — ответ по PR
не дольше 10 минут (`docs/history/runbooks/wave14-speed.md`): задания приложения идут параллельно, а запускается только то, что затронуто правкой.

- **Ссылки на документацию** — `scripts/check-doc-links.sh` в задании gitleaks (DOCS-1): битые ссылки и пути вне `docs/` роняют CI; там же
  `scripts/backlog.py --check` — ID строк `docs/BACKLOG.md` уникальны и по формату (два PR с одним ID git сливает молча; 2026-10-28).
- **Помощь и «Что нового»** (W-REL, 2026-10-28) — там же, в задании gitleaks: `python3 -m unittest discover -s scripts/tests` (сборщик
  «Что нового» `scripts/release_notes.py` и мягкая проверка) и на PR `scripts/help_freshness.py --base origin/<база>` — PR меняет код
  экрана из `screens` статьи `docs/kb/help`, а статью не трогает, или экран менялся без строки «Для пользователей» в описании —
  `::warning::` в логе, не красное. Красное — только новый пункт меню без статьи (`articles.test.ts`, задание Platform).
- **gitleaks** — всегда, по истории ветки, с `.gitleaks.toml` (`legacy/` в allowlist). PR, где изменена только документация (кроме `docs/kb`),
  запускает только его.
- **`ci-ok`** — единственная обязательная проверка для защиты `main`: красная, если любой job упал или отменён; пропущенные (нет изменений) —
  зелёные. Задание есть **на всех событиях** (PR, push в `main`, ночной прогон, ручной запуск): автодеплой (W14-S4) проверяет зелёный
  «CI ok» на sha.
- **Раннер**: переменная репозитория `CI_RUNNER` (Settings → Variables), например `self-hosted`; пусто — `ubuntu-latest`.
- Workflows внутри `apps/crm/.github/` не запускаются (не корень) — их шаги перенесены сюда с `working-directory: apps/crm`.
  Локальный эквивалент всего workflow — `make ci-local` (`scripts/ci_local.sh`, `--full` включает e2e и аудит; уже зелёное на этом дереве
  задание пропускается по штампу `.ci-local/<задание>.ok` — дерево с незакоммиченным, для gitleaks ещё HEAD, для contracts — origin/main;
  `args="--force"` или `CI_LOCAL_FORCE=1` — прогнать заново). CI — финальная проверка
  владельца в чистой среде, один прогон на PR; чинить падение надо локально (CLAUDE.md, «Среда разработки, тесты и CI»).

## События: что и когда идёт

| Событие | Что запускается |
|---|---|
| `pull_request` (не черновик) | Задания по путям изменённых файлов (таблица ниже), включая тяжёлые. Новый коммит отменяет устаревший прогон этого PR |
| `push` в `main` (после слияния) | Только **быстрые** задания по файлам с прошлого коммита `main`: lint и unit (CRM, Platform check, Cabinet, EDS, rt-bus, ERP lint & vitest), миграции и дрейф схемы ERP, `contracts` (совместимость — с коммитом `main` до push), `infra`, gitleaks, `CPU qemu64` при правке Dockerfile/зависимостей/infra. **Не идут:** CRM integration, build, e2e и аудит зависимостей, ERP pytest, Platform e2e — они уже прошли на PR, а полностью проходят ночью. `CI ok` есть. Группа concurrency — на каждый sha, прогон не отменяется следующим слиянием |
| `schedule` (ежесуточно, 01:17 UTC) | **Полный** прогон всех заданий без фильтров, включая тяжёлые и 11 образов под qemu64. Отдельная группа concurrency: не теряется из-за слияний |
| `workflow_dispatch` | То же, что ночной: полный прогон, вручную |

Красный ночной прогон — задача на починку в тот же день: тяжёлые проверки на `main` иначе не ловятся (на push их нет).

## Правка → какие задания

Фильтры `dorny/paths-filter` в задании `changes` (`ci.yml`). Для каждого файла `packages/contracts` указаны **потребители** — приложения, чей код,
тесты, генератор или образ его читают (проверено по коду: тесты-сторожа контракта, генераторы клиентов, Dockerfile с контекстом `contracts`,
compose). Задание `packages · contracts` идёт на любую правку `packages/**`. `*` — тяжёлое задание (не идёт на push в `main`).

| Что изменено | Какие задания |
|---|---|
| Только `docs/**` (кроме `docs/kb`) | gitleaks (с проверкой ссылок) |
| `docs/kb/**` | + CRM, Platform (справку формата читают тесты CRM и `kbDocs.test`) |
| `apps/crm/**` | CRM: lint, unit, integration\*, build\*, e2e\*, аудит зависимостей\* |
| `apps/erp/**` | ERP: lint & vitest, миграции и схема, pytest\* |
| `apps/cabinet/**` | Cabinet |
| `apps/platform/**` | Platform check, e2e\* (3 шарда) |
| `apps/eds/**` | EDS |
| `packages/rt-bus/**` | rt-bus, contracts, CRM, ERP, EDS, Platform (библиотека вшита в образы) |
| `packages/rt-docs/**` | rt-docs\*, contracts (пакет пока не вшит в образы; EDS и ERP подключат его в D-DOC2, D-DOC3 — тогда их фильтры получат путь) |
| `packages/ui-tokens/**` | contracts, CRM, ERP, Cabinet, Platform |
| `packages/contracts/openapi/crm.yaml` | contracts, CRM, Cabinet (типы формы лида), Platform (модели CRM в BFF). **ERP не запускается** |
| `…/openapi/erp-portal.yaml` | contracts, ERP, Cabinet |
| `…/openapi/erp-integration.yaml` | contracts, ERP, CRM (клиент ERP) |
| `…/openapi/erp-internal.yaml` | contracts, ERP (выгрузка из кода, `openapi-check`) |
| `…/openapi/platform-bff.yaml` | contracts, Platform, CRM (тест ролей читает OpenAPI BFF) |
| `…/openapi/eds.yaml` | contracts, EDS, Platform (клиент EDS), CRM (снимок прав EDS) |
| `…/platform-rbac*` (`platform-rbac.yaml`, `platform-rbac.schema.json`) | contracts, CRM (генератор ролей, тесты читают и схему), Platform (матрица, меню, генератор) |
| `…/mcp-tools.json` | contracts, CRM (инструменты агента), ERP (MCP-сервер) |
| `…/events/**`, `…/bus/**` | contracts, rt-bus, CRM, ERP, EDS, Platform (схемы и подписки читает каждый участник шины и вшивает в образ) |
| `…/examples/pairing-bootstrap.json` | contracts, CRM, ERP |
| `…/documents/**` | contracts (ajv, `test_documents.py`, `documents_compat`), rt-docs\* (схема и примеры — тестовые данные пакета) |
| `…/generated/python/**` | contracts, CRM, EDS (`rt_contracts` — path-зависимость) |
| Прочее в `packages/contracts` (`client-statuses.*`, `mcp-tools.schema.json`, `examples/webhook-signature-v2.json`, `generated/*.d.ts`, `generated/crm/**`, `Makefile`, `scripts`, `tests`, `redocly*`, lock-файлы) | только contracts |
| `infra/**`, `scripts/**`, `Makefile`, `.env.example` | infra (compose, caddy) |
| `.github/workflows/**` | infra; `ci.yml` и `deploy.yml` — ещё «CPU qemu64 · таблица правил» (лёгкая сверка, без образов) |
| `**/Dockerfile*`, `uv.lock` / `pyproject.toml` CRM, BFF, EDS, `requirements*` ERP, nginx, `infra/ai/litellm`, `infra/db`, `infra/compose`, `infra/deploy/cpu-baseline-*`, `scripts/qemu_cpu_check.sh` | CPU qemu64: таблица правил, механика, **11 образов** |

Принципы карты: пропущенный потребитель опаснее лишнего задания — новый читатель файла контракта сразу добавляется в фильтр потребителя;
`client-statuses.yaml` сейчас не читает ни одно приложение (grep), поэтому ни одно приложение на его правку не запускается. Фильтры — в
`ci.yml`, комментарии рядом с ними объясняют читателей.

Ни `ci.yml`, ни `deploy.yml` не меняют содержимое образов, поэтому их правка больше не запускает 11 образов под qemu (раньше — десятки
минут на каждую правку workflow): остаётся сверка таблицы правил (`infra/deploy/tests/cpu-baseline-test.sh`). Образы собираются и стартуют
под qemu64 при правке того, что их формирует, и каждую ночь.

## Параллельность и критический путь PR

- CRM: lint, unit, integration, build, e2e и аудит стартуют сразу после `changes`; раньше integration/build/e2e ждали lint и unit (+3–5 минут
  к каждому PR ради экономии минут runner'а при красном lint — цель волны другая: время ответа).
- ERP: три параллельных задания вместо одного `make check-erp` — «lint & vitest» (`make -C apps/erp lint test-frontend`), «pytest»
  (`make -C apps/erp test-backend`), «миграции и схема» (`--migration-check`, `openapi-check`). Критический путь — pytest.
- Platform: e2e не ждёт `Platform · check` (BFF не нужен).
- rt-docs (D-DOC1, подключено с разрешения владельца 2026-10-28): ruff и mypy на раннере, pytest — в одноразовом контейнере
  `packages/rt-docs/docker/test.Dockerfile` (pango, harfbuzz; базовый образ по digest; сеть выключена), тот же образ, что локально, —
  число страниц эталонов совпадает. Тяжёлое: на push в `main` не идёт (сборка образа ≈ 1–2 мин), только на PR, ночью и вручную.
- rt-bus: три прогона pytest (ядро + SQLAlchemy, Django на psycopg2, Django на psycopg 3) идут одновременно на одном PostgreSQL в
  непересекающихся базах (`rt_bus_sa`, `rt_bus_dj_psycopg2`, `rt_bus_dj_psycopg`); вывод печатается по завершении, код выхода — провал любого.

## E2E Платформы (Playwright + axe на MSW)

- Сервер — **сборка**, а не dev-сервер: `vite build --mode mock` (≈1 с, `NODE_ENV=development`, чтобы оставались мокирование MSW и витрина
  `/dev/ui`) и `vite preview`; воркер MSW кладёт в сборку `vite.config.ts` только в режиме `mock`, боевая сборка не меняется.
  `E2E_DEV=1` возвращает dev-сервер (отладка с HMR).
- **Три шарда** (`playwright test --shard=i/3`, matrix в `ci.yml`), по два воркера на шард; отчёт упавшего шарда — артефакт
  `platform-playwright-report-<i>`.
- Проект `mobile` (390) гоняет **только** сценарии с тегом `@mobile` — экраны с адаптивной логикой (нижняя панель и Drawer, центр
  уведомлений, поиск). Остальное — на десктопе (ширины в сценариях задаёт `setViewportSize`). Новый сценарий на узкий экран — `test(…, { tag: "@mobile" }, …)`.
- **Повторов нет** (`retries: 0` и в CI): «flaky» — красный тест. Типовые причины прошлых красных прогонов: (1) дубль столбца-черновика сразу
  после создания роли (исправлено в `RolesPage.tsx`), (2) `getByText("Пробел закрыт")` без `exact` совпадал ещё и с тостом
  «Документ добавлен, пробел закрыт — …» предыдущего шага (strict mode violation на медленном раннере). Локально: `E2E_PORT=<порт> make -C
  apps/platform e2e`; весь набор ≈ 2,5 минуты при двух воркерах.

## Прочее

- **Матрица по путям** до волны 14 была грубее (`packages/contracts/**` во всех приложениях, `ci.yml` запускал qemu-образы); история решений —
  `docs/history/runbooks/wave14-speed.md`.
- Актуально: GitHub Actions работают (прежняя блокировка биллингом, Q-10, снята); `make ci-local` остаётся локальным аналогом workflow.
- **CI → деплой** (W14-S4): `.github/workflows/deploy.yml` стартует по `workflow_run` после успешного workflow «CI» на push в `main` (schedule, ручной запуск CI, красный CI и запуски из форков не деплоят), на том же sha ещё раз проверяет зелёную проверку «CI ok» (`checks: read`) и входит ли sha в `main`, собирает образы параллельно и ждёт одобрения владельца в environment `production`. Порядок и режимы (в том числе `build` — сборка без выкладки) — `docs/runbooks/deploy.md` §2.
