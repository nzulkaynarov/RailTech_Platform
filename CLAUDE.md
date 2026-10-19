# CLAUDE.md — корень монорепозитория RailTech Platform (GitHub `RailTech_Platform`, кодовое имя `rt_platform`)

Три системы одной компании: **CRM** (фронт-офис, лиды, бот), **ERP** (бэк-офис: заявки, КП, договоры,
снабжение, склад, финансы), **Cabinet** (кабинет клиента, фронтенд над API ERP). Связь CRM ↔ ERP —
только API и события. Общих таблиц нет.

**Первым читай `ORCHESTRATOR.md`**, затем `docs/HANDOFF.md` — там цель, инварианты, роли агентов, текущая веха и протокол.
Затем — `CLAUDE.md` того приложения, в котором работаешь: конвенции кода живут у приложений, не здесь.

```
apps/crm/        FastAPI · SQLAlchemy · Alembic · Procrastinate · aiogram · LangGraph · Refine/AntD   → apps/crm/CLAUDE.md
apps/erp/        Django · DRF · Celery · Channels · shadcn/Tailwind                                      → apps/erp/CLAUDE.md
apps/cabinet/    React · shadcn · без бэкенда; ходит в apps/erp /api/portal/*                          → apps/cabinet/CLAUDE.md
legacy/b2b/      удалена по плану M2-INF-01; исходная история сохранена в теге b2b-final
packages/contracts/   OpenAPI ERP (internal, portal, integration), схемы событий, схемы MCP-инструментов
packages/ui-tokens/   общие токены дизайна для AntD и shadcn
infra/           compose (base/dev/prod), caddy (3 домена), ai (LiteLLM, Langfuse), db (2 базы, бэкапы), ci
docs/            HANDOFF (где мы и что дальше), BUSINESS, ARCHITECTURE, CONTRACTS, MIGRATION-MAP, DECISIONS, QUESTIONS, OWNER-CHECKLIST, PROGRESS.md, adr/, runbooks/, history/
```

Правила уровня ансамбля (подробно — ORCHESTRATOR.md §3):
1. Одна система — один главный пользователь. Не добавляй в систему чужого пользователя.
2. Никаких общих таблиц между `crm` и `erp`. Только API, события, внешние идентификаторы.
3. Контракт (`packages/contracts`) меняется раньше кода и в том же PR с обеих сторон.
4. Код решает, модель предлагает. Идентификаторы компании/клиента никогда не приходят от модели.
5. Секретов в репозитории нет. Все модели — через LiteLLM по алиасам.
6. DoD любой задачи с UI — сценарий, пройденный глазами (скриншот), не «тесты зелёные».
7. Отклонение от ARCHITECTURE/CONTRACTS — только через ADR и решение владельца, не молча.

Команды: `make check` (все приложения), `make check-crm|erp|cabinet`, `make up` (весь ансамбль
локально на трёх доменах `*.localhost`), `make contracts` (валидация и генерация клиентов).

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
   среде, один прогон на PR.
5. Если CI упал — скажет владелец. Тогда воспроизведи падение локально (`make ci-local <задание>` или один тест)
   и чини здесь, а не методом «поправил → push → смотрю CI».

Не делать: использовать CI, чтобы узнать, проходят ли тесты; push «на всякий случай» или ради промежуточной
проверки; push в `main` (защищена — только PR); менять `.github/workflows/*`, ruleset и `scripts/ci_local.sh` без
явного запроса.

Отступить можно, только если проверка принципиально невозможна локально (матрица ОС/версий, внешний сервис
только в CI, секреты) — скажи об этом явно и спроси, прежде чем запускать что-либо удалённо. Платные прогоны
моделей (evals) — отдельно и только с согласия владельца на конкретный прогон.
