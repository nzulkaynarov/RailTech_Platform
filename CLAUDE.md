# CLAUDE.md — корень монорепозитория RailTech Platform (GitHub `RailTech_Platform`, кодовое имя `rt_platform`)

Бизнес-платформа одной компании: домены **CRM** (лиды, клиенты, бот), **EDS** (документооборот, с этапа C1) и **ERP**
(бэк-офис) со своими базами, связанные шиной `rt_bus`; фронтенды — **Платформа** (все сотрудники) и **Cabinet** (клиент).

**Вся документация — в `docs/`, одна правда** (`docs/README.md` — карта «тема → документ»). Первым читай
`docs/ORCHESTRATOR.md` (процесс, инварианты, роли агентов, протокол сессии), затем `docs/HANDOFF.md` (где мы и что дальше),
затем `docs/systems/<система>/CONVENTIONS.md` той зоны, где работаешь. Правила процесса (коммиты с трейлером, ветки и PR,
запрет `push`/`merge` в `main`, одна сессия — одна система, скриншоты в PR, `docs/PROGRESS.md` ведёт лид) — ORCHESTRATOR §4 и §7.

```
apps/crm/            домен CRM: FastAPI · SQLAlchemy · Procrastinate · aiogram · LangGraph (фронтенд удаляется на C2)
apps/erp/            домен ERP: Django · DRF · Celery · Channels (фронтенд удаляется на C2)
apps/cabinet/        кабинет клиента: React · shadcn, без бэкенда, портальный API ERP
apps/platform/       Платформа: SPA (React · AntD) + BFF (FastAPI) без БД
apps/eds/            домен EDS: FastAPI · SQLAlchemy · Procrastinate (без фронтенда и без внешнего маршрута)
packages/contracts/  машиночитаемые контракты: OpenAPI, схемы событий, MCP, RBAC
packages/ui-tokens/  токены дизайна для AntD и shadcn
infra/               compose, caddy, ai (LiteLLM), db, deploy
docs/                вся документация: ORCHESTRATOR, HANDOFF, strategy, product, architecture, systems, adr, runbooks, history
```

Инварианты (подробно — `docs/ORCHESTRATOR.md` §3): одна система — один главный пользователь; общих таблиц нет, интеграции —
через шину; контракт (`packages/contracts`) раньше кода и в том же PR с обеих сторон; код решает, модель предлагает; секретов в
репозитории нет, модели — через LiteLLM по алиасам; DoD с UI — сценарий глазами со скриншотом; отклонение от стратегии, ADR и
контрактов — только через ADR и решение владельца; документация — только в `docs/`.

Команды: `make check` (все приложения и ссылки документации), `make check-crm|erp|cabinet|platform|eds`, `make contracts`,
`make docs-links`, `make up` (ансамбль локально), `make ci-local`.

## Среда разработки, тесты и CI (правило владельца 2026-10-19)

Локальная среда полная и воспроизводимая: всё, что проверяет CI (`.github/workflows/ci.yml`), проверяется здесь.
Если команда не работает — почини окружение или спроси владельца. Не обходи проблему через CI.

| Что | Команда |
|---|---|
| Worktree задачи (ORCHESTRATOR §4.1) | только `.claude/worktrees/<задача>`: `git worktree add .claude/worktrees/<задача> -b <ветка> origin/main` или `EnterWorktree`; имя задачи = `ERP_TEST_NS` |
| Зависимости (в новом worktree — первым шагом) | `make -C apps/<crm\|erp\|cabinet> install`; контракты — `cd packages/contracts && pnpm install --frozen-lockfile` |
| Один тест CRM | `cd apps/crm/backend && uv run pytest tests/<файл>.py -x -q`; фронтенд — `cd apps/crm/frontend && pnpm test -- <шаблон>` |
| Один тест ERP (одноразовые Postgres + Redis в Docker) | `ERP_TEST_NS=<задача> make -C apps/erp test-backend args="<app>/tests/<файл>.py -x -q"`; фронтенд — `cd apps/erp/frontend && npm run test -- <шаблон>` |
| Один тест Cabinet | `cd apps/cabinet && npm run test -- <шаблон>` |
| Линтер, типы и все тесты приложения | `make check-crm`, `make check-erp`, `make check-cabinet`; контракт и OpenAPI — `make contracts` |
| Всё, что делает CI | `make ci-local` (по умолчанию — всё, кроме e2e и audit; `args="--quick"` — без integration и build; `args="--full"` — с e2e и audit; задания по имени — `scripts/ci_local.sh crm-integration erp`) |
| Стенд ансамбля (для проверки глазами, не для тестов) | `make env && make up`, `make smoke` |

Рабочий цикл:

1. Во время итераций гоняй только затронутые тесты — это секунды, не минуты.
2. Перед коммитом — `make check-<приложение>` для каждого затронутого приложения (и `make contracts`, если менялся
   контракт или OpenAPI). Коммить только зелёное.
3. Задача завершена целиком: `make ci-local` по затронутым заданиям, затем push ветки и PR с кратким описанием —
   это разрешено без вопроса.
4. После открытия PR — **остановись и доложи**. Не запускай CI вручную, не опрашивай его (`gh run watch`,
   `gh run list`, `gh pr checks`, чтение логов) и не жди результата. CI — финальная проверка владельца в чистой
   среде, один прогон на PR. Исключение (владелец 2026-10-20): **лид** перед следующим раундом один раз смотрит
   состояние своих PR — `gh pr view <n> --json state,mergeable,mergeStateStatus,statusCheckRollup` (влит, конфликт,
   итог проверки «CI ok»); логи CI не читает, в цикле не ждёт.
5. Если CI упал (скажет владелец или лид увидит красный «CI ok» по п. 4) — воспроизведи падение локально
   (`make ci-local <задание>` или один тест) и чини здесь, а не методом «поправил → push → смотрю CI». Конфликт с
   `main` — merge `origin/main` в ветку локально, проверка, push.
6. `docs/PROGRESS.md` правит только лид — одним docs-PR после раунда (решение владельца 2026-10-20: строки PROGRESS
   в каждом PR давали конфликты и лишние прогоны CI). Исполнитель пишет статус, хвосты и вопросы в описание PR;
   `QUESTIONS.md`, ADR, runbook и прочие документы задачи — по-прежнему в её PR.

Не делать: использовать CI, чтобы узнать, проходят ли тесты; push «на всякий случай» или ради промежуточной
проверки; push в `main` (защищена — только PR); менять `.github/workflows/*`, ruleset и `scripts/ci_local.sh` без
явного запроса.

Отступить можно, только если проверка принципиально невозможна локально (матрица ОС/версий, внешний сервис
только в CI, секреты) — скажи об этом явно и спроси, прежде чем запускать что-либо удалённо. Платные прогоны
моделей (evals) — отдельно и только с согласия владельца на конкретный прогон.
