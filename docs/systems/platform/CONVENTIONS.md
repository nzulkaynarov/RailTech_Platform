# docs/systems/platform/CONVENTIONS.md — Платформа (единый интерфейс сотрудников), `apps/platform`

Ты работаешь над **Платформой** ансамбля RailTech: один фронтенд для всех сотрудников компании
(`platform.railtech.uz`) — шесть модулей Dashboard, CRM, EDS, ERP, Chats, Admin в одном окне. Главный
пользователь — **сотрудник** (менеджер, директор, снабженец, гл. инженер, бухгалтер, администратор). Клиенты сюда
не входят: у них Cabinet, Mini App и Telegram-бот. **Своей базы данных нет**: SPA (`web/`) ходит только в BFF
(`bff/`), BFF — в действующие CRM и ERP по их OpenAPI, с токеном сотрудника (ADR-0011).

**Статус (2026-10-22): фаза P0 — ADR-0011 принят, идут контракты v0 и каркас.** Есть документация трансформации в `docs/`. Старые фронтенды CRM и
ERP работают до этапа T4 и с P0 заморожены (только P0-исправления и безопасность).

## 1. Карта документов — читай в этом порядке

| Документ | Что в нём | Когда читать |
|---|---|---|
| `docs/ORCHESTRATOR.md` (корень) | инварианты §3, роли агентов §4, протокол §7 | первым в каждой сессии |
| `docs/HANDOFF.md`, `docs/DECISIONS.md` | где мы, решения владельца | в начале сессии |
| `docs/product/SPEC-v3.md` | **спецификация владельца — источник истины**: словарь §2, процессы §3, роли §4, дизайн §5–§6, модули §7, каналы §8, уведомления §9 | перед любой задачей |
| `docs/history/platform/01-transformation.md` | этапы T0–T5, правила сосуществования со старыми фронтами | перед задачей, которая трогает старые фронты или домены |
| `docs/architecture/platform-bff.md` | SPA + BFF, вход и сессии, кто владеет сущностями, события, роли, развёртывание | перед любой реализацией |
| `docs/architecture/platform-frontend.md` | стек, структура `web/`, каркас и компоненты с размерами из макета, тема, маршруты, тесты | перед экраном |
| `docs/architecture/integration-map.md` | экран → BFF → операции CRM и ERP; маппинг шагов, статусов, ролей; разрывы бэкендов | перед эндпоинтом BFF |
| `docs/history/platform/05-plan.md` | фазы и задачи с «готово, когда» | при взятии задачи |
| `packages/contracts/openapi/platform-bff.yaml` | **API BFF** (создаётся в P0); типы и хуки web генерирует orval | перед каждым эндпоинтом и экраном |
| `docs/adr/0011-unified-platform-frontend.md` | решение уровня ансамбля | перед «а давайте тут иначе» |
| макеты v3 | <https://claude.ai/code/artifact/d82c5f3c-cb33-4914-ae86-c3b85757bea6>, страница «v3 — итоговая» | перед экраном |

Противоречия: SPEC-v3 > ADR-0011 > документы `docs/` этой папки > этот файл > код. Нашёл — в `docs/QUESTIONS.md`,
не угадывай.

## 2. Правила (нарушение = PR не принимается)

1. **Словарь SPEC-v3 §2 обязателен** в интерфейсе, коде и контракте BFF: Лид, Клиент, Контакт, Заявка, Проект,
   Входящее письмо, Резолюция, Расчёт, КП, Договор, Счёт, Платёжка, Оплата, Исполнение, Акт, Служебная записка,
   Чат проекта, Обращение. Старых кодов стадий (`DRAFT`, `CLOSED_WON`…) в интерфейсе нет; «счёт-фактура» для своих
   PDF не пишется.
2. **BFF не решает.** BFF маппит словарь, собирает экраны, держит сессию, раздаёт события. Право на операцию,
   переход стадии, расчёт денег — в CRM и ERP. Если для экрана не хватает операции бэкенда — это разрыв
   (`docs/architecture/integration-map.md` §7), задача в зону бэкенда, а не обход в BFF.
3. **У BFF нет базы.** Redis — только сессии, кэш на секунды и поток событий.
4. **Каждый вызов бэкенда — от имени сотрудника** (его токен). Сервисные токены шва BFF не использует.
5. **Контракт раньше кода.** Новый или изменённый эндпоинт BFF начинается с `platform-bff.yaml`; клиенты
   перегенерируются в том же PR (`make contracts`).
6. **Роли и матрица доступа — один файл** `packages/contracts/platform-rbac.yaml`; BFF и web генерируют из него
   проверки; на каждую ячейку — тест. Поля с ограничением (себестоимость, маржа, цены поставщиков) BFF вырезает
   из ответа, web скрывает `<Restricted>`.
7. **Вид — по макету v3 и `docs/architecture/platform-frontend.md`**: токены из `packages/ui-tokens`, без эмодзи, градиентов, теней на
   карточках, цветных полосок; статус всегда словом; контраст ≥ 4.5:1; реальные `button`/`a`/`input` + `label`;
   `aria-label` на иконочных кнопках.
8. **Одна главная кнопка на экран** с блоком «Что произойдёт» и действием, которое реально делает описанное.
9. **Пустые состояния словами** с действием (тексты SPEC-v3 §7).
10. **Секретов нет в коде и в браузере.** Токены CRM и ERP живут только в сессии BFF; cookie `httpOnly`.
11. **Демо-данные вымышленные.** Репозиторий временно публичный: ни реальных клиентов, ни имён сотрудников.
12. **Старые фронты не трогаешь** (`apps/crm/frontend`, `apps/erp/frontend`): они заморожены и отключаются в T4.

## 3. Стек и команды

| Часть | Стек |
|---|---|
| `web/` | TypeScript ~5.9, Vite 8, React 18, antd 5 + `@ant-design/pro-components`, react-router 7, TanStack Query + orval (хуки и MSW-моки из `platform-bff.yaml`), Zustand, react-i18next (ru/uz/en), Vitest + Testing Library, MSW, Playwright + axe; pnpm 10 |
| `bff/` | Python 3.12, FastAPI, httpx, pydantic v2, redis (asyncio), structlog; uv, ruff, mypy strict, pytest + respx |

| Что | Команда |
|---|---|
| зависимости (новый worktree — первым шагом) | `make -C apps/platform install` (bff: `uv sync --frozen`, web: `pnpm install --frozen-lockfile`) |
| линтеры, типы, тесты, свежесть клиента orval и токенов | `make check-platform` (то же: `make -C apps/platform check`) |
| один тест web | `cd apps/platform/web && pnpm test -- <шаблон>` |
| один тест bff | `cd apps/platform/bff && uv run pytest tests/<файл>.py -x -q` |
| клиент, типы и MSW-моки web из контракта | `make -C apps/platform gen-api` (после правки `platform-bff.yaml`; результат коммитится) |
| RBAC из `platform-rbac.yaml` → `bff/app/rbac_generated.py` и `web/src/app/rbac.generated.ts` | `make -C apps/platform rbac` (после правки матрицы или меню; проверка свежести — `rbac-check`, входит в `check-platform`) |
| токены ui-tokens → `web/src/app/tokens.generated.ts` | `make tokens` из корня (или `make -C apps/platform tokens`); после правки `packages/ui-tokens` |
| e2e Playwright + axe на MSW (BFF и стенд не нужны) | `make -C apps/platform e2e` (браузер один раз: `cd apps/platform/web && pnpm exec playwright install chromium`); скриншот — `E2E_SCREENSHOT_DIR=<каталог>` |
| e2e в параллельном worktree (порт 4173 может быть занят другим прогоном) | `E2E_PORT=4191 make -C apps/platform e2e` (или `E2E_PORT=4191 scripts/ci_local.sh platform platform-e2e`); уже занятый порт — ошибка, чужой vite не подхватывается; `E2E_REUSE_SERVER=1` — осознанно переиспользовать сервер |
| web без бэкенда, ответы MSW | `cd apps/platform/web && pnpm dev:mock` |
| образы bff и web (локальная проверка сборки) | `make -C apps/platform docker-build` |
| стенд | `make up` → `https://platform.localhost:8088` (появится с INF-P0-4) |

Образ `web` собирается с контекстом `apps/platform/web`: сгенерированный клиент
(`src/shared/api/generated`) и токены (`src/app/tokens.generated.ts`) коммитятся рядом с кодом, как у CRM;
`make check-platform` падает, если они расходятся с `platform-bff.yaml` и `packages/ui-tokens`.

DoD экрана — SPEC-v3 §11.2 и чек-лист `docs/architecture/platform-frontend.md` §10: скриншоты 1440/1280/390 рядом с артбордом,
axe без нарушений, сценарий e2e действия.
