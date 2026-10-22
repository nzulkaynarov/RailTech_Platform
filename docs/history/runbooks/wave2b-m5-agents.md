# Runbook: волна 2b (FIX-2xa, FIX-25) ∥ M5-INF-01 — один лид, три исполнителя

Решения — `docs/DECISIONS.md` 2026-10-20 («Путь к пилоту», «Вопросы волны 2», «FIX-25»). Идёт параллельно с волнами 3 и 4
(`docs/runbooks/wave3-4-agents.md`, другая сессия): их зоны (`integration/*`, CRM, `quote_fx`, настройки, dev-команды,
`QuoteBuilder`) не трогать. Контракт `erp-portal.yaml` 0.3.0 уже закоммичен архитектором в ветку `fix/erp-25-portal-030`
(worktree `.claude/worktrees/fix-25`), правит его только архитектор.

## 0. Промпт лида (субагент Opus в сессии архитектора)

```
Ты — лид разработки RailTech Platform (ORCHESTRATOR §4.1), ведёшь волну 2b и M5-INF-01 по
docs/runbooks/wave2b-m5-agents.md. Код сам не пишешь: ставишь задачи исполнителям-субагентам (Sonnet), ревьюишь
свежим субагентом ≠ исполнителю, решаешь, ставишь автослияние. Прочитай: CLAUDE.md корня, ORCHESTRATOR.md (§3, §4.1, §7),
этот runbook целиком.
1. Worktree и зависимости (§2). Запусти параллельно: FIX-2xa, FIX-25-cabinet, M5-INF-01. FIX-25-erp — после того, как
   FIX-2xa открыл PR (один набор тестов ERP `ERP_TEST_NS=wave2b` на волну 2b — §2).
2. Исполнителю — его раздел §4 целиком + преамбула §3. Исполнитель PR не сливает.
3. Ревью каждого PR — по «готово, когда»; блокеры — тому же исполнителю; затем `gh pr merge --auto --merge <n>`.
   FIX-25: обе половины сливаешь в ветку fix/erp-25-portal-030 (merge, без rebase), PR один — с контрактом.
4. CI не запускай, не опрашивай и не жди. Конфликт в docs/PROGRESS.md после чужого слияния — merge origin/main в ветку
   локально, push, автослияние уже стоит.
5. Вопросы — строка в docs/QUESTIONS.md и решение по рекомендации; отклонение от контракта или ARCHITECTURE — стоп и
   вопрос архитектору в отчёте.
6. Конец: верни архитектору отчёт — PR и их состояние, хвосты ревью (они же — в «Что осталось» строк PROGRESS), что
   владельцу проверить глазами. Docs-PR о закрытии не делай: строки PROGRESS ведут сами PR задач.
```

## 1. Исходное состояние (факты архитектора, `main @ 6654f73c`)

- **Гонка рендера PDF КП.** `send_to_client` (`crm/services/quotes/lifecycle.py`) ставит Celery-задачу
  `render_document_pdf` (`crm/tasks.py:290`, внутри `_render_pdf_for` `:242`). Задача читает КП, рендерит и сохраняет его
  целиком (`save()` без `update_fields`) — если клиент принял КП в первые секунды, задача записывает старый статус `SENT`
  поверх `APPROVED`; договор и `CLOSED_WON` при этом уже созданы. Тот же шаблон возможен у `_render_invoice_pdf`,
  `_render_act_pdf`, `_render_receipt_pdf` (`crm/services/billing.py`), `_render_contract_pdf`,
  `_rerender_pdf_after_signature` (`contracts.py`), `_render_delivery_note_pdf` (`fulfillment.py`),
  `_render_generated_pdf` (`generated_documents.py`).
- **Контракт портала 0.3.0** (коммит `510dbc3c` в `fix/erp-25-portal-030`): нет `deal_id` нигде (только `deal.id`; фильтр
  `?deal_id=` у `GET /documents` остаётся), нет `GET /auth/magic/{token}`; у `Quote` (деталь) обязательные `subtotal` и
  `vat` (`Money`): строки без НДС, `subtotal + vat = total`, как в PDF — брать из клиентской проекции
  `crm/services/documents/projection.py`, не пересчитывать; `ErrorCode` + `DELIVERY_FAILED` (503 на `/team/invite`,
  сейчас `portal.exceptions.PortalDeliveryFailed` отдаёт `CONFLICT`); 422 `FILE_TOO_LARGE` на `/uploads` описан; `lines` в
  `ClientRequestCreate` необязателен. `Act.deal` теперь в `required`.
- Cabinet генерирует `src/api/portal.d.ts` из контракта (`npm run gen:api-types`), `make check-cabinet` сверяет файл
  с контрактом — в ветке FIX-25 он красный до перегенерации.
- Хвосты ревью волны 2 для FIX-25 — строки FIX-21…24 и FIX-2xb в `docs/PROGRESS.md` («Что осталось»).
- **M5-INF-01**: раскладка серверов — `docs/runbooks/servers.md` (VPS 1 `app` 8 ГБ — приложения, Caddy, Redis, RustFS,
  LiteLLM; VPS 2 `db` 2 ГБ — PostgreSQL 17 и бэкапы; лимиты памяти по сервисам там же). `infra/compose/base.yml` — общий,
  `dev.yml` — стенд; комментарий в `base.yml` обещает `make up-prod` (base + prod) и профиль `backup`. `prod.yml`, `db.yml`,
  `Caddyfile.prod`, деплоя и бэкапов нет. Правило FIX-03: `/mcp` снаружи — 404 и на проде. Секреты — GitHub environment
  `production` (OWNER-CHECKLIST «До M5»); внутренние IP, SSH-ключ и DNS владелец ещё не дал. Репозиторий временно
  публичный — ни одного значения секрета, IP-адреса из `servers.md` уже публичны.

## 2. Рабочее место и бюджет

| Задача | Worktree | Ветка | `ERP_TEST_NS` |
|---|---|---|---|
| FIX-2xa | `.claude/worktrees/fix-2xa` | `fix/erp-2xa-pdf-render-race` | `wave2b` |
| FIX-25-erp | `.claude/worktrees/fix-25-erp` | `fix/erp-25-portal-030-erp` (от `fix/erp-25-portal-030`) | `wave2b` (после FIX-2xa) |
| FIX-25-cabinet | `.claude/worktrees/fix-25-cab` | `fix/cabinet-25-portal-030` (от `fix/erp-25-portal-030`) | — |
| M5-INF-01 | `.claude/worktrees/m5-inf-01` | `feat/infra-m5-01-prod` | — |

```bash
cd "$(git rev-parse --show-toplevel)" && git fetch origin && git worktree prune
git worktree add .claude/worktrees/fix-2xa -b fix/erp-2xa-pdf-render-race origin/main
git worktree add .claude/worktrees/fix-25-erp -b fix/erp-25-portal-030-erp fix/erp-25-portal-030
git worktree add .claude/worktrees/fix-25-cab -b fix/cabinet-25-portal-030 fix/erp-25-portal-030
git worktree add .claude/worktrees/m5-inf-01 -b feat/infra-m5-01-prod origin/main
# зависимости: make -C apps/erp install | make -C apps/cabinet install; cd packages/contracts && pnpm install --frozen-lockfile
```

Docker (11,7 ГБ): волны 3–4 держат до трёх наборов ERP, стенд остановлен. Волна 2b — **один** набор `wave2b`
последовательно (FIX-2xa, затем FIX-25-erp). M5-INF-01 стенд и прод-конфигурацию локально **не поднимает** — только
проверка конфигурации (§4.3). После задачи — `ERP_TEST_NS=wave2b apps/erp/scripts/test_backend_local.sh --down`.

## 3. Преамбула исполнителя

```
Ты — исполнитель RailTech Platform (ORCHESTRATOR §4.1), одна задача — один worktree — один PR. Работай только в своём
worktree (§2 runbook'а docs/runbooks/wave2b-m5-agents.md). Прочитай CLAUDE.md корня («Среда разработки, тесты и CI»)
и CLAUDE.md своего приложения. Итерации — только затронутые тесты; перед коммитом — make check-<приложение> (и
make contracts, если менялся контракт); коммить только зелёное; перед push — scripts/ci_local.sh <задания>. Затем push и
PR (описание — что и почему, «готово, когда» по пунктам), строка задачи в docs/PROGRESS.md — «готово к слиянию» со
ссылкой на PR и хвостами в «Что осталось». После PR — стоп и отчёт лиду; CI не запускать, не опрашивать, не ждать; PR не
сливать. Контракт не менять — расхождение: строка в docs/QUESTIONS.md и вопрос лиду. Секретов, паролей, токенов, ссылок
входа и данных клиентов в коде, PR и комментариях нет — репозиторий публичный. Платных вызовов моделей нет.
```

## 4. Задачи

### 4.1. FIX-2xa — гонка рендера PDF (ERP, S, первой)

Сделать: каждая задача и функция рендера PDF (§1, весь список) сохраняет только свои поля файла
(`save(update_fields=[...])` или `QuerySet.update`) и не пишет статус, даты и прочие поля объекта, прочитанного до рендера.
Проверить, что нигде больше Celery-задача не сохраняет документ целиком после долгой операции (`grep save()` в
`crm/tasks.py`, `documents/tasks.py`, `notifications`).

Готово, когда: тест воспроизводит гонку (КП отправлено → объект для задачи прочитан → клиент принял через сервис →
задача сохраняет PDF) и падает на `main`, а в ветке статус `APPROVED`, `approved_at` и договор целы; такой же тест на счёт
и акт; `make check-erp` зелёный; PR `fix(erp): рендер PDF не откатывает статус документа (FIX-2xa)`; строка FIX-2xa
в PROGRESS.

### 4.2. FIX-25 — портал 0.3.0 (ERP + Cabinet, M, один PR с контрактом)

**FIX-25-erp** (ветка от `fix/erp-25-portal-030`):
- сериализаторы портала без `deal_id`; `GET /auth/magic/{token}` и его тесты удалены (маршрут → 404);
- `Quote.subtotal`/`vat` из клиентской проекции (§1), тест: суммы совпадают с PDF-проекцией на КП с НДС и без;
- `PortalDeliveryFailed` → 503 `DELIVERY_FAILED`; 422 `FILE_TOO_LARGE` — как есть;
- сторож контракта (`portal/tests/contract_support.py`, `test_contract_guard.py`) — по 0.3.0, `UNREACHABLE` пересмотреть;
- хвосты: `POST /auth/magic` отклоняет лишние поля (422 `VALIDATION_ERROR`, `additionalProperties: false`); N+1 —
  `product.uom` в строках КП, `invoice_due_days()` в `GET /invoices`, `DealRef` в `GET /documents` (`django_assert_max_num_queries`
  на списке из нескольких записей).

**FIX-25-cabinet** (ветка от `fix/erp-25-portal-030`, параллельно):
- `npm run gen:api-types`; типы, фикстуры и обработчики мока по 0.3.0 (без `deal_id`, `subtotal`/`vat`, мок
  `/auth/magic` с `minLength`); маршрут `/auth/magic/:token` (`LegacyMagicLinkRedirect`) удалить — ссылок в пути на проде
  нет;
- КП: «Итого без НДС / НДС / Итого» (ru/uz/en);
- приглашение коллеги: текст `DELIVERY_FAILED` (ru/uz/en), коллега не показан добавленным;
- 429 на входе — по `Retry-After` («повторите через N мин/сек»), без заголовка — «попробуйте позже»;
- хвосты FIX-24: повторное открытие ссылки при живой сессии — путь «В кабинет» вместо тупика 410; сетевая ошибка обмена
  не стирает фрагмент (кнопка «Повторить»); подсказка длины кода — по контракту 4–12 (или по фактической длине кода ERP,
  если она фиксирована — проверить `QuoteAcceptanceCode`); тост на 1440 не перекрывает `h1`, нет гонки тостов;
  `DialogOverlay` с `forwardRef`, фокус после управляемых диалогов возвращается на кнопку-источник;
- `apps/cabinet/CLAUDE.md`: правило «в тестах поиск по роли — внутри `within(…)`, не по всему документу».

Готово, когда (обе половины): лид слил обе ветки в `fix/erp-25-portal-030`; `make contracts`, `make check-erp`,
`make check-cabinet` зелёные на итоговой ветке; скриншоты 1440 и 390 в `docs/screens/fix-25/` (КП с НДС, ошибка
приглашения, 429 и повторная ссылка) — Cabinet на dev-сервере с моком 0.3.0 (стенд — на гейте FIX-51); axe 0 на этих
экранах; PR `feat(portal): контракт 0.3.0 — ERP и Cabinet (FIX-25)`, строка FIX-25 в PROGRESS.

### 4.3. M5-INF-01 — прод-инфраструктура (infra, L, параллельно)

Сделать по `docs/runbooks/servers.md` (раскладка, лимиты памяти — оттуда, не придумывать заново):
- `infra/compose/prod.yml` (VPS 1, поверх `base.yml`): без dev-портов и bind-mount кода, `restart: unless-stopped`, лимиты
  памяти, образы по тегу `${RT_IMAGE_TAG}` из GHCR, healthcheck, логи с ротацией; база — внешняя (VPS 2) по внутреннему
  IP из переменной; профили `observability`, `kb-ingest` — как в `servers.md`;
- `infra/compose/db.yml` (VPS 2): PostgreSQL 17 + pgvector, базы `crm`, `erp`, `litellm`, `langfuse`, слушает только
  внутренний IP, `pg_hba` только для VPS 1, параметры памяти из `servers.md`; бэкап — ежедневный `pg_dump` каждой базы,
  хранение N дней локально + выгрузка во внешнее хранилище (адрес и ключи — переменные; провайдера выбирает владелец);
  скрипт проверки восстановления;
- `infra/caddy/Caddyfile.prod`: `crm.`, `erp.`, `cabinet.` + домен из переменной, ACME, security headers, маршруты как
  в `Caddyfile.dev`, `/mcp` снаружи 404 (FIX-03);
- `infra/deploy/` скрипты `deploy.sh`, `rollback.sh` (по предыдущему тегу), `backup-now.sh`; перед миграциями —
  `pg_dump`-гейт обеих баз приложений (нет дампа — нет миграций);
- `.github/workflows/deploy.yml` — **новый** файл, разрешён решением 2026-10-20 (`ci.yml` не трогать): только
  `workflow_dispatch` (вход — git-ref и действие deploy/rollback), environment `production`, сборка образов и push в GHCR
  с тегом `sha`, деплой по SSH (ключ и хосты — секреты environment), `make smoke`-аналог по трём доменам, на PR и push не
  запускается;
- `infra/.env.prod.example` — все переменные прода с описанием, без значений; `make up-prod` / `make deploy-check` в
  корневом `Makefile`, если нужно;
- `docs/runbooks/deploy.md`: первая установка VPS (Docker, пользователь, firewall: наружу 80/443 и SSH, внутренняя сеть
  для 5432), первый деплой, деплой, откат, восстановление из бэкапа, что владелец заводит в environment `production`
  (сверить с OWNER-CHECKLIST «До M5» и дополнить его).

Не делать: поднимать прод-конфигурацию локально целиком (бюджет Docker); менять поведение `dev.yml` и `make up` — если
правишь `base.yml`, `docker compose -f base.yml -f dev.yml config` до и после совпадает (приложи diff пустым в PR);
`ci.yml`, ruleset, `scripts/ci_local.sh`.

Готово, когда: `docker compose -f infra/compose/base.yml -f infra/compose/prod.yml --env-file infra/.env.prod.example config -q`
и то же для `db.yml` — без ошибок; `caddy validate` для `Caddyfile.prod` (контейнер `caddy`); `shellcheck` скриптов
`infra/deploy/`; `actionlint` для `deploy.yml` (контейнер `rhysd/actionlint`); dev-конфигурация не изменилась;
`gitleaks` чистый; PR `feat(infra): прод на два VPS — compose, Caddy, деплой, бэкапы (M5-INF-01)`, строка M5-INF-01
в PROGRESS «готово к слиянию; проверка на VPS — после данных владельца».

## 5. Порядок слияния

FIX-2xa → FIX-25 (стопкой через merge `origin/main`, если конфликт в PROGRESS); M5-INF-01 — независимо. Все — `--auto`.
