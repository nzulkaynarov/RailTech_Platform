# Конвенции кода Платформы (единый интерфейс сотрудников), `apps/platform`
Статус: действует · Владелец: лид · Обновлено: 2026-10-29

Ты работаешь над **Платформой** ансамбля RailTech: один фронтенд для всех сотрудников компании
(`platform.railtech.uz`) — шесть модулей Dashboard, CRM, EDS, ERP, Chats, Admin в одном окне. Главный
пользователь — **сотрудник** (менеджер, директор, снабженец, гл. инженер, бухгалтер, администратор). Клиенты сюда
не входят: у них Cabinet, Mini App и Telegram-бот. **Своей базы данных нет**: SPA (`web/`) ходит только в BFF
(`bff/`), BFF — в действующие CRM и ERP по их OpenAPI, с токеном сотрудника (ADR-0011).

Это правила кода Платформы; код ссылается на них как `CONVENTIONS.md §N`. Где Платформа сейчас — `docs/HANDOFF.md`. По стратегии 2026-10-23 §7 сосуществования со старыми фронтами нет: экраны CRM и ERP
переезжают сюда (паритет Admin — этап C2a, рабочие экраны — этап D), а старые фронты отключаются задачей P6 волны 18a после гейтов D1-7 и D2-6 (DECISIONS 2026-10-27, 2026-10-28); BFF переходит на публичные API доменов и события `rt_bus`
(этап B), EDS — отдельный домен (ADR-0015). Запуск и команды — [`README.md`](README.md).

## 1. Карта документов — читай в этом порядке

| Документ | Что в нём | Когда читать |
|---|---|---|
| `docs/ORCHESTRATOR.md` | инварианты §3, роли агентов §4, план §6, протокол §7 | первым в каждой сессии |
| `docs/HANDOFF.md`, `docs/DECISIONS.md` | где мы, решения владельца | в начале сессии |
| `docs/product/SPEC-v3.md` | **спецификация владельца — источник истины**: словарь §2, процессы §3, роли §4 (вместе с ADR-0012), дизайн §5–§6, модули §7, каналы §8, уведомления §9 | перед любой задачей |
| стратегия `docs/strategy/2026-10-23-platform-architecture-strategy.md` §3, §7 | целевая архитектура, домены, шина, порядок этапов | перед задачей, которая трогает домены или старые фронты |
| `docs/architecture/platform-bff.md` | SPA + BFF, вход и сессии, кто владеет сущностями, события, роли, развёртывание | перед любой реализацией |
| `docs/architecture/platform-frontend.md` | стек, структура `web/`, каркас и компоненты с размерами из макета, тема, маршруты, тесты | перед экраном |
| `docs/architecture/integration-map.md` | экран → BFF → операции доменов; маппинг шагов, статусов, ролей; разрывы | перед эндпоинтом BFF |
| `packages/contracts/openapi/platform-bff.yaml` | **API BFF**; типы и хуки web генерирует orval | перед каждым эндпоинтом и экраном |
| `docs/adr/0011-unified-platform-frontend.md` | решение уровня ансамбля | перед «а давайте тут иначе» |
| макеты v3 | <https://claude.ai/code/artifact/d82c5f3c-cb33-4914-ae86-c3b85757bea6>, страница «v3 — итоговая» | перед экраном |

Противоречия: SPEC-v3 > стратегия и ADR-0011…0019 > `docs/architecture/` > этот файл > код. Нашёл — в `docs/QUESTIONS.md`,
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
6. **Каталог возможностей — один файл** `packages/contracts/platform-rbac.yaml` (версия 2, ADR-0012: разделы,
   меню, поля, очередь, системные роли и шаблоны); роли — данные CRM, в коде не опираемся на коды ролей, кроме
   системных `ADMIN`/`DIRECTOR`; BFF и web генерируют из каталога проверки; на каждый раздел — тест. Поля с ограничением (себестоимость, маржа, цены поставщиков) BFF вырезает
   из ответа, web скрывает `<Restricted>`.
7. **Вид — по макету v3 и `docs/architecture/platform-frontend.md`**: токены из `packages/ui-tokens`, без эмодзи, градиентов, теней на
   карточках, цветных полосок; статус всегда словом; контраст ≥ 4.5:1; реальные `button`/`a`/`input` + `label`;
   `aria-label` на иконочных кнопках.
8. **Одна главная кнопка на экран** с блоком «Что произойдёт» и действием, которое реально делает описанное.
9. **Пустые состояния словами** с действием (тексты SPEC-v3 §7).
10. **Секретов нет в коде и в браузере.** Токены CRM и ERP живут только в сессии BFF; cookie `httpOnly`.
11. **Демо-данные вымышленные.** Репозиторий временно публичный: ни реальных клиентов, ни имён сотрудников.
12. **Старые фронты не трогаешь** (`apps/crm/frontend`, `apps/erp/frontend`): они заморожены и отключаются задачей P6 волны 18a после гейтов D1-7 и D2-6 (DECISIONS 2026-10-27, 2026-10-28).
13. **Заглушка не врёт** (W15-H1). Раздел без экрана не пишет «пока нет» и «фаза Pn»: `SectionStubPage` говорит, где эта работа
    делается сейчас (`modules/bridge.ts`: старая CRM или ERP и путь там, кнопка в новую вкладку) или кто её делает вне интерфейса,
    и когда появится — словами. Запись моста есть ⇒ раздел заглушка; появился настоящий экран — запись удалить, ключ раздела
    добавить в `NATIVE_SECTIONS` (тест `bridge.test.ts` требует для каждого раздела одно из двух). Бейдж меню у заглушки — только
    с нейтральной подсказкой «ещё в старой системе: N» (`legacyCount`) или без бейджа.
14. **Ссылка ведёт только туда, где можно работать** (W15-H2). «Мои задачи», поиск и колокольчик решают одной функцией
    `isActionable(path)` (`modules/bridge.ts`): у раздела есть родной экран (записи моста нет) — «Открыть» / переход на адрес объекта
    с боковым окном; иначе — «Где сделать» / «Где посмотреть» (`stub/WhereToDo`: старая система и путь там, кнопка «Открыть в …»,
    «Когда появится»), а не ссылка на заглушку. Волна 16 снимает мост записью в `NATIVE_SECTIONS` — три места подхватывают это
    сами. Пустая очередь — по разделам каталога (`queueEmptyKind`, не по кодам ролей); отказ источника — плашка с названиями
    разделов, а не «задач нет».

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
| клиент, типы и MSW-моки web из контракта | `make -C apps/platform gen-api` (после правки `platform-bff.yaml`; результат коммитится). Добавляющее изменение `info.version` не поднимает; шапка orval — без версии и описания, поэтому разница версий клиент не меняет (ORCHESTRATOR §4.1, CONTRACTS §7.1) |
| модели ответов CRM из `packages/contracts/openapi/crm.yaml` → `bff/app/clients/crm_models.py` | `make -C apps/platform crm-models` (после изменения OpenAPI CRM или списка `ROOTS` в `scripts/gen_crm_models.py`; свежесть — `crm-models-check`, входит в `check-platform`) |
| RBAC из `platform-rbac.yaml` → `bff/app/rbac_generated.py` и `web/src/app/rbac.generated.ts` | `make -C apps/platform rbac` (после правки матрицы или меню; проверка свежести — `rbac-check`, входит в `check-platform`) |
| справка формата базы знаний `docs/kb` → `web/src/generated/kb-docs` (копия для сборки; равенство проверяет тест `kbDocs.test.ts`) | `make -C apps/platform kb-sync` (или `cd apps/platform/web && pnpm kb:sync`) после правки `docs/kb` |
| статьи помощи сотрудникам `docs/kb/help/*.md` → `web/src/generated/help-articles` (копия для сборки; равенство проверяет `features/help/articles.test.ts`; в front matter — `title`, `sections` (ключи `<модуль>.<раздел>` или `me`), `order`, `screens` (адреса экранов `[/crm/leads, …]`, W-REL)); записи «Что нового» `docs/kb/help/changelog/<дата>.md` → `help-articles/changelog` (`changelog.test.ts`); «Что ожидается» — статья `roadmap.md` | `make -C apps/platform kb-sync` после правки статьи; правит статьи тот, у кого доступ к репозиторию (PR), редактора в интерфейсе нет (Q-W15-H7). У каждого пункта меню каталога — статья (тест `articles.test.ts`); PR, меняющий экран, правит его статью (ORCHESTRATOR §7 п. 4); статьи компании — отдельно: хранит CRM, правит админ в «Настройки · Статьи компании», в Помощь их добавляет `features/help/companyArticles.ts` (slug `company-<id>`), показ — тот же `Markdown.tsx` (W18A-P5) |
| токены ui-tokens → `web/src/app/tokens.generated.ts` | `make tokens` из корня (или `make -C apps/platform tokens`); после правки `packages/ui-tokens` |
| e2e Playwright + axe на MSW (BFF и стенд не нужны) | `make -C apps/platform e2e` — сервер поднимается сам: сборка `vite build --mode mock` + `vite preview` (≈1 с на сборку; `E2E_DEV=1` — dev-сервер с HMR для отладки); браузер один раз: `cd apps/platform/web && pnpm exec playwright install chromium`; скриншот — `E2E_SCREENSHOT_DIR=<каталог>`; повторов нет (`retries: 0`) — «flaky» это красный тест. Проект `mobile` (390) гоняет только сценарии с тегом `{ tag: "@mobile" }` (экраны с адаптивной логикой); остальные — десктоп (ширину сценарий задаёт сам). Локально — только затронутые спеки: `pnpm exec playwright test e2e/<файл>.spec.ts`; в CI — три шарда (`docs/systems/infra/ci.md`) |
| e2e в параллельном worktree (порт 4173 может быть занят другим прогоном) | `E2E_PORT=4191 make -C apps/platform e2e` (или `E2E_PORT=4191 scripts/ci_local.sh platform platform-e2e`); уже занятый порт — ошибка, чужой vite не подхватывается; `E2E_REUSE_SERVER=1` — осознанно переиспользовать сервер |
| web без бэкенда, ответы MSW | `cd apps/platform/web && pnpm dev:mock` |
| образы bff и web (локальная проверка сборки) | `make -C apps/platform docker-build` |
| стенд | `make up` → `https://platform.localhost:8088` |

Образ `web` собирается с контекстом `apps/platform/web`: сгенерированный клиент
(`src/shared/api/generated`) и токены (`src/app/tokens.generated.ts`) коммитятся рядом с кодом, как у CRM;
`make check-platform` падает, если они расходятся с `platform-bff.yaml` и `packages/ui-tokens`.

DoD экрана — SPEC-v3 §11.2 и чек-лист `docs/architecture/platform-frontend.md` §10: скриншоты 1440/1280/390 рядом с артбордом,
axe без нарушений, сценарий e2e действия.
