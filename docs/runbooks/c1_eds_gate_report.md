# Отчёт E6: гейт этапа C1 (волна 12) — сервис EDS

**Дата:** 2026-10-26 · **Код:** `main` @ `f4dd6e19` (merge #221; в нём E1–E5: контракт EDS, каркас, домен, CRM → EDS, ERP ↔ EDS), ветка `qa/c1-eds-gate`. **Повторный прогон** (пп. 5, 3 и замеры C1-G-2/G-3, §9) — на `main` @ `7b92f137` с влитыми E7a (#225, пробуждение ретранслятора EDS) и E7b (#226, `republish-identity`) ·
**Стенд:** отдельный проект `docker compose -p rt-c1` (`base.yml` + `dev.yml`, свой `.env` в worktree, `HTTP_PORT=8092`, `PLATFORM_SSO_ENABLED=true`); стенд владельца `rt-platform` (порт 8088, 23 контейнера) не затрагивался ·
**Как проверялось:** API, а не экраны — экранов EDS в этой волне нет (этап D). Вызовы EDS — изнутри сети compose (EDS без внешнего маршрута), токен — настоящий путь CRM → EDS ([`sso-token.md`](../architecture/sso-token.md)) ·
**Доказательства:** [`qa/c1-eds/logs/`](qa/c1-eds/logs/) (выводы команд и выборки из баз; без секретов), скрипты — [`qa/c1-eds/`](qa/c1-eds/).

Основание: [`wave12-eds-c1.md`](wave12-eds-c1.md) §3 «Гейт этапа C1», [`../systems/eds/README.md`](../systems/eds/README.md), [`../architecture/CONTRACTS.md`](../architecture/CONTRACTS.md) §10, образец — [`wave11b_gate_b_report.md`](wave11b_gate_b_report.md).

## 1. Итог

**Гейт этапа C1 пройден с оговорками.** Все восемь пунктов выполнены на стенде, блокирующих дефектов нет. Первый прогон дал 4 важных находки, повторный прогон после E7a/E7b **закрыл две из них**: C1-G-2 (задержка событий EDS: p50 3,7–4,8 с → 0,01–0,06 с) и C1-G-3 (`republish-identity` восстанавливает проекцию сотрудников). **Остаются открытыми важные C1-G-1** (тупик «КП готово позже срока резолюции», Q-C1-E3-1 п. 3) и **C1-G-4** (отправить одобренное КП клиенту может только Директор или Администратор — вопрос архитектору), а также малые C1-G-5…C1-G-8 (§4). Повторный прогон КП (п. 5) подтвердил всё сказанное ниже логами [`p5r-*`](qa/c1-eds/logs/).

| № | Пункт гейта | Результат | Доказательство (кратко) |
|---|---|---|---|
| 1 | Первый запуск: CRM setup, подключение ERP, сотрудники по ролям каталога, проекция `permissions.eds` | **пройден** | setup CRM → «Подключить ERP» (bootstrap без кода) → мастер своей компании ERP по SSO; 6 сотрудников (Администратор, Директор, «Менеджер и бухгалтер» = Менеджер + Бухгалтер, Снабженец, Гл. инженер, Менеджер), у всех `erp_sync: ok`, доступ `crm, erp`; проекция EDS = 6 строк с `permissions_eds` ровно по каталогу ([`p1-staff.txt`](qa/c1-eds/logs/p1-staff.txt)) |
| 2 | Заявка CRM → `erp.request.created` → письмо в EDS с ВХ-номером; снаружи EDS нет | **пройден** | «Сделать клиентом» → за 1,2 с передача в ERP; `request.created` создан 03:57:22.065, доставлен `eds` за 0,128 с, письмо **ВХ-001/26** (`awaiting_resolution`, адресат — директор) 03:57:22.227 ([`p2-request-to-letter.txt`](qa/c1-eds/logs/p2-request-to-letter.txt)). Через Caddy :8092 — ни одного ответа EDS по 5 путям × 6 хостов, порты EDS на хост не публикуются ([`p2-eds-not-reachable-outside.txt`](qa/c1-eds/logs/p2-eds-not-reachable-outside.txt)) |
| 3 | Резолюция директора → `eds.letter.resolved` → `CalcTask` в ERP | **пройден** | `POST /letters/{id}/resolution` (goods — Снабженец, services — Гл. инженер, срок +7 дн., маржа 15.00): `letter.resolved` создан 03:58:20.043, доставлен `erp` за 0,669 с; `sales_calctask` №1 (ВХ-001/26, срок 2026-11-02, порог 15.00, 2 исполнителя), сделка D-1 → `CALCULATING` («Расчёт цен») ([`p3-resolution-to-calctask.txt`](qa/c1-eds/logs/p3-resolution-to-calctask.txt)) |
| 4 | Служебная записка: с суммой — директор → бухгалтер; без суммы — только директор | **пройден** | **СЗ-2026/001** (12 500 000.00 UZS, автор — Менеджер): шаги 1 Директор → 2 Бухгалтер; бухгалтер до директора и автор — 403; итог `paid`; журнал 7 записей, события `approval.requested` ×2 / `approval.decided` ×2 / `document.archived`. **СЗ-2026/002** (без суммы): один шаг, бухгалтеру в очередь не попадает ([`p4-memo-journal-events.txt`](qa/c1-eds/logs/p4-memo-journal-events.txt)) |
| 5 | КП: визы в ERP → `quote.ready_for_approval` → маршрут с зелёным чек-листом → `approval.decided` → ИСХ, отправка разблокирована; возврат → новая версия | **пройден с оговоркой** | КП-2026-00001: виза → `quote.ready_for_approval` (визы ×2, маржа 23,10, порог 15,00) доставлено в EDS за 0,034 с, чек-лист зелёный; возврат с комментарием → ERP `DRAFT` с `director_decision=return` и текстом; повторная отправка → редакция 2 → одобрено, **ИСХ-001/26**, директор отправил клиенту: `SENT`, сделка `QUOTE_SENT`. КП-2026-00002: красный чек-лист (маржа 23,1 % < 25 %) → `approve` **409 `checklist_not_green`**, `failed: ["margin"]`, доступны `return/reject`; после правки — **ИСХ-002/26**, `SENT`. Отправка до одобрения — `400 INVALID_STATUS`, автором — `403 ROLE_NOT_PERMITTED`. Оговорки: C1-G-1 (срок), C1-G-4 (кто отправляет), C1-G-5 ([`p5r-quote1.txt`](qa/c1-eds/logs/p5r-quote1.txt), [`p5r-quote2-3.txt`](qa/c1-eds/logs/p5r-quote2-3.txt), [`p5r-quote-state.txt`](qa/c1-eds/logs/p5r-quote-state.txt), [`p5r-decided.txt`](qa/c1-eds/logs/p5r-decided.txt)) |
| 6 | Роль «Менеджер и бухгалтер» видит ровно свои права; негатив → 403 | **пройден** | `/me`: `letters.read, memos.create, payments.confirm, registry.export, registry.read` = каталог. Матрица «операция × сотрудник» по `x-rt-permissions` из `eds.yaml` (19 операций × 6 сотрудников): 0 расхождений; 403: `resolveLetter`, `registerLetter`, `returnLetter`, `rejectLetter`, `resubmitLetter` ([`p6-rbac-matrix.txt`](qa/c1-eds/logs/p6-rbac-matrix.txt), [`p6-rbac-negatives.txt`](qa/c1-eds/logs/p6-rbac-negatives.txt)) |
| 7 | EDS остановлен на 10 мин: CRM и ERP работают, события доходят после включения | **пройден с оговоркой** | честные 10 мин (04:07:39 → 04:17:40 UTC): заявка, лид, правка роли в CRM и КП с визой в ERP — все 200; 3 события копились (ConnectError, попытки 3–4); после включения доставлены **по расписанию повторов**: через 4 мин 48 с (2 события) и 7 мин 57 с (1 событие); 0 потерь, 0 дублей. Оговорка: C1-G-6 (задержка = расписание повторов); в ходе прогона упал один процесс Postgres (O-1, к EDS не относится) ([`p7-timeline.txt`](qa/c1-eds/logs/p7-timeline.txt), [`p7-deliveries-after.txt`](qa/c1-eds/logs/p7-deliveries-after.txt), [`p7-no-loss-no-dup.txt`](qa/c1-eds/logs/p7-no-loss-no-dup.txt)) |
| 8 | Нумерация: 50 параллельных создателей — без пропусков и дублей | **пройден** | 50 служебных записок (5 авторов) → **СЗ-2026/003 … 052**; 50 писем → **ВХ-004/26 … 053/26**; все 201, дублей 0, пропусков 0, 0,41 с и 0,28 с на все 50; счётчики `memo = 52`, `letter_in = 53` ([`p8-numbering.txt`](qa/c1-eds/logs/p8-numbering.txt), [`p8-numbering-db.txt`](qa/c1-eds/logs/p8-numbering-db.txt)) |
| — | `make smoke` на стенде; `eds-api`/`eds-worker` healthy; память | **пройден** | `make smoke` → `smoke: ok` (:8092; EDS в нём по замыслу нет — [`smoke.txt`](qa/c1-eds/logs/smoke.txt)); оба контейнера `healthy`; память — §2 |

**Дополнительно проверено** (все — как заявлено): отказы входа — повтор SSO-токена `401 replayed`, токен `aud=erp` `401 audience`, без Bearer `401`; отключение сотрудника в CRM закрывает уже выданный токен EDS через 0,6 с (`403 USER_INACTIVE`), возврат — через 0,3 с; отзыв КП автором после передачи директору — `409 QUOTE_AWAITING_DIRECTOR`; отклонение письма (`ВХ-054/26`) → сделка D-4 в `CLOSED_LOST` ([`extras.txt`](qa/c1-eds/logs/extras.txt)).

## 2. Стенд

Проект `rt-c1`, образы собраны из worktree (`up --build`), код приложений не менялся. Поднято: `postgres` (+`db-init`), `redis-broker`, `redis-cache`, `rustfs` (+`s3-init`), `litellm` (+`litellm-seed`, без них не стартует `crm-api`), `crm-migrate`, `crm-api`, `crm-worker` (`--no-deps`, без `docling`), `erp-backend`, `erp-worker`, `erp-beat`, `eds-migrate`, `eds-api`, `eds-worker`, `platform-bff` (подписчик `eds.*`), `caddy` (`--no-deps`); к концу — `cabinet-web` и `platform-web` (только для `make smoke`). Не поднимались: `crm-web`, `erp-web`, `crm-bot`, `crm-mcp-*`, `erp-mcp`, `erp-worker-ai`, `docling`, `langfuse`. Порты: `HTTP_PORT=8092`, `DEV_*` 5492, 6392, 6393, 9092, 9093, 4092, 8192, 8193, 3092, 8124. Телеграм выключен (`TELEGRAM_MODE=disabled`). Хост — Mac arm64 (проверка `cpu-baseline` под `qemu64` здесь не делалась — это `make deploy-check` в CI).

**Память** (`docker stats`, снимки [до](qa/c1-eds/logs/mem-before.txt) и [после](qa/c1-eds/logs/health-mem-after.txt) нагрузки и остановки): весь стенд ≈ 3,8 ГиБ (`erp-worker` 1,1 ГиБ, `litellm` 0,7, `crm-api` 0,55); `eds-worker` 94–100 МиБ; `eds-api` 184–190 МиБ — это dev с `--reload`: два процесса, родитель 95 МиБ RSS и рабочий 110 МиБ. Прод запускает один процесс без `--reload`: ≈ 110 МиБ после 100+ запросов при лимите 192 МБ (в `prod.yml` заявлено «≈ 80»). Запас ≈ 40 %, а не ~2,4× (192/80) — C1-G-8.

**Сотрудники** (вымышленные, `*@demo.example`; пароли генерировались скриптом и лежали только в файле состояния внутри контейнера):

| id | Сотрудник | Роли каталога | `permissions.eds` в проекции EDS |
|---|---|---|---|
| 1 | Администратор Демо | Администратор | `memos.create` |
| 2 | Директор Демо | Директор | все 9 кодов |
| 3 | Менеджер-Бухгалтер Демо | Менеджер + Бухгалтер | `letters.read, memos.create, payments.confirm, registry.export, registry.read` |
| 4 | Снабженец Демо | Снабженец | `memos.create, registry.read` |
| 5 | Инженер Демо | Гл. инженер | `memos.create, registry.read` |
| 6 | Менеджер Демо | Менеджер (в п. 7 добавлен Бухгалтер) | `letters.read, memos.create, registry.read` → +`payments.confirm, registry.export` |

Системной роли «Менеджер и бухгалтер» в каталоге нет: это сотрудник с двумя ролями-шаблонами (объединение прав, [`platform-rbac.yaml`](../../packages/contracts/platform-rbac.yaml)). Все шестеро получили доступ к ERP провижинингом (`platform_access: [crm, erp]`) — иначе визы упёрлись бы в `409 VISA_ASSIGNEE_NOT_IN_ERP`.

## 3. Пункты гейта: шаги и результат

Время — UTC (локальное +5 ч). Скрипты — `qa/c1-eds/sNN_*.py`, запуск `qa/c1-eds/run.sh <скрипт>` (§8).

### 1. Первый запуск — пройден

Шаги: `GET /setup/state` → `needs_setup: true`; `POST /setup/admin` (код из журнала `crm-api`, `setup_code_issued`) → администратор; `POST /integrations/erp/pair` с адресом ERP и паролем администратора, **без кода** (bootstrap по `PLATFORM_SSO_SECRET`) → «ERP сопряжена»; SSO-токен `aud=erp` → `POST /api/v1/auth/sso/exchange/` ERP → `POST /api/v1/setup/company/` (мастер своей компании «ООО «Демо Рейл Сервис»») → 201; `POST /users` пять раз с `platform_role_ids`, первый вход и смена временного пароля. Итог — таблица в §2. Проекция EDS получила `identity.user.created` на каждого сотрудника, `permissions.eds` равны ожидаемым из `platform-rbac.yaml` (ожидание выписано руками независимо от кода, [`s13_rbac_matrix.py`](qa/c1-eds/s13_rbac_matrix.py)).
Замечание: администратор создан до сопряжения, его первая попытка провижининга дала `erp_not_configured`; `erp_sync` стал `ok` повтором задачи (≤ 1–2 мин), до этого вход в ERP по SSO — `403 USER_NOT_PROVISIONED` (O-2).

### 2. Заявка → письмо; EDS снаружи недоступен — пройден

Менеджер: `POST /leads` (источник «звонок», с телефоном и e-mail) → `record_consent` → `make_customer` → `erp_handoff_status: done` через 1,2 с. В ERP `request.created` (`source: crm`, заявка №1, сделка `D-1`) ушёл подписчикам `crm`, `platform-bff`, `eds`; EDS зарегистрировал письмо **ВХ-001/26** (тема «Заявка: ООО «Демо Заказчик 1»», суть — потребность из лида, `links.erp_request_id/erp_deal_id/crm_client_id`). Токен: `POST /auth/sso/token {aud:"eds"}` от имени сотрудника → JWT с `iss=crm, aud=eds, ttl 60 с`, `permissions` справочно → `POST /api/v1/auth/sso/exchange` → Bearer на 900 с.
**Снаружи:** `POST` на `/api/v1/letters`, `/api/v1/auth/sso/exchange`, `/bus/v1/events`, `/api/v1/me`, `/api/v1/registry` через Caddy :8092 с `Host` `eds.localhost`, `crm|erp|platform|cabinet.localhost` и `127.0.0.1`: ответов EDS нет — 404/405/422/500 других сервисов, 502 (Cabinet не поднят) или пустой `200 Content-Length: 0` для неизвестного хоста (O-3).

### 3. Резолюция → задание расчёта — пройден

Директор через API EDS: исполнители goods — Снабженец (CRM 4), services — Гл. инженер (CRM 5), срок `2026-11-02`, `min_margin_pct: "15.00"` (процент — строкой, по контракту). Письмо `resolved`; в ERP `sales_calctask` №1 с `eds_letter_id`, номером, порогом и временем решения директора, исполнители сопоставлены с пользователями ERP (`goods` → supply@, `services` → engineer@); сделка в стадии `CALCULATING`, событие `deal.stage_changed` ушло в CRM и BFF. От вызова API до задания в ERP — 0,7 с.

### 4. Служебная записка — пройден

Автор «Менеджер Демо» (нет права решать). С суммой: `POST /documents` (`kind: memo`, `amount: {12500000.00, UZS}`, `Idempotency-Key`) → `СЗ-2026/001`; `submit` → маршрут «Служебная записка»: шаг 1 «Директор» (текущий), шаг 2 «Бухгалтер» (ожидает). Бухгалтер до директора — `403 FORBIDDEN`, автор — `403 FORBIDDEN`. Директор `approve` → шаг 2 становится текущим, в очереди «Менеджера-Бухгалтера» (`payments.confirm`, не автор) → `approve` → маршрут `approved`, документ `paid`, архив. События: `approval.requested` (шаг 1), `approval.decided` (1), `approval.requested` (шаг 2), `approval.decided` (2), `document.archived`. Журнал: 7 строк по документу (кто, что, когда, комментарий). Без суммы (`СЗ-2026/002`): маршрут из одного шага, после решения директора записка `approved`, бухгалтеру ничего не пришло.

### 5. КП — пройден с оговоркой

Подготовка: сделка D-1 с заданием расчёта; Снабженец создал КП (`POST /crm/quotes/`, две свободные строки с наценкой 30 %), отправил на согласование (виза зоны goods — самой отправкой), Гл. инженер завизировал (`approval-act`). Дальше — шесть наблюдаемых переходов; метки времени и состояния — по повторному прогону ([`p5r-quote1.txt`](qa/c1-eds/logs/p5r-quote1.txt), [`p5r-quote2-3.txt`](qa/c1-eds/logs/p5r-quote2-3.txt), [`p5r-quote-state.txt`](qa/c1-eds/logs/p5r-quote-state.txt), [`p5r-decided.txt`](qa/c1-eds/logs/p5r-decided.txt)):

1. ERP публикует `quote.ready_for_approval` (05:02:25.182; в `payload`: КП-2026-00001, версия 1, 2 визы — services и goods, маржа 23.10, порог 15.00, срок 2026-11-02), доставка в EDS 0,034 с; номер КП ERP присвоен при передаче директору. В EDS маршрут «КП», шаг «Директор», чек-лист: виза снабженца ✔, виза гл. инженера ✔, «маржа не ниже порога» ✔ (`23,1 % ≥ 15 %`), «срок расчёта выдержан» ✔ (`готово 26.10.2026, срок 02.11.2026`); снимок КП виден держателю `approvals.decide`.
2. **Возврат:** директор `return` с комментарием → ERP: КП снова `DRAFT`, `director_decision = return`, комментарий директора — по коду в журнале КП и уведомлении автору. Маршрут редакции 1 — `returned`.
3. **Повторная отправка новой версией:** Снабженец правит количество и отправляет снова → новая виза Гл. инженера → `eds_revision = 2`, новый маршрут (круг 2).
4. **Одобрение:** `approve` с каналом `email` → `approval.decided` с `outgoing_number` **ИСХ-001/26**; ERP применил решение за 0,04–0,08 с (`READY_TO_SEND`, номер и каналы на КП). Отправка разблокирована: директор отправил КП-2026-00001 клиенту (`SENT`).
5. **Красный чек-лист:** КП-2026-00002 (заявка с e-mail контакта, порог 25 %): маржа `23,1 % < 25 %`, `allowed_decisions = [return, reject]`, `approve` → **409 `checklist_not_green`**, `details.failed = ["margin"]`. Возврат → правка наценки до 45 % → виза → маржа `30,2 % ≥ 25 %` → `approve` → **ИСХ-002/26**.
6. **Отправка клиенту:** до одобрения (`PENDING_APPROVAL`, КП-2026-00002) — `400 INVALID_STATUS`; автором (Снабженец) после одобрения — `403 ROLE_NOT_PERMITTED` (у Менеджера и Бухгалтера `quote.send` в ERP тоже нет — список прав из SSO-обмена; C1-G-4); Директором — 200, КП `SENT`, цены заморожены, сделка `QUOTE_SENT` (обе сделки D-1, D-2).

Оговорки: **C1-G-1** — проверка Q-C1-E3-1 п. 3: КП-2026-00003 (срок резолюции — вчера, EDS его принял) получило красную строку «срок» (`готово 26.10.2026, срок 25.10.2026`), `approve` — 409 `failed: ["due"]`, а повторная резолюция по `resolved`-письму — 409 `invalid_state`; выхода нет, кроме отказа ([`s12_late_deadlock.py`](qa/c1-eds/s12_late_deadlock.py), [`p5r-quote2-3.txt`](qa/c1-eds/logs/p5r-quote2-3.txt)). Остальные — C1-G-4, C1-G-5 (поля `outgoing_number`/`director_*` в API КП ERP отсутствуют и после E7: [`p5r-c1g5.txt`](qa/c1-eds/logs/p5r-c1g5.txt)).

### 6. Права роли «Менеджер и бухгалтер» — пройден

`/me` каждого из шести сотрудников равен ожидаемому по каталогу (6 из 6). Для каждого сотрудника вызваны все 19 операций `eds.yaml` с пустым телом и случайным UUID: нет права — 403, есть — 404/422/200 (проверка права идёт раньше поиска объекта); расхождений с `x-rt-permissions` — 0. У «Менеджера и бухгалтера» разрешено 14 операций (чтение писем и реестра, **экспорт реестра**, документы, маршруты, решение по шагу бухгалтера, файлы), запрещено 5: `registerLetter`, `resolveLetter`, `returnLetter`, `rejectLetter`, `resubmitLetter`. Тела отказов: `{"code":"FORBIDDEN","details":{"permission":"letters.resolve"}}`; другие негативы — Менеджер без `registry.export` → экспорт 403; Администратор (R3-D-2) → `GET /registry` и `GET /letters` 403 (`registry.read`, `letters.read`); Снабженец → `GET /letters` 403.

### 7. Остановка EDS на 10 минут — пройден с оговоркой

| Время (UTC) | Событие |
|---|---|
| 04:07:39 | `docker compose stop eds-api eds-worker` (T0) |
| 04:07:44–48 | `CRM /health` 200, `ERP /health` 200, `EDS /health` — нет соединения; CRM: заявка (лид 4 → клиент 4, передача в ERP — `done`), обычный лид 5, смена ролей «Менеджер Демо» (+Бухгалтер) — все 200/201; ERP: новое КП №4 на сделке D-1, отправка, виза инженера — 200, КП `PENDING_APPROVAL` |
| 04:07:55 | у издателей копятся доставки `eds`: CRM — 1 (`identity.user.updated`), ERP — 2 (`request.created`, `quote.ready_for_approval`), `ConnectError: Name or service not known`; остальные подписчики (`erp`, `platform-bff`, `crm`) получают без задержки |
| 04:12:43 / 04:16:41 | попытки 3 → 3 и 2 → 3; расписание повторов 30 с → 2 мин → 10 мин: следующие — 04:22:23–28 и 04:25:36 |
| 04:17:40 | `docker compose start eds-api eds-worker` (T1 = T0 + 601 с), `healthy` в 04:18:01 |
| 04:22:28–29 | доставлены `identity.user.updated` (CRM) и `request.created` (ERP) — **через 4 мин 48 с** после включения, попытка 4 |
| 04:25:37–44 | доставлено `quote.ready_for_approval` (ERP) — **через 7 мин 57 с**, попытка 4; EDS обработал за 7 с, маршрут «КП» №4 открыт |

Итог: письмо **ВХ-054/26** по заявке 4 появилось, права сотрудника «Менеджер Демо» в проекции обновились до `letters.read, memos.create, payments.confirm, registry.export, registry.read`, маршрут КП-2026-00004 открыт. Потерь нет (недоставленных у CRM и ERP — 0), дублей нет: в inbox EDS 19 событий, 19 уникальных `event_id`, все `processed`; писем с одной заявкой ERP больше одного — 0; маршрутов на одну редакцию КП больше одного — 0; за время остановки EDS не принял ничего.
**Оговорка (C1-G-6):** время доставки после включения определяется расписанием повторов (до ~12 мин при простое ≥ 10 мин), а не восстановлением подписчика; это поведение шины v1, как в гейте B.
**Происшествие (O-1):** в 04:22:54 один серверный процесс Postgres завершился с кодом 2, сервер за 4 с восстановился (`recovery`), `eds-worker` и `crm-worker` перезапущены Docker; данные целы, доставки до сбоя уже прошли, после него — по расписанию.

### 8. Нумерация — пройден

Два потока по 50 запросов, старт по барьеру (`threading.Barrier`), каждый со своим `Idempotency-Key`. Служебные записки — 5 авторов по кругу: статусы `{201: 50}`, диапазон `СЗ-2026/003 … СЗ-2026/052`, дублей 0, **пропусков нет**, 0,41 с всего, p50 0,25 с. Входящие письма (директор): `{201: 50}`, `ВХ-004/26 … ВХ-053/26`, дублей 0, пропусков нет, 0,28 с. Полный отсортированный список — [`p8-numbering.txt`](qa/c1-eds/logs/p8-numbering.txt). Проверка по базе: `СЗ` — 52 записи / 52 различных номера, `ВХ` — 53 / 53; `number_counters`: `memo 2026 = 52`, `letter_in 2026 = 53`, `outgoing 2026 = 2` (ИСХ-001/26, ИСХ-002/26 — один счётчик на КП и письма).

## 4. Дефекты

Серьёзность: «важный» — мешает пилоту/этапу D или потеряет данные у пользователя; «малый» — неудобство без потерь.

| № | Серьёзность | Что | Шаги | Ожидание / факт | Предложение |
|---|---|---|---|---|---|
| **C1-G-1** | важный | Тупик: КП, готовое позже срока резолюции, нельзя одобрить, срок продлить нельзя (подтверждает Q-C1-E3-1 п. 3) | `POST /letters/{id}/resolution` с `due` вчера (принимается, 200) → КП собрано сегодня → маршрут «КП» → строка «срок расчёта выдержан» красная → `approve` 409 `checklist_not_green` (`failed: ["due"]`); повторная резолюция по письму `resolved` — 409 `invalid_state`; возврат КП не помогает (`ready_at` всегда позже срока) | Ожидание: директор может одобрить, осознанно приняв опоздание, либо продлить срок. Факт: остаётся только `reject`/бесконечный `return`; опоздание на день блокирует сделку. Сервер при этом ещё и принимает срок в прошлом | Принять рекомендацию E3: строка `due` — предупреждение (`ok=True`, как «маржа без порога»), блок остаётся для виз и маржи; отдельно — 422 на `due` < сегодня; позже — продление срока без новой резолюции. Решение архитектора (SPEC §7.3 говорит «неактивна, пока не зелёный») |
| **C1-G-2** | важный → **закрыт** (E7a, #225; повторный замер §9) | События EDS уходили подписчикам с задержкой ~4–5 с: ретранслятор EDS не просыпался по коммиту | любое действие в EDS → сравнить `rt_bus_outbox.created_at` и `rt_bus_delivery.delivered_at` ([`p-latency.txt`](qa/c1-eds/logs/p-latency.txt) — до E7a; [`p-latency-repeat.txt`](qa/c1-eds/logs/p-latency-repeat.txt) — после) | **До:** EDS → `erp` p50 3,75 с, max 5,1 с (n = 10); EDS → `platform-bff` p50 4,78 с, max 5,14 с (n = 124); у CRM и ERP — p50 0,05–0,07 с. Причина: `apps/eds/app/bus/runtime.py` не передавал `wakeup`. **После E7a:** EDS → `erp` p50 0,064 с, p95 0,084 с, max 0,086 с (n = 8); EDS → `platform-bff` p50 0,009 с, p95 0,045 с, max 0,086 с (n = 117), недоставленных 0 — на уровне CRM и ERP, критерий ≤ 2 с для колокольчика (этап D) выполнен | Закрыто. Замер на объёме гейта (≈ 130 событий); для приёмки этапа D повторить на экранах |
| **C1-G-3** | важный → **закрыт** (E7b, #226; повторная проверка §9) | Проекцию сотрудников в EDS нельзя было переопубликовать | EDS поднят, когда сотрудники CRM уже есть: события `identity.user.*` для `eds` не создавались (доставки раскладываются по подписчикам, существующим на момент публикации); команд повторной публикации не было; `PATCH /users/{id}` без изменений события не порождает | **До:** `403 USER_NOT_PROVISIONED` на обмене токена, пока у сотрудника не изменится роль/поле/активность. **После E7b:** сотрудник удалён из проекции EDS → обмен `403 USER_NOT_PROVISIONED` → `python -m app republish-identity --user-id 6` (в `crm-api`) → проекция восстановлена за ≤ 6 с, обмен 200 и `/me` с прежними правами; `republish-identity` без аргументов — 6 из 6, повторы EDS приняты идемпотентно ([`p-republish.txt`](qa/c1-eds/logs/p-republish.txt)) | Закрыто. В runbook деплоя: после первого деплоя EDS при наличии сотрудников выполнить `docker compose … exec crm-api python -m app republish-identity` (`--dry-run` покажет число) |
| **C1-G-4** | важный (вопрос архитектору) | Отправить клиенту одобренное КП могут только Директор и Администратор | КП-2026-00002 одобрено → `POST /crm/quotes/2/send-to-client/` от Снабженца (автор) → 403 `ROLE_NOT_PERMITTED`; от Директора → 200; у Менеджера, Бухгалтера и Гл. инженера `quote.send` в списке прав ERP нет. Права ERP: `quote.send` только у ролей с `eds.drafts: full` ([`platform-rbac.yaml`](../../packages/contracts/platform-rbac.yaml)) | Ожидание по тексту волны: «отправка клиенту разблокирована» для того, кто ведёт клиента (менеджер) или автора КП. Факт: разблокирована, но отправить может лишь директор, который сам же и одобрял | Решить: оставить («одобрение и отправка» — один ресурс, подпись раздела так и называется) или отделить `quote.send` от `eds.drafts` (например, в `eds.inbox`/`erp.calc` для менеджера); если оставить — зафиксировать в SPEC, иначе в пилоте менеджер упрётся в 403 |
| C1-G-5 | малый (открыт, подтверждён повторным прогоном) | ИСХ-номер и комментарий возврата не видны в API КП ERP | `GET /crm/quotes/{id}/` после `approve` и `return` | В ответе нет `outgoing_number`, `director_decision`, `director_comment`, `send_channels` (поля есть в модели и в БД, в `crm/serializers/quote.py` их нет; автор узнаёт из уведомления и журнала). У КП в `DRAFT` после возврата нет признака «на доработке» (отличить от обычного черновика можно только по `director_decision` в БД) | Добавить поля в `QuoteSerializer` (до экранов этапа D; фронтенд ERP удаляется на C2) |
| C1-G-6 | малый | Доставка после простоя EDS ≥ 10 мин занимает 5–8 мин (до ~12) | см. §3 п. 7 | События дошли ровно по расписанию повторов; вернувшийся подписчик не «будит» накопленное | Принять (поведение шины v1) и записать в runbook EDS; либо при старте EDS дёргать `bus retry` у издателей / сброс расписания у вернувшегося подписчика |
| C1-G-7 | малый | У письма из заявки CRM пусты отправитель и менеджер | реестр после §3 п. 2: `sender.name = null`, `manager = null` | Клиент виден только в теме и `links.crm_client_id`; `request.created` несёт имя актора, но не его `crm_user_id` и не название компании | Либо EDS берёт имя клиента/менеджера из события (добавить поля аддитивно), либо экраны D показывают их по `links`; решить до экранов D |
| C1-G-8 | малый | Память EDS в `prod.yml` занижена | §2: рабочий процесс `eds-api` ≈ 110 МиБ RSS, `eds-worker` 94–100 МиБ (в `prod.yml`: «≈ 80 и 70»); лимит 192 МБ | запас ≈ 40 % после 100 запросов; при росте (файлы, XLSX-экспорт реестра до 10 000 строк) риск OOM | поднять лимит до 256 МБ или замерить с экспортом на проде; поправить комментарий |

## 5. Наблюдения

- **O-1.** Postgres стенда: 04:22:54 «server process (PID 7535) exited with exit code 2» → автоматическое восстановление за 4 с (контейнер не перезапускался). Причина не установлена (Docker Desktop, Mac arm64). EDS и CRM пережили: `eds-worker` остановился на ошибке `update_heartbeats` и был перезапущен Docker (`restart: unless-stopped`), `pump` с ошибкой повторился. Данные целы.
- **O-2.** Если сотрудники созданы до сопряжения с ERP, провижининг ждёт повтора (30–60 с); «Подключить ERP» не запускает его сразу. Не EDS.
- **O-3.** Caddy для неизвестного хоста отвечает пустым `200`, а не 404; `POST /api/v1/auth/sso/exchange` ERP без завершающего `/` — 500 (dev). Не EDS; на «снаружи EDS нет» не влияет.
- **O-4.** ERP при остановленном EDS принимает КП «на согласование» и оставляет его `PENDING_APPROVAL`, событие ждёт в outbox (как описано в [`deploy.md`](deploy.md)): подтверждено п. 7.
- **O-5.** Статусы документов: служебная с суммой после бухгалтера — `paid`, без суммы — `approved`; обе сразу в архиве (`archived_at` = момент решения).

## 6. Что нужно для деплоя EDS на прод

По [`deploy.md`](deploy.md) («EDS — сервис документооборота») и результатам гейта; `infra/deploy/tests/eds-prod-test.sh` на этом коде — `ok` (внешнего маршрута нет).

1. **VPS 1, `/opt/rt/.env.prod`:** `make-env-prod.sh init` дописывает `DB_EDS_PASSWORD`, `EDS_ACCESS_SECRET`, `S3_EDS_ACCESS_KEY/SECRET_KEY`, четыре секрета пар шины `RT_BUS_SECRET_CRM_EDS`, `RT_BUS_SECRET_ERP_EDS`, `RT_BUS_SECRET_EDS_ERP`, `RT_BUS_SECRET_EDS_PLATFORM_BFF`; **`PLATFORM_SSO_ENABLED=true`** (по умолчанию в `.env.prod.example` — `true`; на стенде гейта без него токен для EDS не выдаётся — Q-E4-1 п. 4) и общий `PLATFORM_SSO_SECRET` (уже есть). Пустой `RT_BUS_ENDPOINT_EDS` — адрес из `subscriptions.yaml` (`http://eds-api:8000/bus/v1/events`).
2. **VPS 2:** база `eds` и роль `eds_app` — после переноса `DB_EDS_PASSWORD` запустить `infra/deploy/db-up.sh` под root (`prod-init.sh`: роль, база, `REVOKE CONNECT` чужим ролям, `rt_backup` читает; `pg_hba` — `hostssl eds eds_app <внутренний IP VPS 1>/32`); в списки бэкапа, WAL-G и `reset-prod.sh` база `eds` уже включена. Postgres перезапустится на секунды.
3. **Бакет `eds-private` и ключ `S3_EDS_*`:** руками ничего — `s3-init` создаёт при каждом деплое (политика `rt-eds`).
4. **Порядок выкладки:** EDS **раньше или вместе с ERP** (один `deploy.sh` поднимает оба): `deploy.sh` берёт pg_dump-гейт `crm`/`erp`/`eds` → `eds-migrate` (`alembic upgrade head`) → `up` → `healthy` у `eds-api` и `eds-worker` (≤ 120 с). ERP без EDS работает, но КП застревают в `PENDING_APPROVAL` до подписчика (п. 7 гейта подтвердил, что события не теряются). Откат EDS при ERP с EDS-03 не делать.
5. **Сотрудники — до или после EDS?** Сотрудники, созданные в CRM **до** появления подписчика `eds`, сами в проекции EDS не появятся. После E7b (#226) это лечится командой: после деплоя EDS выполнить `docker compose … exec crm-api python -m app republish-identity` (`--dry-run` — только посчитать, `--user-id N` — одного сотрудника); проверено на стенде (§9). На чистом проде (сброс 2026-10-25) сотрудники создаются уже при работающем EDS и команда нужна только для тех, кто заведён раньше.
6. **Права:** кто может отправлять КП клиенту — решить до пилота (C1-G-4); администратор бизнес-документов не видит (`memos.create` и только), директор получает всё.
7. **Проверка после деплоя:** `ps eds-api eds-worker` — `healthy`; `exec eds-api python -m app bus status` (метрики outbox/inbox/DLQ); обмен токена сотрудника через BFF (этап D) или, до экранов, `docker compose exec` с токеном CRM; снаружи любые пути — 404/чужой ответ. Память: `eds-api` ≈ 110 МиБ, `eds-worker` ≈ 95 МиБ при лимите 192 МБ — следить (C1-G-8).
8. **Не готово до этапа D:** экранов EDS нет. Задержка событий EDS после E7a ≈ 0,01–0,09 с — колокольчик по `eds.*` в ≤ 2 с укладывается.

## 7. Не проверено

- Экраны и Платформа/BFF-путь токена (`platform-bff` подписан на `eds.*` и принимал события, но путь «браузер → BFF → EDS» — этап D).
- Файлы документов (`POST /files`, версии, S3 `eds-private`), экспорт реестра CSV/XLSX, исходящее письмо `letter_out` с ИСХ при отправке, заявления и отчёты — тесты E3, на стенде гейта не гонялись.
- `make deploy-check` целиком и образ под CPU `qemu64` — задания CI (`deploy-check`, `cpu-image`); на стенде проверен только `eds-prod-test.sh`.
- Реальная доставка КП клиенту (почта/Telegram): почта и бот на стенде выключены; проверена стадия ERP (`SENT`, заморозка, `QUOTE_SENT`).
- Повторный прогон остановки EDS без сбоя Postgres: сбой пришёлся на 05-ю минуту после включения, после первой пары доставок; выводы о расписании повторов от него не зависят (доставки совпали с `next_attempt_at` до секунды).

## 8. Как повторить

```
make -C <repo> env     # или infra/compose/make-env.sh; в .env: HTTP_PORT=8092, свои DEV_*_PORT, PLATFORM_SSO_ENABLED=true, TELEGRAM_MODE=disabled
docs/runbooks/qa/c1-eds/dc.sh up -d --build crm-api erp-backend erp-worker erp-beat eds-api eds-worker platform-bff
docs/runbooks/qa/c1-eds/dc.sh up -d --no-deps crm-worker caddy
docs/runbooks/qa/c1-eds/run.sh s01_setup.py <код из журнала crm-api>     # затем s02, s03, s04 … s17 в порядке номеров
docs/runbooks/qa/c1-eds/psql.sh eds "select * from letters"            # проверка баз
docs/runbooks/qa/c1-eds/dc.sh down -v --remove-orphans                 # после гейта; затем docker rmi образов rt-c1-*
```

Скрипты — стандартная библиотека Python, запускаются в контейнере `crm-api` (EDS без внешнего маршрута); пароли демо-сотрудников генерируются на лету. Порядок: `s01_setup` → `s02_pair_erp` → `s03_staff` → `s04_request.py 1` → `s05_resolution.py` → `s06_memo.py` → `s07_quote_build.py` → `s08_quote_visa.py <step_id>` → `s09_quote_decide.py return|approve [комментарий]` → `s10_quote_resubmit.py` → `s11_quote_send.py` → `s13_rbac_matrix.py` → `s14_numbering.py` → `s15_outage_actions.py` (между `stop eds-api eds-worker` и `start`) → `ev_poll_after.sh`; `s16_extras.py`, `s17_deactivate.py` — дополнительные проверки.

## 9. Повторный прогон после E7a (#225) и E7b (#226)

`main` @ `7b92f137`, стенд `rt-c1` пересоздан с нуля (те же правила: :8092, `PLATFORM_SSO_ENABLED=true`, без лишних сервисов; после прогона `down -v`). Сценарий первого прогона воспроизведён заново: setup, ERP, 6 сотрудников, 3 заявки с резолюциями (порог 15 / 25 / 15 при сроке «вчера»), КП 1–3, письмо №4 с отклонением.

- **Пункт 5 (КП)** — логи вместо пересказа: [`p5r-quote1.txt`](qa/c1-eds/logs/p5r-quote1.txt) (чек-лист зелёный, возврат с комментарием, `director_decision = return` в ERP, повторная отправка редакцией 2, ИСХ-001/26, `SENT`), [`p5r-quote2-3.txt`](qa/c1-eds/logs/p5r-quote2-3.txt) (`400 INVALID_STATUS` до одобрения, `409 checklist_not_green` + `failed: ["margin"]`, `403 ROLE_NOT_PERMITTED` у автора, отправка директором, ИСХ-002/26, тупик C1-G-1: `failed: ["due"]` и `409 invalid_state` на повторную резолюцию), [`p5r-quote-state.txt`](qa/c1-eds/logs/p5r-quote-state.txt) (КП и сделки в ERP — `SENT`/`QUOTE_SENT`, маршруты EDS, таблица `quote.ready_for_approval` с номером КП, редакцией, числом виз, маржой, порогом и сроком; прежние пустые колонки исправлены — данные лежат в `data.payload`), [`p5r-decided.txt`](qa/c1-eds/logs/p5r-decided.txt) (EDS → ERP за 0,04–0,08 с). Старый `p5-quote-flow.txt` удалён как содержавший пустые колонки.
- **Отклонение письма** ([`extras-repeat.txt`](qa/c1-eds/logs/extras-repeat.txt)): `reject` письма ВХ-004/26 → сделка D-4 в `CLOSED_LOST`; также повтор SSO-токена `401 replayed`, `aud=erp` `401 audience`, без Bearer `401`, отзыв КП у директора `409 QUOTE_AWAITING_DIRECTOR`.
- **Нумерация** ([`p8r-numbering.txt`](qa/c1-eds/logs/p8r-numbering.txt)): снова 50 + 50 параллельных — `СЗ-2026/001…050`, `ВХ-005/26…054/26`, дублей и пропусков нет; все события доставлены.
- **C1-G-2** закрыт (таблица в §4, [`p-latency-repeat.txt`](qa/c1-eds/logs/p-latency-repeat.txt)). Для сравнения: у издателя CRM подписчик `erp` показал p95 2,0 с (единичный всплеск при создании сотрудников) — не EDS.
- **C1-G-3** закрыт ([`p-republish.txt`](qa/c1-eds/logs/p-republish.txt)).
- **Не изменилось:** C1-G-1, C1-G-4, C1-G-5, C1-G-6, C1-G-7, C1-G-8.
