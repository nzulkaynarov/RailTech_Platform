# ТЗ — оставшиеся задачи (2026-07-07)

**База:** main @ `937b3a4`. Аудит 2026-07-02 (архитектура + безопасность) полностью закрыт в коде (PR #230–237).

## Важная поправка к бэклогу

Разведка по коду (2026-07-07) показала, что **значительная часть продуктового бэклога уже реализована** — roadmap-доки (`ai-features-roadmap-2026-06-18.md`, `master-scope-2026-06-24.md`) устарели:

| Считалось открытым | Факт |
|---|---|
| AI F6 #1–#8 «not started» | **Все 8 реализованы** за `run_ai_job` (`backend/sourcing/tasks_ai.py`), с throttle-скоупами и тестами |
| #5 билингв-нормализация | Реализована через `QuoteItem.name_canonical` (свёрнута в extract-вызов) |
| #1 семантический матч | Реализован: `match_lines_to_catalog` (trigram shortlist → Claude json_schema, DB-grounded) |
| CB-send (КП офлайн-контакту) | Реализовано (`crm/tasks.py:387 send_quote_email`, тест `test_quote_public_send.py`) |
| CB-public-link | Реализовано (`PublicQuoteView`, `/api/v1/public/quotes/<token>/`) |
| CB-deal-for-offline | Реализовано (`crm/views/deals.py:145`, тест `test_offline_deal.py`) |

**Реально осталось** (обосновано кодом): инфра-хардненинг (INF-01/04/05/07/08/09), CB-invite + ContactViewSet + фронтенд клиентской базы, калибровка AI-порога, деприкация WorkspaceRole (ADR-0005 Phase E U3), решение по cut-list ADR-0006.

---

## Раздел 1. Инфраструктура (приоритет — высший, риск-driven)

### INF-04 — Backup-gate перед авто-миграцией ⚠️ наивысший инфра-риск

**Проблема.** `backend/entrypoint.sh:10-17` безусловно выполняет `migrate --noinput` при старте web-контейнера (gunicorn/daphne). В `deploy-b2b.yml` НЕТ шага `pg_dump` — новый образ поднимается (`compose up -d --build`), и `entrypoint.sh` накатывает миграции на живую прод-БД без снапшота. Откат сломанной миграции невозможен без свежего дампа. Есть только rsync-исключённая директория `backups/` (никто в неё не пишет из workflow) и aspirational-TODO про Neon PITR (`deploy/RUNBOOK-b2b-vps.md:247`, устарел — БД давно на своём VPS).

**Решение (2 части):**

1. **Развязать миграции от `entrypoint.sh` в проде, оставив локальную DX.**
   - В `entrypoint.sh` гейтить авто-migrate переменной: `if [ "${AUTO_MIGRATE:-true}" = "true" ]; then … migrate … fi` внутри `case gunicorn|daphne`. Локально/dev — `AUTO_MIGRATE` не задан → `true` (поведение не меняется). Прод-`.env` (heredoc в `deploy-b2b.yml`) выставляет `AUTO_MIGRATE=false`.
   - `collectstatic` оставить как есть (идемпотентно, не разрушительно).

2. **Явный gated-шаг в `deploy-b2b.yml` между «Render .env» и «Deploy backend stack»:**
   ```yaml
   - name: Pre-deploy DB backup (gate)
     run: |
       set -euo pipefail
       TS=$(date -u +%Y%m%dT%H%M%SZ)
       mkdir -p "$DEPLOY_DIR/backups"
       # pg_dump через WireGuard в custom-format (быстрый restore, параллельный)
       $COMPOSE run --rm -T backend sh -c \
         "pg_dump \"$DATABASE_URL\" -Fc" > "$DEPLOY_DIR/backups/predeploy-$TS.dump"
       test -s "$DEPLOY_DIR/backups/predeploy-$TS.dump"  # непустой → иначе fail деплоя
       ls -t "$DEPLOY_DIR/backups"/predeploy-*.dump | tail -n +15 | xargs -r rm  # держим 14
   - name: Apply migrations (after backup)
     run: $COMPOSE run --rm -T backend python manage.py migrate --noinput
   ```
   Шаг «Deploy backend stack» остаётся, но теперь миграции уже применены явно после успешного дампа; `AUTO_MIGRATE=false` не даст воркеру/web повторно мигрировать.

   > Примечание: `pg_dump` внутри backend-образа требует наличия клиента `postgresql-client` — проверить, что он в `backend/Dockerfile` runtime-стадии; если нет — добавить (`apt-get install -y postgresql-client` в runtime-стадию, ~15 МБ).

**Критерии приёмки.**
- [ ] Симуляция: локально `AUTO_MIGRATE=false docker compose up backend` → web стартует БЕЗ применения миграций (проверить логом).
- [ ] Локально прогнать шаг backup вручную → в `backups/` появляется непустой `.dump`, `pg_restore --list` его читает.
- [ ] Провальный `pg_dump` (например, неверный `DATABASE_URL`) → workflow-шаг падает, «Apply migrations» и «Deploy» не выполняются.
- [ ] `deploy/RUNBOOK-b2b-vps.md` дополнен процедурой restore из `predeploy-*.dump` (`pg_restore -d "$DATABASE_URL" --clean --if-exists file.dump`).

**Тесты.** Нет unit-тестов (инфра); добавить shell-lint (`shellcheck backend/entrypoint.sh`) в CI security-job если тривиально. Ручная проверка по чек-листу выше на dev-стеке.

**Риск/откат.** Средний — трогаем деплой-путь. Откат: revert PR (entrypoint снова мигрирует; `AUTO_MIGRATE` дефолтит в `true`). Первый прод-деплой с изменением проверить пошагово (можно `workflow_dispatch`).

**Оценка:** ~0.5 дня.

---

### INF-01 — Edge rate-limit в Caddy для `/api/v1/auth/*` и `/admin/*`

**Проблема.** `deploy/caddy/b2b.railtech.uz.caddy` — «голый» reverse-proxy без единой rate_limit-директивы; `/api/*`, `/admin/*` идут прямо на `127.0.0.1:8000`. Единственный слой — DRF app-throttle (`core/settings.py:540-561`): покрывает `/api/v1/auth/*` именованными скоупами (`login 10/min`, `register 5/h`, `password_reset 5/h`, …), но **`/admin/*` (Django session-вьюхи) НЕ покрыт DRF-троттлингом вообще** — брутфорс/скан админки не ограничен ничем на edge.

**Решение (2-pronged):**

1. **Основное — модуль `caddy-ratelimit` на host-Caddy.** Стандартный Caddy НЕ содержит `rate_limit`; нужен модуль `github.com/mholt/caddy-ratelimit`, собранный через `xcaddy`.
   - Собрать бинарь на DB/app-VPS: `xcaddy build --with github.com/mholt/caddy-ratelimit`, заменить host-бинарь Caddy, `systemctl restart caddy`. Задокументировать в `deploy/RUNBOOK-b2b-vps.md` (сборка + версия модуля).
   - В `deploy/caddy/b2b.railtech.uz.caddy` в `@backend`-handle добавить зоны:
     ```
     rate_limit {
       zone auth   { match { path /api/v1/auth/* } key {remote_host} events 30  window 1m }
       zone admin  { match { path /admin/*      } key {remote_host} events 60  window 1m }
     }
     ```
     (числа — потолок «злоупотребления», НЕ нормальный трафик; login-lockout `login_guard.py` остаётся вторым слоем.) Требует глобального `order rate_limit before reverse_proxy` в host-`/etc/caddy/Caddyfile` (задокументировать — файл вне репо).

2. **Дополнительно — покрыть `/admin/login` на app-слое** (быстро, не зависит от пересборки Caddy). `login_guard.py` уже ловит `/api` login; расширить `user_login_failed`-сигнал так, чтобы Django-admin login тоже инкрементировал per-IP счётчик (сейчас — только detection, см. CLAUDE.md Auth Flow). Либо добавить лёгкий middleware, троттлящий `POST /admin/login/` по IP через тот же Redis-механизм, что `login_guard`.

**Критерии приёмки.**
- [ ] На стенде с собранным Caddy: >30 запросов/мин на `/api/v1/auth/token/` с одного IP → часть получает `429` от Caddy (до DRF).
- [ ] >60 запросов/мин на `/admin/` с одного IP → `429`.
- [ ] Нормальный пользовательский трафик (открытие SPA, обычная работа) не ловит 429 — проверить eyes-on.
- [ ] RUNBOOK описывает пересборку Caddy с модулем и версию.

**Тесты.** Edge — интеграционно на стенде (нет unit). App-часть (`/admin/login` throttle) — pytest на middleware/сигнал по образцу `core/test_throttle_ident.py`.

**Риск/откат.** Средний — трогаем host-Caddy (вне Docker, ручной reload). Откат: убрать `rate_limit`-блок, `systemctl reload caddy` (бэкап конфига `b2b.caddy.bak-<ts>` уже практикуется). Сборку Caddy тестировать на стенде до прода.

**Оценка:** ~1 день (в основном возня с xcaddy + RUNBOOK).

---

### INF-05 / INF-09 — Пиннинг зависимостей + lock-файл; уход с psycopg2-binary

**Проблема.** `backend/requirements.txt` — 55 строк с `>=`-полами, ноль `==`, нет lock-файла (`git grep` не находит `requirements.lock`/`poetry.lock`/`uv.lock`). Сборка невоспроизводима: `docker build` в разные дни ставит разные версии. `psycopg2-binary>=2.9` (INF-09) — binary-вариант не рекомендован для прода (бандлит свой libpq, конфликты/безопасность). Конфликт версий: base пинит `pytest>=9.0`, dev — `pytest>=8.0.0`.

**Решение.**
1. **Ввести pip-tools.** Переименовать текущий `requirements.txt` → `requirements.in` (сохранив `>=`-полы и `<`-кэпы как constraints замысла). Добавить `pip-tools` в dev. Компилировать хэшированный lock: `pip-compile --generate-hashes --output-file requirements.txt requirements.in`. `requirements.txt` становится сгенерированным lock (точные `==` + хэши); Dockerfile ставит `pip install --require-hashes -r requirements.txt`.
2. **Аналогично dev:** `requirements-dev.in` (`-c requirements.txt` + dev-инструменты) → `requirements-dev.txt`. Разрешить конфликт pytest (единый пол `>=9.0`).
3. **psycopg2-binary → psycopg2 (source).** В `requirements.in`: `psycopg2>=2.9,<3`. Проверить, что `backend/Dockerfile` builder-стадия имеет `libpq-dev` + `gcc` (по разведке — есть), а runtime-стадия — `libpq5` (рантайм-либа; добавить если нет).
4. **CI-гейт дрейфа:** добавить в `ci.yml` шаг «lock up-to-date» — `pip-compile --dry-run` и `git diff --exit-code` (по образцу api-contract-гейта), чтобы `.in` и `.txt` не расходились.

**Критерии приёмки.**
- [ ] `docker build backend` воспроизводимо ставит одинаковые версии из lock; `pip install --require-hashes` проходит.
- [ ] `psycopg2` (не binary) в проде; backend поднимается, `/health/` = DB up (проверить на dev-стеке с прод-подобным Dockerfile).
- [ ] Полный backend-сьют зелёный на новом lock.
- [ ] CI-шаг ловит рассинхрон `.in`/`.txt`.
- [ ] pip-audit (security-job) проходит на новых пинах.

**Риск/откат.** Средний — обновление транзитивных зависимостей может подтянуть новые версии (numpy/pandas/redis/anthropic уже с кэпами — сохранить). Компилировать lock, прогнать ПОЛНЫЙ сьют, зафиксировать. Откат: revert к floor-`requirements.txt`.

**Оценка:** ~0.5–1 день.

---

### INF-07 — Пиннинг MinIO-образов

**Проблема.** `docker-compose.yml:60,88` — `minio/minio:latest` + `minio/mc:latest`. Хоть и за `profiles:["with-minio"]` (dev-opt-in, в проде выключено — FileSystemStorage), `:latest` = невоспроизводимость + риск ломающего апдейта у того, кто гоняет S3-профиль.

**Решение.** Запинить на конкретные release-теги в `docker-compose.yml` (и в `docker-compose.prod.yml`, где сервисы переобъявлены): `minio/minio:RELEASE.2025-…` и `minio/mc:RELEASE.2025-…` (взять актуальный стабильный на момент реализации; учесть заметку в prod-compose про glibc/`x86-64-v2` — прод VPS не тянет свежие minio, но профиль там не активируется, так что для dev берём свежий стабильный).

**Критерии приёмки.**
- [ ] `docker compose --profile with-minio up` поднимает MinIO на запиненном теге; бакеты создаются (`minio-init` отрабатывает).
- [ ] Нет `:latest` в compose-файлах для minio/mc.

**Риск/откат.** Низкий (dev-only профиль). **Оценка:** ~15 минут.

---

### INF-08 — Сброс унаследованного `./backend:/app` bind-mount в проде

**Проблема.** `docker-compose.prod.yml` переопределяет только `/app/staticfiles` и `/app/media` (named prod-тома) и сбрасывает `depends_on: !reset`, но НЕ сбрасывает `volumes:` — базовый `./backend:/app` (`docker-compose.yml:123`) наследуется в прод-backend/celery. Host-дерево `/opt/railtech-b2b/backend` теневит `/app` собранного образа → прод фактически исполняет rsync-нутый исходник, а не immutable-образ (расходится с идеей воспроизводимого деплоя; потенциальный источник «на проде другой код»).

**Решение.** В `docker-compose.prod.yml` для `backend`, `celery-worker`, `celery-beat`, `celery-worker-ai` заменить `volumes:` на `volumes: !reset` + пере-объявить ТОЛЬКО named-тома (без `./backend:/app`):
```yaml
backend:
  volumes: !reset
    - backend_static_prod:/app/staticfiles
    - backend_media_prod:/app/media
celery-worker:
  volumes: !reset
    - backend_media_prod:/app/media
celery-worker-ai:
  volumes: !reset
    - backend_media_prod:/app/media
celery-beat:
  volumes: !reset
    - backend_media_prod:/app/media   # если beat пишет медиа; иначе без media
```
Проверить `docker compose -f docker-compose.yml -f docker-compose.prod.yml config`, что `/app` больше НЕ имеет host-bind.

**Критерии приёмки.**
- [ ] `config` merged: у прод-backend нет `source: ./backend, target: /app`.
- [ ] Прод-образ исполняет `COPY`-нутый код (проверить: изменить файл в host-дереве после build → в контейнере он не виден).
- [ ] Все 4 сервиса видят `backend_media_prod` (регресс #235 не сломан).
- [ ] `/health/` зелёный, PDF-рендер и импорты работают.

**Риск/откат.** Средний — меняем прод-семантику монтирования. Валидировать `config` + деплой пошагово. Откат: revert. **Оценка:** ~0.5 дня (в основном верификация).

---

## Раздел 2. Продукт (implementation-ready)

### CB-invite — регистрация офлайн-клиента по инвайту, привязанному к его Company

**Цель (петля привлечения, `client-base-design-2026-06-24.md` фаза 4).** Продавец создал офлайн-клиента (`Company(is_registered=False)` + `Contact`, `create_offline_client`), отправил КП по публичной ссылке. Теперь — пригласить контакт **зарегистрироваться и заявить существующую Company** (флип `is_registered=True`), а не создавать дубликат. Так офлайн-книга продавца превращается в зарегистрированных пользователей платформы.

**Текущее состояние.** `Contact` (`accounts/models/company.py:384`), `Company.is_registered` (`:157`), `create_offline_client` (`accounts/services/clients.py:56`) — есть. Инвайта клиента НЕТ (есть только `invite_member` — приглашение сотрудника в свою компанию, другое). Нет company-bound signup-токена, нет сигнала флипа `is_registered`.

**Решение.**
1. **Токен.** Подписанный (itsdangerous/Django signer, как `setup_password`) токен, кодирующий `company_id` + `contact_id` + TTL (напр. 14 дней). Хранить не обязательно (stateless signed), но лучше — модель `ClientInvite(company, contact, created_by, token_hash, expires_at, accepted_at)` для аудита и одноразовости.
2. **Сервис** `accounts/services/clients.py`: `send_client_invite(*, seller, contact_id) -> (invite, error_code)` — проверяет, что контакт принадлежит клиентской компании продавца (scoped, как `seller_clients`), что компания ещё `is_registered=False`, генерит токен, шлёт письмо.
3. **Email-шаблон** `backend/templates/emails/invite_client.{html,txt,_subject.txt}` (канал `transactional`), ссылка `FRONTEND_URL/register?invite=<token>`.
4. **Эндпоинт отправки** — `@action` на будущем `ContactViewSet` (см. ниже) или на deals: `POST /api/v1/accounts/contacts/<id>/invite/`. Тонкая обёртка → сервис. Throttle-скоуп `client_invite` (напр. `20/hour`).
5. **Приём инвайта в регистрации.** Расширить register-флоу (`accounts/views/auth.py` register): если пришёл валидный `invite`-токен — вместо создания новой Company привязать нового `CustomUser` к существующей `Company` (флип `is_registered=True`, создать `CompanyMember(role=OWNER, is_active=True)`, пометить `ClientInvite.accepted_at`). Дедуп по INN: если `stated_inn` совпал с уже зарегистрированной компанией — не сливать автоматически, увести на «join existing company»-путь (см. post-deploy-todos COMPANY_INN_TAKEN) или пометить для admin company-merge.
6. **Гварды.** Инвайт валиден один раз; истёкший/использованный → `CLIENT_INVITE_INVALID`. Нельзя пригласить в уже зарегистрированную компанию (`COMPANY_ALREADY_REGISTERED`).

**Критерии приёмки.**
- [ ] Продавец шлёт инвайт контакту → письмо в `EmailLog` (DEBUG-лог), ссылка с токеном.
- [ ] Приём токена в register → новый пользователь становится OWNER существующей `Company`, `is_registered` флипнулся в `True`, дубликат НЕ создан.
- [ ] Повторный приём того же токена → `CLIENT_INVITE_INVALID`.
- [ ] Инвайт в чужую (не свою клиентскую) компанию отклонён (scoped).
- [ ] i18n-ключи ошибок в ru+en; ошибки в форме `{"detail": CODE}`.

**Тесты.** `accounts/tests/test_client_invite.py`: генерация+отправка (mock email), успешный приём (флип + OWNER + no-dup), истёкший/повторный токен, scope-guard, INN-коллизия. Обновить frontend register-компонент под `?invite=`.

**Риск.** Средний — трогаем регистрацию (чувствительный путь). Плотные тесты + eyes-on. **Оценка:** ~1.5–2 дня (backend + фронт register).

---

### ContactViewSet + фронтенд клиентской базы (ADR-0005 Phase F «Клиенты-REST»)

**Цель.** REST-CRUD для `Contact`/клиентских компаний + UI: страница «Клиенты» продавца и «выбрать или создать клиента» в потоке создания сделки/КП. Замыкает CB-фазу 3 и Phase F ADR-0005.

**Текущее состояние.** `ContactViewSet`/`ContactSerializer`/route — НЕТ (grep пусто). Нет фронтенд-страницы клиентов. Сервисы `seller_clients(user)`, `find_client_company`, `create_offline_client` — есть.

**Решение (backend).**
1. `accounts/serializers.py`: `ContactSerializer` (nested read / flat write, `_data`-суффикс по конвенции), `ClientCompanySerializer` (id, name, inn/stated_inn, is_registered, contacts[]).
2. `accounts/views/clients.py` (новый или в существующем): `ContactViewSet` (ModelViewSet), `get_queryset` — строго scoped через `seller_clients(user)` (только контакты клиентских компаний команды продавца; platform-admin — read-all). Permissions: `IsAuthenticated` + capability `sell`. `@action invite` (см. CB-invite).
3. Роут `core/urls.py`: `router.register(r"accounts/contacts", ContactViewSet)` + endpoint списка клиентских компаний `GET /api/v1/accounts/clients/` (обёртка над `seller_clients`).
4. Дедуп на create: переиспользовать `find_client_company` (мягкий, «дубликатов не боимся», админ мержит на KYC).

**Решение (frontend).**
1. `frontend/src/api/` — `contactsApi`/расширить `accountsApi`: list/create/update/delete + invite.
2. `frontend/src/hooks/useAccounts.ts` — `useClients`, `useCreateClient`, `useSendClientInvite` (React Query).
3. Страница `frontend/src/pages/ClientsPage.tsx` (продавец, в AppShell seller-контексте) — `ResponsiveDataTable` со списком клиентских компаний+контактов, кнопки: создать офлайн-клиента, пригласить, открыть сделку. Навигация — hash `#clients`, добавить в `config/navigation.tsx` под `side:'sell'` + `requires`.
4. Компонент «выбрать или создать клиента» в `CreateDealDialog`/КП-потоке.
5. i18n ru+en, semantic tokens, shadcn/ui (Rule 4/5).

**Критерии приёмки.**
- [ ] Продавец видит только своих клиентов (scoped); чужие — 404/пусто.
- [ ] CRUD контактов работает; создание офлайн-клиента из UI = `create_offline_client`.
- [ ] Кнопка «пригласить» дергает CB-invite.
- [ ] OpenAPI-схема регенерирована, `schema.d.ts` синхронен (api-contract-гейт).
- [ ] Компонентные тесты страницы (по образцу PR #234); backend-тесты scope/CRUD.

**Риск.** Низкий-средний (новая изолированная поверхность). **Оценка:** ~3–4 дня (backend + фронт + тесты).

---

### CB-auto-populate — ⚠️ требует уточнения (возможный блокер)

Дизайн (`client-base-design-2026-06-24.md:63`) помечает auto-populate как «зависит от MS-routing». При этом `DealSellerRouting` (модель multi-seller routing) в коде **есть** (Move 2). Нужно уточнить у владельца/в дизайне, что именно понимается под «MS-routing» блокером — полный ли UX-маршрутизации входящих заявок или только модель. **До уточнения — не начинать.** Вынести отдельным вопросом.

---

### AI — калибровка `AI_DRAFT_MATCH_CONFIDENCE` на реальных данных

**Цель.** Все 8 AI-фич работают; единственный оставшийся AI-пункт — подобрать порог автопривязки (`AI_DRAFT_MATCH_CONFIDENCE=0.9`, `settings.py:677`) по фактическим данным: сейчас значение — догадка.

**Решение.**
1. **Телеметрия.** Логировать (структурно, или лёгкая модель `AIMatchOutcome`) для каждого fuzzy-матча в `draft_quote`: `line_raw`, `candidate_product_id`, `confidence`, и последующий сигнал — продавец оставил привязку / переназначил / удалил (через `ReassignProductDialog` / правки КП). Это ground-truth «был ли автоматч верным».
2. **Отчёт.** Management-команда `python manage.py ai_match_report` — precision/recall по порогам (0.7/0.8/0.85/0.9/0.95): при каком пороге автопривязки минимум ложных при приемлемом покрытии.
3. **Тюнинг.** По ≥N реальных заявок выставить порог; вынести в env (уже есть) — менять без деплоя кода.

**Критерии приёмки.**
- [ ] Исходы матчей пишутся; команда-отчёт считает precision/recall по порогам.
- [ ] Рекомендация порога с обоснованием (в ops-док).

**Риск.** Низкий. **Оценка:** ~1 день на телеметрию+отчёт; тюнинг — по мере накопления данных (нужен реальный трафик).

---

## Раздел 3. Архитектурный долг (ADR-реконсиляция)

### ADR-0006 — решение по cut-list Leads/Analytics (нужно решение владельца)

**Факт.** Фронтенд-страницы Leads/Analytics/Clients удалены (cut исполнен). Но бэкенд жив: `crm/views/leads.py` (`LeadViewSet`), `crm/views/analytics.py` (`CRMAnalyticsView` — orphan; `DashboardAnalyticsView` + `TimeToFirstQuoteView` — используются дашбордом/TTFK), `Lead`-модель, роуты. ADR-0006 объявлял Leads/Analytics/Clients как CUT.

**Рекомендуемый путь (не чистый cut, а амендмент ADR):**
- Оставить `DashboardAnalyticsView` + `TimeToFirstQuoteView` (реально питают Operations Inbox / TTFK-метрику).
- Удалить orphan `CRMAnalyticsView` + его роут `/api/v1/crm/analytics/`, если ничто не дергает (проверить фронт/тесты).
- По `Lead`: решить — используется ли lead-capture где-то (публичная форма?). Если нет входящей точки — удалить `LeadViewSet`+модель+admin+роут (миграция удаления) ИЛИ явно оставить и **амендментом ADR-0006** зафиксировать «Leads-backend сохранён под будущий lead-capture».
- Обновить ADR-0006 (раздел CUT) под фактическое решение.

**Действие:** сначала вопрос владельцу — Leads планируется? Затем cut-миграция ИЛИ ADR-амендмент. **Оценка:** ~0.5 дня после решения.

---

### ADR-0005 Phase E U3 — деприкация WorkspaceRole как enforcement-слоя ⚠️ крупный рефактор

**Цель (ADR-0005:62-67).** Сделать `CompanyRole` (`member_has_permission`) единственным источником прав; убрать `WorkspaceRole` из ветвления бизнес-логики (оставить как derivation-fallback/лейбл).

**Текущее состояние (по разведке — WorkspaceRole всё ещё живой enforcement):**
- КП approval-FSM гейтит на нём: `crm/services/quotes.py:929/989/1007/1025` (`has_workspace_role(actor, company_id, [SALES_MANAGER/FOREIGN_TRADE_SPECIALIST/DIRECTOR])`).
- `crm/services/approvals.py:39` — фильтр OWNER по `role__code=OWNER`.
- `accounts/services/permissions.py:67/129/398` — `WorkspaceRoleCode.OWNER`.
- `roles.py:17-49` — маппинг legacy WorkspaceRole → дефолтный CompanyRole-шаблон (уже есть — основа миграции).
- `CompanyMember.role` FK на `WorkspaceRole` (`company.py:509`, помечен «legacy, kept during transition»).

**Решение (поэтапно, чтобы не сломать approval-цепочку):**
1. **Инвентаризация.** Составить таблицу: каждый `has_workspace_role`/`WorkspaceRoleCode`-сайт → какой CompanyRole-permission-код должен его заменить (напр. `SALES_MANAGER`-гейт отправки → `quote.send`; `DIRECTOR`-финал-апрув → `quote.approve_final`; `OWNER`-проверки → соответствующий admin-permission).
2. **Гарантия покрытия.** Убедиться, что дефолтные CompanyRole-шаблоны (`roles.py`) выдают эти permissions ровно тем, у кого сейчас соответствующий WorkspaceRole — иначе existing-тенанты потеряют доступ. Возможна data-миграция досоздания permissions.
3. **Переключение сайтов** по одному: заменить `has_workspace_role(...)` на `member_has_permission(actor, company_id, 'quote.send')` и т.п. Каждый — с тестом до/после (approval-FSM тесты уже есть: `test_quote_services.py`, `test_fsm.py`).
4. **WorkspaceRole → derivation-only:** оставить `CompanyMember.role` как лейбл/fallback, но ни одно бизнес-ветвление на него не смотрит.

**Критерии приёмки.**
- [ ] Ни один `has_workspace_role`/`WorkspaceRoleCode` не участвует в авторизации бизнес-действий (grep только в derivation/labels).
- [ ] Existing-тенанты не теряют доступ (data-миграция + тест на «до/после прав»).
- [ ] Полный approval-FSM сьют зелёный.

**Риск.** **Высокий** — это ядро прав на КП. Делать отдельным крупным PR, поэтапно, с максимальным тестовым покрытием и eyes-on прогоном полной цепочки заявка→КП→контракт. **Оценка:** ~3–5 дней.

---

## Раздел 4. Отложено / на стороне владельца

### Staging — почему существует и почему пока отложено

**Зачем нужен** (не для обычного теста — это локально): staging ловит **энв-специфичные баги, которые локально не воспроизводятся** — ровно класс уже пойманных нами: прод-том `backend_media` vs `backend_media_prod` (#235), «raw /media 404» (MinIO vs FS), поведение миграций на прод-подобной БД, а также даёт nightly Playwright e2e цель, отличную от прода. Локальный `make up` = прод nginx-сборка фронта + локальный Postgres, но НЕ прод-топология (Caddy edge, DB-VPS, prod-`.env`, prod-тома).

**Статус:** инфраструктура готова наполовину — `deploy-staging.yml` существует (inert, `workflow_dispatch`-only), `docs/ops/staging.md` описывает 3 owner-предпосылки (DNS `staging.b2b.railtech.uz`, GitHub environment `staging` с отдельной БД, Caddy-блок). Нет `docker-compose.staging.yml`.

**Решение по твоему ответу:** **отложено** (тестируем локально). Оставляем `deploy-staging.yml` как есть. Если позже понадобится (перед крупным релизом с рискованной миграцией) — активация = 3 owner-шага + создать `docker-compose.staging.yml` (порт 8001, отдельный project-name, MinIO off) — ~0.5 дня работы.

### P0 коммерческие блокеры — в планах, до готовности продукта не внедряем

По твоему ответу — контур, не реализация:
- **Платёжный провайдер (Click/Payme).** Модели `Invoice/Act/Payment` уже есть (`crm/models/billing.py`) как леджер. Для реального провайдера понадобится: интеграция API (Click Merchant API / Payme Merchant API — webhook-based), идемпотентность (`UniqueConstraint(invoice, provider_reference)`), сверка статусов, обработка вебхуков (подписи), reconcile. Отдельное большое ТЗ на этапе «продукт готов».
- **E-IMZO (квалифицированная э-подпись).** Узбекская ЭЦП; браузерный E-IMZO SDK (client-side подпись) + серверная верификация. Нужен для юридически значимых договоров. Отдельное ТЗ.
- **ЗРУ-547 (локализация данных).** Перепроверить статус — БД уже на собственном VPS в UZ; вероятно требование удовлетворено, но нужна юридическая сверка.

### Governance-as-code / владелец

- **Биллинг GitHub Actions** — починить (CI-гейты + nightly e2e стоят с ~2026-07-06). После — перезапустить CI на `main`.
- **INF-12** — сделать `security`-job (и `docker-build`-агрегат) required status check в branch protection (GitHub-настройка, не код).
- **F0.3** — гейтить `deploy-b2b.yml` на зелёный CI (сейчас деплой триггерится push'ем в main независимо от `ci.yml`). Можно частично как код: `needs`/`workflow_run`-зависимость.
- Опционально: CODEOWNERS (нет в репо) + branch-protection-as-code.

---

## Приложение. Рекомендуемый порядок

1. **INF-04** backup-gate (риск ↑, дёшево) → **INF-08** reset bind-mount → **INF-07** minio-пины (тривиально).
2. **INF-05/09** пиннинг + lock (после — воспроизводимые сборки для всего дальнейшего).
3. **INF-01** Caddy rate-limit (нужна возня с host-Caddy).
4. **ContactViewSet + фронт клиентской базы** → **CB-invite** (продуктовая ценность, петля привлечения).
5. **AI-калибровка** (телеметрия — параллельно, тюнинг по накоплению трафика).
6. **ADR-0006 cut-решение** (после вопроса владельцу).
7. **ADR-0005 Phase E U3** (крупный рискованный рефактор — отдельным заходом, максимум тестов).

⚠️ Всё это без работающего CI валидируется локально (полный backend-сьют + фронт lint/test/build); деплой (self-hosted runner) не затронут биллингом.
