# Runbook: волна 1 исправлений параллельными агентами Claude Code (Sonnet) в терминале

Когда применять: оркестратор запускает волну 1 (FIX-10…15) после закрытой волны 0. Источник задач —
`docs/audits/2026-10-18-main-e0f089e.md` («Волна 1»), статусы — `docs/PROGRESS.md` «Исправления по аудиту»,
правила — `ORCHESTRATOR.md` §4, §7 и `docs/HANDOFF.md` §4. Этот runbook — как разложить волну по сессиям,
в каком порядке сливать и что вставить в каждую сессию как первое сообщение.

## 1. Исходное состояние (проверено 2026-10-18 вечером)

- `main @ cb474d7b`, защищена ruleset `main`; CI на push в `main` зелёный по всем 14 job'ам (run 39129125177).
- Открытых PR нет; все 9 удалённых веток (`fix/*`, `m2/erp-01…02`) влиты, их можно удалять на GitHub.
- Волна 0 (FIX-00…05) закрыта. `PLATFORM_SSO_ENABLED=false` до слияния FIX-10 и FIX-11.
- Факты кода, важные для волны (все подтверждены grep'ом):
  - `platform_access` в CRM **отсутствует** вообще (`apps/crm/backend/app`) — FIX-11 начинается с модели и миграции
    Alembic (голова — `0025_sso_replay_tokens`, файл `20261016_2000_sso_replay_tokens.py`).
  - ERP `accounts/services/sso.py:209–223` на обмене ищет по e-mail и зовёт `provision_crm_user` — это и есть
    самопровижининг FIX-10. CRM `app/services/sso.py:174–184` при неизвестном `sub` ищет по e-mail.
  - `packages/contracts/mcp-tools.json` описывает в `X-Agent-Context` только `exp` — обязательные `iat` и защита
    от повтора в FIX-12 требуют **правки контракта и выпускающей стороны CRM** (`app/security/agent_context.py`,
    `app/agents/mcp_client.py`), а не только ERP. Ветка FIX-12 — `fix/all-12-…`, не `fix/erp-12-…`.
  - FIX-13: `buyer_access` / `buyer_actions` / `BUYER_ONLY` / `can_buy` — 260 вхождений в ~40 файлах, почти все —
    `crm/tests/*` переходного пакета; продуктовый код — `accounts/services/buyer_access.py` (68 строк),
    `core/permissions.py` (строки 169–247), сторож `catalog/tests/test_published_layer.py` (497 строк).
  - FIX-14: `portal/services/magic_link.py:81` пишет токен в лог; `PortalSession.token` и `MagicLinkToken.token`
    хранятся открытым текстом (`portal/models.py:17, 68`).
  - FIX-15: в `core/settings/api.py:27–28` общие `AnonRateThrottle`/`UserRateThrottle`; своего класса для сессии
    портала нет.

## 2. Рабочее место: что нужно до запуска сессий

| Что | Состояние на Mac владельца | Действие |
|---|---|---|
| Docker Desktop | **8 ГБ** памяти (`docker info`), не 12 | стенд `make up` ≈ 20 контейнеров; параллельно с ним — не больше **одного** набора тестов ERP. Для 2–3 наборов тестов одновременно — `make down` на время прогонов |
| `.env` | создан `make env` 2026-10-18 (все `CHANGE_ME` заменены; `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN` пусты) | для волны 1 ключи моделей не нужны |
| `uv`, `node 23`, `pnpm` (corepack) | есть | — |
| `gitleaks`, `pre-commit` | **нет** | `brew install gitleaks pre-commit && make hooks` — иначе утечку поймает только CI |
| venv/node_modules приложений | **нет** (`apps/crm/backend/.venv`, `apps/erp/.venv-tools`, `*/node_modules`) | каждая сессия в своём worktree: `make -C apps/<app> install` первым шагом |
| `gh` | авторизован как `nzulkaynarov` | агенты открывают PR сами под учёткой владельца |

Каждой сессии — свой git worktree (общий `.git`, свой рабочий каталог), чтобы агенты не мешали друг другу:

```bash
cd /Users/znz/Downloads/IT-projects/RailTech_Platform
git fetch origin && git worktree prune
git worktree add ../rt-wt/fix-10 -b fix/all-10-sso-contract        origin/main
git worktree add ../rt-wt/fix-12 -b fix/all-12-mcp-context         origin/main
git worktree add ../rt-wt/fix-13 -b fix/erp-13-no-buyer-accounts   origin/main
git worktree add ../rt-wt/fix-14 -b fix/erp-14-portal-login        origin/main
# после слияния FIX-10 и FIX-14 соответственно:
git worktree add ../rt-wt/fix-11 -b fix/all-11-platform-access     origin/main
git worktree add ../rt-wt/fix-15 -b fix/erp-15-portal-limits       origin/main
```

Запуск сессии: `cd ../rt-wt/fix-10 && claude --model sonnet`, первым сообщением — промпт из §5.
Тесты ERP в worktree: `ERP_TEST_NS=fix10 make -C apps/erp test-backend args="accounts/tests/test_sso.py"` — свой
набор контейнеров на сессию (имя = номер FIX). Тесты CRM (`make -C apps/crm check`) Postgres не требуют.
Стенд `make up` живёт только в основном каталоге и не нужен для юнит-тестов; он нужен для проверки глазами
(FIX-11: переключатель в шапке; FIX-14: письмо magic-link в `EmailLog`).

## 3. Раскладка по сессиям

| Сессия | Роль (§4) | Задача | Ветка | Зависит от | Размер | Зоны кода |
|---|---|---|---|---|---|---|
| S0 | Оркестратор | назначение, ревью, порядок слияния, PROGRESS | — | — | — | только `docs/` |
| S1 | ERP + CRM | **FIX-10** SSO по контракту | `fix/all-10-sso-contract` | — | M | `accounts/services/sso.py`, `accounts/views/sso.py`, `integration/views.py` (provision), CRM `app/services/sso.py`, `packages/contracts/sso-token.md`, `erp-integration.yaml` |
| S2 | ERP + CRM | **FIX-12** строгий `X-Agent-Context`, проекции MCP | `fix/all-12-mcp-context` | — | M | `integration/mcp/{context,tools,views}.py`, CRM `app/security/agent_context.py`, `app/agents/mcp_client.py`, `packages/contracts/mcp-tools.json` |
| S3 | ERP | **FIX-14** вход в портал | `fix/erp-14-portal-login` | — | M | `portal/models.py`, `portal/services/{magic_link,invitation,telegram_auth}.py`, `portal/authentication.py`, `portal/tests/test_portal_auth.py` |
| S4 | ERP | **FIX-13** снять покупательские аккаунты | `fix/erp-13-no-buyer-accounts` | — (сливается последней) | L | `accounts/services/buyer_access.py`, `core/permissions.py`, `accounts/models`, миграция `accounts`, `crm/tests/*`, `catalog/tests/test_published_layer.py`, `accounts/tests/test_role_matrix.py` |
| S5 | CRM + ERP | **FIX-11** `platform_access`, провижининг и отзыв | `fix/all-11-platform-access` | FIX-10 влит | L | CRM: модель `User`, Alembic `0026`, `app/services/sso.py`, задачи Procrastinate, `/me`, шапка SPA; ERP: `integration` provision/revoke, чёрный список access-токенов |
| S6 | ERP | **FIX-15** лимиты, CSRF, cookie Mini App | `fix/erp-15-portal-limits` | FIX-14 влит | M | `portal/throttles.py` (новый), `portal/views.py`, `core/settings/api.py` (CORS, cookie), `portal/tests` |

Параллельно стартуют S1–S4 (четыре терминала). S5 и S6 — вторая очередь, когда влиты FIX-10 и FIX-14.
При 8 ГБ Docker одновременно гонять бэкенд-тесты ERP могут две сессии; остальные в это время пишут код или
гоняют только линтеры (`make -C apps/erp lint`).

## 4. Порядок слияния и конфликтные зоны

Сливать по одному, после каждого слияния остальные делают `git merge origin/main` и перегоняют тесты:

1. **FIX-12** — изолирован (`integration/mcp`, CRM `security/agent_context`), конфликтов ни с кем.
2. **FIX-10** — `accounts/services/sso.py`, `accounts/serializers.py`. Открывает FIX-11.
3. **FIX-14** — `portal/*`. Открывает FIX-15.
4. **FIX-13** — самая широкая (матрица прав, `core/permissions.py`, ~40 тестов, сторож каталога); сливается
   последней и перед PR обязательно подтягивает `main` с FIX-10 и FIX-14: FIX-13 меняет `accounts/serializers.py`
   (`can_buy`) и `portal/tests/conftest.py` (портальная сессия для сторожа), FIX-14 — `portal/services` и те же тесты.
5. **FIX-11** и **FIX-15** — параллельно, не пересекаются.

Контракт правят не вдвоём: `sso-token.md` и `erp-integration.yaml` — только S1 (и позже S5), `mcp-tools.json` —
только S2, `erp-portal.yaml` в волне 1 не трогает никто (это FIX-20, волна 2). Общие сгенерированные файлы
(`packages/contracts/generated/*`, `apps/erp/frontend/src/api/schema.d.ts`, CRM `frontend/src/api/generated`)
перегенерируются после каждого слияния тем, кто сливается следующим.

## 5. Промпты для сессий

### 5.0. Общая преамбула (вставляется перед каждым промптом задачи)

```
Ты — агент {РОЛЬ} RailTech Platform. Работаешь в worktree {ПУТЬ}, ветка {ВЕТКА}, только эта задача: {ID}.
Прочитай по порядку: ORCHESTRATOR.md (§3, §4, §7), docs/HANDOFF.md, docs/PROGRESS.md (раздел «Исправления по
аудиту»), docs/DECISIONS.md (строки 2026-10-18), docs/audits/2026-10-18-main-e0f089e.md (раздел «Волна 1» и
находки {НАХОДКИ} в реестре), CLAUDE.md приложения, которое правишь, docs/CONTRACTS.md и файл контракта задачи.

Правила, которые не обсуждаются:
- `main` защищена: никаких push и merge в main; только PR из этой ветки, «готово» — только после зелёного «CI ok».
- Контракт (`packages/contracts`) меняется раньше кода и в том же PR; после правки — `make contracts`, затем
  перегенерация клиентов (`make -C apps/erp openapi`, `make -C apps/crm openapi`) и коммит сгенерированного.
- Один PR — одна задача. Попутных рефакторингов, переименований и «улучшений» соседнего кода нет.
- Тест-first: сначала падающий тест на находку аудита, потом правка. Негативные тесты обязательны.
- Секретов в коде, тестах и фикстурах нет; тестовые значения — явно фейковые и в `.gitleaksignore` при ложном
  срабатывании (`файл:правило:строка`).
- Платные вызовы моделей не делать. Стенд `make up` не трогать (он в основном каталоге, им управляет оркестратор).
- Тесты ERP: `ERP_TEST_NS={NS} make -C apps/erp test-backend args="<путь>"`; перед PR —
  `make -C apps/erp check` (и `make -C apps/crm check`, если правил CRM), `make contracts`.
  Первым шагом — `make -C apps/erp install` (и `make -C apps/crm install`): venv и node_modules в worktree нет.
- Если задача требует решения владельца или меняет контракт шире задачи — остановись и запиши вопрос в
  docs/QUESTIONS.md (контекст → варианты → рекомендация), продолжай по рекомендации.
- Коммиты: Conventional Commits на русском, суффикс `({ID})`, трейлер `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Финал: PR через `gh pr create` (заголовок `{ID}: …`; тело — что, почему, как проверить, что обновлено в docs,
  открытые вопросы), строка в docs/PROGRESS.md (таблица FIX и журнал сессий) в том же PR, ссылка на PR в ответе.
  Дождись «CI ok»; красный — чини в той же ветке, пока не зелёный. Не объявляй «готово» без зелёного CI.
```

### 5.1. S1 — FIX-10 (ERP + CRM), `fix/all-10-sso-contract`, `ERP_TEST_NS=fix10`

```
Задача FIX-10 (P0, находки S-2, S-3, S-7, I-17): SSO строго по packages/contracts/sso-token.md и решению владельца
2026-10-18 «обмен SSO не создаёт пользователя ERP и не меняет его права».

Готово, когда (всё — тестами):
1. ERP `accounts/services/sso.py`:
   - issue_sso_token: `sub` — только `CrmUserMapping.crm_user_id`; нет сопоставления → 403 `USER_NOT_PROVISIONED`,
     никакого запасного `user.pk`.
   - verify_and_exchange_sso_token: пользователь ищется только по `sub` через CrmUserMapping; поиск по e-mail
     (строки ~209–212) и вызов provision_crm_user (строки ~214–223) удалены; неизвестный `sub` → 403
     `USER_NOT_PROVISIONED`; обмен не меняет `is_superuser`, роли и права (может обновить только email/name).
   - Проверка `exp − iat ≤ 60` (с допуском 5 с) — токен с большим сроком отклоняется 401 даже при валидной подписи.
2. CRM `app/services/sso.py` exchange_token: то же — без поиска по e-mail (строки ~174–184), неизвестный `sub` → 403;
   `exp − iat ≤ 60`. Регенерируй OpenAPI CRM (`make -C apps/crm openapi`) — шаг CI «OpenAPI CRM актуален».
3. Провижининг `POST /api/integration/v1/users/provision` (ERP `integration/views.py` + сервис): коллизия e-mail с
   пользователем, у которого другой `crm_user_id` или нет сопоставления → 409 `EMAIL_CONFLICT`, пользователь не
   переписывается. В `erp-integration.yaml` описать 409.
4. Контракт: в `sso-token.md` п.5 «Проверка приёмником» привести к решению владельца — «пользователь найден по `sub`
   и активен, иначе 403 USER_NOT_PROVISIONED; из токена обновляются только email и name; role и permissions —
   только провижинингом». Добавить явное правило «exp − iat ≤ 60». Правка контракта — первым коммитом.
5. Тесты: ERP accounts/tests/test_sso.py (+ integration/tests/test_integration_api.py для 409), CRM tests для
   services/sso.py: «неизвестный sub → 403», «e-mail совпадает, sub нет → 403, пользователь не создан»,
   «токен на 120 с → 401», «провижининг с чужим e-mail → 409». Матрица прав accounts/tests/test_role_matrix.py
   остаётся зелёной.
Не трогать: platform_access, провижининг из CRM в очередь, кнопки в шапках, отзыв сессий — это FIX-11.
Флаг PLATFORM_SSO_ENABLED не включать и не удалять.
PR: «FIX-10: SSO по контракту — sub только из сопоставления, обмен без провижининга, exp − iat ≤ 60».
```

### 5.2. S2 — FIX-12 (ERP + CRM), `fix/all-12-mcp-context`, `ERP_TEST_NS=fix12`

```
Задача FIX-12 (P0, находки S-8, S-9, S-10): контекст агента и проекции erp-mcp. Решение владельца 2026-10-18:
переход на официальный `mcp` SDK — это FIX-36 (волна 3); здесь только строгий контекст и проекции, транспорт не менять.

Готово, когда:
1. Контракт packages/contracts/mcp-tools.json, раздел `X-Agent-Context`: claims со строгими типами
   (`crm_client_id: int`, `erp_company_id: int|null`, `mode: "prospect"|"customer"`, `language`), обязательные
   `iat` и `exp` с правилом `exp − iat ≤ 60` и `exp ≤ now + 60`, одноразовый `jti` (строка, UUID v4; приёмник хранит
   10 минут). Первый коммит — контракт.
2. CRM — выпускающая сторона (app/security/agent_context.py и app/agents/mcp_client.py): добавляет `iat`, `jti`,
   срок ровно 60 с. Тест в CRM на формат. OpenAPI CRM не меняется (заголовок внутренний), но `make -C apps/crm check`.
3. ERP integration/mcp/context.py verify_agent_context: `bool` не принимается как int (сейчас `True` проходит как
   компания 1) — проверка `type(x) is int`; `iat` обязателен; `exp − iat ≤ 60`; `jti` обязателен и одноразов
   (cache.add с TTL 600, как jti SSO); повтор → 401. Ошибки — 401 `{"detail": "INVALID_AGENT_CONTEXT"}`.
4. integration/mcp/tools.py: клиентская проекция (`mode=customer`) не отдаёт КП в статусах черновика и
   согласования (только отправленные/акцептованные/отклонённые), не придумывает количества в поставках (нет данных —
   поле `null`), `search_catalog` строго через `catalog.published.project()` без полей вне `CATALOG_ITEM_KEYS`
   (`sku` не уходит). Аргументы инструментов валидируются по `input_schema` из mcp-tools.json (jsonschema) → 400
   `INVALID_ARGUMENTS`. Свой лимит частоты по `erp_company_id` (не общий анонимный): throttle-класс на вьюхе MCP.
5. Тесты integration/tests/test_mcp.py: контекст без iat → 401; с exp на 115 суток → 401; повторный jti → 401;
   `True` вместо id → 401; черновик КП не виден клиенту; `sku` отсутствует в ответе search_catalog; невалидные
   аргументы → 400; лимит частоты → 429.
Не трогать: транспорт JSON-RPC, набор инструментов, Caddy (FIX-03 уже закрыл /mcp снаружи).
PR: «FIX-12: строгий X-Agent-Context (iat/exp/jti), клиентская проекция без черновиков, валидация по input_schema».
```

### 5.3. S3 — FIX-14 (ERP), `fix/erp-14-portal-login`, `ERP_TEST_NS=fix14`

```
Задача FIX-14 (P1, находки P-9, P-10, P-11, P-16): вход в портал.

Готово, когда:
1. `MagicLinkToken.token` и `PortalSession.token` (portal/models.py) хранятся как SHA-256-хеш (поле `token_hash`,
   уникальный индекс); в cookie/ссылке — сырой токен; сравнение по хешу. Миграция в `portal` (одна, с переносом:
   старые открытые токены инвалидируются — это допустимо, сессий на проде нет).
2. Погашение magic-link атомарно: `select_for_update` + `used_at` в одной транзакции; второй запрос с тем же токеном
   → 410 `MAGIC_LINK_EXPIRED` (код из erp-portal.yaml, не менять).
3. Токены не пишутся в лог (portal/services/magic_link.py:81 и везде по grep `token` в portal/): в логах —
   только id записи или префикс 6 символов.
4. Письмо magic-link — через шаблон писем ERP (`core` notifications, ARCHITECTURE §18) и `EmailLog`; лимит на адрес
   (не больше N писем в час, N — настройка с умолчанием 5) → 429 `TOO_MANY_REQUESTS`; ответ `request_magic_link`
   одинаков для известного и неизвестного e-mail (без утечки существования).
5. Сотруднику (приглашение из ERP, portal/services/invitation.py) не отдаётся рабочая ссылка входа клиента —
   в ответе и в журнале только факт отправки и канал.
6. Вход по Telegram username удалён (только `telegram_user_id` из подписанного initData, telegram_auth.py).
7. Контакт архивной компании (`Company.is_archived`/аналог — найди в parties) не входит ни одним каналом → 403.
8. Неоднозначный e-mail (несколько активных контактов разных компаний) → письмо не отправляется, ответ как в п.4,
   событие в лог без адреса.
9. Тесты portal/tests/test_portal_auth.py на каждый пункт; существующие тесты портала зелёные;
   сторож каталога не трогать (его переводит FIX-13).
Не трогать: лимиты частоты по сессии, CSRF, cookie Mini App, CORS — это FIX-15 (после тебя).
PR: «FIX-14: вход в портал — хеши токенов, атомарное погашение, письма через EmailLog, без входа по username».
```

### 5.4. S4 — FIX-13 (ERP), `fix/erp-13-no-buyer-accounts`, `ERP_TEST_NS=fix13`

```
Задача FIX-13 (P0, находки P-4, G-8, P-19): клиентов в ERP нет (инвариант §3.1, apps/erp/CLAUDE.md §2 п.1).
Размер L; ветка сливается в волне последней — перед PR обязательно `git merge origin/main` с FIX-10 и FIX-14.

Готово, когда:
1. Удалены: accounts/services/buyer_access.py, маркер `BUYER_ONLY` и `buyer_actions` в core/permissions.py
   (строки ~169–247) и во всех вьюхах; `CompanyMember.can_buy` (миграция accounts — удалить поле; данные не
   переносятся); покупательские коды `BuyerPermission` (`request.create`, `quote.approve` и т.п.).
   Эндпоинты, которые существовали только для покупателя (акцепт/отклонение КП сотрудником «за клиента», подпись
   договора клиентом из internal, приёмка акта клиентом из internal) — удалить; их место — портал
   (`sign_contract_by_client`, `sign_act`/`reject_act` остаются как сервисы, их вызывает портал в FIX-22).
2. Вход в ERP участникам компаний-клиентов запрещён: `accounts/services/auth.py` (или login_guard) — пользователь
   без активного членства в своей компании (`core.tenant.own_company()`) и не суперпользователь → 403
   `STAFF_ONLY`; тест на вход контакта клиента.
3. Матрица прав accounts/tests/test_role_matrix.py: ветка «покупатель вне buyer_actions → 403» удалена, тест
   зелёный на всех мутациях.
4. Сторож catalog/tests/test_published_layer.py: обход GET-маршрутов анонимом и **портальной сессией**
   (фикстура из portal/tests/conftest.py), не покупательским аккаунтом; ответы 5xx — падение теста, а не пропуск.
5. Тесты в crm/tests/* (переходный пакет), опиравшиеся на can_buy/buyer_access: переписать на портальную сессию,
   если они проверяют клиентский путь, иначе удалить с пометкой в описании PR (список файлов). Покрытие
   `--cov-fail-under` не ниже текущего.
6. `make -C apps/erp openapi` — schema.d.ts и erp-internal-full.json без `can_buy`/покупательских путей;
   фронтенд ERP: `grep -rn "can_buy\|canBuy\|buyer" apps/erp/frontend/src` пусто (кроме i18n-ключей, которые
   тоже удалить парой ru/en). `make -C apps/erp check` зелёный.
7. apps/erp/CLAUDE.md §6 и §9: абзацы «Покупательский аккаунт … до M2-ERP-01» заменить на факт удаления (FIX-13).
Не трогать: portal/services/* (FIX-14), accounts/services/sso.py (FIX-10), контракты.
PR: «FIX-13: покупательских аккаунтов в ERP нет — buyer_access, BUYER_ONLY, can_buy удалены; сторож на портальной сессии».
```

### 5.5. S5 — FIX-11 (CRM + ERP), `fix/all-11-platform-access`, после слияния FIX-10

```
Задача FIX-11 (P0, находки S-5, S-6, S-11): довести M3-CRM-06 и M3-ERP-04 — доступом к ERP управляет CRM.

Готово, когда:
1. CRM: поле `users.platform_access` (JSON-список `["crm","erp"]`, умолчание `["crm"]`), миграция Alembic `0026`
   (используй skill `migration`), в схемах `/me` и `/users`, в консоли админа — переключатель «Доступ к ERP» (skill
   `crm-page` при новом UI; скриншот 1440/390 в PR).
2. Выдача доступа → задача Procrastinate `erp_provision_user` → `POST /api/integration/v1/users/provision`
   (идемпотентно по crm_user_id, ретраи); снятие → `erp_revoke_sessions` →
   `DELETE /api/integration/v1/users/{crm_user_id}/sessions`. Ошибки ERP — в ленту внешних сервисов (ADR-0024),
   не в ответ пользователю.
3. Карта прав CRM → ERP: по кодам каталога ERP (`accounts.constants.Permission`, apps/erp/CLAUDE.md §6) — таблица в
   `app/services/sso.py` или отдельном модуле с тестом «каждый код есть в каталоге ERP» (снимок кодов в
   packages/contracts/erp-integration.yaml как enum `permissions`).
4. Кнопка перехода в шапке CRM видна только при `"erp" in platform_access`; выдача токена `POST …/sso/token` без
   доступа → 403; тест матрицы «без доступа переключателя нет» (API + Vitest на шапку).
5. ERP: отзыв сессий гасит и access-токены (чёрный список jti/`token_version` у пользователя в accounts, проверка
   в аутентификации JWT); тест «после revoke старый access → 401». Переключатель в шапке ERP — только у
   пользователя с сопоставлением CrmUserMapping.
6. Аудит: `platform_access.granted|revoked` в CRM, `sso.revoke` в ERP.
6a. Хвосты ревью волны 1 (2026-10-19): CRM на неизвестный `sub` при обмене SSO отвечает 403 со стабильным подкодом
   `USER_NOT_PROVISIONED` (сейчас `ForbiddenError("user not provisioned")` без `reason`, `app/services/sso.py`),
   регенерировать OpenAPI CRM; ERP `CookieTokenRefreshView` не продлевает refresh-токен пользователя, который больше
   не сотрудник (`accounts.services.auth.assert_staff_login`, FIX-13) — тест.
7. После зелёного CI — строка в docs/PROGRESS.md: M3-CRM-06 «готово», владельцу: можно включить
   `PLATFORM_SSO_ENABLED=true` на стенде и проверить переход глазами (сценарий в описании PR).
PR: «FIX-11: platform_access в CRM, провижининг и отзыв через очередь, кнопка только при доступе, карта прав по каталогу ERP».
```

### 5.6. S6 — FIX-15 (ERP), `fix/erp-15-portal-limits`, после слияния FIX-14

```
Задача FIX-15 (P1, находки P-14, C-12, P-18): защита портала.

Готово, когда:
1. `portal/throttles.py`: `PortalSessionRateThrottle` (ключ — id сессии портала, не IP), отдельные scope
   `portal_login` (magic-link запрос, initData) и `portal_accept` (акцепт КП с кодом) с жёсткими лимитами из
   настроек; общий анонимный 20/мин по IP на портал не распространяется. Тесты: 429 по сессии, независимость
   сессий, лимит входа по e-mail/IP.
2. CSRF для сессии в cookie: портал принимает только `Content-Type: application/json`; на всех POST/PATCH —
   обязательный `Idempotency-Key` (CONTRACTS §0), без него 400 `IDEMPOTENCY_KEY_REQUIRED`; `erp-portal.yaml` уже
   описывает заголовок — проверь и дополни описания ответов, не меняя пути (пути — FIX-20).
3. Cookie сессии портала для Telegram Mini App: `SameSite=None; Secure` при `PORTAL_COOKIE_SAMESITE` из настроек
   (умолчание `Lax`; на dev без TLS Mini App не работает — зафиксируй в docs/runbooks/stand.md как ограничение и
   способ проверки через туннель, OWNER-CHECKLIST «До M2»).
4. CORS: dev-источники (`*.localhost`) только при `DEBUG=True`; на `DEBUG=False` список — из настроек
   (`CABINET_ORIGIN`). Тест на обе ветки.
5. Хвосты ревью FIX-14 (2026-10-19): (а) P1 — журнал запросов Daphne (`infra/compose/base.yml`, команда `daphne`)
   пишет в stdout путь `/auth/magic/<токен>` мимо `RedactPortalTokenFilter`: отключить access-лог Daphne
   (`-v 0`, журнал запросов — через Django-логирование с фильтром) и тестом/проверкой на стенде показать, что токена
   в `docker compose logs erp-backend` нет; (б) P1 — `portal/authentication.py`: сессия компании, ставшей архивной,
   и неактивного контакта → 401 (сейчас `PortalSession.is_valid` проверяет только срок); (в) P2 — архивность везде
   через общий предикат `active_company_q()` (`magic_link.py`, `telegram_auth.py`, `invitation.py`), не `is_active`;
   (г) P2 — `request_magic_link` отправляет письмо в Celery, чтобы время ответа не выдавало известный адрес.
6. Все тесты портала зелёные, сторож каталога (уже на портальной сессии после FIX-13) зелёный.
PR: «FIX-15: лимиты по сессии портала, CSRF через JSON + Idempotency-Key, cookie Mini App, dev-CORS только в DEBUG».
```

## 6. Цикл оркестратора (S0)

1. Создать worktrees (§2), открыть 4 терминала, вставить преамбулу + промпт. Записать в журнал PROGRESS строку
   «волна 1 запущена: S1–S4».
2. Раз в час: `gh pr list`, `gh pr checks <n>`; красный CI — вернуть агенту одной строкой («CI job X красный:
   <ссылка на лог>, чини в ветке»).
3. Ревью PR перед слиянием (чек-лист): контракт первым коммитом и совпадает с кодом; негативные тесты есть;
   нет попутных правок вне зон §3; `make contracts` зелёный; строка в PROGRESS со ссылкой на PR; для UI —
   скриншот в теле PR. Слияние — кнопкой владельца или `gh pr merge --squash` с его согласия; после слияния —
   `git branch -d` ветки на GitHub.
4. Порядок слияния — §4. После каждого слияния остальным сессиям: «влит FIX-NN, сделай git merge origin/main,
   перегенерируй контракты, перегони тесты».
5. После FIX-10 — запустить S5; после FIX-14 — S6. После FIX-13 — проверить `make check-erp` на `main`.
6. Закрытие волны: все шесть строк FIX-1x в PROGRESS «готово» с PR; HANDOFF §3 — «волна 1 закрыта, следующая —
   волна 2»; владельцу — включить `PLATFORM_SSO_ENABLED=true` и пройти переход глазами.
7. Волна 2 начинается с **FIX-20 (контракт портала)** силами оркестратора: пока агенты заканчивают FIX-13/11/15,
   S0 готовит правки `erp-portal.yaml` по Q-15…Q-17 (`POST /quotes/{id}/request-code`, приёмка по строкам,
   `deal{id, number, title}`), чтобы FIX-21…24 стартовали сразу после слияния FIX-20.

## 7. Если что-то идёт не так

- Два агента правят один файл контракта → стоп обоим, решает S0 (ORCHESTRATOR §4).
- Тесты ERP падают по памяти (код 137 у контейнера) → `make down` на стенде или оставить один `ERP_TEST_NS`.
- Агент предлагает «заодно» переписать соседний код → отклонить: отдельная задача, отдельный PR.
- Агент сообщает «готово» без ссылки на зелёный CI → не принимать, вернуть на §5.0 последний пункт.
- `gitleaks` в CI красный на явно тестовом значении → строка в `.gitleaksignore` `файл:правило:строка`, не менять
  правило.
