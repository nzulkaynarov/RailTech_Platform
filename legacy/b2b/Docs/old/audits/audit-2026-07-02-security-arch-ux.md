# Аудит системы RailTech B2B SaaS

**Дата:** 2026-07-02
**Аудитор:** Principal Engineer (security / architecture / UX)
**Область:** монорепозиторий RailTech_SaaS_B2B (Django 6 backend, React 18 frontend, Docker/Caddy инфраструктура)
**Метод:** статический анализ кодовой базы (backend ~45k LOC Python, frontend ~61k LOC TS/TSX), пять фаз — инвентаризация, безопасность, архитектура/качество, UX/UI, синтез. Проверка каждой находки по конкретному коду (file:line). Runtime-тесты не запускались; конфигурация прод-окружения (`.env`, branch protection) вне репозитория — помечена как «требует уточнения».

---

## 1. Executive Summary

RailTech B2B — это **зрелая, дисциплинированно спроектированная** B2B-платформа для закупки железнодорожного оборудования: полный жизненный цикл сделки (FSM DRAFT→…→CLOSED), КП с аудит-трейлом цен, PIM-каталог, KYC-верификация, мультитенантность через `CompanyMember`, подписки поставщиков, AI-нормализация заявок и real-time чат через WebSocket. Кодовая база демонстрирует признаки нескольких прошлых итераций харденинга: бизнес-логика строго вынесена в `services/` (Rule 8 соблюдён — нулевая логика в `admin.py`), tenant-scoping реализован двухуровнево (`get_queryset` + object-level permissions с учётом multi-seller confidentiality), секреты в код/историю git не утекали, refresh-токен в HttpOnly-cookie, access-токен только в памяти SPA. Тестовая база (**575 тест-функций в 87 файлах**) существенно больше, чем документирует CLAUDE.md (там указано «79 тестов»).

Критических и High-уязвимостей безопасности **не обнаружено**. Основные риски — не «дыры», а зоны недоведённого харденинга: dead-config валидаторов паролей, хранение токенов сброса пароля в теле `EmailLog`, ненадёжная резолюция IP для throttling за прокси. Главный архитектурный риск — **синхронные вызовы LLM (Anthropic) в обработчиках запросов**, блокирующие ASGI-воркеры. UX/UI — на высоком уровне (единый `PageShell`, `ConfirmActionDialog`, глобальный error-toast, near-perfect i18n-симметрия); единственная заметная брешь — удаление KYC-документа без подтверждения.

### Оценка зрелости по ISO/IEC 25010

| Характеристика | Оценка | Комментарий |
|---|---|---|
| **Functional suitability** | ★★★★★ Высокая | Полнофункциональный домен: FSM сделок, КП, контракты, инвойсы, KYC, подписки, AI. Реальные ORM-запросы (нет mock-данных). |
| **Reliability** | ★★★★☆ Выше среднего | Idempotency-middleware, optimistic locking (If-Match), FSM без тупиковых состояний, Sentry. Снижает: auto-migrate без backup-gate, 13 `except Exception`. |
| **Security** | ★★★★☆ Выше среднего | Сильная база (tenant isolation, JWT rotation+blacklist, enumeration-safe reset, magic-byte upload validation). Снижают: 4 Medium (см. реестр). |
| **Maintainability** | ★★★★★ Высокая | Rule 8 (logic в services), пакеты views/services по доменам, лимиты длины файлов/функций, api-contract CI gate. |
| **Usability** | ★★★★☆ Выше среднего | Единые UI-state примитивы, i18n RU/EN, WCAG-осознанность. Снижают: UX-01 (delete без confirm), локальные пробелы error-state. |
| **Performance efficiency** | ★★★☆☆ Средняя | Отличные aggregate-дашборды и N+1-free списки, но синхронные LLM/PDF в request-path и бесполезное кэширование по JWT. |

---

## 2. Реестр находок

Severity: **Critical** (эксплуатируется, тяжёлые последствия) → **High** → **Medium** → **Low** → **Info**. Отсортировано по приоритету реального риска/влияния.

### Безопасность

| ID | Severity | Место | Описание | Риск | Рекомендация |
|---|---|---|---|---|---|
| SEC-01 | Medium | `core/settings.py:441-454` vs `accounts/services/auth.py:130-167` | `AUTH_PASSWORD_VALIDATORS` объявлены, но `validate_password()` **не вызывается ни в одном** пути установки пароля (setup/reset/change). Проверено: `password_validation` встречается только в settings. Единственный контроль — `min_length=8` в сериализаторе. | Пользователь ставит `password`, `12345678`, `aaaaaaaa` — то, что `CommonPassword`/`NumericPassword` валидаторы должны блокировать. В связке с credential-stuffing повышает риск. | Вызвать `django.contrib.auth.password_validation.validate_password(pwd, user)` в `verify_and_setup_password`, `reset_password`, `change_user_password`. |
| SEC-02 | Medium | `notifications/emails.py:220-228`, `notifications/models.py:156-163` | Полный отрендеренный `body_html`/`body_text` письма (включая URL с `?uid=…&token=…`) пишется в `EmailLog` и просматривается в Unfold. | OWASP A09: любой Platform Engineer с доступом к Unfold или к бэкапам БД читает **неистёкший** токен сброса/setup и захватывает аккаунт до легитимного клика (токен валиден до использования / `PASSWORD_RESET_TIMEOUT`). | Редактировать query-string токенов перед записью тела, либо хранить только шаблон+получатель+статус, не рендер. |
| SEC-03 | Medium | `core/management/commands/core_seed.py:31,278-300` | `DEFAULT_SEED_PASSWORD = os.environ.get("SEED_USER_PASSWORD", "Demo1234!")`; сбрасывается при каждом прогоне; **нет guard на `DEBUG`/prod**. | Запуск `core_seed` в проде создаёт логинящиеся аккаунты (часть с `is_staff`/ролями) с публично известным паролем. | Отказываться выполнять при `DEBUG=False` (или явный `--force-prod`); не иметь статического fallback — требовать `SEED_USER_PASSWORD`. |
| SEC-04 | Medium | `core/settings.py:526-546` (нет `NUM_PROXIES`); прокси ставят XFF | DRF throttling идентифицирует клиента по `REMOTE_ADDR`; за Caddy/nginx это loopback прокси. Без `NUM_PROXIES` все анонимы либо делят один bucket (over-throttle), либо `X-Forwarded-For` можно подделать (under-throttle). | Обход per-IP throttles `login`/`register`/`password_reset` подделкой XFF — а это единственная защита от brute-force (см. SEC-06). | Задать `NUM_PROXIES` = точному числу доверенных прокси; прокси должен **перезаписывать** клиентский XFF, а не дополнять. |
| SEC-05 | Low/Med | `accounts/services/auth.py:140-153` | `verify_and_setup_password` не вызывает `revoke_user_refresh_tokens` (в отличие от reset) и setup-ссылка остаётся воспроизводимой до первой успешной установки пароля. | Утёкшая setup-ссылка (см. SEC-02 / логи прокси) реиграбельна для приглашённого, ещё не активированного участника. | Обрабатывать setup как reset: после установки вызывать `revoke_user_refresh_tokens(user)`; отклонять setup для уже активного пользователя с рабочим паролем. |
| SEC-06 | Low | `accounts/views/auth.py:286-291` | Нет per-account lockout / учёта неудачных попыток (нет `django-axes`). Защита — только per-IP `10/minute`. | Распределённый (ротация IP) brute-force одного email: 10/min × N IP. В связке с SEC-01 — реальный риск. | Добавить per-account lockout (например `django-axes`) с экспоненциальным backoff поверх IP-throttle. |
| SEC-07 | Low | `core/middleware.py:79,83-84` | WS-middleware всё ещё принимает `?token=<JWT>` как fallback (хотя SPA использует только one-time ticket, `frontend/src/lib/ws.ts`). | Долгоживущий access-JWT в query-string попадает в логи прокси/CDN — ровно та проблема, ради которой сделаны ticket-и. | Удалить ветку `?token=`, оставить только `?ticket=`. |
| SEC-08 | Low | `sourcing/views.py:115-135,156-162` | На AI-ветке загрузки проверяется только расширение имени файла (управляется атакующим) — нет magic-byte/content-type (в отличие от строгого `_validate_xlsx_signature` и `core/validators.py`). Байты сохраняются в `Attachment` дословно. | Произвольный контент хранится под безобидным расширением. Влияние ограничено — файлы отдаются `as_attachment=True`, не исполняются. | Прогонять `core.validators.validate_document_upload` и на AI-пути. |
| SEC-09 | Low | `core/settings.py:337,346-363` | `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`/`HTTPONLY`/HSTS применяются только при `_is_real_production` (`not DEBUG and PRODUCTION=="true"`). | Деплой с `DJANGO_DEBUG=False`, но забытым `PRODUCTION=true` работает без secure-cookie и HSTS. (На проде edge — Caddy — их выставляет, но defense-in-depth теряется.) | Включать эти флаги всегда при `DEBUG=False`; localhost-over-HTTP сделать явным opt-out. |
| SEC-10 | Low | `core/management/commands/init_superadmin.py:24-45` | `get_or_create(username=<local-part email>)`; коллизия при совпадении local-part. Пере-`set_password` + принудительный `is_superuser/is_staff/is_active=True` при каждом прогоне. | Намеренно отключённый суперадмин «воскресает» при следующем деплое. | Ключевать `get_or_create` по `email`; не переактивировать существующего суперадмина безусловно. |
| SEC-11 | Low | `core/health.py:29-30` | На 503 в ответ пишется `str(e)` исходного DB-исключения; `except Exception`. | Мелкая утечка внутренних деталей (хост/драйвер БД) неаутентифицированному клиенту health-эндпоинта. | Логировать исключение, отдавать клиенту обобщённый статус без строки ошибки. |
| SEC-12 | Info | `accounts/services/auth.py:133-134` | `reset_password` выставляет `is_active=True` по валидному токену сброса. | Деактивированный аккаунт может само-реактивироваться через reset-flow (в обход `toggle_user_active` guards). | Подтвердить намеренность; при необходимости не менять `is_active` в reset. |

### Архитектура / качество / производительность

| ID | Severity | Место | Описание | Риск | Рекомендация |
|---|---|---|---|---|---|
| ARCH-01 | High | `crm/views/ai.py:47`, `sourcing/views_ai_conversational.py:70`, `catalog/views/ai.py:54`, `sourcing/services_ai_preflight.py:136` | Синхронные `client.messages.create(...)` внутри HTTP-обработчиков. Каждый блокирует ASGI-воркер на всю латентность LLM (5–30с). | Под нагрузкой исчерпывается пул воркеров и встают несвязанные запросы. Смягчено throttle + `AI_IMPORT_ENABLED`, но не устранено. Bulk-Excel корректно вынесен в Celery — интерактивные AI нет. | Вынести LLM в Celery-задачи с task-id/polling (как Excel-импорт), либо выделенный async-пул. |
| ARCH-02 | Medium | `catalog/views/products.py:46-47` | `@cache_page` + `vary_on_headers("Accept-Language","Authorization")` на списке товаров. Ключ включает ротируемый JWT. | Hit-rate ≈0 для аутентифицированного трафика + распухание кэша per-token. Нарушает правило «не кэшировать authenticated ответы». | Варьировать по стабильному низкокардинальному ключу (anon / `owner_company_id`) или убрать page-cache для authenticated. |
| ARCH-03 | Medium | `crm/views/quotes.py:61,214`, `crm/views/deals.py:515` | WeasyPrint рендерится синхронно в request-path; самый рисковый — неаутентифицированный `PublicQuoteView` (рендер на cache-miss). | CPU-тяжёлый рендер блокирует воркер; неаутентифицированный путь может тригерить его on-demand. Async-путь уже есть (`crm/tasks.py:367`) — эти являются fallback. | Всегда пре-рендерить PDF при отправке КП; эндпоинты отдают 202/«генерируется». |
| ARCH-04 | Medium | `crm/views/analytics.py:149-244` | 10+ последовательных `.count()` вместо одного `aggregate()` (нарушает performance-конвенцию проекта). | Множество раздельных запросов к БД на один вызов аналитики. | Свернуть в `aggregate(total=Count(...), active=Count('id', filter=Q(...)))`. |
| ARCH-05 | Medium | `crm/views/deals.py:122,198` vs `:343,409`, `quotes.py:230,266` | Неоднородная форма ошибки: часть эндпоинтов `{"detail":"CODE"}`, часть `{"error":"CODE"}` — даже в одном файле. | Фронтенду приходится обрабатывать оба ключа; хрупкость контракта. | Стандартизировать один ключ-обёртку (коды SCREAMING_SNAKE оставить — они хороши). |
| ARCH-06 | Medium | `crm/services/fulfillment.py`, `crm/services/messaging.py` | Нет выделенных unit-тестов для сервисов с побочными эффектами (WebSocket-notify, архивация, смена состояния). | Регрессии в side-effecting-логике не ловятся. (В целом тест-база сильная — 575 функций.) | Добавить service-level тесты на `fulfillment` и `messaging`; подтвердить покрытие матрицы FSM-переходов в `test_fsm.py`. |
| ARCH-07 | Low/Med | 13 мест (`accounts/services/applications.py:71,77,146`, `crm/services/messaging.py:55`, `notifications/*`, `core/middleware.py:57`, `core/idempotency.py:66`, `core/health.py:30` и др.) | `except Exception` вопреки правилу проекта. Большинство — вокруг некритичных side-effects (email/подписка/архив), логируются через `logger.exception` — не «глотаются». | Маскируют неожиданные классы отказов; нарушают заявленный стандарт. | Сузить до конкретных исключений (`OSError`, `SMTPException`, `OperationalError`) или `# noqa: BLE001` с обоснованием (как в `sourcing/catalog_import.py:329`). |
| ARCH-08 | Low | `accounts/migrations/` (два `0019_*`) | Дубль префикса `0019` (реальная ветка), **корректно** сведён `0021_merge_20260624_2300`. `migrate` проходит чисто. | Гигиенический smell, путаница нумерации. Действие не обязательно. | Оставить как есть; учитывать при ревью будущих migrations. |
| ARCH-09 | Low | `crm/views/messages.py` (`ActivityLogViewSet.get_queryset`) | Ветвление на `user.is_superuser` при permission-классе `IsPlatformAdmin`. | Platform Admin без флага Django `is_superuser` молча ограничен только своими логами. | Использовать `is_platform_admin` консистентно. |
| ARCH-10 | Low | `sourcing/views.py:17-18` | Мёртвый комментарий про удалённый импорт. | Шум. | Удалить. |

### Инфраструктура / конфигурация / зависимости

| ID | Severity | Место | Описание | Риск | Рекомендация |
|---|---|---|---|---|---|
| INF-01 | Medium | `deploy/caddy/b2b.railtech.uz.caddy` | На прод-edge (Caddy) **нет rate limiting**; `limit_req_zone`-зоны есть только в `nginx/nginx.conf`, который не подключён ни к одному compose. **Смягчение (проверено):** DRF-throttling настроен в приложении (`login 10/min`, `anon 20/min`, per-endpoint). Т.е. приложенческий слой есть, edge-слой отсутствует. | Отсутствие edge-защиты до попадания в Django (сетевой abuse, до app-throttle). | Добавить Caddy `rate_limit` для `/api/v1/auth/*` и `/admin/` как defense-in-depth поверх DRF. |
| INF-02 | Medium | `ci.yml:394,404` | `pip-audit \|\| true` и `npm audit \|\| true` — job `security` всегда зелёный, не блокирует merge. | Новая уязвимая зависимость проходит CI незамеченной. | Убрать `\|\| true` (с `--ignore-vuln` для принятых рисков). |
| INF-03 | Medium | `deploy/caddy/b2b.railtech.uz.caddy:65` | Прод-CSP отдаётся как `Content-Security-Policy-Report-Only` — только предупреждает, не блокирует. | На origin SPA нет enforced CSP. | Убедиться, что консоль чиста, и переименовать в `Content-Security-Policy`. |
| INF-04 | Medium | `backend/entrypoint.sh:10-17`, `deploy-b2b.yml:135` | `manage.py migrate --noinput` при каждом старте контейнера; деплой = `compose up -d --build`. Нет ручного gate/backup-checkpoint. | Плохая/деструктивная миграция применяется к прод-БД молча. | Добавить pre-deploy `pg_dump` step или manual-approval environment gate. |
| INF-05 | Medium | `backend/requirements.txt` | Почти всё через `>=`-floor без lock-файла (`Django>=5.2` может резолвиться в 6.x и т.д.). Контраст: фронтенд использует `package-lock.json` + `npm ci`. | Невоспроизводимые сборки; авто-подтягивание breaking/свежеуязвимого релиза. | `pip-compile`/`uv` → hash-pinned lock, либо верхние границы. |
| INF-06 | Medium | `ci.yml`, `deploy-b2b.yml:42`, `e2e.yml` | Actions прибиты к мутабельным мажор-тегам (`checkout@v4` и т.п.), не к SHA. Значимее, т.к. `deploy-b2b.yml` идёт на **self-hosted runner на прод-VPS**. | Supply-chain: скомпрометированный/перетегированный action. | Прибить сторонние actions к полным commit SHA (Dependabot обновляет). |
| INF-07 | Medium | `docker-compose.yml:59,87` | `minio/minio:latest`, `minio/mc:latest`. | Невоспроизводимые/тихие breaking-обновления. Риск ограничен — MinIO за профилем `with-minio`, выключен в проде. | Прибить к релизному тегу/digest. |
| INF-08 | Low | `docker-compose.yml:122`, `docker-compose.prod.yml:97-99` | Прод-override не сбрасывает `volumes`, поэтому bind-mount `./backend:/app` сохраняется в проде — запускается host-дерево, а не образ. | Ломает иммутабельность/parity образа (контент совпадает, не баг корректности). | `volumes: !reset` + явные named volumes в prod backend. |
| INF-09 | Low | `requirements.txt:28` | `psycopg2-binary` в проде (bundled libpq/libssl, без линковки к системным security-обновлениям). | Не получает системные обновления OpenSSL. | Перейти на `psycopg[binary]` (psycopg3) или source-сборку в прод-образе. |
| INF-10 | Low | `docker-compose.yml:4`, `docker-compose.prod.yml:14`, `deploy-staging.yml:11` | Устаревшие комментарии «Neon Cloud», хотя Neon выведен 2026-06-19 (self-hosted DB-VPS). | Вводит операторов в заблуждение. | Обновить комментарии на DB-VPS. |
| INF-11 | Low | `e2e.yml:15,18-19,44` | Ночной Playwright по умолчанию бьёт в `https://b2b.railtech.uz` (прод). Спеки заявлены неинвазивными. | Любой будущий инвазивный спек попадёт в прод. | Перенаправить schedule на staging. |
| INF-12 | Clarify | вне репо (GitHub settings) | Являются ли CI-jobs required status checks — не видно из репозитория. | Если не enforced — тесты/линт не блокируют merge. | **Требует уточнения:** подтвердить branch protection на `backend-test`, `migration-check`, `frontend-lint`, `frontend-build`, `api-contract`, `docker-build`. |

### UX / UI / доступность

| ID | Severity | Место | Описание | Влияние на пользователя | Рекомендация |
|---|---|---|---|---|---|
| UX-01 | High | `frontend/src/pages/AdminKYCPage.tsx:103-111,218-227` | Удаление KYC-документа (`handleDeleteDoc`) выполняется сразу по клику на trash-иконку — без `ConfirmActionDialog`, в отличие от всех прочих destructive-действий. | Случайное необратимое удаление compliance-доказательства по одному промаху; несогласованность с собственным паттерном безопасности. | Обернуть в `ConfirmActionDialog`/`AlertDialog` (как reject-флоу). |
| UX-02 | Medium | `frontend/src/components/ui/chart.tsx:294-299` | Легенда графика через inline `style={{ backgroundColor }}` — прямой запрет Rule 4 (нужен `bg-[var(--color-chart-N)]`). Это vendored shadcn-код, но правило называет именно этот кейс. | Цвета легенды в обход theme-token системы. | Маппить цвет серии в CSS-var Tailwind-класс, либо задокументировать исключение для vendored-примитива. |
| UX-03 | Medium | `frontend/src/components/ui/LoadingSkeleton.tsx:11,43` | `bg-white dark:bg-background` (Rule 4 запрещает `bg-white`, нужен `bg-card`). Экспорты (`KPICardSkeleton` и др.) **нигде не импортируются** — мёртвый код (живой skeleton — другой файл `components/LoadingSkeleton.tsx`). | Стоячее нарушение токена + dead-code-мусор (low runtime). | Удалить неиспользуемые экспорты или починить `bg-white`→`bg-card`. |
| UX-04 | Medium | `frontend/src/pages/SourcingImportPage.tsx:37` (+ Profile/Settings в меньшей степени) | `const { data: deals } = useDeals()` без ветки `isError`/`isLoading`. | При отказе чтения — пустой селектор без объяснения. | Добавить `isLoading`/`isError` ветки (`ErrorState`/`LoadingRows` уже есть). |
| UX-05 | Low | vendored overlays + `Shared/OnboardingTour.tsx:69` | Scrim через `bg-black/50`, `bg-black/20` (Rule 4 запрещает `bg-black`). Для vendored-примитивов — норма; `OnboardingTour` — app-код. | Косметика/консистентность. | Принять для vendored; ввести семантический scrim-токен для `OnboardingTour`. |
| UX-06 | Low | `AdminKYCPage.tsx:221` (`h-7 w-7`) и др. table-контролы | Tap-таргеты 28–32px — ниже WCAG 2.5.5 AAA (44px), но проходят AA 2.5.8 (24px). | Риск на тач-устройствах; для desktop-admin приемлемо. | Для desktop — без действий; на мобильных увеличить hit-area. |
| UX-07 | Low | `frontend/src/components/Admin/AdminDataTable.tsx:309-338,556-571` | Кликабельные строки без per-row `role="button"`/`tabIndex`; клавиатура работает только через глобальный keydown-listener без явного «сфокусируйте таблицу». | Не самоочевидно для keyboard/AT-пользователей (контраст: stat-cards в `PageShell` сделаны верно). | Добавить roving-tabindex или начальный focusable-anchor в table body. |

### Документация

| ID | Severity | Место | Описание | Рекомендация |
|---|---|---|---|---|
| DOC-01 | Low | `CLAUDE.md` («Testing») | Заявлено «79 tests, ~30% coverage, известный долг в crm/accounts services». Реально: **575 тест-функций в 87 файлах**, долг во многом погашен (`test_quote_services.py`, `test_fsm.py`, `test_kyc_service.py` существуют). | Обновить CLAUDE.md — устаревшие цифры вводят в заблуждение при планировании. |
| DOC-02 | Low | `.env.example` (JWT-блок) | `JWT_ACCESS_TOKEN_LIFETIME_MINUTES`, `JWT_REFRESH_TOKEN_LIFETIME_DAYS`, `JWT_ROTATE_REFRESH_TOKENS` документированы, но `SIMPLE_JWT` в `settings.py:566-571` хардкодит значения и **не читает** эти переменные. | Убрать мёртвые переменные из `.env.example` или начать их читать в settings. |

---

## 3. Мёртвый / бесполезный код — кандидаты на удаление

| Кандидат | Место | Обоснование |
|---|---|---|
| Неиспользуемые skeleton-экспорты | `frontend/src/components/ui/LoadingSkeleton.tsx` (`KPICardSkeleton`, `ProductCardSkeleton`, `CatalogGridSkeleton`, `TableRowSkeleton`, `TableSkeleton`) | Экспортируются, но не импортируются нигде; живой skeleton — в другом файле `components/LoadingSkeleton.tsx`. Дополнительно содержат `bg-white` (нарушение токена). |
| `nginx/nginx.conf` | корень | Не подключён ни к одному compose (проверено — `frontend/nginx.conf` используется контейнером, edge — Caddy). Содержит нерабочие/слабые директивы (закомментированный SSL при `listen 443 ssl`, `unsafe-inline`, deprecated `X-XSS-Protection`). Удалить или явно пометить reference-only. |
| WS `?token=<JWT>` fallback | `core/middleware.py:79,83-84` | SPA использует только one-time ticket (`frontend/src/lib/ws.ts`); ветка мертва и вредна (JWT в query-string, см. SEC-07). |
| Мёртвый комментарий об удалённом импорте | `sourcing/views.py:17-18` | Шум. |
| JWT-переменные окружения | `.env.example` (JWT-блок) | Dead config — не читаются в `settings.py` (см. DOC-02). |

> Примечание: `deprecated manufacturer` FK на `Product` уже используется как legacy-fallback в `IsProductManagerOrAdmin.has_object_permission` (`core/permissions.py:128`) для pre-split строк — **не** кандидат на слепое удаление до миграции данных.

---

## 4. Дорожная карта приведения к международным стандартам

### Горизонт 1 — Quick wins (до 1 недели)

| Задача | Находки | Стандарт/практика | Эффект | Трудоёмкость |
|---|---|---|---|---|
| Вызвать `validate_password()` во всех password-flow | SEC-01 | OWASP ASVS 2.1 (Password Security) | Блок слабых паролей на всех путях | **S** |
| Редактировать токены в теле `EmailLog` (regex по query-string) | SEC-02 | OWASP A09 (Logging) | Устранить путь захвата аккаунта через audit-лог/бэкапы | **S** |
| Задать `NUM_PROXIES` + перезапись XFF на Caddy | SEC-04 | OWASP ASVS 11 (Business Logic / Anti-automation) | Надёжный per-IP throttling | **S** |
| Guard `core_seed` на `DEBUG=False` | SEC-03 | 12-Factor (dev/prod parity), least-privilege | Нет prod-аккаунтов с известным паролем | **S** |
| `revoke_user_refresh_tokens` в setup-password | SEC-05 | OWASP ASVS 3 (Session) | Инвалидация после установки пароля | **S** |
| Убрать `\|\| true` у `pip-audit`/`npm audit`; прибить actions к SHA | INF-02, INF-06 | Supply-chain (SLSA), CI gating | Блок уязвимых депов и action-injection | **S** |
| Добавить `ConfirmActionDialog` на удаление KYC-документа | UX-01 | Nielsen #5 (Error Prevention), WCAG консистентность | Нет случайного удаления compliance-доказательств | **S** |
| Обновить CLAUDE.md (тесты) + убрать мёртвый код/комментарии | DOC-01, DOC-02, ARCH-10, dead-code | Conventional docs, DRY | Корректная база для планирования | **S** |
| health-эндпоинт: не отдавать `str(e)` | SEC-11 | OWASP A05 (Misconfiguration) | Нет утечки внутренних деталей | **S** |

### Горизонт 2 — Среднесрочные (1–2 месяца)

| Задача | Находки | Стандарт/практика | Эффект | Трудоёмкость |
|---|---|---|---|---|
| Вынести интерактивные LLM-вызовы в Celery (task-id/polling) | ARCH-01 | 12-Factor VIII (Concurrency), async-паттерны | Устранить блокировку ASGI-воркеров под нагрузкой | **M** |
| Всегда пре-рендерить PDF async; эндпоинты → 202 | ARCH-03 | Performance, resilience | Убрать CPU-blocking из request/public-path | **M** |
| Убрать/исправить кэширование списка по JWT | ARCH-02 | Performance-конвенции проекта | Реальный cache hit-rate, нет памяти per-token | **S** |
| `aggregate()` в analytics вместо серии `.count()` | ARCH-04 | Performance-конвенции проекта | Меньше запросов на вызов аналитики | **S** |
| Стандартизировать форму ошибки API (один ключ) | ARCH-05 | REST API Guidelines (RFC 9457 Problem Details) | Единый контракт ошибок | **M** |
| Сузить `except Exception` до конкретных | ARCH-07 | Clean Code, соблюдение правил проекта | Не маскировать неожиданные отказы | **M** |
| `django-axes` per-account lockout | SEC-06 | OWASP ASVS 2.2 (Anti-bruteforce) | Защита от распределённого stuffing | **M** |
| Enforced CSP на проде + edge rate-limit в Caddy | INF-03, INF-01 | OWASP Secure Headers, defense-in-depth | Блок XSS-инъекций, сетевой anti-abuse | **M** |
| pip lock-файл (`uv`/`pip-compile`) + `psycopg3` | INF-05, INF-09 | 12-Factor II (Dependencies), reproducible builds | Воспроизводимые сборки, актуальный TLS | **M** |
| Backup-gate перед auto-migrate в деплое | INF-04 | SRE / change management | Защита от деструктивной миграции | **M** |
| Service-тесты `fulfillment`/`messaging`; magic-byte на AI-upload; single-use WS-token cleanup | ARCH-06, SEC-08, SEC-07 | Test coverage, OWASP A08 | Ловля регрессий, валидация загрузок | **M** |

### Горизонт 3 — Стратегические (рефакторинг/смена подходов)

| Задача | Находки | Стандарт/практика | Эффект | Трудоёмкость |
|---|---|---|---|---|
| Выделенный async-пул/сервис для всех AI-нагрузок (очередь + backpressure + бюджет токенов) | ARCH-01 | Scalability, cost-control | Изоляция дорогих LLM от request-serving; управляемая стоимость | **L** |
| Иммутабельные образы в проде (`volumes: !reset`, no bind-mount, SHA-digest base images) | INF-08, INF-07 | 12-Factor V (Build/Release/Run), reproducibility | Точное соответствие «что собрано = что запущено» | **L** |
| Полный аудит user-journey и упрощение многошаговых цепочек (buyer RFQ→pay, seller bid→quote в `QuoteBuilderGrid` 804 строки) | UX-04, UX-07 (+ не до конца прослеженные journey) | Nielsen эвристики, WCAG 2.1 AA | Меньше шагов до цели, полное keyboard-a11y | **L** |
| Аргон2 как основной password hasher; ротация к SHA-256-signed короткоживущим токенам вместо `default_token_generator` | SEC-12, defense-in-depth | OWASP ASVS 2.4 (Credential Storage) | Усиленное хранение/жизненный цикл кредов | **M** |
| Формальный API-error-контракт (RFC 9457) на уровне DRF exception handler | ARCH-05 | REST API Guidelines | Единый machine-readable контракт ошибок | **M** |

---

## Приложение — что сделано хорошо (проверено в коде)

- **Tenant isolation / IDOR:** двухуровневая защита — `get_queryset` scoping (`crm/views/deals.py:77-110`, `billing.py`, `catalog/views/offers.py`) + object-level `IsCompanyMemberOrPlatformAdmin` (`core/permissions.py:155-206`) с multi-seller confidentiality (`seller_visible_deal_ids`). Detail-actions ре-авторизуются в сервисах.
- **Rule 8 (logic в services):** grep по `admin/` — нулевая inline бизнес-логика; admin/views — тонкие обёртки.
- **AuthN/session:** JWT rotation + blacklist-after-rotation; refresh в HttpOnly path-scoped cookie; access только в памяти SPA; refresh-mutex против гонок; enumeration-safe forgot-password с dual-throttle.
- **Инъекции/SSRF:** нет `.raw()`/`.extra()`/`cursor.execute`; всё через ORM; параметризованный `TrigramSimilarity`; AI-байты грузятся напрямую, URL-ов пользователя не фетчит.
- **Secrets:** чистая история git (проверено), нет tracked `.env`, `.secrets.baseline` (detect-secrets), `SECRET_KEY` обязателен в проде.
- **Upload:** `core/validators.py` — extension + content-type + size + **magic-byte**; SVG намеренно убран (stored-XSS); UUID-имена файлов.
- **FSM:** матрица переходов без тупиковых состояний; `CLOSED_WON` требует подписанного контракта; force-override требует reason.
- **Frontend:** единые `PageShell`/`AdminDataTable`/`ConfirmActionDialog`; глобальный mutation error-toast; сравнение по `stage_code` (не по переведённому name); i18n RU/EN симметрия (расхождение — только 4 русских plural-формы); нет `alert()`, нет hex, нет `text-[Npx]`.
- **Инфраструктура:** non-root контейнеры (`gosu`→`appuser`), healthchecks, порты на `127.0.0.1`, deploy-секреты через GitHub environment с `umask 077`/`chmod 600`, presence-check секретов, `permissions: contents: read`, separate migration-check + api-contract CI-jobs.

---

*Конец отчёта. Пункты «требует уточнения» (INF-12 branch protection, прод-`.env`) не проверялись, т.к. находятся вне репозитория.*
