# EDS (электронный документооборот) — `apps/eds`
Статус: действует (каркас — волна 12, задача E2; домен — E3) · Владелец: архитектор · Обновлено: 2026-10-29

EDS — отдельный сервис со своей базой `eds` (ADR-0015): письма и резолюции, служебные записки, заявления, отчёты, общий движок
маршрутов согласования, реестр и нумерация документов. Стек — [ADR-0013](../../adr/0013-stack-and-standards.md): FastAPI + SQLAlchemy 2
(async, psycopg 3) + Alembic + Procrastinate. Интеграции — только через шину `rt_bus` ([ADR-0014](../../adr/0014-integration-bus-rt-bus.md),
[`rt-bus.md`](../../architecture/rt-bus.md)). План волны — [`wave12-eds-c1.md`](../../history/runbooks/wave12-eds-c1.md). Правила кода — [`CONVENTIONS.md`](CONVENTIONS.md).

| Владеет данными | Публикует события | Подписывается на |
|---|---|---|
| входящие и исходящие письма с регистрацией, резолюции, служебные записки, заявления, отчёты; **общий движок маршрутов согласования** (КП, договор, служебка); реестр и архив документов (метаданные, версии, сканы, журнал «кто и когда») | `letter.*`, `document.*`, `approval.requested/decided` (контракт — `packages/contracts/events/eds/`) | CRM: `identity.user.*`; ERP: `request.created`, `quote.ready_for_approval` |

## Что сделано

**Каркас (E2).**

| Есть | Где |
|---|---|
| `GET /health` — живость и база (`200`/`503`), `X-Request-ID` в ответе и в каждой записи журнала, единый формат ошибок `Error` (`code`, `message`, `source="eds"`, `details`) | `app/api/health.py`, `app/errors.py`, `app/log.py` |
| вход: `POST /api/v1/auth/sso/exchange` (SSO-токен сотрудника CRM → токен доступа EDS), `GET /api/v1/me`, зависимости `current_employee` и `require_permission(*коды)` | `app/api/`, `app/security/`, `app/services/sso.py` |
| проекция сотрудников `employees` из `identity.user.created/updated/deactivated` (права `permissions.eds`), идемпотентно | `app/bus/handlers.py`, `app/services/employees.py` |
| шина: таблицы outbox/inbox, приёмник `POST /bus/v1/events`, ретранслятор и обработка inbox в `eds-worker`, `python -m app bus …` | `app/bus/`, `app/tasks/`, `app/cli/bus_cli.py` |

**Домен (E3)** — подробнее в разделе «Домен» ниже: реестр и нумерация, входящие письма и резолюции, документы, движок маршрутов согласования, КП (EDS-03), журнал, файлы
в S3 с версиями, реестр «Все документы» и экспорт. Дальше: **E4** — CRM публикует `permissions.eds` и выдаёт токен сотрудника для EDS; **E5** — ERP; **E6** — гейт этапа C1.
Экраны — этап D (Платформа).

## Структура

```
apps/eds/
  app/            api/ (health, v1/: auth, me, letters, documents, approvals, registry, files) · schemas/ (модели eds.yaml)
                  bus/ (handlers, snapshots, erp_snapshots, runtime) · models/ · security/ · services/ · tasks/ · cli/
                  config.py · db.py · log.py · errors.py · clock.py · container.py · main.py · __main__.py
  alembic/        env.py, versions/ (YYYYMMDD_HHMM_slug), sql/ (снимок схемы Procrastinate 3.10.0)
  tests/          unit (без базы) и pg (настоящий PostgreSQL) — маркер `pg`
  Dockerfile      один образ: api, worker, миграции (`python -m app api|worker`, `alembic upgrade head`)
```

## Команды (из корня репозитория)

| Что | Команда |
|---|---|
| зависимости (новый worktree — первым шагом) | `make -C apps/eds install` |
| ruff, mypy `--strict`, все тесты | `make check-eds` (то же: `make -C apps/eds check`) |
| тесты без базы (секунды) | `make -C apps/eds test-unit` |
| один тест | `cd apps/eds && ./scripts/with_pg.sh uv run pytest tests/<файл>.py -x -q` |
| миграция | `make -C apps/eds migration m="…"` (нужна база по `EDS_DATABASE_URL`) |
| как CI | `scripts/ci_local.sh eds` · образ под CPU `qemu64`: `make cpu-check args="rt-eds"` (на Mac arm64 долго) |

Тесты идут против настоящего PostgreSQL: без `EDS_TEST_DATABASE_URL` `scripts/with_pg.sh` поднимает одноразовый `postgres:17` (удаляется после прогона; имя —
`EDS_PG_CONTAINER`). Стенд ансамбля и его базы тестами не затрагиваются.

## Переменные окружения

Читает только `app/config.py` (`pydantic-settings`); в compose их задаёт `infra/compose/base.yml` из `.env` (шаблоны — `.env.example`, `infra/.env.prod.example`).

| Переменная | Что задаёт |
|---|---|
| `EDS_DATABASE_URL` | `postgresql+psycopg://<роль>:<пароль>@<хост>:5432/eds` (прод: роль `eds_app`, `?sslmode=require`) |
| `EDS_ACCESS_SECRET` | секрет токена доступа EDS (HS256, 15 минут), ≥ 16 символов |
| `PLATFORM_SSO_SECRET` | общий секрет SSO-токена сотрудника CRM; ротация — два значения через запятую |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` | RustFS: свой ключ сервиса, бакет `eds-private` (в `.env` — `S3_EDS_*`); файлы документов (E3) |
| `RT_BUS_SECRET_CRM_EDS`, `RT_BUS_SECRET_ERP_EDS` | приём событий CRM и ERP (проверка подписи) |
| `RT_BUS_SECRET_EDS_ERP`, `RT_BUS_SECRET_EDS_PLATFORM_BFF` | подпись доставки событий EDS в ERP и BFF Платформы |
| `RT_BUS_CONTRACTS_DIR`, `RT_BUS_SUBSCRIPTIONS` | схемы событий и подписки; в образе — `/opt/rt/contracts`, задаёт Dockerfile |
| `RT_BUS_ENDPOINT_<ИМЯ>` | необязательное переопределение адреса подписчика |
| `APP_ENV` (`dev`/`prod`/`test`), `LOG_LEVEL`, `LOG_FORMAT` (`json`/`console`), `EDS_VERSION`, `WORKER_CONCURRENCY` | служебные |

## Вход и права

Своей формы входа у EDS нет. Нормативно — [`sso-token.md`](../../architecture/sso-token.md), «Токен сотрудника для EDS» (решение L-C1-1), и [`wave12-eds-c1.md`](../../history/runbooks/wave12-eds-c1.md) §2.2:

1. BFF берёт у CRM SSO-токен (`aud=eds`, 60 с, одноразовый `jti`) и вызывает `POST /api/v1/auth/sso/exchange {token}`.
2. Проверки по порядку: подпись `PLATFORM_SSO_SECRET` (оба значения) → `aud == "eds"` → срок (`exp` не прошёл с допуском 5 с, `exp − iat ≤ 60 (+5)`) → `jti` не встречался
   (таблица `sso_jti`, 10 минут, уборка задачей) → сотрудник **только по `sub`** в проекции: нет — `403 USER_NOT_PROVISIONED`, неактивен — `403 USER_INACTIVE`.
   Отказы первых четырёх — `401 INVALID_SSO_TOKEN` (`details.reason`: `signature`, `audience`, `expired`, `lifetime`, `replayed`, `malformed`). Обмен никого не создаёт.
3. Ответ `{access_token, token_type: "bearer", expires_in: 900}`; refresh нет (истёк — новый SSO-токен у CRM).
4. Каждый запрос — `Authorization: Bearer`; сотрудник и его права берутся из проекции **на момент запроса**: отзыв роли и отключение действуют сразу. Нет права — `403 FORBIDDEN`
   (`details.permission`). Коды v1: `letters.read`, `letters.register`, `letters.resolve`, `memos.create`, `memos.approve`, `approvals.decide`, `registry.read`, `registry.export`, `payments.confirm`, с eds.yaml 0.3.0 — `bus.manage` (журнал шины, раздел `admin` уровня `full`, W13-A2), `files.upload` (D1-2b; свой файл: `POST /files` и чтение только своих файлов, раздел `crm.clients` уровня `full` — письмо директору к «Создать заявку», D1-2b). Неизвестные будущие коды проекция хранит как строки и не падает.

Тест `tests/test_contract_permissions.py` сверяет права маршрутов с `x-rt-permissions` в `eds.yaml`.

## Шина

Подписчик `eds` в `packages/contracts/bus/subscriptions.yaml` получает `identity.user.*`, `erp.request.created`, `erp.quote.ready_for_approval`, `erp.contract.status_changed`, `erp.invoice.*`, `erp.act.*` (проекция документов проектов, D2-5) по `POST http://eds-api:8000/bus/v1/events`
(только сеть compose). Приём: подпись → inbox → задача `rt_bus.process_inbox` в `eds-worker`. Проекция сотрудников — `app/bus/handlers.py`:

- более старый снимок не применяется (версия — `user.updated_at`, у `deactivated` — время события); повтор безвреден;
- права читаются терпимо: нет `user.permissions.eds` (CRM до E4) — прав нет; неизвестные коды хранятся, но не действуют;
- `deactivated` раньше `created` оставляет «надгробие» (`email = ''`), запоздавший старый снимок доступ не вернёт.

Типы без обработчика приёмник записывает как `skipped` и отвечает 200. `erp.request.created` и `erp.quote.ready_for_approval` обрабатывает домен (см. ниже). Эксплуатация —
экран **Admin · Журнал интеграций** Платформы (W13-A2): API `/api/v1/bus/*` (`eds.yaml`, тег `bus`, право `bus.manage`), каждый повтор — строка журнала EDS
`bus.*` с автором (`docs/architecture/rt-bus.md`, «Журнал в Admin»); запасной путь — `docker compose … exec eds-api python -m app bus status|dead|failed|retry|retry-dead|retry-inbox`.

## Домен (E3)

Нормативка — [`wave12-eds-c1.md`](../../history/runbooks/wave12-eds-c1.md) §2 и контракт (`packages/contracts/openapi/eds.yaml`, `events/eds/`): здесь только устройство кода. Объекты в пути
адресуются UUID, не номером (номер содержит «/»; номер — поле и фильтр `GET /registry?number=`). Слои: `api/v1/*` → `services/*` (команды и чтение отдельно: `letters` /
`letters_read` и т. д.) → `models/*`; события публикует только сервис, в транзакции изменения.

| Что | Как устроено | Код |
|---|---|---|
| **Нумерация** (§2.1) | строка `number_counters (kind, year)` под `SELECT … FOR UPDATE` в транзакции создания; год — по `Asia/Tashkent`; откат возвращает номер, выданный номер не возвращается; `ИСХ` — один счётчик на письма и КП | `services/numbering.py`, `clock.py` |
| **Письма** | `awaiting_resolution` → `resolved` / `returned` (→ `submit` → снова ждёт) / `rejected`; регистрация вручную или по `erp.request.created` (идемпотентно по `erp_request_id`, без него — по сделке; отправитель — компания, ИНН и контакт, менеджер — `manager_crm_user_id` из `payload` заявки, если есть — C1-G-7); резолюция хранится в письме, срок `due` — не раньше сегодня по `Asia/Tashkent` (иначе `422`, C1-G-1) | `services/letters.py`, `letters_read.py`, `bus/handlers.py` |
| **Поручения** (P8b, SPEC-v3 §3.2a) | путь письма `track_of`: `calc` (есть `erp_request_id`, или нет вида документа и есть `erp_deal_id`) — резолюция «расчёт по зонам», иначе `office` — `POST …/office-resolution` трёх типов (`409 track_mismatch` на чужую); проект делопроизводителя — `letters.resolution_draft` (JSONB, `PUT …/resolution-draft`); поручения `instructions` (ответственный и соисполнители, `in_work` → `executed`, отчёт, файлы `files.instruction_id`, ИСХ), переносы `instruction_extensions` (один без решения — частичный уникальный индекс; срочное одобрить нельзя), ознакомление `letter_acquaintances`; все исполнены — письмо `executed`, `on_control = false`; ИСХ `in_reply_to` при отправке закрывает «Подготовить ответ» (`close_by_outgoing` из `documents._send_letter`); напоминания — задача `instruction_reminders` (раз в 30 минут, с 9:00, `reminders_sent` — одна точка один раз, правила — чистая функция `reminder_due`); уведомления — `notice.requested` (доставляет CRM); участник поручения видит письмо и файлы без `letters.read` (`require_readable`, `can_view_file`) | `services/instructions.py`, `models/instructions.py`, миграция `20261101_1814_letter_instructions` |
| **Документы** | `memo`/`application`/`report` — номер при создании, правка черновика без отправки — `PATCH /documents/{id}` (0.4.0, D1-5: автор, `draft`/`returned`, журнал `document.updated`), маршрут при `submit`, версия растёт после возврата (снимок тела в `document_versions`); `letter_out` — `ИСХ` при отправке; архив (`archived_at`, `document.archived`) автоматически | `services/documents.py`, `document_state.py` |
| **Маршруты** (§2.5) | маршрут = круг; шаги «сотрудник или любой с правом»; шаблоны: служебная — директор (`memos.approve`) → бухгалтер (`payments.confirm`, если есть сумма), заявление и отчёт — директор, КП — директор (`approvals.decide`); решения `approve`/`return`/`reject`, `comment` обязателен для двух последних; `approval.requested` — на каждом шаге, ставшем текущим | `services/approvals.py`, `approvals_read.py` |
| **КП** (EDS-03) | `erp.quote.ready_for_approval` → маршрут «КП» (идемпотентно по КП и версии; событие старее известной версии игнорируется; новая версия закрывает открытые круги прежних — `returned`, шаг `skipped`, журнал `approval.superseded`, события нет); чек-лист на сервере: визы, маржа ≥ порога **резолюции EDS** (блокирующие: красная строка → `409 checklist_not_green`), срок расчёта — **предупреждение** (`blocking = false`): КП, готовое позже срока, директор одобряет с отметкой `approved_late` у маршрута, строкой журнала `approval.approved_late` и полем `approved_late` в `approval.decided` (решение архитектора 2026-10-26, C1-G-1, [`DECISIONS.md`](../../DECISIONS.md)); одобрение выдаёт `ИСХ-` в `approval.decided` | `services/quotes.py`, `checklist.py` |
| **Проекты** (D2-5) | договор, счёт и акт проекта — владелец ERP, EDS хранит проекцию для реестра «Все документы»: строка на `(kind, erp_id)` по событиям `erp.contract.status_changed`, `erp.invoice.issued/paid/overdue`, `erp.act.issued/accepted/returned` (идемпотентный upsert, старое событие по `time` не перезаписывает новое; название — сделка, клиент и ответственный — из письма по заявке); статус — слово SPEC-v3 §2.4 как прислал ERP; события не публикуются, решений нет. `GET /registry` отдаёт `kind=contract\|invoice\|act` с `links.erp_deal_id` (eds.yaml 0.5.0) только держателям `registry.read` (суммы и клиенты проекта): без права этих видов в реестре нет совсем | `models/project_documents.py`, `services/project_documents.py`, миграция `0008_project_documents` |
| **Справочники** (EDS-REG, eds.yaml 0.9.0) | значения — данные администратора, поведение — код из закрытого списка (`SPECS`): таблица `dictionary_items (kind, code)` — название ru/uz/en, `attrs` по описанию вида, «действует», порядок; виды `letter-kinds` (`urgent` — «срочно» при регистрации, `due_days` — подсказка срока резолюции) и `receipt-methods`; ресурс `/dictionaries/{kind}` (читают `letters.read`/`letters.register`/`bus.manage`, меняет `bus.manage` — код раздела `admin`); код из названия, использованное значение только скрывается (`409 value_in_use` на удаление); письмо хранит код строкой, регистрация принимает только действующие коды; каждое изменение — строка журнала `dictionary.*`. Миграция `20261103_1200_dictionaries` засеяла прежние константы и сняла CHECK способа получения | `services/dictionaries.py`, `models/dictionaries.py`, `api/v1/dictionaries.py` |
| **Шаблоны резолюций** (EDS-REG R2, eds.yaml 0.9.0) | `resolution_templates`: личные (`owner_crm_user_id`, директор и делопроизводитель) и общие (`company`, `bus.manage`); вид — закрытый список `execute/reply/info` (названия — справочник `resolution-kinds`, закрытый: только переименовать и переставить); ответственный `person`, `addressee` (адресат письма) или `none`; соисполнители, «ознакомить», срок в днях; у «Для сведения» людей-исполнителей и срока нет (код снимает); люди — активные сотрудники; чужой личный — 404; журнал `resolution_template.*`. Шаблон только заполняет форму резолюции, письмо его не хранит | `services/resolution_templates.py`, миграция `20261104_1000_resolution_templates` |
| **«Заполнить из файла»** (EDS-REG, ИИ-помощник регистрации) | только по кнопке, ничего не пишет в письмо: файл письма (`POST /letter-intake`) → PDF с текстовым слоем — текст `pypdf`, маска ПД (`security/pii.py`, правила CRM, скрытые числа — нумерованными метками, возврат номера — локально) по политике защиты данных для ИИ (PD-BIZ, DECISIONS 2026-11-03: «Деловая» по умолчанию — паспорт, ПИНФЛ, карты, даты рождения; «Строгая» — ещё телефоны, почта, ИНН, счета; политика — проекция настройки CRM `ai.pii_policy`, событие `crm.ai_policy.changed`, `docflow_settings.pii_policy`, читается при каждом вызове) → модель; скан или фото — при «Деловой» и включённом `docflow_settings.recognize_scans` (по умолчанию вкл., переключатель — «Расходы на ИИ» Платформы, подпись «паспорта и личные документы не загружайте»), при «Строгой» — 409 `scan_recognition_disabled`; пределы до чтения — PDF 10 МБ и 30 страниц, изображение 5 МБ, разбор PDF в потоке; ИНН своей компании (бланк) не берётся; алиас `intake-model` через LiteLLM своим ключом `EDS_LITELLM_API_KEY` (регистрирует `python -m app ai-key-sync`, сервис `eds-ai-gateway`, дневной бюджет `EDS_AI_DAILY_BUDGET_USD`, также проверяется по журналу, 0 — без лимита; на проде ключ создаёт `make-env-prod.sh ensure-secrets`); промпт `app/ai/prompts/letter_intake.md` (версия — SHA-256[:12]); JSON по схеме, код решает: вид — только действующий код `letter-kinds`, даты разбираются, ИНН — регулярным выражением в исходном тексте; журнал `ai_suggestions` без текстов (кто, когда, функция, алиас, версия промпта, источник, итог, токены, стоимость, решение человека `accepted/edited/manual`) | `services/letter_intake.py`, `app/ai/`, `services/docflow_settings.py`, миграции `20261105_1000_ai_letter_intake`, `20261107_1000_pii_policy` |
| **Дубли входящих** (EDS-DUP, eds.yaml 0.10.0) | одно письмо — один ВХ (ГОСТ Р 7.0.97; эталоны — проверка дублей 1С:Документооборота и Directum RX): точное совпадение «корреспондент (ИНН, иначе название без регистра, кавычек и ООО/LLC/MChJ) + исх. № + дата исх.» — 409 `duplicate_letter`, `force` с причиной (журнал `letter.duplicate_forced`); гонку ловит частичный уникальный индекс `uq_letters_dedup_key` (у `force` и дубля ключа нет; миграция дала ключ только самому раннему из совпадающих). Похожие (корреспондент + тема ±3 дня, исх. № с другой датой, тот же SHA-256 файла) — `POST /letters/duplicates-check`, только подсказка. «Это дубль ВХ-…» (`POST /letters/{id}/duplicate`, `letters.register`): статус `duplicate`, `duplicate_of_id`, поручения `cancelled`, ожидающие «ознакомить» сняты, номер не освобождается; после резолюции — `confirm`, путь `calc` после резолюции — 409 `calc_in_progress` | `services/letter_dedup.py`, миграция `20261106_1000_letter_duplicates` |
| **Журнал** | `journal`: кто, что, когда, файл — по письму, документу, маршруту; без объекта — `registry.export`, `sso.exchange` | `services/journal.py` |
| **Оплата служебной записки** (D2-4, eds.yaml 0.5.0) | `POST /documents/{id}/payment` (`payments.confirm`): дата платежа (не в будущем по `Asia/Tashkent`), сумма (≤ согласованной, валюта записки), платёжка — файл из `POST /files`; записка обязана быть `to_accountant`, шаг «Бухгалтер» — ждать этого сотрудника (`approvals.may_decide`: автор не платит свою записку, если есть другой держатель права); закрывает шаг решением `approve`, статус → `paid`, архив, журнал `document.paid`; таблица `document_payments`; повтор с теми же данными идемпотентен, другие — 409 `already_paid`; `approve` через `/approvals/{id}/decision` на шаге бухгалтера — 409 `payment_required`, в `allowed_decisions` его нет | `services/payments.py`, `models/documents.py` |
| **Файлы** | метаданные в `files`/`file_versions`, содержимое в S3 `eds-private` (`files/<id>/v<n>`), чтение потоком; ≤ 25 МБ (отказ по `Content-Length` до разбора multipart), PDF/изображения/Office (по типу и сигнатуре); новая версия — `version_of` (добавляет загрузивший, автор документа или регистратор писем, пока документ в `draft`/`returned`, письмо в `awaiting_resolution`/`returned`) | `services/files.py`, `storage.py` |
| **Реестр** | один запрос по письмам, документам и маршрутам КП: фильтры SPEC §7.3, курсор, `?number=`; экспорт CSV/XLSX без внешних библиотек, ≤ 10 000 строк. **Реестр не шире прав на вид документа (D1-10)**: письма (`letter_in`, `letter_out`) — только с `letters.read`, чужие черновики (`draft`) не видит никто, кроме автора; отбор — в SQL до курсора, экспорт — те же правила | `services/registry.py`, `registry_export.py` |
| **Разделение обязанностей** | автор документа не решает шаг по своему документу, пока есть другой активный держатель права шага; адресат ≠ автор; на КП не действует | `services/access.py` (`step_open_to`), `approvals.may_decide` |
| **Видимость** | без `registry.read` — свои документы и маршруты, где сотрудник участник (назначен, держит право шага или уже решал); иначе `404`. Снимок КП (себестоимость, маржа) — только держателю `approvals.decide`. Для документов в любом случае (D1-10): чужой черновик видит только автор, `letter_out` — только с `letters.read`, даже у держателя `registry.read`; один предикат `document_visible` у реестра, `/documents`, карточки и файлов; маршрут документа (`/approvals`, `route_visible`) — участнику всегда, неучастнику только если виден документ, КП — по `registry.read` (`403 not_author` на чужой черновик теперь `404`) | `services/access.py`, `services/registry.py` |
| **Идемпотентность** | `Idempotency-Key` создающих POST: таблица `idempotency_keys`, 24 часа, уборка задачей `idempotency_cleanup` | `services/idempotency.py` |

Тесты домена: `tests/test_numbering.py`, `test_letters.py`, `test_letter_instructions.py` и `test_instruction_rules.py` (P8b), `test_documents.py`, `test_quotes.py`, `test_erp_events.py`, `test_files.py`, `test_registry.py`, `test_project_documents.py`,
`test_payments.py` (оплата записки: матрица ролей, объектная проверка, идемпотентность, правила суммы), `test_permissions_matrix.py` (по `x-rt-permissions` контракта), `test_review_rules.py`, `test_outbox_atomicity.py` (откат — события нет), `test_concurrency.py` (50 параллельных создателей), `test_contract_permissions.py`
(прямая и обратная сверка маршрутов с `eds.yaml`). Ответы проверяются по схемам `components.schemas` самого контракта (`tests/domain.py`, `validate`). S3 в тестах — хранилище в памяти и
локальный S3-совместимый сервер для `S3Storage`.

Решения сверх контракта (вопросы архитектору — `docs/QUESTIONS.md`, Q-C1-E3-1): адресат документа с `addressee_crm_user_id` обязан иметь `memos.approve` (иначе `422`);
`file_ids` при `submit` добавляются к уже привязанным; регистрация письма вручную требует отправителя или клиента CRM; строка «маржа» чек-листа без резолюции или без порога зелёная
(«порог не задан»), а значение маржи скрыто от тех, кто не решает КП; `details.fields` доменных `422` — как у ошибок разбора: `[{field, message, type}]`.

## Как поднять локально

`make env && make up` поднимает весь ансамбль, включая `eds-migrate` → `eds-api` и `eds-worker` (база `eds` создаётся `db-init`). Порт EDS на хост не публикуется и в Caddy маршрута нет —
смотреть только изнутри сети compose:

```bash
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml exec eds-api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"
```

Отдельный стенд для проверки без трогания общего: `docker compose -p rt-c1 …` со своим `.env` и `HTTP_PORT` (ORCHESTRATOR §4); поднимать только нужные сервисы
(`postgres`, `s3-init`, `eds-migrate`, `eds-api`, `eds-worker`), после — `down -v`.

## Прод

Образ `rt-eds` собирает `.github/workflows/deploy.yml`; в `prod.yml` — `eds-api`, `eds-worker`, `eds-migrate` (256 МБ у api и 192 МБ у worker; факт гейта C1 ≈ 110 и 95–100 МиБ — C1-G-8). База `eds` и роль `eds_app` — на VPS 2
(`infra/db/prod-init.sh`, `pg_hba`, бэкап и WAL-G включают `eds`), бакет `eds-private` и ключ `S3_EDS_*` — `s3-init`. Миграции — `deploy.sh` после pg_dump-гейта. Что сделать
владельцу до первого деплоя — [`deploy.md`](../../runbooks/deploy.md), раздел «EDS — сервис документооборота»; память — [`servers.md`](../../runbooks/servers.md).
**Внешнего маршрута нет** ни на одном домене (решение волны 12 §4 п. 4); `make deploy-check` это проверяет (`infra/deploy/tests/eds-prod-test.sh`).
