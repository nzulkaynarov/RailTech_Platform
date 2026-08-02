# Аудит сквозного пути «Продавец → wedge-петля» + приоритизированное ТЗ

**Дата:** 2026-07-08 · **Ветка:** main @ `670d3f7` · **Аудитор:** Senior PM + System Architect (прогон по коду + живой прогон в браузере)
**Роль:** Продавец (seller) — `diana.rakhimova@railtech.uz`, OOO RailTech (KYC L2, активная подписка, SALES_MANAGER)
**Сквозной путь:** routed заявка → **claim** → сборка КП → внутреннее согласование → отправка клиенту → контракт (подпись)

**Метод.** `[проверено]` — открыто/выполнено вживую в браузере под ролью Diana на `localhost:5173`. `[по коду]` — выведено из чтения исходников. Каждая находка снабжена ссылкой `файл:строка`.

**Out of scope** (вынесено одной строкой): покупательский путь (создание/submit заявки, приём КП), плоскость оператора платформы (KYC/подписки/модерация), каталог/PIM-обогащение, инвойсы/акты/платежи после подписания, массовый импорт каталога.

**Итог одной строкой.** Wedge-петля продавца проходится от начала до конца `[проверено]` (claim → сборка → подпись контракта выполнены вживую). Гигиена дизайн-токенов и i18n — образцовая (0 нарушений Rule 4/5 в целевых файлах). Реальные дефекты — во **friction навигации** (claim спрятан в Канбан, очередь согласования ведёт не туда), **немых состояниях** (Канбан без loading/error, проглоченные ошибки грида), **производительности бэка** (N+1 на списках КП/сделок) и **контракт-нарушении API** (человеческие строки вместо кодов в `{"detail":…}`).

---

## ЧАСТЬ 1 — ПРОДУКТОВЫЙ АУДИТ (по шагам)

### Шаг 0 — Вход в систему / контекст продавца

✅ Единая форма логина роутит продавца в `AppShell`; контекст выводится из компании (ADR-0005), ручной переключатель убран.

🟠 **P1 · Продавец приземляется на пустой buyer-онбординг.** `[проверено]` После входа Diana (у которой есть входящая заявка, согласованный КП и контракт на подписи) видит дашборд «Добро пожаловать, Diana! Начните работу за 3 простых шага» с покупательскими карточками «Изучите каталог / Сформируйте запрос / Создайте первую заявку». Продавцовский `SellerDashboard` (очередь согласований `QuoteApprovalQueue`, `TimeToFirstQuoteCard`, `SellerAttentionStrip`) не показывается, потому что `activeStatus` для dual buy+sell компании по умолчанию = `BUYER`. `[по коду]` `store/userStore.ts` `loadFromAuth()` — `activeStatus = firstEntry || 'BUYER'`; `pages/Dashboard.tsx` рендерит `BuyerDashboard`, пока контекст не станет `SELLER` (переключается только при заходе в seller-страницу вроде `#crm-deals`). Продавец с активной работой не видит свою очередь на главном экране — теряется первый шаг воронки.

### Шаг 1 — Воронка «Сделки» (pipeline)

✅ `[проверено]` Заход в «Сделки» переключил контекст на SELLER; список плотный, колонки Сделка/Клиент/Этап/Сумма/Менеджер/Дата с сортировкой (стрелки ↕). KPI-плитки (Все сделки / В работе / КП отправлено / Закрыто-выиграно). Есть поиск и фильтр «Все этапы».

🟡 **P2 · Тумблер «Список / Канбан» — самодельные `<button>`.** `[проверено]`+`[по коду]` `pages/DealsPage.tsx:133-148` — активное состояние красится вручную (`view === 'list' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'`) вместо shadcn `ToggleGroup`/`Tabs`. Токены семантические (не Rule-4), но «изобретение велосипеда».

🟡 **P2 · Избыточная колонка «глаз».** `[проверено]` `pages/DealsPage.tsx:99-107` — иконка `Eye` вызывает `openDeal`, идентична клику по всей строке (`:192`). Лишняя колонка ест ширину таблицы.

🟡 **P2 · KPI «КП отправлено» — точечный счёт, вводит в заблуждение.** `[проверено]` Сделка на этапе «Договор подписан» → плитка «КП отправлено 0», хотя КП фактически было отправлено. Счётчик считает текущий этап, а не накопительно; для продавца «сколько КП я отправил» читается как накопительная метрика.

### Шаг 2 — Claim (взять сделку в работу) 🔑 ключевой шаг wedge

✅ `[проверено]` Claim работает: в Канбан-карточке кнопка «Взять в работу» → тост «Заявка взята в работу», карточка показывает владельца «Diana Rakhimova». Ошибки claim корректно через `translateApiError` (`DealsKanban.tsx:43`). Бэк-гейты верные (`services/assignment.py`: `select_for_update`, `ADMIN_VIEWER_CANNOT_ACT`, seller-routing, `DEAL_ALREADY_CLAIMED`).

🔴 **P0 · Claim недоступен в списке — только в Канбане.** `[проверено]` Дефолтный вид пайплайна — `'list'` (`pages/DealsPage.tsx:37`), а в списке **нет ни кнопки claim, ни колонки владельца/статуса назначения**. `useClaimDeal` используется исключительно в `DealsKanban.tsx:37`. Для документированного шага «routed заявка → **claim**» список — тупик: продавец обязан сначала вручную переключиться в Канбан. Это разрыв в основной монетизируемой петле в дефолтном представлении.

🟠 **P1 · Канбан не имеет loading/error-состояния.** `[по коду]` `pages/DealsPage.tsx:159-164` рендерит `<DealsKanban deals={deals ?? []} …>` безусловно, минуя гейтинг, который есть у списка (`:183` loading, `:184` error+retry, `:185` empty). `components/CRM/DealsKanban.tsx` рисует прямо из пропа без `isLoading`/`isError`. Итог: при загрузке — пустые колонки, при ошибке фетча — **пустые колонки без сообщения и без retry**, а `t('dealsKanban.empty')` («нет сделок») маскирует упавшую загрузку. Именно там, где живёт единственная кнопка claim.

### Шаг 3 — Открытие сделки / детали (`RequestDetailPage`)

✅ `[проверено]` Детали заявки богатые: шапка со статусом, КП v1 с итогами (Сумма без НДС / НДС 12% / Итого с НДС), «Скачать КП (PDF)», превосходная «История» (полный аудит-трейл: claim, приём КП, создание контракта, все смены стадий), правый рельс — чат с WS «Подключено».

🟠 **P1 · Длинная цепочка кликов до билдера КП.** `[по коду]` `pages/RequestDetailPage.tsx:264-297` — от пайплайна до первой цены: строка → детали, затем «Начать подбор» (`:265`), «Начать расчёт» (`:274`), «Собрать КП» открывает `GenerateQuoteDialog` (`:288`), submit, `onGenerated → openQuoteBuilder` навигация на `deal-quote/<id>` (`:101`). ~5 кликов + 2 полностраничных перехода + 3 round-trip смены стадий (каждый с рефетчем `['deals']`) до того, как можно назначить цену.

🟡 **P2 · Дубль поверхности «Отправить КП» без подтверждения.** `[по коду]` `pages/RequestDetailPage.tsx:307-316` шлёт `sendQuote.mutateAsync(quote.id)` напрямую **без confirm-диалога**, тогда как `pages/DealQuotePage.tsx:196` тот же необратимый шаг гейтит через `ConfirmActionDialog`. Несогласованная защита клиент-видимого необратимого действия на двух экранах.

🟡 **P2 · Самодельный success-вариант кнопки.** `[проверено]`+`[по коду]` `pages/RequestDetailPage.tsx:321-322` — `variant="default"` + `className="bg-success text-success-foreground hover:bg-success/90"` вместо `success`-варианта у Button. Токены семантические (не Rule-4), но паттерн повторяется ad-hoc (`:343`).

🟡 **P2 · Прайсовая таблица КП — raw `<Table>`, а не `ResponsiveDataTable`.** `[проверено]`+`[по коду]` `pages/RequestDetailPage.tsx:459-518` — ручной `overflow-x-auto`, `min-w-[32rem]`, ручной подсчёт `colCount` для seller/buyer-раздела колонок. Работает, но расходится со стандартом `ResponsiveDataTable`; без сортировки/плотности.

🟡 **P2 · PDF-экспорт: слабый прогресс 202-поллинга.** `[по коду]` `pages/RequestDetailPage.tsx:123-132` + `api/crmApi.ts:668` — `exportDealPDF` проходит окно 202 GENERATING (секунды), но пользователь видит только спиннер на кнопке (`:445`), без «генерируется…»/тоста. Медленный рендер выглядит как зависшая кнопка.

### Шаг 4 — Сборка КП (`QuoteBuilderGrid`) + статьи расхода + экономика

✅ `[проверено]` Грид плотный и функциональный: колонки Наименование / Кол-во / Базовая цена FCA / Маржа / Сумма, «AI-подбор каталога», «+ Добавить». Правый рельс «ЭКОНОМИКА И ИТОГИ» с предупреждением «Маржа ниже порога компании (15%) — потребуется согласование», себестоимость/валовая прибыль/маржа/операционная прибыль (cost-гейт `canViewCost` корректно открыт продавцу), блок «Статьи расхода / скидки на КП» снизу. Удаление — через `AlertDialog`.

🟠 **P1 · Длинные AI-джобы показывают только спиннер (до 150 c, без отмены).** `[по коду]` `components/Admin/QuoteBuilderGrid.tsx:80-95,275-298` — `handleGenerateDraft`/`handlePricingAssist` крутят `runAiJob` с бюджетом поллинга **150 c** (`lib/aiJob.ts:20` — «2 последовательных 60-c вызова Claude»), а единственный фидбэк — `draftBusy`/`pricingBusy` → спиннер на кнопке (`:249`, `:571`). Нет прогресса, нет «это может занять до минуты», нет `AbortSignal`. При таймауте (`aiJob.ts:59` `AI_JOB_TIMEOUT`) серверная Celery-задача продолжает выполняться — пользователь получает ошибку, хотя черновик может материализоваться через миг, без реаттача. Высокий риск, что пользователь решит «зависло», задваивает клик или уходит.

🟡 **P2 · Проглоченные ошибки на денежно-критичных мутациях.** `[по коду]` `components/Admin/QuoteBuilderGrid.tsx:177,195,214` (`handleSave`/`handleAddItem`/`confirmDeleteItem`) и `components/CRM/QuoteChargesSection.tsx:88-90,121-135` — `catch` кидает общий `toast.error(t('errors.operationFailed'))` вместо `translateApiError(e)`. Реальные коды бэка (валидация, `QUOTE_FROZEN`, entitlement) схлопываются в одно непрозрачное сообщение. Контраст — корректный `translateApiError` в `handleGenerateDraft:91`. Возведено в P0-класс на бэке (см. ниже: ещё и коды не доходят).

🟡 **P2 · Нет error-состояния грида; ошибка фетча маскируется под «нет КП».** `[по коду]` `QuoteBuilderGrid.tsx:219-231` гейтит только `itemsLoading || dealLoading`; при ошибке `useQuoteItems`/`useDeal` исполнение проваливается в `if (!activeQuote)` (`:237`) → пустое состояние «создайте КП», пряча сбой. Без retry.

🟡 **P2 · Инпуты цены/маржи визуально редактируемы на замороженном КП.** `[проверено]` На КП уже APPROVED/подписанной сделке грид показывает активные поля базовой цены и маржи. Бэк отклонит сохранение (`QUOTE_FROZEN`, `services/charges.py`), но UI не блокирует поля визуально — пользователь может внести правки и получить ошибку только на «Сохранить».

🟡 **P2 · Экономический рельс — raw `<aside>` с ручным collapse+localStorage.** `[проверено]`+`[по коду]` `QuoteBuilderGrid.tsx:842-855` — ниже `xl` корректно `Sheet`, но ≥xl самодельная сворачиваемая панель (`railOpen ? 'w-80' : 'w-14'`) вместо `Collapsible`/`Resizable`. Защитимо (точного shadcn-эквивалента нет), но единственное место кастомных лейаут-примитивов.

🟡 **P2 · Хрупкий dirty-tracking через `JSON.stringify`.** `[по коду]` `QuoteBuilderGrid.tsx:133-135` сравнивает `JSON.stringify(localItems) !== JSON.stringify(quoteItems)`; нормализация чисел (`'' → "0"`, `:140`) может ложно взводить Alert «несохранённые изменения» (`:548`).

### Шаг 5 — Внутреннее согласование КП (approval chain / queue)

✅ `[по коду]` Цепочка согласования — корректный shadcn (`AlertDialog` для причины отклонения, `Badge`, семантические статус-иконки `text-success/destructive/warning`), все строки в `t()`, инвалидация централизована (`useCRM.ts:437-442` включая `['my-approval-queue']`).

🟠 **P1 · Очередь согласования ведёт не на тот экран.** `[по коду]` `components/CRM/QuoteApprovalQueue.tsx:44-47` — каждая строка `<button onClick={() => onNavigate('crm-deals')}>` роутит в **список сделок**, а не к конкретному КП (хотя `quote.id`/`quote.deal` известны в `:45/:55`). Ревьюер, которому показали шаг для действия, должен вручную искать сделку в списке. Разрыв непрерывности задачи в approval-workflow.

🟡 **P2 · Низкая плотность строк очереди.** `[по коду]` `QuoteApprovalQueue.tsx:50-57` — строки показывают только `queueDeal {id}` и `queueVersion {version}`, без названия/клиента/суммы. Ревьюер не может приоритизировать, не открыв каждый. `STATUS_VARIANT` (`:14-19`) не покрывает часть статусов → fallback `'neutral'`. Нет error-состояния (упавший `useMyApprovalQueue` молча пуст, `:31`).

🟡 **P2 · Мутация массива при рендере.** `[по коду]` `components/CRM/QuoteApprovalChain.tsx:142` — `group.items.sort((a,b)=>a.order-b.order)` сортирует **на месте** массив, производный от кэша React-Query (иммутабельность). Нужно `[...group.items].sort(...)`.

### Шаг 6 — Отправка КП клиенту

✅ `[по коду]` Бэк-гейты корректны: `crm/views/quotes.py:310-348` `send-to-client` → `can_send_quote_to_client` (`ROLE_NOT_PERMITTED`), `assert_seller_can_operate` (`SELLER_KYC_REQUIRED`/`QUOTE_SEND_NOT_ENTITLED`), сервис пере-проверяет KYC + entitlement `quote.send` (`services/quotes.py:706-713`). PDF+email off-thread: `transaction.on_commit(lambda: send_quote_email.delay(...))` (`services/quotes.py:767`) — WeasyPrint не в request-потоке. Публичная ссылка КП (`PublicQuoteView`) отдаёт 202 + `render_document_pdf.delay`.

🟡 **P2 · Маппинг ошибок send-to-client маскирует неизвестные коды.** `[по коду]` `crm/views/quotes.py:333-347` — неизвестный `ValueError` от сервиса схлопывается в `"INVALID_STATUS"`. Если сервис начнёт кидать новый код вне whitelisted-кортежа, реальный код молча потеряется.

*(Живой повтор отправки невозможен — КП сделки уже SENT/APPROVED; шаг покрыт `[по коду]`.)*

### Шаг 7 — Контракт (генерация + подпись) 🔑 финал wedge

✅ `[проверено]` Экран «Контракты»: KPI Всего/Ожидают подписи/Подписаны, честный баннер «Ручной режим… E-IMZO будет подключена до production-релиза», таблица с сортировкой. Открытие контракта — корректный shadcn `Sheet`: Сделка/Сумма, «Подписать (клиент)», «Подписать (продавец)», «Экспорт», «Загрузить скан», блок «Проверка документа (ИИ)» с оговоркой «числа ИИ для денег не используются — сверка Decimal в коде», «Отменить контракт». **Подпись продавца выполнена вживую** → тост «Подпись менеджера поставлена».

🟠 **P1 · Терминология этапа расходится с состоянием контракта.** `[проверено]` Этап сделки называется **«Договор подписан»** (`CONTRACT_SIGNED`), в то время как сам контракт CT-2026-00001 — статус «Ожидает клиента», подписей 0/2. Пользователь видит «Договор подписан», но договор не подписан ни одной стороной. `[по коду]` FSM: стадия `CONTRACT_SIGNED` наступает при APPROVE КП покупателем (авто-материализация контракта, `services/quotes.py approve_quote`), а фактические подписи и `CLOSED_WON` требуют двойной подписи. Название стадии вводит в заблуждение.

🟡 **P2 · После подписи панель не обновляется (риск повторной подписи).** `[проверено]` После «Подписать (продавец)» тост пришёл, но в открытом `Sheet` поле «Подписать (продавец)» осталось «—», кнопка «Подписать (продавец)» осталась активной — нет оптимистичного обновления/рефетча контракта в панели. Коррелирует с гранулярностью инвалидации (см. ниже).

🟡 **P2 · Строка контракта не кликабельна (несогласованность).** `[проверено]` В «Контрактах» клик по номеру/строке ничего не открывает — только иконка «Действия» справа; в «Сделках» кликабельна вся строка. Разные модели взаимодействия для одинаковых списков.

🟡 **P2 · `GenerateContractDialog` без busy-guard на закрытие.** `[по коду]` `components/CRM/GenerateContractDialog.tsx:41` — `onOpenChange` проброшен напрямую, диалог можно закрыть в процессе `generateMut`; `notes` сбрасывается только при успехе (`:33`), после отмены остаётся stale.

### Cross-cutting — FE↔BE согласованность и производительность

🟠 **P1 · N+1 на списках сделок и КП.** `[по коду]`
- `crm/views/deals.py:99-103` — `get_queryset` не prefetch-ит `seller_routings`; сериализатор дергает `_viewer_routing` → `obj.seller_routings.all()` и `routing.assigned_to` **на каждую строку** (3 method-поля × N).
- `crm/views/deals.py:91-93` — `select_related` не включает `product__uom`; `get_product_uom` (`serializers.py:108-109`) → `uom`-запрос на каждый item.
- `crm/views/deals.py:94-98` и `crm/views/quotes.py:160-175` — prefetch-ят `items`, но **не `charges`**; `QuoteSerializer.charges` (`serializers.py:312`) рендерится на списке до `pop` в `to_representation` (`:443-449`) → `charges`-запрос на каждый активный КП. Комментарий `deals.py:76-81` («без items+charges N+1») вводит в заблуждение.
- `services/quotes.py:255-258` (`approval_queue_for`) — только `select_related`, без `prefetch("items","charges")` → N+1 в очереди согласования.

🟠 **P1 · API-ошибки не в форме `{"detail":"CODE"}`.** `[по коду]` `crm/views/deals.py:531` `{"detail":"No active quote for this deal"}`, `:543` `{"detail":"Failed to generate PDF"}`, `crm/views/quotes.py:648` `{"detail":"PDF generation failed"}`, `:288` `{"detail": str(e)}` — человеческие строки вместо кодов. Фронт сравнивает `detail` по значению-коду → эти ветки не мапятся в i18n-сообщение; риск падения гейта `api-contract`/`test_error_shape`.

🟡 **P2 · Пропущена инвалидация `['deals', id]` на части мутаций.** `[по коду]` `hooks/useCRM.ts` — `useCreateQuote` (`:553-563`), `useSendQuoteToClient` (`:400-409`), `useChangeDealStage` (`:115-121`), `useDeleteDeal` (`:132-138`) инвалидируют только `['deals']`, но не точечный `['deals', id]` (используется `useDeal`). Открытые `DealQuotePage`/`RequestDetailPage` зависят от каскада list-ключа; деталь может показывать устаревший `active_quote`. Контраст — `useClaimDeal:78-81`/`useRouteDeal:66-69` инвалидируют оба.

🟡 **P2 · Rule 8: бизнес-логика в ViewSet, а не в service.** `[по коду]` `crm/views/deals.py:137-179` (`perform_create` — cross-tenant проверка контакта, capability-гейты, назначение стадии) и `crm/views/quotes.py:201-234` (`perform_create` — версия `Max`, anchoring seller-компании, `apply_company_quote_defaults`) несут многомодельную оркестрацию в представлении; должно жить за сервисом. Также `quotes.py:950-972` (`QuoteChargeViewSet`) считает `Max("sort_order")` и `recalculate_totals()` в вью.

---

## ЧАСТЬ 2 — ТЗ НА ИСПРАВЛЕНИЕ (приоритизированное)

| # | P | Проблема | Файл(ы) | Что сделать | Оценка |
|---|---|---|---|---|---|
| 1 | 🔴P0 | Claim недоступен в списке (только Канбан) | `pages/DealsPage.tsx`, `components/CRM/DealsKanban.tsx` | Колонка «Менеджер» с inline-кнопкой claim в списке (reuse `useClaimDeal`) | M |
| 2 | 🔴P0 | API-ошибки человеческими строками, не `{"detail":"CODE"}` | `crm/views/deals.py:531,543`; `crm/views/quotes.py:648,288` | Заменить на коды (`NO_ACTIVE_QUOTE`, `PDF_RENDER_FAILED`…), добавить i18n-ключи | S |
| 3 | 🔴P0 | Проглоченные ошибки грида/статей (`errors.operationFailed`) | `QuoteBuilderGrid.tsx:177,195,214`; `QuoteChargesSection.tsx:88,121,130` | Заменить на `translateApiError(e)` | S |
| 4 | 🟠P1 | Дашборд продавца = пустой buyer-онбординг | `store/userStore.ts`, `pages/Dashboard.tsx` | Дефолт контекста по «основной» способности; либо seller-виджеты вне контекста | M |
| 5 | 🟠P1 | Канбан без loading/error-состояния | `pages/DealsPage.tsx:159-164`, `components/CRM/DealsKanban.tsx` | Прокинуть `isLoading`/`isError`+retry, скелет-колонки | S |
| 6 | 🟠P1 | Очередь согласования ведёт в список сделок | `components/CRM/QuoteApprovalQueue.tsx:44-47` | Навигация на `deal-quote/<deal>` (или `request-detail`) по `quote.deal` | S |
| 7 | 🟠P1 | Длинные AI-джобы: спиннер без прогресса/отмены | `lib/aiJob.ts`, `QuoteBuilderGrid.tsx:249,571` | `onProgress`+`AbortSignal` в `runAiJob`; прогресс-копи «до минуты», реаттач по task_id | M |
| 8 | 🟠P1 | N+1 на списках сделок/КП/очереди | `crm/views/deals.py:91-103`, `crm/views/quotes.py:160-175`, `services/quotes.py:255-258` | Добавить `prefetch_related`/`select_related` для `seller_routings`, `charges`, `product__uom` | M |
| 9 | 🟠P1 | Термин этапа «Договор подписан» ≠ контракт не подписан | `crm/i18n` / `ru.json,en.json` (stage label), опц. FSM-нейминг | Переименовать stage-label в «КП принято / договор сформирован»; статус подписи — отдельно | S |
| 10 | 🟠P1 | Длинная цепочка кликов до билдера КП | `pages/RequestDetailPage.tsx:264-297` | Свернуть sourcing→calculating в один «Собрать КП» (сервис делает переходы) | M |
| 11 | 🟡P2 | Пропущена инвалидация `['deals', id]` | `hooks/useCRM.ts:115,132,400,553` | Добавить `['deals', id]` в `invalidateQueries` этих мутаций | S |
| 12 | 🟡P2 | Дубль «Отправить КП» без confirm | `pages/RequestDetailPage.tsx:307-316` | Обернуть в `ConfirmActionDialog`, как на `DealQuotePage` | S |
| 13 | 🟡P2 | Строка контракта не кликабельна | `pages/ContractsPage.tsx` | `onRowClick` открывает Sheet (как строки сделок) | S |
| 14 | 🟡P2 | Инпуты редактируемы на замороженном КП | `QuoteBuilderGrid.tsx` | `readOnly`/disabled при `quote.frozen_at`/статус SENT+ | S |
| 15 | 🟡P2 | Тумблер/success-кнопка/таблицы КП — не shadcn-стандарт | `DealsPage.tsx:133`, `RequestDetailPage.tsx:321,459` | `ToggleGroup`, `success`-variant у Button, `ResponsiveDataTable` | M |
| 16 | 🟡P2 | Rule 8: логика в `perform_create` | `crm/views/deals.py:137`, `crm/views/quotes.py:201,950` | Вынести в `services/deals.py`/`services/quotes.py` | M |
| 17 | 🟡P2 | Мутация массива при рендере в approval-chain | `QuoteApprovalChain.tsx:142` | `[...group.items].sort(...)` | S |
| 18 | 🟡P2 | Плотность/error очереди согласования | `QuoteApprovalQueue.tsx:14,50` | Добавить title/клиент/сумму, error-состояние, дополнить `STATUS_VARIANT` | S |
| 19 | 🟡P2 | Слабый прогресс PDF-экспорта (202) | `RequestDetailPage.tsx:123-132,445` | Тост «Генерируется PDF…» на время окна GENERATING | S |
| 20 | 🟡P2 | Панель контракта не рефрешится после подписи | `pages/ContractsPage.tsx`, `hooks/useBilling.ts` | Инвалидировать `['contracts', id]`; дизейблить кнопку по `signed_by_*` | S |

### Детали по задачам

#### 1. Архитектура (Django / API / сериализаторы)

**Задача 8 (N+1).** Единственная содержательная бэк-правка производительности.
```python
# crm/views/deals.py — DealViewSet.get_queryset
from django.db.models import Prefetch
return (
    Deal.objects.select_related("company", "stage", "assigned_to", "contact")
    .prefetch_related(
        "seller_routings__assigned_to",
        "target_sellers",
        Prefetch("quotes", queryset=Quote.objects
            .select_related("status")
            .prefetch_related(
                Prefetch("items", queryset=QuoteItem.objects.select_related("product__uom", "offer")),
                "charges",
            )),
    )
)
# crm/views/quotes.py — зеркально добавить "charges" и "items__product__uom";
# services/quotes.py:approval_queue_for — добавить .prefetch_related("items","charges")
```
**Задача 2 (коды ошибок).** Коды сравниваются фронтом по значению — заменить строки на UPPER_SNAKE и завести i18n-ключи в `ru.json`+`en.json` (иначе падает `check-i18n`):
```python
# было: return Response({"detail": "No active quote for this deal"}, status=404)
return Response({"detail": "NO_ACTIVE_QUOTE"}, status=status.HTTP_404_NOT_FOUND)
# quotes.py:648 → "PDF_RENDER_FAILED"; :288 → замапить str(e) на whitelist или "PDF_RENDER_FAILED"
```
**Задача 16 (Rule 8).** Перенести оркестрацию `perform_create` в `services/deals.create_request(user, data)` / `services/quotes.create_draft(...)`; вью — тонкая обёртка `authorize → validate → call service → return`. Гейт `api-contract` не затрагивается (форма ответа не меняется).

#### 2. UI/UX-рефакторинг (конкретные shadcn + Tailwind)

**Задача 1 (claim в списке).** Добавить колонку с inline-claim в `DealsPage` list-ветку — плотнее, чем гнать в Канбан:
```tsx
// колонка "Менеджер" в списке DealsPage
{deal.assigned_to
  ? <span className="text-sm text-muted-foreground">{deal.assigned_to_name}</span>
  : <Button size="sm" variant="outline"
      disabled={claim.isPending}
      onClick={(e) => { e.stopPropagation(); claim.mutate(deal.id); }}>
      {t('deals.claim')}
    </Button>}
```
**Задача 5 (Канбан-состояния).** Прокинуть состояния из `DealsPage`, а не `deals ?? []`:
```tsx
{view === 'kanban' && (
  isLoading ? <KanbanSkeleton /> :
  isError   ? <ErrorState onRetry={refetch} /> :
              <DealsKanban deals={deals ?? []} onClaim={…} />
)}
```
**Задача 6 (очередь → нужный экран).** `onNavigate(\`deal-quote/${item.quote.deal}\`)` вместо `'crm-deals'` — восстанавливает непрерывность.
**Задача 7 (AI-прогресс).** `runAiJob(…, { signal, onPoll })`; кнопка показывает `Progress`/счётчик и «обычно 30–60 c, до минуты»; при unmount — `abort()`; хранить `task_id` для реаттача, чтобы `AI_JOB_TIMEOUT` не выбрасывал уже готовый результат.
**Задача 15 (shadcn-стандарт).** Тумблер → `ToggleGroup type="single"`; success-кнопка → добавить `success` в `buttonVariants`; статичный прайс-лист КП → `ResponsiveDataTable` с column-config (сорт/плотность/мобильный fallback «из коробки»). Всё — семантические токены, строки в `t()` → проходит `design-check`+`check-i18n`.
**Задача 13/20 (контракты).** `onRowClick` открывает тот же `Sheet`; после `signContract*` — `queryClient.invalidateQueries(['contracts', id])` и `disabled={!!contract.signed_by_seller}` на кнопке (убирает риск повторной подписи, замеченный вживую).

#### 3. Бизнес-логика (только `services/`)

**Задача 9 (терминология).** Правка чисто в i18n-лейбле стадии (`ru.json`/`en.json`): `CONTRACT_SIGNED` отображать как «КП принято — договор сформирован», а факт подписи показывать из `Contract.status`/`signed_by_*`. FSM-коды не трогаем (Rule 2 — сравнение по `code`). Логика материализации контракта уже в `services/quotes.approve_quote` — менять не нужно.
**Задача 10 (склейка стадий).** Кнопка «Собрать КП» из `RFQ_OPEN` должна одним действием вызвать сервис, который сам проведёт `SOURCING→CALCULATING` (переходы уже в `services/deals.transition_deal_stage`) и создаст черновик — вместо трёх последовательных клиентских мутаций. Правка оркестрации — в `services/`, вью/хук лишь вызывают один эндпоинт.
**Задача 14 (заморозка).** UI-`readOnly` по `quote.frozen_at`; серверный инвариант `QUOTE_FROZEN` уже есть в `services/charges.py`/`quotes.py` — дублировать на бэке не нужно.

---

## SELF-CHECK

- [x] Ни одного упоминания библиотек вне стека (Mantine и пр.) — только shadcn/ui, Tailwind v4, Zustand, React Query, DRF.
- [x] У каждой находки есть `файл:строка` и метка `[проверено]`/`[по коду]`.
- [x] Каждая P0 (№1 claim, №2 коды ошибок, №3 проглоченные ошибки) имеет конкретную задачу в ТЗ.
- [x] ТЗ не нарушает инварианты репо: семантические токены, i18n-ключи в обоих locale, бизнес-логика только в `services/`, форма ошибок `{"detail":"CODE"}`.
- [x] Правки совместимы с CI-гейтами: `design-check` (токены/shadcn), `check-i18n` (ключи ru+en), `api-contract` (форма ответа не меняется).

**Живой охват `[проверено]`:** вход → воронка «Сделки» (список+Канбан) → **claim** → детали заявки → **сборка КП** (грид+экономика+статьи) → «Контракты» → **подпись контракта (продавец)**. Не пройден вживую: повторная отправка КП (сделка уже за стадией отправки) — покрыт `[по коду]`.
