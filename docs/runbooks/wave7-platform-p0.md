# Волна 7 — Платформа, фаза P0 (подготовка): токены, каркас web и bff, стенд, CI, прод

Архитектор, 2026-10-22. Основание: SPEC-v3 и ответы владельца «на все да» (DECISIONS 2026-10-22), ADR-0011 (accepted),
`apps/platform/docs/05-plan.md` P0. Контракты v0 (INF-P0-1) сделал архитектор: `packages/contracts/openapi/platform-bff.yaml`
0.1.0, `platform-rbac.yaml`, `client-statuses.yaml` (PR #140). Владелец **разрешил** правку `.github/workflows/ci.yml`,
`scripts/ci_local.sh`, `.github/workflows/deploy.yml` и деплоя под Платформу (DECISIONS 2026-10-22, п. 10).

## 0. Промпт лида — одним сообщением

```
Ты — лид разработки RailTech Platform (ORCHESTRATOR §4.1), ведёшь волну 7 «Платформа, фаза P0» по
docs/runbooks/wave7-platform-p0.md. Код сам не пишешь. Прочитай: CLAUDE.md корня, ORCHESTRATOR.md (§3, §4.1, §6 «MP», §7),
docs/HANDOFF.md, этот runbook целиком, apps/platform/CLAUDE.md, apps/platform/docs/02-architecture.md, 03-frontend.md,
05-plan.md (P0), docs/CONTRACTS.md §8, packages/ui-tokens/README.md.
Старт — когда PR #140 влит в main (git ls-remote origin main + наличие packages/contracts/openapi/platform-bff.yaml).
Работай по раундам §2: worktree .claude/worktrees/<задача> от свежего origin/main, зависимости ставишь до запуска
исполнителя, исполнители — субагенты (model sonnet, run_in_background=false) с промптом «преамбула §3 с подставленными
значениями + раздел §4.x». Ревью — свежим субагентом ≠ исполнителю, строго по «готово, когда». Перед автослиянием — merge
origin/main в ветку и повтор проверок задачи; затем gh pr merge --auto --merge <n>. Перед раундом — одна проверка своих PR
(gh pr view <n> --json state,mergeable,mergeStateStatus,statusCheckRollup, без логов). Общий стенд rt-platform не пересобирай
и .env не трогай (§1). PROGRESS ведёшь ты — один docs-PR после волны: строки INF-P0-2…6 с PR.
Закрытие: отчёт архитектору — что влито, что осталось владельцу (DNS, деплой), хвосты и вопросы.
```

## 1. Исходное состояние и правила волны

- `main` после #137 (аудит) и #140 (документы и контракты Платформы). Волна 6 закрывает FIX-65 (#128) — её файлы
  (`apps/erp/**` мастер компании, `infra/.env.prod.example`) не трогаем без нужды; конфликт — merge `origin/main` в ветку.
- Фронтенды `apps/crm/frontend` и `apps/erp/frontend` **заморожены** (ADR-0011): в этой волне меняются только сгенерированные
  токены CRM (`src/app/tokens.generated.ts`) задачей INF-P0-2.
- Общий стенд `rt-platform` (порт 8088) не пересобирается: проверка сервисов Платформы — на отдельном проекте compose
  `-p rt-p0-<задача>` только с нужными сервисами (`redis`, `platform-bff`, `platform-web`, `caddy`); без CRM и ERP BFF отвечает
  `/api/v1/health` = 200 со `status: degraded` — это норма проверки P0.
- Репозиторий временно публичный: никаких реальных имён, ИНН, токенов, адресов серверов в коде и PR.
- Прод не деплоится в этой волне: деплой запускает владелец после DNS `platform.railtech.uz`.

## 2. Раунды

| Раунд | Задачи (параллельно) | Ветки |
|---|---|---|
| 1 | **INF-P0-2** токены 0.2.0 ∥ **INF-P0-3** каркас `web` и `bff` | `mp/inf-p0-2-ui-tokens-v02`, `mp/plt-p0-3-skeleton` |
| 2 | **INF-P0-4** дев-стенд ∥ **INF-P0-6** CI и `ci_local` | `mp/inf-p0-4-dev-stand`, `mp/inf-p0-6-ci` |
| 3 | **INF-P0-5** прод: Caddy, compose, образы, деплой | `mp/inf-p0-5-prod` |

Префикс веток `mp` — веха MP (Платформа) по ORCHESTRATOR §6; `ERP_TEST_NS` не нужен (ERP не тестируется).

## 3. Преамбула исполнителя

```
Ты — исполнитель RailTech Platform (ORCHESTRATOR §4.1). Работаешь ТОЛЬКО в worktree {ПУТЬ} (все команды из него), ветка
{ВЕТКА}, одна задача: {ID}. Прочитай: CLAUDE.md корня (раздел «Среда разработки, тесты и CI» обязателен), ORCHESTRATOR.md
(§3, §7), docs/runbooks/wave7-platform-p0.md (§1 и свой раздел §4), apps/platform/CLAUDE.md, apps/platform/docs/02-architecture.md
и 03-frontend.md, CLAUDE.md приложений, которые правишь.

Правила, которые не обсуждаются:
- main защищена; PR только из этой ветки; PR не сливаешь — после открытия PR остановись и доложи лиду ссылкой.
- Локальная проверка — основная: перед push — проверки из «готово, когда» и make ci-local по затронутым заданиям. CI не
  запускай, не опрашивай и не жди.
- Контракт (packages/contracts) не правишь; расхождение — строка в docs/QUESTIONS.md и в описании PR.
- Общий стенд rt-platform не трогаешь (make up/down, .env); свои контейнеры — только в проекте compose -p rt-p0-{ID}, после
  проверки docker compose -p rt-p0-{ID} down -v.
- Секретов, реальных имён и адресов серверов в репозитории нет; демо-данные вымышленные.
- Параллельно работают: {ПАРАЛЛЕЛЬНО}. Их файлы не трогай. docs/PROGRESS.md не правь.
- Коммиты: Conventional Commits на русском, суффикс ({ID}), трейлер Co-Authored-By: Claude <noreply@anthropic.com>.
- Финал: gh pr create (заголовок «{ID}: …»; тело — что, как проверено, скриншоты, открытые вопросы), ссылка — и стоп.
```

## 4. Задачи («готово, когда»)

### 4.2. INF-P0-2 — `packages/ui-tokens` 0.2.0 по SPEC-v3 §5.2

Зоны: `packages/ui-tokens/**`, сгенерированные файлы тем: `apps/crm/frontend/src/app/tokens.generated.ts`, CSS токенов Cabinet и
ERP, которые строит `make tokens`; тесты контраста. Экраны CRM и ERP не правятся.

- `tokens.json` → версия 0.2.0, значения таблицы `apps/platform/docs/03-frontend.md` §3: primary `#1668dc` (hover `#1677ff`,
  bg `#e6f4ff`, text `#0958d9`); success `#52c41a` / текст `#237804`; warning `#faad14` / текст `#874d00`; error `#ff4d4f` /
  текст `#a8071a`; теги purple `#531dab`, cyan `#006d75`; текст `#1f1f1f` / `#595959` / `#767676`; рамки `#d9d9d9` /
  `#f0f0f0`; фон `#f5f5f5` / `#ffffff`; радиусы 6 и 8; шрифт `Inter, -apple-system, "Segoe UI", Roboto, Arial, sans-serif`.
- Для Ant Design текст ошибок, предупреждений и успеха задаётся явно (`colorErrorText`, `colorWarningText`,
  `colorSuccessText` = значения «текст»): затравочные `#ff4d4f`, `#faad14`, `#52c41a` на белом не проходят 4.5:1 и не должны
  попадать в текст.
- Файлы шрифта в пакет не кладутся: Inter подключают приложения пакетом `@fontsource-variable/inter` (Платформа — INF-P0-3,
  Cabinet — позже в CAB-03). Без шрифта стек падает на системный.
- Новые выходы `build.mjs` для Платформы: `dist/antd.ts` уже подходит; добавить экспорт компонентных токенов
  (`03-frontend.md` §3, таблица «Компонентные токены»), если генератор их держит, иначе — в INF-P0-3 в `theme.ts` Платформы.

Готово, когда: `make -C packages/ui-tokens check`, `make check-crm`, `make check-cabinet`, `make check-erp` (только фронтенд-часть,
если полная долгая — `cd apps/erp/frontend && npm run test` и `npm run typecheck`) зелёные; тест контраста ui-tokens проверяет
каждую пару «текст / фон» ≥ 4.5:1; в PR — таблица «было → стало» и скриншоты входа Cabinet 1440 и 390 (MSW-режим Cabinet, без
стенда).

### 4.3. INF-P0-3 — каркас `apps/platform/web` и `apps/platform/bff`

Зоны: `apps/platform/web/**`, `apps/platform/bff/**`, `apps/platform/Makefile`, корневой `Makefile` (цель `check-platform` и её
вызов из `check`), `.gitignore`/`.dockerignore` при необходимости.

**web** (pnpm 10, как CRM): Vite 8, React 18.3, TypeScript ~5.9, antd ^5.29, `@ant-design/pro-components` ^2,
`@ant-design/icons` ^5, react-router ^7, `@tanstack/react-query` ^5, zustand ^5, i18next + react-i18next (ru — по умолчанию,
uz, en), `@fontsource-variable/inter`, orval (хуки TanStack Query и MSW-моки из `packages/contracts/openapi/platform-bff.yaml`
в `src/shared/api/generated/`), msw, Vitest + Testing Library, Playwright + `@axe-core/playwright`, eslint
(typescript-eslint, react-hooks), prettier. Структура каталогов — `03-frontend.md` §2. Тема `src/app/theme.ts` — как
`apps/crm/frontend/src/app/theme.ts` (`cssVar`, токены из ui-tokens через генерацию, компонентные токены §3). В каркасе:
провайдеры (Query, ConfigProvider с ru-локалью antd, i18n), роутер с маршрутом `/` → страница-заглушка «Платформа — каркас P0»
с вызовом `getHealth` через сгенерированный хук и выводом статуса; тест рендера; e2e-тест Playwright, открывающий
страницу на MSW, и проверка axe. `pnpm gen:api` и проверка «сгенерированный клиент свеж» (как `openapi-check` CRM).
`Dockerfile`: `node:22-slim` build → `caddy:2.11.7-alpine` со статикой (образец — `apps/crm/frontend/Dockerfile` и его
`Caddyfile`: SPA-фолбэк на `index.html`).

**bff** (как `apps/crm/backend`): Python 3.12, uv (версия — как в `apps/crm/backend/Dockerfile`), FastAPI, uvicorn, httpx,
pydantic v2 + pydantic-settings, redis (asyncio), structlog; dev — ruff, mypy strict, pytest, pytest-asyncio, respx.
Структура: `app/main.py` (приложение, префикс `/api/v1`), `app/config.py` (переменные `PLATFORM_CRM_URL`,
`PLATFORM_ERP_URL`, `REDIS_URL`, `PLATFORM_SESSION_TTL_HOURS`, `LOG_LEVEL`), `app/api/health.py`, `app/clients/` (пустые
httpx-клиенты CRM и ERP с таймаутом 3 с и пробросом `X-Request-Id`), `app/errors.py` (формат `Error` контракта), `tests/`.
`GET /api/v1/health` по контракту: проверяет Redis (`PING`), CRM `/health`, ERP `/health` параллельно; 200 всегда, `status:
ok|degraded`. Тест: ответ `/health` проверяется по схеме `Health` из `platform-bff.yaml` (чтение YAML и `jsonschema`), все три
комбинации ok/fail. `Dockerfile` — по образцу `apps/crm/backend/Dockerfile` (тот же базовый образ `python:3.12-slim-trixie`,
uv из того же образа), запуск `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`.

**Makefile**: `apps/platform/Makefile` с целями `install` (web — `pnpm install --frozen-lockfile`, bff — `uv sync --frozen`),
`check` (web: lint, typecheck, test, проверка свежести API-клиента; bff: ruff check, ruff format --check, mypy, pytest),
`gen-api`, `e2e`; корень: `check-platform` и добавление в `check`.

Готово, когда: `make -C apps/platform install && make check-platform` зелёные; `make contracts` зелёный; `docker build`
обоих образов проходит локально; `docker run` образа bff отвечает на `/api/v1/health` 200 `degraded` без CRM и ERP;
скриншот страницы-заглушки web 1440 в PR; `apps/platform/CLAUDE.md` §3 — команды актуальны.

### 4.4. INF-P0-4 — дев-стенд Платформы

Зависит от INF-P0-3. Зоны: `infra/compose/base.yml` (и `dev.yml`, если сервисы там), `infra/caddy/Caddyfile.dev`,
`.env.example`, корневой `Makefile` (`smoke`), `docs/runbooks/stand.md`.

- Сервисы `platform-bff` (сборка `apps/platform/bff`, `PLATFORM_CRM_URL=http://crm-api:8000`,
  `PLATFORM_ERP_URL=http://erp-backend:8000`, `REDIS_URL` с паролем Redis, healthcheck `/api/v1/health`) и `platform-web`
  (сборка `apps/platform/web`).
- Caddy dev: сайт `platform.localhost` — `/api/*` → `platform-bff:8000` (`flush_interval -1`), остальное → `platform-web`;
  заголовки безопасности и CSP как у CRM; `no_mcp`.
- `.env.example`: `PLATFORM_SESSION_TTL_HOURS` с комментарием; `make smoke` проверяет `platform.localhost/api/v1/health` и `/`.
- `docs/runbooks/stand.md`: адрес Платформы на стенде.

Готово, когда: `docker compose -p rt-p0-inf-p0-4 … up` только `redis`, `platform-bff`, `platform-web`, `caddy` — `curl` по
`platform.localhost:<порт>/api/v1/health` 200 и `/` 200 (вывод в PR); `make -C infra check` или задание `infra` в `ci_local`
зелёное; общий стенд не пересобирался.

### 4.6. INF-P0-6 — CI и `ci_local` для Платформы (разрешено владельцем 2026-10-22)

Зависит от INF-P0-3. Зоны: `.github/workflows/ci.yml`, `scripts/ci_local.sh`.

- Фильтр путей `platform`: `apps/platform/**`, `packages/contracts/openapi/platform-bff.yaml`, `packages/contracts/platform-rbac.yaml`,
  `packages/contracts/client-statuses.yaml`, `packages/ui-tokens/**`.
- Задание «Platform · check»: pnpm и uv с кэшем по lock-файлам (как CRM), `make -C apps/platform install`, `make check-platform`;
  e2e Платформы — отдельным шагом с Playwright, как CRM e2e (или в задании `--full`, если долго).
- Задание входит в итоговый «CI ok» (needs и проверка результата — как у остальных).
- `scripts/ci_local.sh`: стадия `platform` в списке по умолчанию и в `--quick`.

Готово, когда: `scripts/ci_local.sh platform` и `make ci-local args="--quick"` зелёные; `actionlint` (есть в `make deploy-check`)
без ошибок; в PR — пояснение, какие пути запускают задание.

### 4.5. INF-P0-5 — прод: домен, compose, образы, деплой

Зависит от INF-P0-4 и INF-P0-6. Зоны: `infra/caddy/Caddyfile.prod`, `infra/compose/prod.yml`, `infra/.env.prod.example`,
`.github/workflows/deploy.yml` (и workflow сборки образов, если отдельный), `infra/deploy/*`, `docs/runbooks/deploy.md`.

- Caddy prod: сайт `{$PLATFORM_DOMAIN}` по образцу `{$CRM_DOMAIN}`; переменная `PLATFORM_DOMAIN` в `prod.yml` для Caddy и в
  `.env.prod.example` (`platform.railtech.uz`).
- `prod.yml`: `platform-bff` и `platform-web` из GHCR `rt-platform-bff`, `rt-platform-web` по `RT_IMAGE_TAG`; лимиты памяти как у
  соседних сервисов (bff ≈ 256 МБ, web ≈ 64 МБ).
- Сборка и публикация образов в существующем деплой-процессе (тег = sha), проверка `cpu-baseline-check.sh` включает новые образы;
  `deploy.sh` проверяет наличие `PLATFORM_DOMAIN`.
- `docs/runbooks/deploy.md`: раздел «Платформа» — DNS (владелец), переменная, первый деплой, проверка `/api/v1/health`.

Готово, когда: `make deploy-check` зелёный (compose prod/db, Caddy, shellcheck, тесты деплоя, actionlint); в PR — что владелец
делает перед первым деплоем Платформы (A-запись, строка в `/opt/rt/.env.prod`). Деплой не запускается.

## 5. Что после волны

Гейт P0 (`05-plan.md`): контракты v0 и каркас влиты, `make check-platform` в CI. Затем волна 8 — фаза P1 (каркас AppShell,
вход через CRM, CRM-01 роли Платформы) — runbook готовит архитектор.
