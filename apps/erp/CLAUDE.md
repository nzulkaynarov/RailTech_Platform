# CLAUDE.md — ERP (бэк-офис), `apps/erp`

Ты работаешь над **ERP** ансамбля RailTech Platform: бэк-офис одной компании — заявка → КП → договор →
снабжение → исполнение → финансы. Один главный пользователь — **специалист бэк-офиса** (расчётчик,
закупщик, логист, финансист; «Администратор» = суперпользователь). Клиент сюда не входит — ему служит
Cabinet через портальный API этой же ERP. Продукт нейтрален к отрасли и бренду: имя и логотип — настройки.

**Статус документа: заготовка (M0-DOC-01), обновлена в M1-ERP-01.** Код скопирован из `legacy/b2b` как есть
(2026-10-13) и перестраивается задачами M1-ERP-02…09 — до них в коде ещё живут удаляемые слои из §9 и бренд B2B.
Окончательная версия этого файла — **M1-ERP-10**.
Всё, что помечено «появится в <ID>», пока не существует — не ищи и не выдумывай.

## 1. Карта документов — читай в этом порядке

| Документ | Что в нём | Когда читать |
|---|---|---|
| `ORCHESTRATOR.md` (корень) | цель, инварианты §3, роли §4, вехи и задачи §6, протокол сессии §7 | первым в каждой сессии |
| `docs/PROGRESS.md`, `docs/QUESTIONS.md`, `docs/DECISIONS.md` | состояние, открытые вопросы, решения владельца | в начале сессии |
| `docs/ARCHITECTURE.md` §4 | **состав ERP: приложения и откуда они из B2B**; §7 — что настраивает администратор в ERP; §8 — ИИ; §9 — вход и роли; §18 — e-mail | перед любой реализацией |
| `docs/MIGRATION-MAP.md` §1 | что переезжает, что **удаляется**, что новое | перед M1-ERP-02 и при любом «а где в B2B было…» |
| `docs/CONTRACTS.md` | §1 пространства API; §2 integration; §3 события; §4 portal; §5 `erp-mcp`; §6 SSO | перед задачами с контрактом |
| `docs/adr/0004…0007` | Cabinet без бэкенда; ИИ через LiteLLM; свежие миграции; снабжение внутри ERP | перед изменением того, что покрыто ADR |
| `docs/BUSINESS.md` §3.3, §7, §11, §12 | ценность ERP, товары и услуги, роли бэк-офиса, чего не делать | перед продуктовой задачей |
| `legacy/b2b/CLAUDE.md` | конвенции и грабли B2B — источник этого файла | когда переносишь код; **только чтение** |

Противоречия: `BUSINESS` > `ARCHITECTURE` > `CONTRACTS` > этот файл > код. Нашёл — не угадывай, пиши в `docs/QUESTIONS.md`.

## 2. Инварианты ансамбля применительно к ERP (нарушение = PR не принимается)

1. **Один главный пользователь.** В ERP входят только сотрудники (SSO из CRM или пароль). Клиентских аккаунтов нет; клиент — контакт контрагента в `parties` с сессией портала, а не `User`.
2. **Общих таблиц с CRM нет.** База `erp` своя. Связь — внешние идентификаторы `crm_client_id`, `crm_lead_id`, `crm_contact_id`, `crm_user_id` (CONTRACTS §0); идемпотентность по ним и по `Idempotency-Key`.
3. **Контракт раньше кода.** Любой эндпоинт `portal`/`integration`, событие, инструмент MCP, claim токена — сначала `packages/contracts` (есть с M0-INF-02: `openapi/erp-*.yaml`, `events.schema.json`, `mcp-tools.json`, `sso-token.md`), потом код; клиенты пересобираются в том же PR (`make contracts`).
4. **Код решает, модель предлагает.** Стадии, права, цены, доступ — детерминированно и с тестами. Идентификаторы компании никогда не приходят от модели: только из подписанного `X-Agent-Context`.
5. **Клиент видит только опубликованный слой** каталога и проекцию сделки: без поставщиков, себестоимости, маржи. Каждый портальный эндпоинт — негативный тест «чужая компания → 404», «внутренний слой не отдаётся».
6. **Секреты только в окружении.** `gitleaks` в pre-commit корня. Модели — через LiteLLM по алиасам; импорт SDK провайдера в коде ERP запрещён (M1-ERP-06).
7. **`legacy/b2b` не редактируется.** Код копируется в `apps/erp`; `git log --follow` сохраняет историю.
8. **Документация в том же PR:** OpenAPI в `packages/contracts`, ADR, runbook, `docs/PROGRESS.md`.
9. **DoD с UI = сценарий глазами** (скриншот/GIF в PR, 1440 и 390 px), не «тесты зелёные».
10. **Benchmark-first** для продуктовых задач: как у Odoo / ERPNext / SAP B1 — именованный паттерн в описании PR, потом код.

## 3. Стек

```
backend/   Python 3.12 · Django 6 · DRF · Daphne (ASGI) · Channels · Celery (+ Beat) · PostgreSQL 17, база `erp` ·
           Redis (отдельные БД под Channels и Celery) · RustFS (S3), бакет `erp` · WeasyPrint (PDF off-thread) ·
           pandas + openpyxl (Excel) · LiteLLM (алиасы intake-model, match-model, draft-model, enrich-model) · Langfuse
frontend/  React 18 · TypeScript · Vite · Tailwind CSS 4 · shadcn/ui · React Query · Zustand · i18next (ru/en, uz позже) ·
           openapi-typescript (типы из packages/contracts) · Vitest + Testing Library
```

Версии — как в `legacy/b2b` на момент копирования (M1-ERP-01); обновления — отдельными PR с `make check-erp`.
Общие сервисы (Postgres, Redis, LiteLLM, Langfuse, RustFS, Caddy) — из `infra/compose` (есть; сервисы `erp-*` добавлены в M1-ERP-01),
ERP сам их не описывает. Токены дизайна — из `packages/ui-tokens` (есть: `dist/shadcn.css`); подключение в `frontend/src/index.css` — при перестройке UI (M1-ERP-04).
Хранилище файлов — целевое RustFS через S3-бэкенд Django; после копирования пока FileSystemStorage в томе `erp_media` (перевод — отдельной задачей M1).

## 4. Структура приложений (ARCHITECTURE §4; имена и одна миграция на приложение — ADR-0006)

| Приложение | Что внутри | Откуда из `legacy/b2b/backend` |
|---|---|---|
| `core` | настройки (`PLATFORM_NAME`, `SUPPORT_EMAIL`, логотип, домен), аудит, идемпотентность, оптимистичные блокировки, валидаторы загрузок, health, пагинация, versioning | `core/` (audit, idempotency, optimistic_locking, validators, health, csp, file_streaming) |
| `accounts` | сотрудники, роли бэк-офиса (`Role` с правами), 2FA, сессии, lockout, провижининг из CRM, приём SSO-токена | `accounts/` минус KYC, подписки, операторские роли, заявки на роли, регистрация |
| `parties` | контрагенты: клиент / поставщик / субподрядчик; контакты (`telegram_user_id`, язык, предпочитаемый канал); реквизиты; `crm_client_id` | `accounts` `Company`, `Contact`, `CompanyDocumentProfile` минус KYC-уровни, merge по ИНН, `CounterpartyRelationship` |
| `catalog` | единая карточка «товар / услуга», два слоя (внутренний / опубликованный), политика видимости `cabinet` / `on_request`, категории, импорт Excel, ИИ-обогащение по полям, полнота, ТН ВЭД как справочник | `catalog/` + `master_data.HSCode` минус `EquipmentGroup`, `DomainType` ЖД; `SupplierOffer` → `supply` |
| `sales` | запрос → сделка (FSM) → КП (билдер, версии, экономика, согласование, курс на дату) → договор → публичная страница акцепта | `crm/` (deals, quotes, contracts, approvals, numbering, wording, document_blocks) |
| `supply` (M4) | поставщик, заказ поставщику (back-to-back, дропшип), приёмка, счёт и оплата поставщику, сроки; субподряд как этапы | `catalog.SupplierOffer`, `crm/services/availability.py`; остальное новое |
| `inventory` (M4) | журнал движений, остаток = сумма движений, резервы, «доступно к обещанию»; отгрузки по строкам | `crm` `Fulfillment` |
| `finance` | счета клиентам, платежи, акты (двусторонние), напоминания, отклонение маржи по курсу | `crm/services/billing.py`, `invoice_lifecycle.py`, `deal_emails.py` |
| `documents` | шаблоны компании, PDF off-thread, квитанции, накладные, поиск, «недавние» | `crm/services/documents/`, `generated_documents.py`, `crm.tasks.render_document_pdf` |
| `ai` | очередь `ai`: разбор запроса, сопоставление с каталогом, черновик КП, обогащение карточки, разбор прайса (M4), диф КП; клиент LiteLLM; трейсы Langfuse; evals | `sourcing/` (`services_ai*.py`, `tasks_ai.py`, `AIJob`, `ImportTask`) минус прямой SDK |
| `portal` (M2) | `/api/portal/v1/*`: только своя компания; вход Telegram `initData` / magic-link; действия клиента | покупательские вьюхи `crm`, `crm/views/documents_public.py`, `crm/services/public_page.py` |
| `integration` (M3) | API для CRM, исходящие вебхуки с подписью и журналом, `erp-mcp` | новое |

Не выделено отдельной строкой в ARCHITECTURE §4, но переносится по MIGRATION-MAP: `notifications`
(EmailLog, шаблоны писем, WS-уведомления — ARCHITECTURE §18) и справочники `master_data` (страны,
валюты, единицы, базисы, курсы). Куда их положить — отдельными приложениями или внутрь `core`/`documents` —
решает M1-ERP-03; до решения не предполагай.

Папки `apps/erp/` сейчас — как в B2B (`backend/<app>/`, `frontend/src/`, `Makefile`, `scripts/`, `pyproject.toml`, `.flake8`); целевая структура после M1-ERP-03:

```
backend/<app>/{models/, services/, views/, serializers/, tasks.py, migrations/0001_initial.py, tests/}
backend/core/settings/        prompts/*.md (ИИ, версия по хэшу — M1-ERP-06)    locale/ (django.po)
frontend/src/{api/ (типы из contracts), components/ui/ (shadcn), components/<домен>/, pages/, hooks/, store/, i18n/locales/{ru,en}.json, layouts/AppShell.tsx}
Makefile · .env.example · docs/ (ADR и runbook ERP — M1-ERP-10)
```

## 5. Конвенции кода (из B2B; то, что остаётся верным)

**Python**
- Бизнес-логика **только в `<app>/services/`** как обычные функции: переходы FSM, валидации, побочные эффекты, письма, Celery-диспетчи. `views` и `admin.py` — тонкие обёртки: авторизовать → валидировать → вызвать одну функцию сервиса → вернуть. Одна и та же логика в admin-action и DRF-эндпоинте — запрещена; оба зовут сервис.
- **Словари сеются миграциями** (`RunPython` + `get_or_create`, reverse no-op): стадии, статусы, виды документов, роли, образцы шаблонов. После `migrate` на пустой базе каждый код, на который ссылаются сервисы, уже существует. В горячих путях — `Model.objects.get(code=...)`, не `get_or_create`. `loaddata` и management-команды — только для dev/demo.
- **Нет фейковых данных:** каждый эндпоинт читает реальную БД; никаких статических массивов и заглушек в продуктовом коде.
- **Нет хардкода:** URL, ключи, идентификаторы — из окружения; бизнес-константы — из БД или настроек; роли, стадии, статусы сравниваются по `code`, никогда по переведённому `name`.
- Ошибки API — `{"detail": "<CODE>"}` (DRF-native, CONTRACTS §0); фронтенд сравнивает код по значению. Держит тест вида `core/tests/test_error_shape.py` B2B.
- Бизнес-дата — `timezone.localdate()`, никогда `timezone.now().date()` (`TIME_ZONE=Asia/Tashkent`, `USE_TZ=True`).
- Списки — `select_related` / `prefetch_related`, без N+1; дашборды — `aggregate()` с условными `Count`, не `.count()` в цикле; пагинация у всех списков.
- Запрос не блокирует ASGI: PDF, импорт, ИИ — в Celery; публичные и тяжёлые ответы — 202 + `Retry-After`. Celery-задачи — с `time_limit`/`soft_time_limit`, ретраями и backoff (исключение — ИИ-задача, одна попытка: платный вызов).
- Загрузки — через валидаторы `core` (размер, тип, расширение, magic-bytes).
- Деньги — `DecimalField`; каноническая валюта представления из B2B — UZS; курс фиксируется на дату КП (M1-ERP-08). Оптимистичная блокировка на мутациях КП.
- Исключения конкретные (`ValidationError`, `OSError`, …), не голый `except Exception`. Функции ≤ 50 строк, файлы ≤ 500 строк (иначе пакет), параметров ≤ 5 (иначе dataclass). Имена описательные.
- Сериализаторы: вложенное чтение, плоская запись; суффикс `_data` для вложенных представлений. Справочники — наследники `AbstractLookup` (code, name, sort_order, is_active).
- Линтеры и форматирование — как в B2B (black 120, isort profile=black, flake8); смена инструментов — отдельным решением, не попутно.
- Django-админка (Unfold) — инженерам: справочники, аудит, Beat, аварийные правки. Бизнес-настройки — в SPA (ARCHITECTURE §7). Новый `@admin.action` с бизнес-логикой — стоп, делай страницу + эндпоинт.

**ИИ (ADR-0005; детали — M1-ERP-06)**
- Ни одного вызова модели в пути запроса: эндпоинт валидирует → ставит задачу в очередь `ai` → 202 `{task_id}` → SPA опрашивает статус; владение задачей — IDOR-гард как в B2B `AIJob`.
- Клиент — LiteLLM по алиасам `intake-model`, `match-model`, `draft-model`, `enrich-model`; `LITELLM_URL` и ключ — секреты окружения; теги вызова `system=erp`, `feature`, `model`; трейсы в Langfuse; бюджет на день.
- Промпты — файлы `backend/prompts/*.md` с версией по хэшу; пользовательский текст — в отдельных блоках. Результат модели — предложение по полям, человек утверждает; ошибки ИИ — логируемые no-op, не 500.
- Evals с golden-кейсами по образцу CRM; платные прогоны (`make eval-quick`) — только с «да» владельца на конкретный прогон.

**TypeScript / UI**
- Только компоненты `@/components/ui/` (shadcn) и **семантические токены**: `bg-primary`, `text-foreground`, `bg-destructive`, `bg-success`… Никаких `bg-emerald-500`, `text-white`, hex, inline-стилей для статики, кастомного CSS. Размеры текста — только шкала Tailwind (`text-xs` минимум). Сайдбар — shadcn `<Sidebar>`. Списки — адаптивная таблица с карточками на мобильном (`ResponsiveDataTable` из B2B).
- **Весь текст через i18n**: `t()` из `useTranslation()`, ключи в `ru.json` и `en.json` одновременно (симметрия проверяется скриптом; `uz` добавляется позже без переписывания экранов). Zustand-сторы хранят ключи, не текст. Zod-сообщения — фабрикой `createSchema(t)`.
- **Типы API только сгенерированные** из `packages/contracts/openapi/erp-internal.yaml` через openapi-typescript (`make contracts`); ручные дубли типов запрещены. Для логики — `stage_code`, для показа — `stage_name`.
- Права на фронте — только скрытие/блокировка UI по правам из `/me`; истина на бэке. Навигация строится из прав роли (`buildNavigation` из B2B), без тиров KYC/подписки.
- Правила React Compiler включены (`eslint-plugin-react-hooks`): форма из данных запроса — `useDraftState`, «сейчас» — `useNow`, свежее значение в колбэке — `useLatestRef`; точечные отключения только с причиной в файле.
- Деньги на фронте — `decimal.js`. Никаких `as any` / `@ts-ignore` без комментария. Ошибки — toast, не `alert()`.
- Бренд и отрасль в UI, письмах, PDF, i18n — запрещены (M1-ERP-04): имя продукта — `PLATFORM_NAME`, логотип и домен — настройки. Слова интерфейса нейтральны: «поставка / оказание», «позиция / этап» (BUSINESS §7).

**Тесты**
- Backend: pytest + pytest-django, маркеры `unit` / `integration` / `slow`; CI гоняет `--create-db` **с миграциями** (словари сеются ими — база без них другая). Порог покрытия из B2B — 70 % (`--cov-fail-under`). Любой баг сначала воспроизводится тестом.
- Обязательные классы тестов: матрица прав ролей на каждом эндпоинте мутации (M1-ERP-05); параметризованные таблицы переходов FSM и расчётов; негативные тесты portal (чужая компания 404, подделанный `initData` 401, просроченный magic-link 410), integration (без токена 401, повторный handoff без дубля), MCP (без контекста 401, чужой клиент — пусто); тест на отсутствие N+1 в карточке сделки.
- Frontend: Vitest + Testing Library + jsdom, рендер через провайдеры с настоящим `ru.json`.
- Контрактные тесты по OpenAPI из `packages/contracts`; расхождение схемы и сгенерированного — красный CI.

## 6. Роли бэк-офиса (ARCHITECTURE §7, §9; BUSINESS §11; M1-ERP-05)

| Роль | Владеет | Права (префиксы) |
|---|---|---|
| Расчёт | запросы, КП, согласование, договоры | `quote.*`, `contract.*` |
| Каталог и закупки | карточки, поставщики, заказы поставщикам, приёмки | `catalog.*`, `supply.*` |
| Исполнение и логистика | отгрузки, накладные, приёмка клиентом, акты | уточняет M1-ERP-05 |
| Финансы | счета клиентам, оплаты, счета поставщиков, курсы | `finance.*` |

- «Администратор» в CRM = суперпользователь ERP. Одному человеку — несколько ролей, очереди складываются.
- Источник истины по людям и доступам — CRM (ADR-0003): пользователь создаётся провижинингом (`POST /api/integration/v1/users/provision`), вход — SSO-токеном на 60 с с одноразовым `jti` (CONTRACTS §6), отзыв доступа в CRM отзывает сессии ERP. Локальный пароль и 2FA (из B2B) остаются как запасной вход.
- Права проверяются **в сервисах** (`member_has_permission`-подход B2B), фронт только прячет кнопки. Никаких «OWNER»/«Sales Manager» в коде — только коды прав.
- Режим «глазами клиента» (ORCHESTRATOR §3.1) — сотрудник смотрит проекцию компании из ERP; это не вход в Cabinet.

## 7. Пространства API (CONTRACTS §1)

| Пространство | Префикс | Кто зовёт | Аутентификация | Появится в |
|---|---|---|---|---|
| internal | `/api/v1/` | ERP SPA | JWT сотрудника (access 30 мин, refresh в HttpOnly-cookie, как в B2B) | M1-ERP-01 (копия B2B), экспорт в contracts — M1-ERP-10 |
| portal | `/api/portal/v1/` | Cabinet | сессия портала: Telegram `initData` / magic-link | M2-ERP-01 |
| integration | `/api/integration/v1/` | CRM | `Authorization: Bearer <SERVICE_TOKEN>` (по токену на направление, два активных для ротации) | M3-ERP-01 |
| mcp | `/mcp/erp` | агент CRM | `X-Agent-Context` (HMAC, 60 с) | M3-ERP-03 |
| события → CRM | `POST {CRM}/api/v1/integrations/erp/events` | ERP (Celery) | `X-Signature` HMAC, `X-Event-Id`, ретраи 1 мин … 24 ч | M3-ERP-02 |

Правила: эндпоинты — kebab-case, множественное число; `Idempotency-Key` на всех POST интеграции (ключ хранится 7 дней);
деньги — строка с двумя знаками + ISO-4217; даты — ISO-8601 с зоной; версия — префикс `v1`, несовместимое изменение — новый префикс.
Любое изменение здесь начинается с `packages/contracts` и PR с обеих сторон в одной вехе.

## 8. Команды

| Команда | Что делает | Появится в |
|---|---|---|
| `make check-erp` (из корня) | делегирует в `make -C apps/erp check`: flake8/black/isort, eslint, tsc, i18n, vitest, pytest в контейнере на одноразовых Postgres 17 + Redis | есть (M1-ERP-01) |
| `make -C apps/erp check \| test \| lint \| migrate \| openapi` | проверки, pytest, линтеры, миграции на стенде, экспорт `backend/schema.json` + типы фронтенда | есть (M1-ERP-01); экспорт в `packages/contracts` — M1-ERP-10 |
| `make contracts` (из корня) | валидация контракта, генерация типов для ERP/Cabinet и клиента CRM | есть (M0-INF-02) |
| `make up` (из корня) | весь ансамбль: `erp.localhost` через Caddy → `erp-backend`/`erp-web`, Postgres с базой `erp`, Redis (БД 1 Celery, 2 Channels), LiteLLM, Langfuse, RustFS (бакет `erp`) | есть (M1-ERP-01) |
| `make logs s=<сервис>` / `make ps` | логи и статус стенда | есть (M0-INF-03) |
| `make -C apps/erp eval-quick` | платный прогон evals — только с согласия владельца | M1-ERP-06 |

ERP не имеет своего compose: контейнеры `erp-backend`, `erp-worker`, `erp-worker-ai`, `erp-beat`, `erp-web`
описаны в `infra/compose/base.yml` (M1-ERP-01); код бэкенда монтируется в dev, но Daphne/Celery не перезагружаются сами; `.env.example` корня уже содержит `ERP_SECRET_KEY`, `PLATFORM_NAME`, `SUPPORT_EMAIL`, `SERVICE_TOKEN_*`, `WEBHOOK_SECRET`, `PLATFORM_SSO_SECRET`, `ERP_MCP_CONTEXT_KEY`. Миграции на проде — явным шагом после pg_dump-гейта (M5-INF-01).
Celery не перезагружается сам — после изменения моделей и задач перезапускай воркеры.

## 9. Чего здесь нет (MIGRATION-MAP §1, удаляется в M1-ERP-02) — не ищи и не воссоздавай

- **Маркетплейс:** multi-seller, `DealSellerRouting`, «скрытая конкуренция», `seller_visible_deal_ids`, `claim`; типы компаний CLIENT/SUPPLIER/MANUFACTURER как роли пользователя; `CompanyMember.can_buy/can_sell`; контексты buyer/seller в UI. Продавец один — это сама компания.
- **Монетизация:** подписки, `CompanyEntitlement`, `FeatureKey`, DEMO, кредиты, водяные знаки, `MySubscriptionPage`. «Биллинг» ансамбля — дашборд затрат на ИИ в CRM (M3-CRM-09), не здесь. **Фронтенд удалён (M1-ERP-02, волна 2 frontend):** `pages/MySubscriptionPage` (маршрут `#my-subscription`, секция настроек «План и подписка» `billing` и её группа), `components/Shared/{SubscriptionPayDialog,SubscriptionStatusBanner,DetailKPIGrid}` (баннер подписки в `AppShell`; `DetailKPIGrid` жил только ради страницы подписки), `hooks/useQuoteSendGate` и `components/CRM/QuoteSendGateBanner` (гейт отправки КП «нужна подписка / DEMO-водяной знак / запрещено платформой» — кнопка «Отправить» больше не блокируется на фронте, отправку решает право роли `quote.send` на сервере), шаг «Активируйте подписку» чек-листа онбординга. API/хуки: `accountsApi.{getSubscriptions,getMySubscription,activateSubscription,suspendSubscription,paySubscription,createSubscription,updateSubscription,deleteSubscription}`, тип `Subscription`, `useSubscriptions/useMySubscription/use{Activate,Suspend,Pay,Create,Update,Delete}Subscription`. Навигация: в `NavRequirement` нет `subscription`, в `pageRegistry` нет `my-subscription`, `SettingsGateInput` без `companySells`. Типы: в `Capabilities` нет `subscription_active`/`can_send_quotes`/`quote_send_is_demo`/`quote_send_blocked_by_operator`, в `userStore` — `sellerSubscriptionOperational`, в `accountsApi.User` — `seller_subscription_operational`. `codes`: нет `SubscriptionPlan`/`SubscriptionStatus`/`EntitlementAccess` и меток `featureKeys`. Остались осознанно: `ManualModeBanner` (напоминание «оплата / подпись — вручную» на счетах, платежах, актах и договорах — это `finance`, не подписка; из удалённого диалога оплаты подписки он просто ушёл), показ дневного лимита ИИ в карточке товара (`capabilities.ai_daily_*` — защита бюджета, не тариф; заменит бюджет LiteLLM в M1-ERP-06), подписи событий `activity.{subscription.paid,admin.subscription.*,admin.entitlement.*}` и `notification.subscription.suspended` — до слияния бэкенда волны 2: бэкенд ещё пишет эти коды, `subscription.*` требует `activityCoverage.test`.
- **KYC:** уровни L1–L3, `verification_status`, KYC-воронка, регистрация «с улицы», заявки на роли. Контрагента создаёт бэк-офис или передача из CRM. **Бэкенд удалён в M1-ERP-02 волна 1c:** нет моделей `KYCDocument`, `KYCDocType`, `VerificationStatus`, `CompanyRoleApplication`, `ClientInvite` и полей `Company.verification_status`/`is_verified`/`kyc_notes` (миграция `accounts/0051_remove_kyc_role_applications_client_invite`), сервисов `accounts/services/{kyc,applications,merge,profile}`, эндпоинтов `auth/register`, `auth/submit-profile`, `accounts/role-applications`, KYC/merge-действий компании и `contacts/{id}/invite`, гейтов `SELLER_KYC_REQUIRED`/`KYC_REQUIRED_TO_SUBMIT` (действие — по правам роли), писем KYC/заявок/регистрации. Слияние компаний по ИНН удалено вместе с KYC; `CounterpartyRelationship` — волна 3. Вход, 2FA, сброс пароля и `setup-password` по приглашению остаются. **Фронтенд удалён (M1-ERP-02, волна 1c frontend):** `components/Auth/KYCRegistrationForm` (форма регистрации и экран «письмо отправлено», маршрут `/register`, ссылка «Пройти регистрацию» на входе), `components/Cabinet/ProfileCompletionForm` (создание компании после входа, `auth/submit-profile`; вместо неё — `components/Auth/NoCompanyScreen`: «учётная запись не привязана к компании» + выход), `components/Settings/CompanyRoleSection` (подача заявки на роль), `hooks/useCatalogPublishGate` (порог публикации карточек), карточка «KYC-документы» и блокировка ИНН в `CompanyTab`, `KYCPendingBanner` дашборда (с mailto в поддержку), шаг KYC чек-листа онбординга, причина `kyc` гейта отправки КП; приглашение контакта клиента зарегистрироваться (`accounts/contacts/<id>/invite/`, кнопка в книге контрагентов). API/хуки: `accountsApi.{registerInterest,submitProfile,verifyCompany,uploadDocument,deleteDocument,inviteContact,getCompanyTypes,*RoleApplication*}`, `useVerifyCompany/useUploadDocument/useDeleteDocument/useCompanyTypes/use*RoleApplication*`, типы `KYCDocument`, `RoleApplication`, неиспользуемый клиент `analytics/platform-dashboard/`. Навигация: нет флага `kycExempt`, набора `KYC_ALLOWED_PAGES`, требования `kyc` в `buildNavigation`, `isKycVerified`; `pageGuard` решает только по контексту. Типы: в `Capabilities` нет `kyc_level`/`kyc_status_code`/`kyc_last_reason`, в `userStore.Company` — `kycStatus`, в `CompanyStatusEntry` — `verification`, в `authStore` — `kyc_status`, в `accountsApi.Company`/`User` — `verification_status*`, `is_verified`, `kyc_*`; экран `screen` — `'loading' | 'main'`. Этап сделки `KYC_PENDING` (выведен из эксплуатации в B2B) снят из `codes`/`statusVariants`/`requestStatus`. Вход, сброс пароля, setup-password по приглашению и приглашение участника команды остались.
- **Операторская плоскость:** `SystemRole.ADMIN`, `OperatorRole`, break-glass, 16 страниц `Admin*`, `PlatformAdminShell`, `PlatformAdminDashboard`, `AdminAccessLogPage`. Администрирование людей — в CRM; настройки бизнеса — Settings Hub ERP (M1-ERP-09). **Бэкенд удалён в M1-ERP-02 волна 1a:** нет `OperatorRole`, `operator_role`, `OperatorPermission`, break-glass, пакета `core/admin_api` (`/api/v1/admin/queue|pulse|search|activity|access-log|break-glass|operator-roles|operator-permissions`), `is_platform_admin_viewer`/`operator_has_permission`/`ADMIN_VIEWER_CANNOT_ACT`. Администратор = `is_superuser` (`core.permissions.IsPlatformAdmin`); модель `SystemRole` и коды `ADMIN`/`USER` ещё живут до M1-ERP-03/05, но «ADMIN без компании» больше ничего не даёт. Поля `is_platform_admin` в `/me` и `users` и ключ `viewer.is_viewer` в хабе документов сделки — переходные, SPA их уже не читает (типы перегенерированы в волне 1b frontend); убрать из бэкенда при случае. **Фронтенд удалён (M1-ERP-02, волна 1a):** 17 `pages/Admin*`, `pages/admin-{catalog,kyc,users}`, `layouts/PlatformAdminShell`, `pages/PlatformAdminDashboard`, `components/Admin`, `components/PlatformAdmin`, `components/Layout/CommandPalette`, `api/adminApi`, `hooks/useAdmin`, `hooks/useViewerMode`, `lib/accessLogBuckets*`, `lib/operatorPermLabels`; в `userStore` больше нет `role`/`isViewerMode`/`isSuperuser`/`operatorPermissions` (и `is_platform_admin`/`operator_permissions` в `Capabilities`), в `authStore` — `role`; в `pageRegistry` нет флагов `admin`/`adminReachable`, гейт страниц — только контекст (KYC снят в волне 1c); `dealsListRoute` без `isPlatformAdmin`; force-действия оператора (КП force-approve, договор force-cancel) убраны из UI. Используемое не-операторскими экранами вынесено: `QuoteBuilderGrid`, `AICatalogMatchDialog` → `components/QuoteBuilder/`; `DetailKPIGrid`, `SubscriptionPayDialog`, форма карточки товара → `components/Shared/` (`product-form/`). Что из этого должно вернуться в Settings Hub — список в `docs/PROGRESS.md` (сессия M1-ERP-02 1a).
- **Фронт-офис и чат:** `Lead`, `LeadCreateView`, `AdminLeadsPage`, `Message`, `ChatDrawer`, `SupportButton`, обращения в поддержку. Лиды и диалог — CRM; вопросы клиента — бот CRM через `erp-mcp`. **Бэкенд удалён в M1-ERP-02 волна 1b:** нет моделей `Lead`, `Message`, `SupportTicket`, `SupportTicketMessage` (миграции `crm/0096_remove_lead_and_message`, `core/0005_remove_support_tickets`, `sourcing/0008_remove_attachment_message`), эндпоинтов `crm/leads`, `crm/messages`, `support/tickets`, `crm/deals/<id>/suggest-reply/`, WS `ws/chat/…`, сервисов `crm/services/{messaging,leads,ai_chat}`, `core/services.py`, задачи `archive_old_messages`, уведомлений о сообщениях в чате и о тикетах, пунктов Unfold «Лиды с сайта»/«Сообщения», `Attachment.message`. Граница доступа к сделке — `crm.services.user_can_access_deal` (бывший `user_can_access_deal_chat`). **Фронтенд удалён (M1-ERP-02, волна 1b frontend):** `components/Layout/{ChatDrawer,SupportButton}`, `components/Sourcing/DealChatPanel` (на `request-detail` и в конструкторе КП вместо него — `DealAttachmentsPanel`, вложения сделки), `api/supportApi`, `hooks/useSupport`, `crmApi.{getMessages,getRecentMessages,sendMessage,listLeads,routeLead,rejectLead,claimLead,suggestChatReply}`, типы `Message`/`Lead`, хуки `useLeads/useRouteLead/useRejectLead/useClaimLead/useSuggestChatReply` (`hooks/crm/leadsAi.ts` → `hooks/crm/ai.ts`), карточка «Входящие лиды» на дашборде, WS `ws/chat` (остался только `ws/notifications`), `Attachment.message`, подпись статуса обращения в `eventText`/`codes`; i18n `admin.*` (support/leads), `chat.*`, `dealChat.*`, `activity.{lead,support,deal.chat_message}`, `notification.support.ticket_created`, `apiErrors.LEAD_*`, `confirmActions.convertLead`; `src/api/schema.d.ts` перегенерирован. Старые строки журнала с кодом `deal.chat_message` печатаются сохранённым текстом. `RelationshipSource.LEAD` («Лид с лендинга») — источник записи книги контрагентов, не модель `Lead`: остаётся.
- **Контрагентские связи:** `CounterpartyRelationship`, слияние компаний по ИНН. Слияние по ИНН удалено в волне 1c вместе с KYC; `CounterpartyRelationship` — следующая волна.
- **Отрасль и бренд:** `EquipmentGroup`, `DomainType` ЖД, `DomainKeyword`, `AdminEquipmentGroupsPage`; «RailTech» в UI, письмах, PDF, i18n, тестах, дефолтах (`admin@railtech.uz`).
- **Инфраструктура B2B:** FileSystemStorage/MinIO (→ RustFS), прямой SDK Anthropic и `ANTHROPIC_API_KEY` (→ LiteLLM), `deploy/`, workflows, Caddy-фрагмент (→ `infra/`), `make ci-local` как протокол мержа (CI ансамбля — M0-INF-04).
- **Старые миграции:** 197 файлов и приложение с именем `crm` (ADR-0006). Данные старого прода переносит скрипт M5-ERP-01.

## 10. Self-check перед PR

- [ ] Задача по ID из ORCHESTRATOR §6, зависимости закрыты в `docs/PROGRESS.md`; ветка `m<N>/erp-<NN>-<slug>`.
- [ ] `make check-erp` зелёный; для контракта — `make contracts` зелёный, изменения с обеих сторон в одной вехе.
- [ ] Миграции: одна начальная на приложение (`showmigrations`), словари в ней; `migrate` на пустой базе даёт рабочую систему.
- [ ] Логика в `services/`, views/admin тонкие; права проверены в сервисе и покрыты тестом матрицы ролей.
- [ ] Негативные тесты для portal / integration / MCP (чужая компания, без токена, внутренний слой каталога).
- [ ] Ни одного импорта SDK провайдера моделей; алиасы LiteLLM; промпты в файлах.
- [ ] `grep -ri railtech apps/erp` пусто вне `.env.example`; отраслевых слов в UI нет.
- [ ] Весь текст через `t()`, ключи в `ru.json` и `en.json`; только shadcn и семантические токены.
- [ ] Типы API сгенерированы, ручных нет; `stage_code` для логики.
- [ ] UI-задача: скриншот сценария (1440 и 390 px), axe 0, консоль без ошибок — в описании PR.
- [ ] Секретов нет; `.env.example` актуален; `gitleaks` прошёл.
- [ ] Документация в том же PR: OpenAPI в `packages/contracts`, ADR при отклонении, runbook, строка в `docs/PROGRESS.md`; открытые вопросы — в `docs/QUESTIONS.md`.

## 11. Контекст, который нужно помнить

- Часовой пояс и рабочие часы: Asia/Tashkent, 09:00–18:00, пн–пт — для сроков, напоминаний, cron.
- Языки: интерфейс ru/en (uz — позже, через словари); письма клиенту — на языке контакта.
- Один клиентский Telegram-бот принадлежит CRM; ERP в Telegram не пишет — отдаёт события, бот говорит. ERP отправляет клиенту только транзакционные письма (ARCHITECTURE §18).
- Цены и наличие клиент видит только в Cabinet; лидам и боту вне кабинета — «по запросу» (режим `lead` в интеграционном поиске каталога).
- Остаток не хранится числом — считается из журнала движений (M4-ERP-01). Акт — по факту поставки, не по оплате; `OVERDUE` не проставляется — вычисляется из `due_date` (решения B2B, остаются).
- Платёжный провайдер и E-IMZO отложены до пилота (DECISIONS 2026-10-13).
