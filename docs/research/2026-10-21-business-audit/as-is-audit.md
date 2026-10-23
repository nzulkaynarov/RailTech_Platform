# RailTech Platform — картина «КАК ЕСТЬ» (as-is) бизнес-процесса и ролей

Дата: 2026-10-21 · `main @ cc9a0a44` · материал для аудита бизнес-логики (архитектор по поручению владельца).

**Степень проверки.** Источники — `docs/*`, `docs/ORCHESTRATOR.md`, `apps/*/CLAUDE.md`, `docs/systems/crm/SPEC.md`, `docs/adr/crm/0022`,
`docs/QUESTIONS.md`, `docs/PROGRESS.md`, `docs/runbooks/deploy.md`, `servers.md`. Факты из кода в этом отчёте взяты из тех
документов, которые сами являются описанием кода с путями к файлам (`docs/systems/erp/CONVENTIONS.md` §5–§7, `docs/systems/crm/SPEC.md` §6–§13,
ADR-0022 CRM, строки DECISIONS с путями). Прямая построчная сверка с исходниками (три фоновых прогона по `apps/crm`, `apps/erp`,
`apps/cabinet`) **не успела завершиться** до сдачи отчёта — такие места помечены «(по документу; сверить с кодом)».
Упомянутые в задании «FIX-65…71» в репозитории **отсутствуют**: последний номер — FIX-64 (`docs/DECISIONS.md:157`), а
«тупики на проде» описаны в `docs/runbooks/deploy.md:184-207` и `docs/DECISIONS.md:159-161`.

---

## A. Сводная карта процесса as-is

Целевая картина — `docs/product/BUSINESS.md:102-132` (10 шагов, три передачи) и `docs/product/BUSINESS.md:217-233` (полный цикл с каталогом,
закупкой, приёмкой). Ниже — что из этого есть, кто и где действует, что видит клиент, и где разрыв.

| # | Шаг | Кто | Где (система / экран / бот) | Событие / интеграция | Что видит клиент | Состояние в коде |
|---|---|---|---|---|---|---|
| 1 | Первое сообщение | лид | Telegram-бот CRM (`/start`, выбор языка, согласие) | — | `texts.language_first` на 3 языках, согласие с кнопкой (`docs/systems/crm/SPEC.md:534`, `:362`) | есть |
| 1b | Веб-форма «Я новый клиент» | лид | `cabinet.*/` страница входа → `POST /api/v1/leads/web` CRM | CORS только `CABINET_ORIGIN` | «Спасибо» + «Написать в Telegram» (`docs/systems/cabinet/CONVENTIONS.md:70`) | есть; лид `web` без ответственного, бот ему не пишет (`docs/systems/crm/SPEC.md:374`) |
| 1c | Звонок / письмо / рекомендация | менеджер | CRM «Входящие → Новый лид» | — | ничего | есть; лид сразу `in_progress` (`docs/systems/crm/SPEC.md:375`); согласие — кнопкой «Согласие получено» (FIX-57, `docs/DECISIONS.md:152`) |
| 2 | Квалификация | бот + квалификатор (код) | CRM, стадии `new → engaged → qualified` | score (`domain/scoring.py`), триггеры `settings.escalation` | диалог по KB | есть (`docs/systems/crm/SPEC.md:327-354`) |
| 3 | Передача менеджеру | триггер → канал команды | стадия `handoff`, пост в приватный канал, кнопка «Забрать» → `in_progress` | `LeadService.take` | «ваш вопрос у менеджера» | есть (`docs/systems/crm/SPEC.md:497-522`) |
| 3→4 | **Передать в бэк-офис** | менеджер фронт-офиса | CRM карточка лида/клиента; кнопка видна только в режиме `erp` (коннектор ERP настроен) из `in_progress`/`won`/`customer` | `POST /api/integration/v1/clients/handoff` (`docs/architecture/CONTRACTS.md:34`); идемпотентно по `crm_client_id`, поиск по ИНН, 409 `INN_CONFLICT` (`docs/systems/erp/CONVENTIONS.md:105`) | приглашение в кабинет **только письмом** (`sent_via` — реально ушедшее; Telegram ERP не шлёт: `docs/systems/erp/CONVENTIONS.md:105`); бот один раз пишет `texts.client_access_granted` (`docs/systems/crm/SPEC.md:532`) | есть; стадия лида = `customer` (ADR-0022, `docs/adr/crm/0022-…md:66-73`). **Тупики:** лид без согласия — 422 `handoff_no_consent`; в режиме `local` клиент создаётся без ERP, повторная передача — только кнопкой FIX-34b (`docs/PROGRESS.md`, строка FIX-34b); контакт без e-mail приглашение не получает (`CONTACT_EMAIL_REQUIRED`, `docs/QUESTIONS.md:213-219`) |
| 4 | Заявка в очереди | бэк-офис, роль «Расчёт» | ERP: сделка FSM стадия `DRAFT` (`stages.initial_fsm_stage`, `docs/systems/erp/CONVENTIONS.md:105`), «Взять в работу / Вернуть в очередь / Назначить» (`Deal.assigned_to`, `docs/systems/erp/CONVENTIONS.md:220`) | событие `request.created(source=crm|cabinet)` → лента лида CRM (`docs/architecture/CONTRACTS.md:63`) | статус в Cabinet «Запросы» | есть; ИИ-разбор запроса в строки — задача `intake` через LiteLLM (`docs/systems/erp/CONVENTIONS.md:120-121`) |
| 5 | КП | «Расчёт» → согласование (`quote.review`, `quote.approve_final`) → `quote.send` | ERP конструктор КП; курс фиксируется при отправке на согласование (`docs/systems/erp/CONVENTIONS.md:110`); позиции правятся только в `DRAFT` (FIX-55, `:111`) | `quote.sent {public_url, valid_until}` → CRM → бот «КП готово» с кнопками «Открыть КП» и «Кабинет» (`docs/architecture/CONTRACTS.md:65`; тексты ×3 языка — FIX-34) | КП в Cabinet (`SENT/APPROVED/REJECTED`), публичная страница `/api/v1/public/quotes/<token>/` с PDF 202 + Retry-After (`docs/DECISIONS.md:108`) | есть. Разрыв: автор не может согласовать своё КП (403 `SELF_APPROVAL_NOT_ALLOWED`), но единственный согласующий — автосогласование; автор-руководитель закрывает последний шаг сам (`docs/QUESTIONS.md:554-560`) |
| 6 | Акцепт | клиент | Cabinet `POST /quotes/{id}/request-code` → код 6 цифр → `accept {code}` / `reject {reason}`; публичная страница — тот же код | код уходит **письмом**; в Telegram — прямой Bot API из ERP за флагом `PORTAL_ACCEPT_CODE_TELEGRAM` (нарушение «ERP в Telegram не пишет», снимается в FIX-60: `docs/history/runbooks/wave6-agents.md:40-41`); ни e-mail, ни Telegram → 422 `CONTACT_CHANNEL_REQUIRED` (`docs/systems/erp/CONVENTIONS.md:102`) | «принято», договор формируется | есть. Разрыв: контакт без e-mail и без Telegram-привязки **не может принять КП** |
| 7 | Договор | ERP «Расчёт» (`contract.manage`), подпись компании — `contract.sign` (только «Расчёт»? нет: `HEAD`; см. B) | договор рождается из принятого КП; статусы `PENDING_CLIENT / PENDING_MANAGER / SIGNED` (`docs/systems/erp/CONVENTIONS.md:102`) | `contract.signed {by}`; при подписи обеими сторонами — `_finalize_if_signed` → сделка `CLOSED_WON`, событие `deal.won` (`docs/QUESTIONS.md:310`, `docs/DECISIONS.md:149`) | «Подписать» в Cabinet (`billing.tsx`), только для контакта с `can_act` | есть. Разрывы: порядок подписей «компания раньше клиента» — открыт (D-08, `docs/PROGRESS.md:157`); **ЭЦП/E-IMZO нет** (отложено до пилота, `docs/DECISIONS.md:34`); подпись = клик; офлайн-клиент — загрузка скана (`docs/DECISIONS.md:70`) |
| 8 | Счёт → оплата | «Финансы» (`finance.invoice`, `finance.payment`) | ERP: счёт из КП/договора, фиксация оплаты вручную (`ManualModeBanner`, `docs/DECISIONS.md:69`) | `invoice.issued/paid/overdue` → бот «счёт выставлен» (`docs/architecture/CONTRACTS.md:68`); ссылка `{CABINET_URL}/invoices/<id>` — **страницы счёта в Cabinet нет** (`docs/DECISIONS.md:154`) | счёт в списке «Счета», просрочка считается из `due_date` на клиенте (`docs/DECISIONS.md:63`) | есть, но: `OVERDUE` не проставляется (`docs/systems/erp/CONVENTIONS.md:292`), платёжного провайдера нет, политики «предоплата / по факту / по этапам» (ARCHITECTURE §11) в коде **не найдено** по документам ERP (сверить с кодом) |
| 8b | Исполнение / поставка | «Исполнение и логистика» (`fulfillment.manage`) | ERP `Fulfillment` → `sales.DeliveryLine` по строкам подтверждённого КП, статусы контракта `assembling…delivered`; накладная из отгрузки (`docs/systems/erp/CONVENTIONS.md:102-103`) | `delivery.status_changed`, `delivery.eta_changed` (эмитируется? — ETA считать нечем до M4), `delivery.line_accepted|disputed` | «Поставки» по строкам: принять / «есть замечания» | есть частично: склада, резервов, заказов поставщикам **нет** (`supply`, `inventory` — M4, не начата: `docs/HANDOFF.md:24`); приёмка всех строк клиентом **не двигает** исполнение (Q-FIX22-5, FIX-62 не сделан) |
| 9 | Акт | «Исполнение» (`fulfillment.act`) выставляет из счёта; клиент принимает / возвращает | ERP → Cabinet `POST /acts/{id}/accept {upload_id?}` / `return {reason}` | `act.issued/accepted`; **`act.returned` боевым кодом не выпускается** (`docs/QUESTIONS.md:505`, FIX-62) | «всё завершено» — но сделку закрывает подпись договора, а не акт (`docs/systems/erp/CONVENTIONS.md:102`) | разрыв: «закрыто» в ERP наступает на шаге 7, а не 9; акт — «по факту поставки, не по оплате» (`docs/systems/erp/CONVENTIONS.md:292`) |
| 10 | Повторный запрос / вопросы | клиент | Cabinet «Новый запрос» → заявка `DRAFT` с `source=cabinet` (`docs/systems/erp/CONVENTIONS.md:103`); бот — сервисный режим | `request.created(source=cabinet)` → лента лида CRM | «Написать менеджеру» → `t.me/<bot>?start=deal_<id>` | есть, но **бот не разбирает `/start deal_<id>`** и отвечает приветствием (`docs/systems/cabinet/CONVENTIONS.md:132`); сервисный режим через `erp-mcp` (M3-CRM-07) **не реализован** (`docs/HANDOFF.md:23`, `docs/history/runbooks/wave6-agents.md:61`) |

### A.1. Шаги, которые есть в документах, но нет в коде

- BUSINESS §9 шаги 0, 4–6, 8 (каталог с импортом прайсов, back-to-back заказ поставщику, резерв, приёмка от поставщика,
  накладная с треком, дропшип, ATP-дата) — веха M4 не начата (`docs/ORCHESTRATOR.md:224-239`, `docs/HANDOFF.md:24`).
- BUSINESS §4 шаг 10 «бот в сервисном режиме отвечает “где мой акт” сам» — `erp-mcp` на стороне ERP есть (FIX-36), промпт
  `dialog_customer.md` и инструменты в агенте CRM — M3-CRM-07 не сделан. SPEC CRM §7.3 честно: «статус — заглушка в v2 →
  `create_service_request`» (`docs/systems/crm/SPEC.md:451`).
- ARCHITECTURE §7 «центр внешних сервисов показывает сервисы ERP» — ERP-сторона M3-ERP-06 не сделана; CRM-часть есть (ADR-0024).
- ARCHITECTURE §7/§18 «один набор SMTP на ансамбль, выдаётся ERP» и «мастер первого запуска ансамбля» — M3-CRM-11 не сделан;
  SMTP в ERP — свой `.env` (см. E).
- ARCHITECTURE §9 «Администратор CRM = суперпользователь ERP» — провижининг `admin → is_superuser` есть, но **роли бэк-офиса
  из CRM выдать нельзя** (D-10, `docs/QUESTIONS.md:515-526`): админ ERP назначает их вручную в «Команде».
- CONTRACTS §4 `POST /team/invite` с `channels: [telegram]` — 422 `INVALID_CHANNEL` (`docs/QUESTIONS.md:213`).
- CONTRACTS §2 `invite{channels: [telegram, email]}` — Telegram-приглашение ERP не делает (`docs/systems/erp/CONVENTIONS.md:105`).

### A.2. Шаги, которые есть в коде, но не описаны как процесс

- Режим `local` CRM («Сделать клиентом» без ERP, закрытие сделки в CRM `won/lost`) — живёт параллельно режиму `erp`
  (`docs/adr/crm/0022-…md:66-73`); переключение — фактом настройки коннектора, пользователь об этом не знает.
- Зеркало сделок `deals` в CRM с `erp_deal_id`/`external_stage` и запретом правок полей ERP (409 `deal_owned_by_erp`,
  `docs/DECISIONS.md:152`) — «вторая воронка» в CRM, которую BUSINESS не описывает.
- Force-эндпоинты ERP (`force-approve`, `force-cancel`, `force-change-stage`) — только `is_superuser`, экранов нет
  (`docs/DECISIONS.md:138`).
- Публичная страница КП с кодом по e-mail (наследие B2B) — параллельный Cabinet путь акцепта.

### A.3. Тупики, найденные на проде и прогонах (факты)

- Прод установлен 2026-10-21; CPU VPS без x86-64-v2 → официальный LiteLLM и numpy ≥ 2.4 не стартуют; **Langfuse/ClickHouse
  на проде недоступны**, docling не проверен и не используется (`docs/runbooks/servers.md:64-83`, `deploy.md:196-200`).
- База знаний на проде — только Markdown по формату, docling снят; документы клиентов без извлечения текста (`docs/DECISIONS.md:161`).
- Первый вход владельца: код мастера из `docker logs … grep setup_code_issued` → `/setup` → дальше вручную коннектор ERP,
  ключи моделей, бот, почта (`docs/runbooks/deploy.md:203-207`) — «сопряжение в один клик» (M3-CRM-10) не сделано.
- Гонка `workflow_dispatch` деплоя с мержем — релиз без нового файла (`deploy.md:194-196`).
- Прогоны M1/M2: P0 D-04 (позиции КП менялись после отправки) закрыт FIX-55; D-10 (роли из CRM) открыт; D-08 (порядок
  подписей) открыт; D-3 `promised_date: null` открыт (`docs/PROGRESS.md:147-158`).
- Не проверено на стенде: «Написать менеджеру» (нет `TELEGRAM_BOT_USERNAME`), Mini App на телефоне, ИИ и сообщения бота
  (`docs/PROGRESS.md:148,158`).

---

## B. Роли as-is

### B.1. Коды ролей

| Система | Коды | Где |
|---|---|---|
| CRM | `admin`, `manager`, `viewer`; инвариант «≥ 1 активный admin»; `users.platform_access` ∈ {`["crm"]`, `["crm","erp"]`}; `users.ui_mode` Админ/Менеджер — только навигация | `docs/systems/crm/CONVENTIONS.md:159`, `docs/architecture/CONTRACTS.md:144`, `docs/systems/crm/SPEC.md:575-577` (по документу; сверить с `app/security/*`, casbin policy) |
| ERP — системные роли `BackofficeRoleCode` | `CALCULATION` (Расчёт), `CATALOG_SUPPLY` (Каталог и закупки), `FULFILLMENT` (Исполнение и логистика), `FINANCE` (Финансы), `HEAD` (Руководитель — все права), `VIEWER` (Наблюдатель — ни одного) | `docs/systems/erp/CONVENTIONS.md:183-193`; сеются `accounts/0003_backoffice_roles` |
| ERP — права (22 кода) | `deal.manage`, `deal.assign`; `quote.build`, `quote.edit_pricing`, `quote.view_cost_margin`, `quote.send`, `quote.review`, `quote.approve_final`; `contract.manage`, `contract.sign`; `catalog.manage`, `catalog.publish`; `supply.manage`; `fulfillment.manage`, `fulfillment.act`; `finance.invoice`, `finance.payment`, `finance.rates`; `settings.edit`, `settings.charge_templates`; `team.manage`; `data.export` | `docs/systems/erp/CONVENTIONS.md:171-181`, `accounts/constants.py` (по документу) |
| ERP — администратор | `is_superuser` (нет роли «Администратор компании») | `docs/systems/erp/CONVENTIONS.md:217` |
| ERP — роль «CRM Sync: <e-mail>» | создаётся провижинингом из CRM (`managed_by_crm`), в «Команде» не правится | `docs/DECISIONS.md:153` |
| Карта CRM → ERP | `admin` → суперпользователь; `manager` → `deal.manage, quote.build, quote.edit_pricing, quote.send`; `viewer` → нет прав | `docs/DECISIONS.md:127`, `docs/architecture/sso-token.md` |
| Клиент | `parties.Contact` с сессией портала; `can_act` (по умолчанию `False` с FIX-54; `True` при создании сотрудником и при передаче новой компании из CRM) | `docs/DECISIONS.md:154` |

### B.2. Таблица ролей: рабочий день, права, экраны, тупики

| Роль | Что делает | Система / экраны | Права в коде | Чего не может / тупик |
|---|---|---|---|---|
| **Лид** | пишет боту, выбирает язык, даёт согласие, задаёт вопросы, делится телефоном | Telegram-бот (меню `prospect`: Начать · Связаться с менеджером · Сменить язык · Что умеет бот · Удалить переписку, `docs/systems/crm/SPEC.md:530`); веб-форма на входе Cabinet | — | лид `web`/`phone` боту не пишет и ответов не получает; до согласия бот только приветствие; «Связаться с менеджером» → эскалация, ответит человек из CRM |
| **Клиент** | смотрит запросы/КП/договоры/счета/акты/поставки/документы, принимает КП (код), подписывает (клик), принимает акт (скан), приёмка строк поставки, новый запрос, команда, каталог с ценами | Cabinet (веб по magic-link, Mini App по `initData`); бот в меню `client` (`/docs`, `/request`, `/status`, `/human`) | `can_act` на мутациях; чтение — любому контакту компании; чужая компания 404 | нет страницы счёта; нет уведомлений в приложении (только бот/почта); бот не понимает `/start deal_<id>`; «статус» в боте — заглушка; приглашение коллеги только по e-mail; код акцепта без e-mail/Telegram — 422; контакт, пришедший «по ИНН», — `can_act=false` и без приглашения (Q-FIX31-5) |
| **Менеджер фронт-офиса (CRM `manager`)** | «Входящие» (передачи, мои, без ответственного, запросы клиентов), «Забрать», переписка от имени бота, шаблоны ответов, «Новый лид», «Согласие получено», «Передать в бэк-офис», «Закрыть отказом», «Новая сделка», привязка Telegram клиенту, документы клиенту | CRM: Входящие, Лиды, Карточка лида, Клиенты, Сделки, Документы, KB (ro), Дашборд (`docs/systems/crm/SPEC.md:554-573`) | `leads:*`, `clients:write`, `kb:read`, `reply_templates:read` … (матрица `GET /me/permissions`; точные объекты casbin — сверить) | в режиме `erp` не может «Сделка заключена» (409 `won_decided_by_erp`); не видит ERP-стадию иначе как `external_stage` в зеркале; при `platform_access=["crm"]` нет кнопки в ERP; SSO включается флагом `PLATFORM_SSO_ENABLED` |
| **ERP `CALCULATION` Расчёт** | берёт заявку, ИИ-разбор, КП (позиции, цены, расходы), отправка на согласование, отправка клиенту, договор (подготовка) | ERP: очередь заявок, карточка сделки, конструктор КП, договоры | `deal.manage, quote.build, quote.edit_pricing, quote.view_cost_margin, quote.send, quote.review, contract.manage` (`docs/systems/erp/CONVENTIONS.md:188`) | не подписывает договор (`contract.sign` только у HEAD), не выставляет счёт, не видит договорной курс; автор не согласует своё КП |
| **ERP `CATALOG_SUPPLY` Каталог и закупки** | карточки товаров/услуг, публикация, предложения поставщиков (ручной остаток), импорт Excel, ИИ-обогащение | ERP: каталог, офферы, категории | `catalog.manage, catalog.publish, supply.manage, quote.view_cost_margin` (`:189`) | заказов поставщикам, приёмок, счетов поставщиков нет (M4) — роль из BUSINESS §11 реализована на четверть |
| **ERP `FULFILLMENT` Исполнение и логистика** | отгрузки, накладные, акты (выставить из счёта, переоформить, напомнить) | ERP: отгрузки, акты | `fulfillment.manage, fulfillment.act` (`:190`) | склад/остатки/трек ETA нет; приёмка клиента не двигает исполнение; `act.returned` не уходит в CRM |
| **ERP `FINANCE` Финансы** | счета клиентам, фиксация оплат, договорной курс КП, факт закупки (отклонение маржи), экспорт | ERP: счета, платежи, курсы | `finance.invoice, finance.payment, finance.rates, quote.view_cost_margin, data.export` (`:191`) | оплата только вручную; просрочка не проставляется; счетов поставщикам нет; напоминания — есть ли задача? (сверить) |
| **ERP `HEAD` Руководитель** | всё: финальное утверждение КП, подпись договора, команда, настройки | ERP: всё + Settings Hub | все коды (`:192`) | не `is_superuser`: нет `system-settings`, force-действий, справочников (ADMIN_ONLY) |
| **ERP `VIEWER` Наблюдатель** | только просмотр всех реестров | ERP | нет кодов | дашборд показывает «Объём сделок» — политика (`docs/PROGRESS.md:157`) |
| **Администратор** | CRM: Подключения (бот, ERP, почта), Модели ИИ, Пользователи (+ доступ к ERP), Настройки, KB, Пробелы KB, Проверить бота, Аудит, Расходы, Внешние сервисы, Состояние системы, `/setup`; ERP: `is_superuser` — Settings Hub, справочники, шаблоны писем, force-действия, «Команда» (роли вручную) | CRM + ERP (переключатель по SSO), Django Unfold (инженерам: журнал вебхуков, повтор) | CRM `admin`; ERP `is_superuser` | **прыгает между системами**: роли ERP — только в ERP; SMTP, LiteLLM-ключ, Sentry, курсы ЦБ ERP — в `.env` ERP, не в консоли (см. E); сопряжение CRM↔ERP — ручное копирование токенов; Mini App — в BotFather |
| **Руководитель бизнеса / наблюдатель** | дашборды | CRM Дашборд (лиды, передачи, выиграно по зеркалу, стоимость моделей), «Расходы»; ERP дашборд | CRM `viewer`/`admin`; ERP `VIEWER`/`HEAD` | сквозной цифры «от сообщения до оплаты» нет: воронка CRM кончается на `customer`, деньги — в ERP/зеркале |

---

## C. Кабинет клиента as-is

Источник — `docs/systems/cabinet/CONVENTIONS.md:55-76`, `docs/architecture/CONTRACTS.md:76-111`, `docs/DECISIONS.md:52-67,109`.

| Экран | Данные | Действия клиента | Чего нет |
|---|---|---|---|
| Вход (веб) | `POST /auth/magic-link` → ссылка `/auth/magic#token` → `POST /auth/magic` | «Войти», «Я новый клиент» (форма → CRM `web`-лид) | пароль «необязательный» по ARCHITECTURE §5 — не реализован (по документам Cabinet его нет) |
| Mini App | `POST /auth/telegram` при каждом запуске; `start_param` `deal_<id>`/`quote_<id>` | — | выхода нет; cookie `SameSite=None` ⇒ только HTTPS |
| Запросы `/requests` | `GET /requests`, `GET /requests/{id}`; виджет «Требует вашего решения» (КП, договоры на подпись, неоплаченные счета, акты) | «Новый запрос»: строки + вложения (`POST /uploads`), подбор из каталога | нет статуса «в расчёте» как отдельного — только `DealRef` и стадия |
| КП `/quotes` | строки (позиции/разделы/заметки/этапы), итог, `valid_until`, `subtotal/vat` | «Запросить код» → «Принять {code}» / «Отклонить {reason}» | `promised_date: null` (Q-FIX55-1); PDF — через документы |
| Договоры / Счета / Акты `/billing` | списки; подписи сторон; «к оплате» по валютам | «Подписать», «Принять акт (скан)», «Вернуть акт {reason}» | **нет страницы счёта** (ссылки бота ведут в «не найдено»); нет «оплатить»; нет ЭЦП |
| Поставки `/deliveries` | строки по сделкам, статус, ожидаемая дата, трек | «Принять» (только `delivered`), «Есть замечания» | статусы со склада — M4; ETA нечем считать |
| Документы | `GET /documents` (только выпущенные), `GET /documents/{id}/file` 202+Retry-After | скачать | — |
| Компания и команда `/company` | `GET/PUT /company`, `GET /team` | `POST /team/invite` (только e-mail) | права коллег и основной контакт меняет менеджер в ERP (`docs/DECISIONS.md:66`) |
| Каталог `/catalog` | опубликованный слой с ценой и наличием | «Запросить» → новый запрос | — |
| Сделка `/deals/<id>` | собирается из списков по `deal.id` (своего `GET /deals/{id}` нет) | «Написать менеджеру» | — |
| Уведомления | **нет** (решение: бот CRM и письма ERP; `docs/systems/cabinet/CONVENTIONS.md:110`) | — | клиент без Telegram узнаёт о КП/счёте только письмом ERP |

---

## D. Бот as-is

- **Лид (prospect):** `/start` → язык ×3 → согласие (версия `settings.texts.consent_version`) → диалог по KB (LangGraph агент +
  квалификатор), цены только из источника (ADR-0016), «менеджер» — по словарю без модели, номер телефона один раз; вложения в S3
  «передам коллеге» (`docs/systems/crm/SPEC.md:526-548`). Эскалация → пост в канал команды с «Забрать» (`:497-522`).
- **После передачи (client):** меню `/docs` (до 10 документов клиента — **из CRM `documents`**, не из ERP), `/request` (сервисный
  запрос → эскалация `service_request`), `/status` (заглушка), `/human`. Сообщение `client_access_granted` один раз (`:530-538`).
- **События ERP → клиент в боте** (приёмник `POST /api/v1/integrations/erp/events`, тексты `settings.texts` ×3): `quote.sent`
  («КП готово» + кнопки «Открыть КП», «Кабинет»), `invoice.issued/paid/overdue`, `delivery.status_changed/eta_changed`,
  `act.issued` («акт ждёт подтверждения»); остальные — лента лида и алерты сотрудникам (`docs/architecture/CONTRACTS.md:61-74`,
  `docs/DECISIONS.md:116`). Индекс документов клиента в CRM — без файла (`document.created`).
- **Mini App:** кнопка меню/Mini App в BotFather → `cabinet.*` — **владелец ещё не настроил** (`docs/OWNER-CHECKLIST.md`, «До M2»).
- **Не реализовано:** разбор `/start deal_<id>|quote_<id>|invite_<token>|web`; `dialog_customer.md` и инструменты `erp-mcp`
  (`list_client_deals`, `get_deal_status`, `get_delivery_status`, `list_client_documents`, `get_document_link`, `search_catalog`,
  `create_request` — `docs/architecture/CONTRACTS.md:126-134`); код акцепта в Telegram через событие (FIX-60); веб-виджет (SPEC §15).

---

## E. Настройки и внешние сервисы as-is

| Сервис | Где настраивается сейчас | Дубль / требует перезапуска |
|---|---|---|
| Telegram Bot API (токен, канал команды, профиль бота) | CRM «Подключения» (ADR-0018), БД CRM; `.env` `TELEGRAM_BOT_TOKEN` — резерв | ERP проверяет `initData` **тем же токеном** → `TELEGRAM_BOT_TOKEN` в `.env` ERP (`docs/architecture/CONTRACTS.md:80`; сверить имя переменной); `PORTAL_ACCEPT_CODE_TELEGRAM` в ERP; `TELEGRAM_BOT_USERNAME` — build-arg Cabinet (`docs/DECISIONS.md:57`) → **три места**, смена токена = пересборка/перезапуск ERP и Cabinet |
| LiteLLM (ключи вендоров, модели по алиасам, бюджеты) | CRM «Модели ИИ» (ADR-0020) → БД прокси; `infra/ai/litellm.models.yaml` дефолты | ERP: `LITELLM_BASE_URL`, `LITELLM_API_KEY` (виртуальный ключ, `ai_gateway_sync`), `ERP_AI_DAILY_BUDGET_USD` — `.env` (`docs/systems/erp/CONVENTIONS.md:120-123,255`); бюджет ERP дублируется в CRM `settings.budget.erp_daily_usd` (только показ, `docs/DECISIONS.md:51`) |
| Langfuse | ключи — `.env` (`CRM_LANGFUSE_*`, `ERP_LANGFUSE_*`), колбэк ключа в LiteLLM | **на проде не работает** (ClickHouse, `servers.md:76`); «выключатель Langfuse» в центре внешних сервисов есть |
| SMTP (почта) | CRM коннектор «Почта» — письма сотрудникам (ADR-0023); ERP — транзакционные письма клиенту через свой `EMAIL_*` в `.env` (`docs/history/ARCHITECTURE.md:218-234`) | два набора SMTP; M3-CRM-11 (единый) не сделан; владелец SPF/DKIM — не сделано (`OWNER-CHECKLIST` «До M3») |
| S3 / RustFS | `.env` (бакеты CRM `kb-sources`, `client-documents`, `tg-attachments`; ERP `erp`, `docs/DECISIONS.md:39`) | перезапуск; статус в центре внешних сервисов |
| docling | профиль compose `kb-ingest`; на проде не используется (`docs/DECISIONS.md:161`) | — |
| Курсы ЦБ РУз | ERP Beat `master_data.tasks.refresh_exchange_rates`; лимит возраста — `CompanySettings.fx_rate_max_age_days` в Settings Hub (`docs/systems/erp/CONVENTIONS.md:110`) | статуса в CRM нет (M3-ERP-06) |
| ТН ВЭД / таможенный тариф | справочник ERP (`catalog`), ИИ-подбор | статуса нет |
| Sentry | `SENTRY_DSN` ERP `.env` (M5-INF-01) | в центре внешних сервисов — через M3-ERP-06 (нет) |
| Бэкапы | VPS 2 `pg_dump` → RustFS `backups`; статус читает CRM (M5-CRM-01, `docs/DECISIONS.md:158`); внешнее хранилище — не выбрано | — |
| TLS | Caddy, Let's Encrypt `admin@railtech.uz` (`docs/DECISIONS.md:159`) | срок сертификатов в центре — заявлен M3-CRM-12 |
| Шов CRM↔ERP (`SERVICE_TOKEN_*`, `WEBHOOK_SECRET`, `PLATFORM_SSO_SECRET`, `ERP_MCP_CONTEXT_KEY`, `ERP_BASE_URL`) | CRM: «Подключения → ERP» (адрес, токен, секрет, предыдущий секрет — в БД, пароль админа); ERP: только `.env` (`docs/systems/erp/CONVENTIONS.md:255`) | **ручное копирование** в два места; M3-ERP-05/M3-CRM-10 не сделаны; `PLATFORM_SSO_ENABLED` — `.env` |
| Своя компания ERP | `OWN_COMPANY_ID` `.env` или единственная компания-продавец (`docs/systems/erp/CONVENTIONS.md:220`) | на проде обязательна при >1 — неочевидный тупик первого запуска |
| Бренд (`PLATFORM_NAME`, `SUPPORT_EMAIL`, логотип, домен) | CRM настройки; в ERP read-only с ссылкой (FIX-42) | ERP получает их **из `.env`**, а не из CRM (M3-CRM-11 нет) → фактически два источника |
| Реквизиты, нумерация, шаблоны документов, формулировки, роли, политика каталога, курс, НДС | ERP Settings Hub (`settings.edit`, `settings.charge_templates`, `team.manage`) | — |
| Тексты бота, правила квалификации/эскалации, `service_alerts`, `web_form`, `budget` | CRM «Настройки» (`settings.*`) | — |
| Мастер первого запуска | CRM `/setup` (код из логов контейнера, `deploy.md:203`) | ERP: `core_seed`/`ensure_default_company_roles`/`OWN_COMPANY_ID` — вручную; единого мастера ансамбля нет |

---

## F. Документы as-is

| Документ | Как рождается | Шаблон / PDF | Нумерация | Подпись | Клиенту |
|---|---|---|---|---|---|
| КП | конструктор ERP, версии, курс-снимок, согласование | шаблоны компании, WeasyPrint off-thread (`crm.render_document_pdf`), 202+Retry-After; плашка «ЧЕРНОВИК» до отправки | `numbering` (из B2B; `docs/systems/erp/CONVENTIONS.md:66`) | нет; акцепт кодом | публичная ссылка (`public_quote_url`) + Cabinet + бот |
| Договор | из принятого КП; `wording`, `document_blocks` | PDF; `contract.notes` печатается клиенту (FIX-4xb) | да | клик обеих сторон; скан офлайн; **ЭЦП нет** | Cabinet, `GET /documents` |
| Счёт | из КП/договора; ручная оплата | PDF | да | нет | Cabinet список (без страницы), бот ссылка |
| Акт | из счёта (`fulfillment.act`) | PDF; скан `SCAN-<номер акта>` | да | двусторонний клик | Cabinet |
| Накладная | из отгрузки `Fulfillment` | PDF; дефекты D-6 (0 Б, смена номера) закрыты FIX-55 | номер в GET списка для старых (хвост) | нет | Cabinet |
| ЭСФ / E-IMZO / платёжка | **нет** (отложено, `docs/DECISIONS.md:34`) | — | — | — | — |

Отправка клиенту: письмо ERP (`EmailLog`, шаблоны `portal_invitation`, `portal_magic_link`, код акцепта …) и событие → бот CRM;
файл через подписанную ссылку 10 мин (`docs/architecture/CONTRACTS.md:40`). Бот сам файл из ERP пока не отдаёт (`/docs` читает CRM `documents`).

---

## G. Универсальность (товары vs услуги) по коду

- Одна карточка `Product` с `fulfillment_policy` у услуг (`fixed` / `milestones` / `time`), у товара пусто (`docs/systems/erp/CONVENTIONS.md:153-155`,
  `docs/DECISIONS.md:97`); политика не отдаётся в портал.
- Строки КП: позиции, разделы, заметки, этапы (Cabinet показывает «этапы», `docs/systems/cabinet/CONVENTIONS.md:60`) — тип строки сверить с кодом.
- Исполнение: `Fulfillment`/`DeliveryLine` — только «поставка»; «оказание по этапам», «отчёт об этапе», субподряд (BUSINESS §9) — нет.
- Акт один (`Act`), различия «приёма-передачи» / «выполненных работ» — только словами шаблона (сверить).
- Наличие — из предложений поставщиков уровня 1 (`in_stock/expected/on_order`), остаток — ручное число (`docs/product/BUSINESS.md:266`).

---

## H. Разрывы и противоречия (документы ↔ код), пронумерованно

1. BUSINESS §4 шаг 3→4 «клиенту уходит приглашение в кабинет (кнопка в боте и ссылка)» ↔ ERP шлёт только письмо; Telegram-канал
   приглашения отвергается (`docs/systems/erp/CONVENTIONS.md:103,105`; `docs/QUESTIONS.md:213`). Бот пишет лишь `client_access_granted` без ссылки на кабинет (сверить).
2. ARCHITECTURE §2 «ERP в Telegram не пишет» ↔ `PORTAL_ACCEPT_CODE_TELEGRAM` прямой Bot API из ERP (`docs/history/runbooks/wave6-agents.md:40`).
3. BUSINESS §4 шаг 10 / ORCHESTRATOR M3 гейт «бот отвечает “где мой счёт”» ↔ M3-CRM-07 не сделан; `/status` — заглушка (`docs/systems/crm/SPEC.md:451`).
4. ARCHITECTURE §9 «admin CRM = суперпользователь ERP; роли бэк-офиса по платформам» ↔ роли ERP из CRM не выдаются (D-10, `docs/QUESTIONS.md:515`).
5. ORCHESTRATOR §3.13 «одна консоль, без `.env` и перезапуска» ↔ токены шва, SMTP ERP, LiteLLM-ключ ERP, Sentry, `OWN_COMPANY_ID`,
   `TELEGRAM_BOT_USERNAME` — `.env`/build-arg (`docs/systems/erp/CONVENTIONS.md:255`, `docs/DECISIONS.md:57`).
6. ARCHITECTURE §18 «один набор SMTP на ансамбль» ↔ два SMTP (CRM коннектор + ERP `.env`); M3-CRM-11 не сделан.
7. BUSINESS §9 шаг 9 «акт → сделка закрыта» ↔ `CLOSED_WON` при подписи договора (`docs/systems/erp/CONVENTIONS.md:102`, `docs/QUESTIONS.md:310`).
8. CONTRACTS §3 `act.returned` ↔ не выпускается (`docs/QUESTIONS.md:505`); `invoice.overdue` — `OVERDUE` не проставляется (`docs/systems/erp/CONVENTIONS.md:292`) — чем выпускается событие, сверить.
9. CONTRACTS §3 `delivery.eta_changed` ↔ ETA нечем считать до M4; ADR-0008 ожидает политику ERP в M4-ERP-03.
10. CONTRACTS §4 `POST /team/invite channels: telegram` ↔ 422 `INVALID_CHANNEL`.
11. ARCHITECTURE §5 «пароль необязательный» в Cabinet ↔ в Cabinet нет входа по паролю (`docs/systems/cabinet/CONVENTIONS.md:36` упоминает, экрана нет).
12. CONTRACTS §3 ссылка `invoice.*.link` ↔ страницы счёта в Cabinet нет (`docs/DECISIONS.md:154`).
13. ARCHITECTURE §7 «центр внешних сервисов — сервисы ERP» ↔ M3-ERP-06 нет; Langfuse на проде невозможен (`servers.md:76`).
14. BUSINESS §5.3 «переключатель CRM↔ERP без повторного входа» ↔ за флагом `PLATFORM_SSO_ENABLED`, только при `platform_access` и
    сопоставлении; на проде включать «только вместе с…» (`docs/DECISIONS.md:133`).
15. BUSINESS §11 роль «Каталог и закупки» владеет заказами поставщикам и приёмками ↔ в коде только `supply.manage` = офферы (M4 нет).
16. ARCHITECTURE §11 «счёт по политике предоплата/по факту/по этапам, напоминания» ↔ в документах ERP политики нет (сверить `finance`).
17. BUSINESS §6 «кто правит контакты: бэк-офис через ERP → синхронизация» ↔ обратной синхронизации контактов ERP → CRM нет (только `PUT /contacts/{crm_contact_id}` CRM → ERP, `docs/architecture/CONTRACTS.md:35`).
18. ADR-0022: «воронка CRM заканчивается на “Клиент”, деньги — только в зеркале» ↔ BUSINESS §5.4 «сквозная цифра от сообщения до оплаты» — не считается нигде.
19. SPEC CRM §7.3 `/docs` отдаёт документы CRM ↔ ARCHITECTURE §6 «хранение документов клиента уходит; бот отдаёт файл из ERP» — не реализовано.
20. ORCHESTRATOR M3-CRM-04 имя таблицы `integration_events` ↔ код `erp_incoming_events` (`docs/DECISIONS.md:116`).
21. BUSINESS §7 «одна модель, разные слова: поставка/оказание, позиция/этап» ↔ исполнение услуг по этапам в коде отсутствует.
22. Лид `web`: BUSINESS ждёт «ответ сразу» ↔ лид без Telegram ответов не получает, ждёт менеджера в «Без ответственного».
23. Первый запуск (`deploy.md:203-207`): код мастера читается из логов контейнера по SSH — противоречит §3.13 «что система может сделать сама — делает сама».
24. Задание упоминает FIX-65…71 — таких задач нет; хвосты после FIX-64 — волна 6 (`docs/history/runbooks/wave6-agents.md`).

---

## Что требует сверки с кодом (не успело)

Точные пути/строки для: casbin-политики CRM, `domain/backoffice.py`/`services/clients.py` (handoff), `erp_event_handlers.py`
(какие события дают Telegram), стадий FSM ERP (словарь `DealStage`) и `stages.py`, статусов `Quote/Contract/Invoice/Act`,
типов строк КП, шаблонов писем `notifications`, `portal/urls.py`, `integration/signals.py` (реально выпускаемые события),
`routes.tsx` Cabinet, `.env.example` (полный перечень переменных), `infra/compose/base.yml` (сервисы), `litellm.config.yaml`.
