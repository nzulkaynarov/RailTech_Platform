# Стандарты B2B-процесса продаж и сервиса: что считать нормой для ансамбля CRM + ERP + Cabinet

Дата: 2026-10-21. Контекст: малый/средний B2B в Узбекистане, промышленные товары под заказ и нематериальные услуги.
Цель исследования: вывести «общий знаменатель» стадий, объектов, ролей и паттернов интерфейса, которые используют
все зрелые системы (Salesforce, HubSpot, Odoo, ERPNext, Dynamics 365, SAP Business One) и рекомендуют отраслевые
аналитики (APQC, Gartner, Forrester, McKinsey), чтобы RailTech строил «по стандарту, без велосипеда».

Пометки надёжности: **[оф.]** — официальная документация вендора или первоисточник; **[втор.]** — вторичный источник
(партнёрский блог, пересказ); цифры из вторичных источников даны с оговоркой.

---

## 1. Эталонный сквозной процесс: Lead-to-Cash / Quote-to-Cash / Order-to-Cash

### 1.1. Как это называют и где граница

- **Lead-to-Cash (L2C)** — от момента появления лида до поступления денег. Salesforce определяет его как «сквозной
  процесс выручки, соединяющий момент, когда потенциальный клиент попал в воронку, с моментом, когда платёж прошёл»;
  охватывает управление лидами, возможностями (opportunity), квотирование, договор, исполнение заказа, биллинг и
  признание выручки [оф.].
- **Quote-to-Cash (Q2C)** — то же, но начинается с коммерческого предложения (КП/quote). Salesforce прямо разводит:
  L2C стартует раньше, Q2C — со стадии квотирования [оф.].
- **Order-to-Cash (O2C)** — бэк-офисная часть: от подтверждённого заказа до оплаты (ERP-термин; в APQC это
  группы «Manage sales orders» и финансовые процессы категории 9).
- Трёхфазная формула, удобная для SMB (Armanino): **Lead → Qualify**, **Qualify → Order**, **Order → Cash** [втор.].

### 1.2. APQC Process Classification Framework (категории 3, 4, 9)

APQC PCF — отраслевая нейтральная таксономия процессов. Категория **3.0 Market and Sell Products and Services**
стоит в цепочке создания ценности между 2.0 (разработка продуктов) и 4.0 (Deliver). Внутри — группа **«Manage sales
orders»** (3.5.4.x в PCF 7.x/8.0): принять и валидировать заказ (3.5.4.1), определить доступность (3.5.4.3),
обрабатывать запросы по заказу (3.5.4.6); охват — «от получения заказа до доставки / выставления счёта» [оф.,
по странице бенчмарка APQC]. Категория 4.0 закрывает исполнение (снабжение, производство, логистика), категория 9.0 —
финансы (дебиторка, счета, платежи). Полный текст PCF 8.0 для 3.0 опубликован в марте 2026, но под членством.

Вывод из APQC: стандарт разводит **фронт (3.x: маркетинг, лиды, КП, заказ)**, **исполнение (4.x: закупка, склад,
доставка)** и **финансы (9.x: счёт, платёж, дебиторка)** как три владельца. Это ровно граница CRM / ERP-операции /
ERP-финансы.

### 1.3. Стадии и объекты по системам

| Система | Фронт-офис (CRM) | Коммерция | Исполнение | Финансы |
|---|---|---|---|---|
| **Salesforce** | Lead → (конверсия) Account + Contact + Opportunity; стадии Opportunity по умолчанию: Prospecting, Qualification, Needs Analysis, Value Proposition, Id. Decision Makers, Perception Analysis, Proposal/Price Quote, Negotiation/Review, Closed Won / Closed Lost [втор., совпадает у нескольких гидов] | Quote, Contract | Order, Asset | Invoice, Payment (Revenue Cloud / Billing) |
| **HubSpot** | Lifecycle stage контакта/компании: Subscriber → Lead → MQL → SQL → Opportunity → Customer → Evangelist (+ Other); SQL не ставится автоматически, определяет компания; Opportunity = контакт, связанный со сделкой (Deal); Customer = есть закрытая сделка | Deal (pipeline stages), Quote | — (нет исполнения) | Payments/Invoices (ограничено) |
| **Odoo** | Lead (опциональный шаг, включается в настройках) → Opportunity; стадии по умолчанию New → Qualified → Proposition → Won; Lost архивирует с причиной | Quotation → (подпись/оплата онлайн) → Sales Order (блокируется после подтверждения) | Delivery (товар) / Task, Project, Milestone (услуга) | Invoice → Payment |
| **ERPNext** | Lead → Opportunity (ожидаемая сумма, вероятность) | Quotation → Sales Order (обязательство, не выручка) | Delivery Note (списывает склад и COGS); для услуг — Skip Delivery Note | Sales Invoice (дебиторка, доход, налоги) → Payment Entry |
| **Dynamics 365 Sales** | Lead → (Qualify) Opportunity; бизнес-процесс по умолчанию Qualify → Develop → Propose → Close (→ Fulfill) | Quote (формальная оферта с ценами и условиями) → Order («принятый quote») | Order fulfilment | Invoice («заказ, по которому выставлен счёт») |
| **SAP Business One** | (CRM-активности, opportunity) | Sales Quotation → Sales Order | Delivery; A/R Reserve Invoice (счёт до отгрузки); Return | A/R Invoice (единственный обязательный документ) → Incoming Payment |

Примечания:
- ERPNext: модуль CRM внутри ERPNext объявлен устаревающим (удаление в v17), рекомендуется отдельный Frappe CRM —
  ещё одно подтверждение, что фронт-офис и бэк-офис разводят по разным продуктам, связанным API [оф.].
- SAP B1 и ERPNext одинаково говорят: все документы цепочки создаются «из предыдущего» с переносом данных, и только
  счёт обязателен; КП, заказ, отгрузка — опциональны по бизнесу [оф.].
- Dynamics: при конверсии Opportunity → Quote → Order позиции (каталожные и write-in) переносятся; при создании
  Order можно закрыть Opportunity с фиксацией итоговой выручки [оф.].

### 1.4. Общий знаменатель (что используют все)

| Объект | Смысл | Владелец стадии | Есть у всех? |
|---|---|---|---|
| **Lead** | неквалифицированный контакт/запрос | маркетинг / SDR / бот | да (Odoo и HubSpot — опционально) |
| **Opportunity / Deal** | квалифицированная потребность с суммой, вероятностью, стадией | продавец (AE) | да |
| **Account + Contact** | компания и люди (создаются при конверсии лида) | продавец | да |
| **Quote / Quotation / КП** | формальная оферта: позиции, цены, сроки, условия | продавец; акцепт — клиент | да |
| **Sales Order / заказ / договор** | принятая оферта, обязательство; после подтверждения блокируется | order desk / продавец | да |
| **Delivery / Delivery Note / Task+Milestone** | факт исполнения (товар — отгрузка; услуга — выполненный этап) | склад/логистика или исполнитель услуг | да, с ветвлением по типу |
| **Invoice** | требование оплаты; единственный обязательный документ (SAP B1, ERPNext) | финансы | да |
| **Payment** | поступление денег, закрывает дебиторку | финансы | да |

Канонический сквозной путь (нормализованный):
`Lead → Opportunity → Quote → Order → Fulfilment (Delivery | Milestone/Acceptance) → Invoice → Payment`, с ветвями
Lost (причина обязательна) и Return/Credit Note.

Источники раздела 1:
- https://www.salesforce.com/sales/revenue-lifecycle-management/lead-to-cash/
- https://trailhead.salesforce.com/content/learn/modules/quotes-and-orders-with-enterprise-sales-management/get-to-know-sales-processes
- https://www.salesforcetutorial.com/lead-to-cash/
- https://www.armanino.com/articles/lead-to-cash-how-it-can-help-improve-cash-flow/
- https://www.apqc.org/resource-library/resource-listing/30-market-and-sell-products-and-services-definitions-and-key-3
- https://www.apqc.org/what-we-do/benchmarking/open-standards-benchmarking/measures/cycle-time-days-perform-process-manage
- https://ascendix.com/blog/salesforce-opportunity-stages/
- https://www.salesforceben.com/complete-guide-tutorial-to-salesforce-opportunity-stages/
- https://developer.salesforce.com/docs/atlas.en-us.api.meta/api/sforce_api_calls_convertlead.htm
- https://www.blendb2b.com/blog/hubspots-lifecycle-stages-explained
- https://www.mo.agency/blog/hubspot-lifecycle-stages
- https://www.odoo.com/documentation/18.0/applications/sales/crm/acquire_leads/convert.html
- https://www.cybrosys.com/blog/how-to-manage-crm-pipeline-in-odoo-18
- https://docs.frappe.io/erpnext/selling.md
- https://docs.frappe.io/erpnext/CRM.md
- https://docs.frappe.io/erpnext/accounting-entries.md
- https://learn.microsoft.com/ja-jp/training/modules/explore-dynamics-365-sales/8-describe-dynamics-365-sales-business-process-flows
- https://learn.microsoft.com/tr-tr/dynamics365/sales/developer/sample-process-quotes-sales-orders-invoices
- https://learning.sap.com/courses/managing-logistics-in-sap-business-one/running-the-sales-process-in-sap-business-one
- https://learning.sap.com/courses/discovering-sap-business-one-web-client-logistics/navigating-the-process-from-quotation-to-cash

---

## 2. Роли в продажах и сервисе, lead handoff, критерии квалификации

### 2.1. Эталонная специализация (Predictable Revenue, Winning by Design)

Аарон Росс (Predictable Revenue): ключевая идея — **специализация**: отделить поиск (prospecting) от закрытия, чтобы
каждая роль делала одно дело хорошо. Типичный набор: inbound-квалификатор (MRR/SDR), outbound SDR/BDR, closer
(Account Executive), Account Manager / Customer Success. AE не должен тратить время на холодный поиск [втор.].

Winning by Design (Bowtie Model, обновлён 2023, «Bowtie Standard» 2026): воронка «повёрнута» и продолжена вправо —
левая половина = приобретение (prospecting, pipeline, close), правая = onboarding, adoption, expansion; у каждой
половины свои стадии и метрики; модель привязана к GTM-режимам от No Touch до Dedicated Touch [оф., PDF проприетарный].

| Роль | Зона | Владеет | Метрика |
|---|---|---|---|
| SDR / BDR | лид → квалифицированный лид | отклик, квалификация, назначение встречи | кол-во SQL/встреч, скорость ответа |
| Account Executive (AE) | opportunity → closed won | потребность, КП, переговоры, договор | выручка, win rate, цикл сделки |
| Account Manager (AM) | коммерческая сторона после продажи | продления, расширение, переговоры по цене | renewal rate, expansion |
| Customer Success (CSM) | ценность после продажи | внедрение, здоровье аккаунта, достижение результата | adoption, NPS, здоровье |
| Бэк-офис: order desk, закупки, склад/логистика, финансы | order → cash | ввод/валидация заказа, снабжение, отгрузка, счёт, оплата | cycle time, % заказов без ручного вмешательства (APQC) |

AM vs CSM (Gainsight, Planhat): AM «владеет контрактом, продлениями и коммерцией», CSM — «внедрением, здоровьем,
реализацией ценности»; владение продлением должно быть назначено явно, иначе спор [втор., консенсус источников].

### 2.2. Lead handoff: критерии и SLA

- **MQL** — лид, который маркетинг счёл готовым для продаж (HubSpot: «контакт, которого маркетинг квалифицировал
  как готового для команды продаж»). **SQL** — лид, который продажи приняли как стоящий прямой работы. Между ними
  часто вводят **SAL (Sales Accepted Lead)**: продажи обязаны принять или отклонить MQL за фиксированный срок,
  типично 24 ч (inbound) / 48 ч (outbound) [втор.].
- **Фреймворки квалификации**: BANT (Budget, Authority, Need, Timeline), CHAMP (Challenges, Authority, Money,
  Prioritization), MEDDIC (Metrics, Economic buyer, Decision criteria, Decision process, Identify pain, Champion).
  BANT/CHAMP — для SMB и коротких циклов; MEDDIC — для enterprise.
- **Письменный SLA** маркетинг ↔ продажи обязателен: без него «обе команды работают на разных допущениях».
- **Что передаётся при handoff**: контактные данные и компания; источник и действия лида (что смотрел, что
  спрашивал); боль/потребность; бюджет/сроки, если известны; согласованный следующий шаг; тёплое представление
  (SDR вводит AE письмом или коротким звонком и выходит). Обратная связь: продажи возвращают маркетингу причину
  отклонения.
- **Скорость**: отклик в первые 5 минут повышает вероятность контакта в 21 раз против 30 минут (HBR/Lead Response
  study, широко цитируется) [втор.].

### 2.3. Как это сворачивается в SMB

Консенсус VC/практиков (Wing VC, Airtree, SaaStr-ссылки): основатель лично закрывает первых 10–20 клиентов; первый
найм — **full-cycle AE** (сам ищет и закрывает), а не чистый SDR; SDR добавляют вторыми-третьими; менеджер продаж —
при 5–8 продавцах или после $1–2M ARR; разделение на отдельные команды SDR/AE/CS — поздняя стадия [втор.].

Минимальная конфигурация для 2–3 ролей:

| Роль SMB | Что берёт из эталона |
|---|---|
| **Менеджер по продажам (full-cycle)** | SDR + AE: квалификация, КП, договор, первичное сопровождение; в RailTech первичная квалификация частично уходит ИИ-боту |
| **Менеджер по сопровождению / проектный менеджер** | AM + CSM + order desk: исполнение, статусы, акцепт, повторные заказы |
| **Бэк-офис (снабжение + склад + финансы, часто 1–2 человека)** | закупки, отгрузка, счета, оплата |

Критичный момент при сворачивании: **границы владения стадией** всё равно должны быть явными (кто отвечает за
Opportunity, кто — за Order, кто — за Invoice), даже если это один человек в двух ролях.

Источники раздела 2:
- https://pulserevops.com/knowledge/bs0009
- https://resources.rework.com/vi/libraries/leadership-legends/aaron-ross-leadership
- https://winningbydesign.com/press/winning-by-design-releases-updated-bowtie-model-and-benchmarks-to-provide-go-to-market-teams-with-a-standardized-customer-journey-and-data-model/
- https://winningbydesign.com/wp-content/uploads/2026/01/The-Bowtie-Standard.pdf
- https://abmatic.ai/blog/what-is-sales-qualified-lead-sql
- https://thatagency.com/blog/mql-to-sql/
- https://statsig.com/perspectives/sql-leads-criteria-tips
- https://revboss.com/blog/sales-marketing-campaign-handoffs-what-good-looks-like
- https://www.gainsight.com/blog/customer-success-vs-account-management/
- https://www.planhat.com/editorial/customer-success-vs-account-manager
- https://wing.vc/docs/sales/making-the-transition-from-founder-selling-to-having-an-entire-sales-team
- https://www.airtree.vc/open-source-vc/founder-led-sales-building-sales-team
- https://www.hireinsouth.com/post/sales-team-structure-10-essential-roles-and-their-key-responsibilities

---

## 3. Боли B2B-клиентов и тех, кто им помогает: цифры

### 3.1. Покупатели

| Факт | Цифра | Источник, год |
|---|---|---|
| Предпочитают покупку без участия продавца (rep-free) | 61% (опрос 632 покупателей, авг–сен 2024); 75% в опросе 2021 — устаревшая цифра, не сравнима по выборке | Gartner, пресс-релиз 25.06.2025 [оф.] |
| Избегают поставщиков с нерелевантными рассылками | 73% | Gartner 2025 [оф.] |
| Видят расхождение между сайтом поставщика и словами продавца | 69% | Gartner 2025 (пересказ mi-3) [втор.] |
| Где self-service выигрывает | общая информация и обучение; для «подходит ли нам» покупатели хотят продавца | Gartner 2025 [оф.] |
| Назвали последнюю покупку «очень сложной» | 77% | Gartner 2021 (пересказ) [втор.] |
| Время покупателя на встречи с поставщиками | ~17% всего цикла, ~5% на одного поставщика | Gartner (пересказ FedEx) [втор.] |
| Шесть «работ» покупателя | выявление проблемы, поиск решений, формирование требований, выбор поставщика, валидация, консенсус — нелинейно | Gartner [втор.] |
| Покупки, которые «застревают» в процессе | 86% | Forrester, State of Business Buying 2024 (>16 000 респондентов) [оф.] |
| Недовольны выбранным поставщиком | 81% | Forrester 2024 [оф.] |
| «Правило третей»: in-person / удалённо с человеком / цифровой self-service | ≈ по трети каждого; до 2020 — ~50% предпочитали личное | McKinsey B2B Pulse 2024 (~4 000 ЛПР, 13 стран) [оф.] |
| Каналов в пути покупателя | в среднем 10 (5 в 2016) | McKinsey [оф.] |
| Готовы тратить > $500 000 за заказ через self-service / удалённо | 39% (28% двумя годами ранее) | McKinsey 2024 (пересказ DC360) [втор.] |
| Предпочитают личный канал для нового поставщика / первой покупки | 41% / 40% | McKinsey 2024 [оф.] |
| «Запутанные порталы» — существенное трение | ~1/3 покупателей (900 респондентов, вендорский опрос) | Netconomy [втор.] |

Что из этого следует: покупатель хочет **сам** смотреть статус, документы и цены, но хочет **человека** там, где
нужен контекст («подходит ли это нам»). Нужны оба режима и бесшовный переход между ними; смена поставщика —
реакция на негладкий опыт между каналами (McKinsey).

### 3.2. Менеджеры и операторы

| Факт | Цифра | Источник |
|---|---|---|
| Доля времени продавца на собственно продажу | ~28–30% (пересказ State of Sales), «только 40%» (Trailhead), «1/3» (Salesforce Research) — цифры расходятся, но все < 50% | Salesforce [оф./втор.] |
| Непродающая работа (админ, подготовка) | до 70% времени | Salesforce News [оф.] |
| Переключений между приложениями в день | ~1 200; потеря ~4 ч/нед (≈9% рабочего времени) на «возврат в контекст» | HBR «toggling tax» (Fortune 500, 137 пользователей) [втор.] |
| Продавец пользуется ≥10 приложений в день; ~2 дня в неделю — админ | — | Forrester (3 031 продавец), пересказ Apollo [втор.] |
| «Слишком много инструментов снижают продуктивность» | 45% | Qatalog [втор.] |

Типовые боли менеджера, которые подтверждают эти цифры: нет единого контекста по клиенту (история, документы,
статус), ручной перенос данных между CRM/ERP/мессенджером, «где лежит документ», повторный ввод одного и того же,
отсутствие владельца следующего шага.

Источники раздела 3:
- https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-sales-survey-finds-61-percent-of-b2b-buyers-prefer-a-rep-free-buying-experience
- https://www.mi-3.com.au/04-07-2025/gartner-survey-reveals-b2b-buyers-preference-rep-free-experience
- https://www.brighttalk.com/resource/core/398948/jun16dbushee_856200.pdf
- https://fedex.com/en-at/campaign/small-business-hub/guides-and-tools/b2b-customers-insights.html
- https://www.forrester.com/blogs/state-of-business-buying-2024/
- https://www.forrester.com/press-newsroom/forrester-the-state-of-business-buying-2024/
- https://www.forrester.com/report/the-rise-of-self-service-buying/RES180954
- https://www.mckinsey.com/capabilities/growth-marketing-and-sales/our-insights/five-fundamental-truths-how-b2b-winners-keep-growing
- https://www.mckinsey.com/capabilities/growth-marketing-and-sales/our-insights/the-new-b2b-growth-equation
- https://www.digitalcommerce360.com/2024/09/12/more-b2b-buyers-are-willing-to-spend-big-bucks-per-online-order/
- https://netconomy.net/blog/top-5-b2b-sales-frictions/
- https://www.salesforce.com/news/?p=79781
- https://trailhead.salesforce.com/content/learn/modules/introduction-to-agentforce-sales/discover-the-modern-sales-landscape
- https://salesscreen.com/okf/studies/salesforce-state-of-sales-report
- https://www.apollo.io/magazine/the-toggle-tax-what-1200-daily-app-switches-are-costing-sales-teams
- https://clickup.com/blog/toggle-tax/

---

## 4. Личный кабинет клиента B2B

### 4.1. Что умеют эталонные порталы

| Портал | Документы и статусы | Действия клиента | Команда клиента | Сервис |
|---|---|---|---|---|
| **Odoo Portal** [оф.] | только чтение: лиды/возможности, КП/заказы, заказы на закупку, счета, проекты, задачи, таймшиты, тикеты, подписи, подписки; история всей компании, если контакт привязан к компании | Sign & Pay на КП (нарисовать/автоподпись/загрузить файл) → заказ подтверждается и блокируется, создаётся счёт; «Request changes / Reject»; оплата счетов; смена своих данных, пароля, 2FA, способов оплаты | контакт компании видит документы всех её контактов | тикеты, комментарии в проектах |
| **HubSpot Support Portal** [оф.] | тикеты (только тикеты; чаты/письма без тикета не видны) | создать/посмотреть тикет, база знаний для самообслуживания | — | требует Service Hub Pro+ |
| **Zoho Books Client Portal** [оф., старый анонс] | сметы и счета в статусе Sent, история платежей | принять/отклонить смету, оплатить счёт | — | — |
| **Freshdesk Portal** [оф.] | тикеты со статусом | создать и отслеживать тикет, база знаний, форум | — | несколько брендов/порталов, SSO, мультиязык |
| **Salesforce Experience Cloud** [оф. Trailhead + втор.] | кейсы, статьи знаний, история заказов, выписки, данные аккаунта | создать кейс, управлять заказами | — | кейс по телефону виден в портале (единая база) |
| **Shopify B2B** [оф.] | Company → Locations (свои реквизиты, адреса, цены, payment terms) → Contacts с правами («только свои заказы») | заказ, оплата net-terms (Net 7/15/30/45/60/90, due on fulfillment), депозит % | лимиты 10 000 локаций / контактов | — |
| **Adobe Commerce B2B** [оф.] | Company account → подразделения → пользователи; роли и права (Sales, PO, Negotiable Quotes, Credit, профиль) | negotiable quote (торг в обе стороны, история переписки, шаблоны), purchase orders с правилами одобрения и лимитами | иерархия, approver/buyer | — |

### 4.2. Общий знаменатель кабинета

1. **Документы и статусы по всей цепочке** — КП, заказ/договор, отгрузка/этап, счёт, оплата; «где мой документ»
   закрывается именно этим.
2. **Акцепт КП онлайн** (подпись + опционально предоплата) — после него заказ фиксируется; это стандарт Odoo/Zoho.
3. **Оплата и условия оплаты** (net terms, депозит) — Shopify/Odoo.
4. **Тикеты/обращения** со статусом и единой базой с внутренней системой — HubSpot/Freshdesk/Salesforce.
5. **Команда клиента**: компания → контакты с ролями (кто видит всё, кто только свои заказы, кто одобряет) —
   Shopify/Adobe/Odoo.
6. **Самообслуживание профиля**: реквизиты, пароль, 2FA, способы оплаты — Odoo.
7. **Только чтение документов** — изменения проходят через действия (акцепт, запрос изменений, тикет), не через
   правку записей.

### 4.3. Чем кабинет отличается от чата/бота

| | Чат / Telegram-бот | Кабинет (web + Mini App) |
|---|---|---|
| Сильная сторона | скорость, вопрос-ответ, уведомление «сейчас» | постоянный реестр: документы, история, статусы, действия с юридической силой |
| Сценарии | лид, уточнение, «где заказ?», напоминание | акцепт КП, подпись, оплата, тикет, команда, выгрузка документов |
| Хранение | лента, теряется | структура, поиск, фильтры |
| Роль ИИ | квалификация, ответ по базе знаний, навигация в кабинет | подсказки в контексте документа |

Паттерн источников по уведомлениям: in-app (кабинет) — **постоянный журнал**; чат/push — **сигнал «сейчас»**,
исчезает; e-mail — **долговечная резервная копия для важного** (счёт, договор, продление). Рекомендуемая эскалация:
всё — в кабинет, не прочитано за N минут → письмо, срочное → push/чат; таргетинг по ролям внутри аккаунта клиента
(несколько пользователей, разные роли).

| Событие | Чат (Telegram) | Кабинет | E-mail |
|---|---|---|---|
| Новое КП / изменение цены | да (ссылка) | да (документ + акцепт) | да (PDF) |
| Статус заказа/этапа изменился | да (коротко) | да (журнал) | нет |
| Счёт выставлен / срок оплаты | да | да (оплата) | да |
| Отгрузка / акт готов к подписи | да | да (подпись) | да |
| Ответ в тикете | да | да | по настройке |
| Договор, юридически значимое | ссылка | да | да (архив) |

Источники раздела 4:
- https://www.odoo.com/documentation/18.0/applications/general/users/portal.html
- https://documentation-user.readthedocs.io/en/latest/ecommerce/shopper_experience/portal.html
- https://www.cybrosys.com/odoo/odoo-books/v18/sales/sales-orders/
- https://www.cybrosys.com/blog/managing-online-signature-and-payment-with-odoo-17
- https://www.binhex.cloud/en_GB/blog/odoo-1/odoo-portal-16
- https://knowledge.hubspot.com/inbox/set-up-a-support-portal
- https://knowledge.hubspot.com/get-started/support-your-customers
- https://help.zoho.com/portal/en/community/topic/client-portal-is-now-available-in-zoho-books
- https://support.freshdesk.com/support/solutions/articles/50000003752
- https://www.freshworks.com/freshdesk/self-service/customer-portal/
- https://trailhead.salesforce.com/content/learn/modules/community_cloud_basics/communities_setting_goals_for_community
- https://technologyblog.rsmus.com/technologies/salesforce/common-customer-portal-functionality-with-salesforce/
- https://help.shopify.com/en/manual/b2b/companies/creating-companies
- https://help.shopify.com/en/manual/b2b/payment-terms
- https://shopify.dev/apps/b2b
- https://experienceleague.adobe.com/en/docs/commerce-admin/b2b/introduction
- https://developer.adobe.com/commerce/webapi/rest/b2b/roles
- https://www.suprsend.com/post/in-app-notification-center
- https://courier.com/blog/how-multichannel-notifications-reduce-saas-churn-and-boost-engagement
- https://www.courier.com/blog/rethinking-push-and-in-app-notifications-what-b2b-can-learn-from-b2c

---

## 5. Единая консоль администратора, интеграции, первый запуск, пустые состояния

### 5.1. Как показывают внешние сервисы и их здоровье

| Система | Паттерн |
|---|---|
| **HubSpot Connected Apps** [оф.] | Settings → Integrations → Connected Apps. Вкладка «Needs attention»: истёкшие, отключённые, с ошибками — кнопка **Reconnect**. По каждому приложению: статус, дата подключения, кто подключил, **last activity** (когда данные последний раз отправлены/получены). «Connection insights»: активность, расход API, изменения записей. Уведомления (email/in-app) о подключении, отключении, удалении — с повтором ежечасно/ежедневно/еженедельно. |
| **Atlassian Statuspage** [оф.] | Компоненты с пятью статусами: Operational, Under maintenance, Degraded performance (жёлтый), Partial outage (оранжевый), Major outage (красный). Статус страницы вычисляется из статусов компонентов. |
| **Odoo Settings / Apps** | Настройки сгруппированы по приложениям, переключатели включают функции; Apps — каталог модулей с установкой в один клик (общеизвестно, оф. документация Odoo). |
| **Zapier-подобные хабы** | список подключений, история запусков, ошибки с повтором (autoreplay) — паттерн «журнал + повтор». |

Минимальный стандарт карточки интеграции: **название, статус (цвет), последняя успешная активность, кнопка «Проверить
соединение», кнопка «Переподключить», ссылка на журнал ошибок, кто и когда настроил**. Для RailTech это: Telegram Bot
API, LiteLLM/модели, Langfuse, ЭСФ-оператор, платёжный шлюз, SMTP, связь CRM ↔ ERP.

### 5.2. Первый запуск: setup wizard и onboarding-чеклист

| Система | Паттерн |
|---|---|
| **Odoo Accounting/Invoicing onboarding banner** [оф.] | На первом экране — баннер с 4 шагами (Company Data, Documents Layout, Create Invoice, Online Payments для Invoicing; Company Data, Bank/Taxes, Periods, Chart of Accounts для Accounting). Баннер закрывается, каждый шаг ведёт в форму настроек, всё можно изменить позже в Configuration → Settings. |
| **ERPNext Setup Wizard** [втор.] | При первом входе: язык, страна, часовой пояс, валюта, компания, финансовый год, план счетов; создаёт базовые данные, на которые опираются все модули. |
| **Shopify Setup Guide** [оф. dev-docs] | Интерактивный чеклист с прогрессом на главной: шаги раскрываются, отмечаются выполненными, виден общий прогресс; рекомендуется для онбординга приложений. |
| **HubSpot** | «Get started» с чеклистами по хабам; Connected Apps — см. выше. |

Общие свойства: ордер шагов короткий (4–6), каждый шаг — ссылка в реальную настройку, прогресс виден, баннер
можно закрыть и вернуть, ничего не блокирует работу, кроме действительно обязательного (валюта, компания).

### 5.3. Пустые состояния (empty states)

NN/g (Kaplan): пустое состояние должно **сообщать статус системы**, **учить, что здесь будет**, и **давать прямой путь
к ключевому действию**; контекстная подсказка в момент прихода на экран лучше вводного тура [оф., краткое изложение].
SAP Fiori: заголовок-причина в одну строку + короткое описание + опциональная кнопка; оставлять запас под перевод.
Carbon (IBM): при нескольких пустых состояниях на экране — не плодить primary-кнопки, использовать tertiary;
вторичная ссылка на документацию. Vercel Geist: различать варианты — blank slate (первое использование), no results
(фильтр), cleared, permission (нет прав), error — и выбирать по ситуации пользователя.

| Вариант | Что писать | Действие |
|---|---|---|
| Первое использование | «Заявок пока нет. Заявки появляются из бота и формы, или создайте вручную» | «Создать заявку», «Подключить бота» |
| Нет результатов | «По фильтру ничего не найдено» | «Сбросить фильтр» |
| Нет прав | «Раздел доступен роли Финансы» | «Запросить доступ» |
| Ошибка/недоступна интеграция | «ЭСФ-оператор не отвечает с 12:40» | «Проверить соединение», «Журнал» |

Источники раздела 5:
- https://knowledge.hubspot.com/integrations/manage-connected-apps
- https://support.atlassian.com/statuspage/docs/what-is-a-component
- https://support.atlassian.com/statuspage/docs/top-level-status-and-incident-impact-calculations
- https://www.odoo.com/documentation/master/applications/finance/accounting/get_started.html
- https://www.odoo.com/documentation/14.0/applications/finance/accounting/getting_started/initial_configuration/setup.html
- https://ecosire.com/ja/guides/platform/erpnext-complete-guide
- https://discuss.frappe.io/t/anyone-with-a-blueprint-for-setting-up-in-erpnext/157938
- https://shopify.dev/docs/api/app-home/latest/patterns/compositions/setup-guide.md
- https://www.nngroup.com/videos/empty-states-in-application-design-guidelines/
- https://www.sap.com/design-system/fiori-design-web/v1-148/foundations/best-practices/global-patterns/designing-for-empty-states
- https://carbondesignsystem.com/patterns/empty-states-pattern/
- https://vercel.com/geist/empty-state

---

## 6. Товары и услуги в одной модели

### 6.1. Как различают типы

| Система | Тип продукта | Что это даёт процессу |
|---|---|---|
| **Odoo** [оф.] | Product Type: Goods (storable — отслеживается остаток; consumable — не отслеживается) / Service / Combo. Для Service — **Invoicing Policy**: Prepaid/Fixed price, Based on Timesheets, Based on Milestones, Based on Delivered Quantity (manual); **Create on Order**: Nothing / Task / Project & Task / Project (с шаблонами проекта). | Goods → Delivery order; Service → Task/Project; Milestones: «Reached» → строка заказа становится Delivered → счёт только по достигнутым этапам → оплата. |
| **ERPNext** [оф.] | Item: флаг **Maintain Stock** (is_stock_item). Нет склада → нет stock ledger. Sales Order: Order Type Maintenance + **Skip Delivery Note** → доставка не требуется. | Товар → Delivery Note (склад и COGS); услуга → Sales Invoice напрямую из Sales Order; проект/таймшит — отдельно. |
| **Dynamics 365 SCM** [оф.] | Product type: Item / Service; для Item — Item model group с флагом **Stocked product** (stocked / not stocked). Not stocked: нет остатков, нет планирования, но приём/отгрузка возможны. Флаг нельзя снять при открытых транзакциях. | Три комбинации: inventory item (stocked), non-inventory item (not stocked), service. |
| **SAP B1** | Item master: Inventory / Sales / Purchase item флаги; услуги — строки типа Service в документах без item master. | Delivery для товаров; услуга — A/R Invoice без Delivery. |

### 6.2. Общий знаменатель

Все системы делают одно: **единая строка заказа (order line)**, у которой тип продукта определяет **способ подтверждения
исполнения**:

| Тип | Событие «исполнено» | Документ-доказательство | Триггер счёта |
|---|---|---|---|
| Товар со склада (storable) | отгрузка со списанием остатка | Delivery Note / накладная (в Узбекистане ЭСФ+ЭТТН объединены в один документ с 2025) | delivered qty |
| Товар под заказ / consumable | приёмка и передача без складского учёта | накладная | delivered qty |
| Услуга фикс/предоплата | подтверждение заказа | акт | ordered qty (prepaid) |
| Услуга по этапам | этап достигнут (Milestone reached) | акт по этапу | достигнутые этапы |
| Услуга по времени | таймшит утверждён | акт + расшифровка | approved timesheets |

Акцепт (acceptance) — отдельный шаг, который Odoo моделирует как «Milestone Reached»/«Delivered», а бухгалтерский
контур в Узбекистане требует как **акт выполненных работ / ЭСФ с подтверждением покупателем**: покупатель подтверждает
ЭСФ ЭЦП или отклоняет с причиной в течение 10 календарных дней, иначе документ считается принятым; зачёт НДС — только
по принятым электронным счетам-фактурам [втор., buxgalter.uz]. С 2026 — автоматическая оценка рисков ЭСФ в реальном
времени, статус поставщика «в зоне риска» виден покупателю [втор., anhor.uz].

### 6.3. Минимальный набор сущностей для одного процесса

1. **Product** с полем `kind` ∈ {storable, consumable, service} и для service — `fulfilment_policy` ∈ {on_order,
   milestones, timesheets, manual}.
2. **Quote** → **Order** с **OrderLine** (product, qty, price, `delivered_qty`, `invoiced_qty`).
3. **Fulfilment** — полиморфный факт исполнения: `Delivery` (склад) | `Milestone` (этап) | `Timesheet` (время),
   каждый двигает `delivered_qty` строки.
4. **Acceptance** — подтверждение клиентом (подпись в кабинете / ЭСФ-подтверждение), со ссылкой на Fulfilment.
5. **Invoice** строится по `delivered_qty − invoiced_qty` (или по предоплате), **Payment** закрывает счёт.
6. **Purchase/Procurement** — для товаров под заказ: из OrderLine в заявку поставщику (ERPNext drop-ship, Odoo
   MTO-маршрут), с видимостью статуса закупки в заказе.

Источники раздела 6:
- https://www.odoo.com/documentation/18.0/applications/sales/sales/invoicing/milestone.html
- https://www.odoo.com/documentation/13.0/applications/services/project/advanced/so_to_task.html
- https://hibou.io/docs/sales-30/milestones-1195
- https://hibou.io/docs/sales-30/timesheets-on-tasks-1194
- https://cybrosys.com/blog/how-to-set-up-milestones-with-odoo-16-project-management
- https://docs.frappe.io/erpnext/erpnext-for-services-organization.md
- https://docs.frappe.io/erpnext/item.md
- https://docs.frappe.io/erpnext/accounting-entries.md
- https://learn.microsoft.com/en-us/training/modules/create-products-product-masters-dyn365-supply-chain-mgmt/5-not-stocked
- https://learn.microsoft.com/en-us/training/modules/configure-inventory-management-dyn365-supply-chain-mgmt/14-item-groups-model-groups
- https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/sales-marketing/field-service-product
- https://firebearstudio.com/blog/?p=45927
- https://buxgalter.uz/publish/doc/text155310_perehod_na_elektronnye_schet-faktury_-_bez_potryaseniy
- https://anhor.uz/news/invoices-uzb/
- https://anhor.uz/news/dokument/

---

## Выводы для RailTech: что считать стандартом и что заимствовать

1. **Канонический путь один и он у всех одинаков**: Lead → Opportunity → Quote → Order → Fulfilment → Invoice → Payment
   (+ Lost с обязательной причиной, + Return/Credit Note). Названия объектов в контрактах и UI брать из этого ряда,
   не изобретать своих. Единственный обязательный документ цепочки — счёт (SAP B1, ERPNext); КП, заказ, отгрузка
   — опциональны и должны пропускаться без боли.
2. **Граница CRM / ERP совпадает с границей APQC 3.x / 4.x+9.x и с конверсией лида**: CRM владеет Lead и
   Opportunity (до квалифицированной потребности), ERP — Quote и дальше. Событие «Opportunity → заявка в ERP» —
   это и есть lead handoff; оно должно переносить всё, что эталон требует при handoff: контакт, компанию, источник,
   историю диалога бота, потребность, бюджет/сроки, согласованный следующий шаг, владельца.
3. **Lead и Opportunity — разные объекты, Account/Contact создаются при конверсии** (Salesforce, Odoo, ERPNext).
   Бот создаёт Lead; человек (или ИИ по правилам кода) квалифицирует и конвертирует. Идентификаторы клиента — из
   кода, не из модели (совпадает с правилом 4 CLAUDE.md).
4. **Квалификация — по BANT/CHAMP, с письменным SLA**: критерии MQL→SQL зафиксировать в настройках CRM, SLA на отклик
   (≤5 минут ботом, ≤24 ч человеком) и SAL-шаг «принял / отклонил с причиной» — обратная связь в бот/маркетинг.
5. **Роли сворачиваются в три**, но владение стадией остаётся явным: «Продажи» (SDR+AE: Lead, Opportunity, Quote),
   «Сопровождение» (AM+CSM+order desk: Order, Fulfilment, Acceptance, тикеты), «Бэк-офис» (закупки, склад, финансы:
   Procurement, Delivery, Invoice, Payment). В Odoo это «Own documents / All documents / Administrator» по приложению —
   простая и достаточная модель прав.
6. **Правило третей McKinsey**: клиент хочет треть личного, треть удалённого с человеком, треть self-service. Бот
   — удалённый канал, кабинет — self-service, менеджер — личный. Все три видят одни и те же документы и статусы;
   переход между ними без потери контекста — главный критерий «не потерять клиента».
7. **Кабинет — постоянный реестр, бот — сигнал**. Кабинет: КП/заказ/этап/счёт/оплата со статусами, акцепт КП
   онлайн (подпись + опциональная предоплата → заказ фиксируется), оплата, тикеты, команда клиента с ролями
   («видит всё» / «только свои заказы» / «одобряет»), профиль (реквизиты, 2FA). Документы в кабинете — только
   чтение; изменения — через действия (акцепт, запрос изменений, тикет).
8. **Матрица уведомлений**: всё — в кабинет (журнал), важное дублировать письмом (КП, счёт, договор, акт), срочное и
   статусное — в Telegram коротко со ссылкой в кабинет/Mini App; эскалация «не прочитано → письмо». Таргетинг по
   ролям внутри компании клиента.
9. **Один процесс для товаров и услуг** через тип продукта + политику исполнения: storable → отгрузка; consumable
   /под заказ → приёмка-передача; service → on_order | milestones | timesheets. Строка заказа с delivered_qty и
   invoiced_qty — единая точка истины для счёта (модель Odoo/ERPNext/Dynamics).
10. **Acceptance — отдельная сущность**, а не статус: подпись в кабинете и/или подтверждение ЭСФ покупателем (10 дней,
    иначе принято). Для Узбекистана ЭСФ+ЭТТН как единый документ и оценка рисков с 2026 — учесть в контуре ERP и
    в карточке интеграции «ЭСФ-оператор».
11. **Товар под заказ = Procurement из строки заказа** (drop-ship/MTO): статус закупки виден в заказе и в кабинете
    клиента как этап исполнения, а не как внутренняя тайна снабжения.
12. **Консоль администратора по образцу HubSpot Connected Apps + Statuspage**: карточка каждого внешнего сервиса
    (бот, LiteLLM, Langfuse, ЭСФ, платежи, SMTP, связь CRM↔ERP) со статусом пяти уровней, last activity, «Проверить
    соединение», «Переподключить», журнал ошибок; раздел «Требует внимания» наверху; уведомления о разрывах.
13. **Первый запуск — баннер-чеклист из 4–6 шагов** (Odoo/Shopify): компания и реквизиты, валюта/налоги, пользователи
    и роли, бот и каналы, интеграции, первый документ. Каждый шаг ведёт в реальную настройку, прогресс виден,
    ничего не блокирует, кроме действительно обязательного.
14. **Пустые состояния по NN/g**: статус + что здесь будет + одно действие; различать «первое использование / нет
    результатов / нет прав / интеграция недоступна». Это и есть «тупик первого запуска — дефект продукта» из
    памяти владельца.
15. **Метрики как в APQC**: cycle time «Manage sales orders», % заказов без ручного вмешательства, время отклика на
    лид, доля времени менеджера в продаже. Показывать их в дашборде команды (как Odoo: открытые возможности, КП,
    заказы, ожидаемая выручка, цель по выручке) — это понятный любому бизнесу язык «удовлетворить клиента и
    заработать».
