# Аналоги RailTech Platform: что устроено «как у лучших» и что заимствовать

Дата: 2026-10-21. Веб-ресёрч по официальной документации вендоров, справочным центрам и обзорам (Capterra, G2).
Контекст: малый/средний B2B в Узбекистане — промышленные товары под заказ + услуги; свой ансамбль CRM + ERP + Cabinet.
Жалоба владельца: «сложно, непонятно, никто не знает, как работать». Цель — не «переписать на Odoo», а вынести
паттерны экранов, процессов и ролей, которые делают аналоги понятными.

Пометки достоверности: **[док]** — официальная документация вендора; **[обзор]** — сторонний обзор/партнёр;
**[память]** — по знанию модели, в источниках за сегодня не подтверждено, проверить в живом инстансе.

---

## 0. Главная мысль за 10 строк

1. У всех «лучших» один и тот же сквозной скелет: **Лид → Сделка (возможность) → КП (quotation) → Заказ/Договор → Счёт → Исполнение → Акт/Оплата**. Названия отличаются, скелет — нет.
2. Понятность даёт не количество модулей, а **один центральный объект** (сделка/заказ) с лентой активности, «следующим шагом» и кнопками действий в одном месте.
3. Клиенту показывают **один первичный документ — КП/заказ**, а не внутреннюю воронку. Его стадии для клиента: «Ждёт вашего решения → Принято → Оплачено → Выполняется → Выполнено».
4. Акцепт КП везде сделан как **публичная ссылка + «Принять/Подписать (& оплатить)» + «Отклонить с причиной»**; подпись — встроенная (Odoo, HubSpot) или внешняя (DocuSign/PandaDoc).
5. Мессенджер — это **канал в карточке сделки**, а не отдельная система. Чат из Telegram ложится в таймлайн сделки (Bitrix24 Открытые линии, Kommo).
6. Стадии дисциплинируют через **обязательные поля на стадии** (Bitrix24, Zoho Blueprint, HubSpot) и **«гниение» сделки без следующего шага** (Pipedrive).
7. ИИ у лидеров 2025–2026 — три роли: автоответчик по базе знаний с жёстким handoff, **ассистент менеджера** (резюме, заполнение полей, черновик), и никогда — «решающий по деньгам».
8. Первый запуск у Odoo/HubSpot — **баннер-чек-лист из 4–6 шагов** в самом модуле (реквизиты → шаблон документа → способ оплаты → пробный документ), а не страница настроек.
9. Слабости аналогов для нас: Bitrix24 — перегружен; Odoo — баги/апгрейды/платные модули; ERPNext — CRM-модуль объявлен к удалению в v17; локальные (Smartup, Billz) — FMCG/ритейл, не «под заказ».
10. Локализация РУз (ЭСФ через Didox/Faktura и др., узбекский язык, Telegram как главный канал) — наше преимущество, которого у глобальных систем нет «из коробки»; сохранять, а не ломать.

---

## 1. Аналоги: как у них устроен путь «лид → клиент»

### 1.1 Odoo 17/18 (CRM + Sales + Sign + Invoicing + Portal + Helpdesk)

| Аспект | Как сделано |
|---|---|
| Путь | Лид (опц.) → Возможность (opportunity) в канбане CRM → «Новое КП» из возможности → Quotation → Quotation Sent → **Sales Order** (при подтверждении) → счёт → доставка/проект. Цепочка «smart buttons» на форме: Quotations N / Invoices N / Deliveries N. |
| Стадии по умолчанию | CRM: **New → Qualified → Proposition → Won**; «Lost» — не колонка, а флаг с причиной потери, восстанавливается **[обзор, Cybrosys]**. Quotation: Quotation → Quotation Sent → Sales Order → (Locked — флаг) / Cancelled **[обзор + память]**. |
| Роли | Sales Teams: лидер, участники, алиас email (письмо на алиас = лид), лимиты назначения, правила автораспределения **[док]**. Права: User: Own documents / All documents / Administrator **[память]**. |
| Портал клиента | Один логин → дашборд «Мои документы» со счётчиками: Quotations, Sales Orders, Invoices, Tickets, Projects/Tasks, Signatures, Subscriptions. Только чтение + действия (подписать, оплатить, отклонить, комментировать). Доступ выдаётся из контакта: Action → Grant portal access **[док]**. |
| Акцепт КП | На КП в Other Info: Online Signature / Online Payment. Клиент видит КП по ссылке: **Sign & Pay**, Reject (с причиной), Feedback (комментарий), скачать PDF. После подписи — вкладка Signature (кто, когда), КП → Sales Order **[док/обзор]**. Odoo 19: клиент сам отмечает опциональные секции/строки в портале **[док, release notes 19]**. |
| Мессенджеры | Нативно — Live Chat на сайте + email в chatter. Telegram/WhatsApp — платные модули из apps.odoo.com. WhatsApp есть в Enterprise 17+ **[память]**. |
| Админка/онбординг | В Invoicing/Accounting — **onboarding banner** из 4 шагов (Company Data → Documents Layout → Create Invoice/Online Payments → Sample) **[док]**. Чат-тер с «Activities» у любой записи. Odoo 19: Ask AI в верхней панели, упрощённое создание активностей **[док]**. |
| Сильное для нас | Единый объект Quotation→SO с портальным акцептом; smart buttons; chatter+activities; портал без отдельной разработки; «Lost» как причина, а не стадия. |
| Слабое для нас | Capterra 4.2/1309: 73% негативных упоминаний «баги и медленные фиксы», 74% — биллинг/неожиданные платежи; апгрейды ломают кастомные модули **[обзор]**. Telegram нет из коробки. ЭСФ РУз нет. |

Источники: https://www.odoo.com/documentation/18.0/applications/general/users/portal.html · https://www.odoo.com/documentation/18.0/applications/sales/crm/pipeline/manage_sales_teams.html · https://www.odoo.com/documentation/18.0/applications/essentials/activities.html · https://www.odoo.com/odoo-19-release-notes · https://www.cybrosys.com/odoo/odoo-books/v18/sales/sales-quotations/ · https://www.cybrosys.com/blog/how-to-manage-crm-pipeline-in-odoo-18 · https://odoo-online.readthedocs.io/sv/latest/sales/online_customer_approval_on_quotation.html · https://www.odoo.com/documentation/saas-18.1/applications/finance/accounting/get_started.html · https://www.capterra.com/p/135618/Odoo/reviews/

### 1.2 ERPNext / Frappe CRM (open source)

| Аспект | Как сделано |
|---|---|
| Путь | Lead → Opportunity («qualified lead») → Quotation → Customer → Sales Order → Delivery Note / Sales Invoice → Payment Entry. Путь «типичный, не обязательный»: КП можно делать прямо из лида **[док]**. |
| Статусы лида | **Lead → Open → Replied → Opportunity → Quotation → Lost Quotation → Interested → Converted → Do Not Contact** — статус меняется автоматически при появлении связанного документа **[док]**. |
| Opportunity | Поля: Opportunity From (Lead/Customer), Type (Sales/Support/Maintenance), Amount, Probability, **Next Contact Date / Next Contact By** (создаёт событие и напоминание), Minutes to First Response, Lost reasons/competitors. Кнопка «Make → Quotation / Supplier Quotation» (запрос цен у поставщика прямо из возможности — важно для «под заказ») **[док]**. |
| Роли | Sales User / Sales Manager / Customer (website user). Assignment Rules для авто-назначения **[док]**. |
| Портал | Клиент регистрируется на /login → видит Orders, Invoices, Shipments, статусы оплаты/отгрузки; проекты — при привязке к Customer + Sales Order **[док]**. **Акцепта КП в портале нет** — только через права на DocType и сторонний модуль (ECOSIRE quote-proposal-esign) **[обзор/форум]**. |
| Мессенджеры | Нет Telegram. Frappe CRM — WhatsApp через отдельное приложение **[док]**. |
| Важно | CRM-модуль ERPNext **объявлен к удалению в v17**; рекомендован Frappe CRM (лиды/сделки, канбан, звонки, заметки, SLA, assignment rules) **[док]**. |
| Сильное | Чистая цепочка документов с авто-статусами лида; «Next Contact Date» как поле возможности; Supplier Quotation из Opportunity. |
| Слабое | Портал без акцепта; CRM в переходном состоянии; UI «форма-таблица», понятность низкая без настройки. |

Источники: https://docs.frappe.io/erpnext/lead · https://docs.frappe.io/erpnext/opportunity · https://docs.frappe.io/erpnext/quotation · https://docs.frappe.io/erpnext/crm · https://docs.frappe.io/erpnext/customer-portal · https://docs.frappe.io/erpnext/customer-orders-invoices-and-shipping-status · https://docs.frappe.io/crm/introduction.md · https://frappe.io/crm · https://discuss.frappe.io/t/quotation-approval-from-customer-portal/24839

### 1.3 Битрикс24

| Аспект | Как сделано |
|---|---|
| Путь | Два режима: «классический» (Лид → Сделка) и «простой» (обращение сразу = Сделка) — простой рекомендован малым компаниям **[док]**. Сделка → КП (документ по шаблону из сделки) → Счёт (документ для оплаты, данные из CRM) → Смарт-процессы/Задачи на исполнение. |
| Стадии по умолчанию | Справочник предзаполнен; начальная, промежуточные, две финальные (успех/провал). По памяти: лиды «Не обработан → В работе → Обработан → Качественный / Некачественный»; сделки «Новая → Подготовка документов → Предварительный счёт → В работе → Финальный счёт → Сделка успешна / провалена» **[память, подтверждено частично]**. Настраивается: CRM → Настройки → Справочники. |
| Карточка | Таймлайн (вся история), «Дела» (звонок/встреча/задача) с умными счётчиками «просрочено/сегодня», настраиваемые поля и секции **[док]**. |
| Stage gates | «Обязательное на стадии» для поля (шестерёнка у поля → Настроить); доступно не на всех тарифах; действует для всех карточек типа **[док]**. Маркет: «Обязательные поля PRO», «Чек-лист для стадий сделки». |
| Клиент | Полноценного портала нет: публичная ссылка на счёт («Ссылка на счёт» → просмотр/печать/оплата при подключённых платёжках), **Sales Center** — отправка страницы оплаты в чат/СМС из таймлайна сделки **[док]**. «Личный кабинет клиента» — только приложения Маркета (Клиент24, atwebsite) **[обзор]**. |
| Мессенджеры | **Открытые линии**: создать бота в BotFather → токен в настройках канала → выбрать линию и очередь ответственных; переписка в чате портала и в карточке клиента; можно пригласить клиента в Telegram по СМС-ссылке из мобильной CRM **[док]**. |
| ИИ | CoPilot/BitrixGPT: расшифровка звонка, резюме, **заполнение полей сделки**, оценка по скрипту — три кнопки в блоке звонка в таймлайне **[док]**. **AI-агент для открытых линий**: роль, правила, база знаний (прайсы, описания), опциональная связь с CRM (статус заказа); передаёт оператору с историей, если ответа нет в базе или «не уверен»; сотрудник может перехватить вручную; не совместим с чат-ботом в той же линии **[док]**. |
| Онбординг | Раздел «С чего начать» в настройках CRM; при создании портала — мастер выбора режима CRM **[память]**. |
| Сильное | Готовая связка Telegram ↔ карточка сделки; КП/счёт как документы сделки; обязательные поля на стадии; AI-агент с честным handoff. |
| Слабое | Capterra 4.2/997: «сложно, новым сотрудникам долго учиться», «перегружен функциями», «захламлённый интерфейс», мобильное слабее **[обзор]**. Портала клиента нет. Именно жалоба нашего владельца — это про Битрикс. |

Источники: https://helpdesk.bitrix24.ru/open/26035204/ · https://helpdesk.bitrix24.ru/open/17545216/ · https://helpdesk.bitrix24.ru/open/17612604/ · https://helpdesk.bitrix24.ru/open/27744544/ · https://helpdesk.bitrix24.ru/open/28426770/ · https://helpdesk.bitrix24.ru/open/5451177/ · https://helpdesk.bitrix24.com/open/9613777 · https://helpdesk.bitrix24.com/open/10055593 · https://helpdesk.bitrix24.com/open/26052591/ · https://www.bitrix24.ru/features/copilot · https://www.bitrix24.ru/apps/app/itnebo.client24/ · https://www.capterra.com/p/113540/Bitrix24/reviews/ · https://umnico.com/ru/blog/user-case-uzum-rus/ (Bitrix24 — 59,5% рынка CRM в РУз, Telegram доминирует)

### 1.4 amoCRM / Kommo

| Аспект | Как сделано |
|---|---|
| Путь | Одна сущность — **Сделка** (lead) в воронке; «Неразобранное» — входящий буфер из мессенджеров/форм, откуда принимают или отклоняют. По умолчанию: «Первичный контакт → Переговоры → Принимают решение → Согласование договора → Успешно реализовано / Закрыто и не реализовано» **[обзор, частично; память]**. До 10 воронок × 100 этапов **[обзор]**. |
| Мессенджеры | Telegram-бот через BotFather → источник лида в воронке; **одна воронка — один Telegram-бот**; входящие создают сделку в Incoming Leads; весь чат — в карточке **[док]**. Единый Inbox «Чаты». |
| Salesbot / Digital Pipeline | Триггеры на этапах: «при переходе на этап → отправить сообщение/задачу/письмо/запустить бота»; Salesbot — сценарии с интентами, тестирование в превью **[док]**. |
| ИИ (Kommo AI, 2025–26) | **AI agent**: Sources (документы/FAQ) + Actions (WHEN: что сказал лид/тональность/молчание → DO: ответить, запросить данные, обновить лид, запустить бота, **передать чат**) + Persona (роль, тон, язык, задержка). Лимиты сообщений/кредитов на диалог → автопередача с уведомлением. Один агент на этап воронки; агент **не начинает диалоги, не выходит за свои источники, не редактирует кастомные поля**. Отдельно: резюме диалога, suggested replies по базе знаний **[док]**. |
| Онбординг | Мастер «настройка воронки» при первом входе; шаблоны ботов **[память]**. |
| Сильное | Самая простая модель: «всё — сделка в воронке, чат — внутри». Явные правила бота. |
| Слабое | Нет документов (КП/счёт/акт) и ERP-части; Capterra 4.3/194: слабая поддержка, бедные отчёты **[обзор]**. |

Источники: https://support.kommo.com/docs/connect-telegram-to-kommo · https://support.kommo.com/docs/create-a-salesbot-in-kommo.md · https://support.kommo.com/docs/kommo-ai-agent · https://support.kommo.com/docs/kommo-ai-overview · https://support.kommo.com/docs/kommo-basics.md · https://www.kommo.com/blog/kommo-ai-pricing/ · https://vc.ru/links/3036928-nastroika-amocrm-dlya-effektivnykh-prodazh · https://www.directline.pro/connect/p/voronka-prodazh-v-amocrm/ · https://capterra.com/p/120048/amoCRM/reviews/

### 1.5 1С:CRM / 1С:УНФ / 1С:Управление торговлей (в т.ч. для Узбекистана)

| Аспект | Как сделано |
|---|---|
| Путь (УНФ/УТ) | Документная цепочка **[память]**: Обращение/Лид (1С:CRM) → Сделка → **Коммерческое предложение → Заказ покупателя → Счёт на оплату → Реализация (ТТН/акт) → Счёт-фактура (ЭСФ)** → Поступление оплаты. Каждый документ создаётся «на основании» предыдущего — кнопка «Создать на основании». |
| Стадии | В УНФ состояния заказа покупателя: «Не подтверждён / Подтверждён / В работе / Выполнен / Закрыт» **[память]**; в 1С:CRM — настраиваемые сценарии продаж с этапами. |
| ЭСФ РУз | Операторы ЭСФ по gov.uz: Didox (didox.uz), Faktura.uz, Soliq-Servis, e-invoice.uz; у Faktura.uz — «API для интеграции, готовые модули для 1С» **[док/обзор, 2019]**. С 01.01.2026 — система оценки налоговых рисков ЭСФ **[обзор]**. Конкретный модуль ЭСФ в «1С для Узбекистана» в открытых источниках сегодня не найден — проверять у 1c.uz / партнёров. |
| Портал | Нет; только внешние надстройки. Мессенджеры — через 1С:CRM/внешние коннекторы. |
| Сильное | Эталон **названий документов РУз-рынка** (КП, Заказ, Счёт, Акт, Счёт-фактура) и логики «на основании». Бухгалтер и клиент понимают эти слова без обучения. |
| Слабое | Интерфейс «справочники/документы/журналы», тяжёлый онбординг, нет портала/Telegram. |

Источники: https://gov.uz/ru/soliq/pages/elektron-hisobvaraq-fakturalar · https://www.spot.uz/ru/2019/12/30/factures/ · https://buxgalter.uz/esf/kakogo_operatora_esf_vybrat · https://anhor.uz/news/invoices-uzb/ · https://its.1c.ru/docs/itsp

### 1.6 Zoho One (CRM + Books + Sign + Desk + портал)

| Аспект | Как сделано |
|---|---|
| Путь | Lead → Convert (создаёт Account + Contact + Deal) → Deal → Quote → Sales Order → Invoice (CRM) или Estimate → Invoice (Books) **[память]**. |
| Стадии сделки по умолчанию | **Qualification → Needs Analysis → Value Proposition → Identify Decision Makers → Proposal/Price Quote → Negotiation/Review → Closed Won / Closed Lost**, с вероятностями; Expected Revenue считается из стадии×суммы **[док]**. |
| Stage gates | **Blueprint**: состояния и переходы; каждый переход — кнопка на карточке; у перехода — владелец, критерии, обязательные/опциональные поля, чек-лист, заметки, валидация; SLA на пребывание в состоянии **[док]**. Это самая зрелая реализация «stage gate». |
| Портал | Zoho Books Client Portal: клиент видит Estimates/Invoices в статусе Sent, **принимает/отклоняет estimate, оплачивает счёт**; приглашение из карточки контакта **[док]**. Zoho Desk — портал тикетов. |
| ИИ | Zia «Next Best Experience»: по истории подсказывает следующий шаг по сделке с объяснением и заготовкой (черновик письма, повестка встречи) **[док]**; Zia LLM — черновики писем, резюме; Zia Agents — студия агентов (2025) **[док]**. SalesIQ Zobot: «Handoff to Operator» в середине диалога, Forward Message при передаче **[док]**. |
| Навигация | Zoho One 2025: **Quick Nav** (Z+Space) — поиск по 50+ приложениям; **Action Panel** — единая очередь задач/напоминаний/согласований из всех приложений **[док]**. |
| Сильное | Blueprint; единая очередь действий; портал Books с акцептом estimate. |
| Слабое | Десятки приложений с разными UI; портал разбит по продуктам (Books/Desk/Projects отдельно). |

Источники: https://www.zoho.com/one/guides/dealmanagement.html · https://help.zoho.com/portal/en/kb/crm/articles/blueprint-glossary-terms · https://help.zoho.com/portal/en/community/topic/effortlessly-advance-through-your-crm-blueprints-by-including-optional-fields-in-transitions · https://help.zoho.com/portal/en/community/topic/client-portal-is-now-available-in-zoho-books · https://www.zoho.com/crm/next-best-experience.html · https://help.zoho.com/portal/fr/community/topic/wrapping-up-2025-on-a-high-note-crm-release-highlights-of-the-year · https://www.zoho.com/salesiq/help/developer-guides/create-bot.html · https://help.zoho.com/portal/en/community/topic/announcing-zo25-the-refreshed-more-unified-and-intelligent-os-for-business

### 1.7 HubSpot (Sales Hub + Quotes + Payments + Service портал)

| Аспект | Как сделано |
|---|---|
| Путь | Contact/Company → Deal → Quote (из сделки, с line items) → Signed → Payment link / Invoice → Ticket (сервис). |
| Стадии сделки по умолчанию | **Appointment scheduled (20%) → Qualified to buy (40%) → Presentation scheduled (60%) → Decision maker bought-in (80%) → Contract sent (90%) → Closed won / Closed lost** **[обзор, совпадает у нескольких]**. Closed → close date = сегодня **[док]**. |
| Stage gates | «Required properties» при переходе на стадию (Settings → Objects → Deals → Pipelines); Deal Pipeline Rules: создавать только в первой стадии, запрет пропуска стадий, запрет движения назад **[обзор/комьюнити]**. Pipeline automations: «при входе в стадию → создать задачу / уведомление» **[док]**. |
| Акцепт КП | Клиент открывает ссылку (опц. пароль/верификация email) → Sign now → рисует/печатает/загружает подпись → контрподпись → PDF обеим сторонам → **Set up payment**. Статусы: Draft → Pending approval → Approved → Published → Pending signature → Signed → Paid / Expired; e-sign на базе Dropbox Sign, лимит подписей в месяц **[док]**. Buying rooms (Commerce Hub) — общее пространство покупатель/продавец **[обзор]**. |
| Портал | Support portal (бывший Customer Portal): только тикеты, вход из базы знаний или по ссылке; нужна домен + inbox/help desk **[док]**. Коммерческих документов в портале нет — только ссылки на quote/invoice. |
| ИИ (Breeze) | **Customer Agent**: отвечает по одобренным источникам; handoff по умолчанию — «не может ответить», «просит человека», «агент на паузе»; кастомные триггеры-фразы («refund», «cancellation») и текстовые guidelines; выбор «передать сразу / позже / оставить агента» **[док]**. **Prospecting Agent**: готовит черновики писем — **человек проверяет перед отправкой** **[обзор]**. Customer Handoff Agent (beta): собирает досье для передачи аккаунта между сотрудниками **[док, trust]**. |
| Онбординг | In-app «Getting started» чек-лист: подключить почту/календарь, профиль, пригласить команду, импорт, воронка **[обзор + план HubSpot]**. |
| Сильное | Лучший в классе buyer-side flow для КП; явные правила handoff; pipeline rules. |
| Слабое | Дорого (Commerce seats), портал — только сервисный; нет Telegram нативно; ЭСФ нет. |

Источники: https://knowledge.hubspot.com/quotes/use-e-signatures-with-quotes · https://knowledge.hubspot.com/object-settings/set-up-and-customize-pipelines · https://knowledge.hubspot.com/properties/hubspots-default-deal-properties · https://knowledge.hubspot.com/object-settings/set-up-pipeline-automations-for-objects · https://knowledge.hubspot.com/inbox/set-up-a-customer-portal · https://knowledge.hubspot.com/customer-agent/set-up-and-customize-the-customer-agents-handoff-process · https://trust.hubspot.com/ai/f98d718d-2ed5-4959-ace1-3bf77e7c7ca9 · https://www.spotdev.co.uk/blog/how-to-create-deal-stage-dependencies-in-hubspot · https://offers.hubspot.com/sales-hub-onboarding-plan · https://coefficient.io/sales-pipeline-2/sales-pipeline-stages-hubspot

### 1.8 Pipedrive + Smart Docs · PandaDoc · DocuSign

| Система | Что важно |
|---|---|
| Pipedrive | Философия **activity-based selling**: «интерфейс построен на действии — закрыв активность, вас всегда просят добавить следующую» **[док, маркетинг]**. **Rotting**: сделка краснеет, если не обновлялась N дней на стадии (срок per-stage); таймер сбрасывается активностью/письмом **[док]**. Smart Docs: шаблоны КП/договоров с подстановкой полей и товаров, shareable link с трекингом открытий (уведомление при первом/каждом открытии), версия документа на каждую ссылку, e-sign **[док]**. |
| PandaDoc | Статусы: Draft → Sent → Viewed → (Suggest edits / To approve) → **Waiting for payment** → Completed / Paid / Declined / Expired; вручную — только Completed, Expired, Paid, Declined; платёжный блок (Stripe: карта/ACH) сразу после подписи **[док]**. Интеграция с Pipedrive: двусторонний CPQ, подпись внутри Pipedrive **[обзор]**. |
| DocuSign | Envelope: Created → Sent → Delivered (все открыли) → Signed → Completed / Declined / Voided; статусы per-recipient **[обзор]**. Эталон словаря «конверт/получатель/статус». |

Источники: https://www.pipedrive.com/features/activities-goals · https://support.pipedrive.com/en/article/the-rotting-feature · https://support.pipedrive.com/en/article/smart-docs · https://support.pandadoc.com/en/articles/9714842-manually-change-document-status · https://support.pandadoc.com/en/articles/9714824-home · https://www.pipedrive.com/en/marketplace/app/panda-doc-proposals-e-signatures-and-cpq/bde8d47250a2302c · https://community.nintex.com/t5/Technical-Issues/DocuSign-Statuses/ta-p/86663

### 1.9 Локальные (Узбекистан): Smartup, Billz, прочие

| Система | Что известно | Релевантность |
|---|---|---|
| **Smartup** (smartup24.com) | Облачная ERP/SFA для дистрибуции и производства: Продажи, Склад, Финансы, Торговый маркетинг, **Telegram-бот приёма заказов и контроля продаж**, AI Shelf Recognition, Маркировка; B2B-маркетплейс (600+ поставщиков, 10 000+ точек); целевой клиент — 50+ сотрудников с полевыми процессами (FMCG, pharma, автозапчасти, стройка); внедрение 3–7 дней **[док сайт/обзор]**. | Паттерн «Telegram-бот = канал заказа» и быстрый запуск. Не про «под заказ» и КП. ЭСФ/портал на сайте не упомянуты. |
| **Billz** | Облачная POS/учёт для розницы: продажи, склад, CRM, e-commerce, аналитика; 4 000+ бизнесов; TBC Uzbekistan купил 53% за $9 млн (2025) **[обзор]**. | Ритейл; для B2B под заказ — не аналог. API/Telegram-документация в открытых источниках не найдена. |
| **Jet ERP / Iman** | «Jet ERP» как продукт не найден (есть ИТ-компании «Jet» в Ташкенте, не ERP); **Iman** — финтех (исламские финансы, рассрочка), не CRM/ERP **[обзор]**. | Не аналоги. |
| Рынок | Bitrix24 ≈ 59,5% CRM-рынка РУз, далее amoCRM; Telegram — доминирующий канал (сайт-интеграции: Telegram 97,9% vs WhatsApp 5,6%; >70% населения по словам Дурова) **[обзор]**. | Ожидания сотрудников и клиентов сформированы Bitrix24/amoCRM + Telegram. Наши названия стадий и действий должны быть узнаваемы для людей, видевших Bitrix24. |

Источники: https://smartup24.com/ · https://apps.apple.com/app/id1531868864 · https://app.dealroom.co/companies/smartup_3 · https://finder.techleap.nl/news/feed/tbc-uzbekistan-acquires-billz-for-9m · https://the-tech.kz/it-produkty-iz-uzbekistana-za-kotorymi-stoit-sledit-v-2025-godu/ · https://www.spot.uz/ru/2022/02/22/iman · https://www.wmtips.com/technologies/crm/country/uz/ · https://www.wmtips.com/technologies/instant-messaging/country/uz/ · https://daryo.uz/2024/06/30/over-70-of-uzbekistans-37-mn-population-utilizes-telegram-pavel-durov/

---

## 2. UX-паттерны, которые делают системы «понятными»

| Паттерн | Где подсмотрено | Как выглядит (описание экрана) |
|---|---|---|
| **Один центральный объект с лентой** | Odoo chatter; Bitrix24 таймлайн; HubSpot deal record; ERPNext comments/email thread | Правая/нижняя часть карточки — хронология: письма, чаты, звонки, смена стадии, документы; сверху — поле «написать/заметка/запланировать». Один экран отвечает на «что было и что дальше». |
| **Следующий шаг (next action) как обязательный атрибут** | Pipedrive («всегда просят добавить следующую активность»); OnePageCRM (цветной значок next action на карточке); ERPNext Opportunity «Next Contact Date/By»; Odoo activities (часы: зелёный/жёлтый/красный) | На карточке канбана — иконка часов с цветом: просрочено/сегодня/будущее. Закрытие активности открывает «Done & Schedule Next». |
| **Rotting / протухание** | Pipedrive | Карточка краснеет, если N дней без обновления на стадии; срок задаётся per-stage. |
| **Канбан стадий с вероятностью и суммой** | Odoo, HubSpot, Zoho, Bitrix24, Kommo | Колонки = стадии; в заголовке сумма; карточка: клиент, сумма, ответственный, next action; «Lost» — не колонка, а кнопка с причиной (Odoo). |
| **Карточка клиента 360°** | Bitrix24 Контакт/Компания; HubSpot company; Odoo contact smart buttons | Шапка — реквизиты; smart buttons: Сделки N / КП N / Счета N / Задолженность; лента всех касаний по всем сделкам. |
| **Inbox/очередь менеджера** | Kommo «Чаты» + «Неразобранное»; Bitrix24 Открытые линии (очередь ответственных); Zoho One Action Panel; HubSpot Help Desk inbox | Один список «требует ответа/действия» с фильтром «мои/все», SLA-таймером, кнопкой «принять в работу». |
| **Омниканал в карточке** | Bitrix24 (чат Telegram в карточке), Kommo, HubSpot conversations | Сообщения клиента из Telegram видны в ленте сделки; ответ пишется из карточки и уходит в Telegram. |
| **Stage gates / обязательные поля** | Zoho Blueprint (переход = кнопка с формой обязательных полей, чек-лист, SLA); Bitrix24 «Обязательное на стадии»; HubSpot required properties + pipeline rules | При перетаскивании в стадию всплывает форма «чтобы перейти, заполните…»; запрет пропуска стадий и движения назад. |
| **Автоматизации «стадия → действие»** | HubSpot pipeline automations; Kommo Digital Pipeline; Bitrix24 роботы/триггеры | В настройке стадии — список действий: задача ответственному, письмо/сообщение клиенту, уведомление руководителю. |
| **Шаблоны документов из записи** | Odoo quotation templates + PDF Quote Builder; Bitrix24 «Документ по шаблону»; Pipedrive Smart Docs; PandaDoc | В карточке кнопка «Документ» → выбрать шаблон → подставились поля/товары → ссылка/PDF. |
| **Smart buttons / связанные документы** | Odoo, 1С «Структура подчинённости», ERPNext «Connections» | Верх формы: кнопки-счётчики связанных документов; видна цепочка КП→Заказ→Счёт→Акт. |
| **Пустые состояния и образцы** | Odoo (help-текст в пустом канбане, sample data в list/kanban); общие гайды | Пустой список: заголовок «зачем страница», 2 строки «что появится», кнопка «Создать первый…», опционально «показать пример». |
| **Баннер-чек-лист первого запуска** | Odoo Invoicing/Accounting (Company Data → Documents Layout → Create Invoice/Online Payments → Sample); HubSpot Getting started; Bitrix24 «С чего начать» | Полоса сверху модуля из 4–6 шагов с галочками; исчезает по завершении. |
| **Переключатель модулей** | Odoo home menu (сетка приложений) / верхний левый app menu; Zoho One Quick Nav (Z+Space); Bitrix24 левое меню | Единая шапка: кнопка приложений + глобальный поиск + колокольчик активностей (Odoo: красный счётчик «late/today/future» по приложениям). |
| **Единый словарь статусов** | Odoo (Quotation/Quotation Sent/Sales Order), HubSpot quotes, PandaDoc, DocuSign | Статус документа — одно слово в бейдже + подсказка; цветовая семантика одинакова во всех модулях. |

Источники: https://www.odoo.com/documentation/18.0/applications/essentials/activities.html · https://help.onepagecrm.com/article/642-pipeline-kanban-view · https://www.affinity.co/product-releases/increase-the-speed-of-your-deals-with-quick-actions-from-kanban-view · https://docs.agiled.app/docs/crm/deals-views · https://support.pipedrive.com/en/article/the-rotting-feature · https://help.zoho.com/portal/en/kb/crm/articles/blueprint-glossary-terms · https://helpdesk.bitrix24.ru/open/27744544/ · https://knowledge.hubspot.com/object-settings/set-up-pipeline-automations-for-objects · https://cybrosys.com/slides/how-to-show-sample-data-in-tree-and-kanban-view-in-odoo-17 · https://produktly.com/guides/how-to-use-empty-states-for-onboarding · https://help.zoho.com/portal/en/community/topic/announcing-zo25-the-refreshed-more-unified-and-intelligent-os-for-business

---

## 3. Как оформлена коммуникация с клиентом

### 3.1 КП со ссылкой «принять онлайн»

| Система | Что видит клиент | Действия клиента | Что происходит после |
|---|---|---|---|
| Odoo | Страница КП в портале: шапка компании, строки, опциональные товары (можно отметить), срок действия | **Sign & Pay** (нарисовать/напечатать/загрузить подпись → оплата), Reject (причина), Feedback (комментарий), PDF | КП → Sales Order; вкладка Signature; при auto-invoice счёт «Paid» |
| HubSpot | Ссылка (опц. пароль/верификация email), line items, Acceptance block | Sign now → подпись → контрподпись продавца → PDF обеим сторонам → Set up payment | Статус Signed → Paid; ссылка на подписанный документ живёт до expiry |
| Zoho Books | Client Portal: Estimates/Invoices в статусе Sent | Accept / Decline estimate; Pay invoice | Estimate → Invoice |
| PandaDoc | Документ с блоком подписи и платёжным блоком | Подписать → заплатить (Stripe) | Sent → Viewed → Completed / Waiting for payment → Paid |
| Bitrix24 | Публичная ссылка на счёт (просмотр/печать/оплата), страница оплаты из Sales Center в чат/СМС | Оплатить | Триггер «оплата получена» двигает сделку |
| Pipedrive Smart Docs | Shareable link с трекингом открытий | Подписать | Уведомление менеджеру о первом/каждом открытии |

### 3.2 Какой объект первичен для клиента и как называются его стадии

- Везде первичен **КП/Quotation → затем Заказ/Order/Invoice**. Лиды и внутренние стадии воронки клиенту не показывают никогда.
- Стадии глазами клиента (сводно): **«Отправлено / Ждёт вашего решения» → «Принято / Подписано» → «Ожидает оплаты» → «Оплачено» → «В работе» (ERPNext: billing/shipping status) → «Выполнено / Доставлено»** + «Отклонено» и «Истёк срок».
- Портал Odoo: дашборд со счётчиками по типам документов; ERPNext: Orders/Invoices/Shipments; Zoho Books: Estimates/Invoices; HubSpot: только Tickets.

### 3.3 Подпись

- Встроенная «лёгкая» подпись (нарисовать/напечатать/загрузить) — Odoo (Community и Enterprise), HubSpot (Dropbox Sign под капотом), Pipedrive, PandaDoc. Юридически значимая КЭП для РУз — отдельный слой (E-IMZO), глобальные системы его не знают.
- Полноценный e-sign (Odoo Sign, DocuSign) — для договоров, с полями, порядком подписантов, сертификатом подписи (PandaDoc: при ручном «Completed» сертификат не генерируется).

### 3.4 Оплата по ссылке

- HubSpot payment link после подписи; Odoo Online Payment как режим подтверждения КП; Bitrix24 Sales Center — ссылка на оплату в чат/СМС; PandaDoc — платёжный блок. Для РУз это Payme/Click/Uzum — паттерн тот же: «кнопка Оплатить на странице документа».

### 3.5 Уведомления и «портал vs чат»

- Email — базовый канал у всех (Odoo chatter, HubSpot, Zoho). Мессенджер — у Bitrix24 (Открытые линии + СМС-ссылка), Kommo (все каналы в одном inbox). Odoo 19 добавил WhatsApp/Live chat с AI-агентом.
- Практика: **портал — для документов и статусов (структурированное), чат — для вопросов и уведомлений (разговорное)**; из уведомления в чате всегда ведёт ссылка на документ в портале/Mini App. Smartup и кейс Uzum подтверждают: для РУз Telegram — не «ещё один канал», а основной.

Источники: https://www.cybrosys.com/odoo/odoo-books/v18/sales/sales-quotations/ · https://odoo-online.readthedocs.io/sv/latest/sales/online_customer_approval_and_payment_on_quotation.html · https://knowledge.hubspot.com/quotes/use-e-signatures-with-quotes · https://help.zoho.com/portal/en/community/topic/client-portal-is-now-available-in-zoho-books · https://support.pandadoc.com/en/articles/9714842-manually-change-document-status · https://helpdesk.bitrix24.ru/open/5451177/ · https://helpdesk.bitrix24.com/open/10055593 · https://support.pipedrive.com/en/article/smart-docs · https://docs.frappe.io/erpnext/customer-orders-invoices-and-shipping-status · https://www.odoo.com/documentation/18.0/applications/general/users/portal.html

---

## 4. ИИ-бот в продажах: как делят работу бот ↔ человек (2025–2026)

| Система | Роль ИИ | Правила handoff | Ассистент менеджера | Безопасность / деньги |
|---|---|---|---|---|
| **Bitrix24 AI-агент (открытые линии) + CoPilot** | Отвечает в мессенджерах по базе знаний (прайсы, описания), помогает оформить заказ, переносит данные чата в поля CRM | Нет ответа в базе / «не уверен» / требует человека → передать оператору **с историей**; сотрудник может перехватить в любой момент; бот и агент в одной линии — нельзя | CoPilot: расшифровка звонка, резюме, заполнение полей, оценка по скрипту — по кнопке в таймлайне | Правила общения задаются текстом; решения по цене — не описаны как функция агента |
| **Kommo AI agent** | Отвечает только на входящие, только из Sources | Action DO: «передать чат» при квалификации; лимиты сообщений/кредитов → автопередача с уведомлением; один агент на этап | Резюме диалога; suggested replies по базе знаний; переписывание текста | Не редактирует кастомные поля; не начинает диалоги; не выходит за источники |
| **HubSpot Breeze** | Customer Agent отвечает по одобренным источникам (~65% резолюций по данным HubSpot) | По умолчанию: не может ответить / просит человека / агент на паузе; кастомные фразы-триггеры (refund, cancellation) и текстовые guidelines; режимы «сразу / позже / оставить агента» | Prospecting Agent готовит черновики — **человек проверяет и отправляет**; Customer Handoff Agent собирает досье | Деньги/отмены — всегда триггер handoff |
| **Intercom Fin** | Автоответы по справке + Procedures (сбор данных, проверки) | Escalation Guidance (до 100 правил), «Talk to human», API escalate с резюме в internal note; Fin отвечает, пока сотрудник не ответил клиенту | — | Принцип: «AI собирает информацию и делает стандартные проверки, **человек принимает решение**» |
| **Zoho Zia / SalesIQ** | Next Best Experience — подсказка следующего шага с заготовкой; Zobot | Handoff to Operator в середине диалога; Forward Message | Черновики писем, резюме | — |
| **Odoo 19 AI** | Агенты на документах + Live chat агент создаёт лиды; AI fields; Ask AI; транскрипция встреч | Через конструктор агента **[обзор]** | Черновик/улучшение письма, резюме chatter | — |

**Хорошая практика 2025–2026 (сводно из Intercom guide + консалтинг по pricing-guardrails):**

1. Handoff проектируется так же тщательно, как автоматизация: явные триггеры (просит человека; исключение из политики; юридический/финансовый спор; несколько неудачных попыток; негативная тональность; VIP-аккаунт).
2. Передача — с **структурированной запиской**: исходный запрос, собранные данные, результат проверок, причина эскалации, рекомендованный следующий шаг. Клиенту — «что дальше и когда».
3. «Explain vs commit»: ИИ объясняет публичные цены и стандартные условия, **скидки, сроки, нестандартные условия подтверждает человек**; дискаунт-полосы, уровни согласования, «never concede»-пункты, аудит-трейл.
4. Автономию повышают поэтапно: черновик с подтверждением → автоответ по прайсу → end-to-end только для типовых кейсов.
5. Метрики: полнота записки handoff (≥90%), доля уместных эскалаций (≥85%), время обработки после эскалации, CES. Не мерить успех одной «долей автоматизации».
6. Антипаттерны: тихая передача без сообщения клиенту; расплывчатые записки; менеджер игнорирует записку и спрашивает заново; нет канала «пожаловаться на плохую передачу».

Источники: https://helpdesk.bitrix24.ru/open/28426770/ · https://www.bitrix24.ru/features/copilot · https://helpdesk.bitrix24.ru/open/24481492/ · https://support.kommo.com/docs/kommo-ai-agent · https://knowledge.hubspot.com/customer-agent/set-up-and-customize-the-customer-agents-handoff-process · https://www.intercom.com/learning-center/ai-human-collaboration-procedures-handoffs · https://developers.intercom.com/docs/references/preview/rest-api/api.intercom.io/fin-agent/escalatefinconversation · https://www.zoho.com/crm/next-best-experience.html · https://www.odoo.com/odoo-19-release-notes · https://www.pedowitzgroup.com/can-ai-agents-negotiate-pricing-and-terms-governance-guide · https://www.limio.com/blogs/support-agents-vs-selling-agents · https://www.spotdev.co.uk/blog/hubspot-breeze-customer-agent

---

## 5. Таблица сопоставления

«?» в колонке RailTech заполняет архитектор.

| Строка | RailTech | Odoo 17/18 | ERPNext / Frappe CRM | Bitrix24 | Zoho One | HubSpot |
|---|---|---|---|---|---|---|
| Стадии лида | ? | Лид опционален; New→Qualified→Proposition→Won; Lost = причина | Lead→Open→Replied→Opportunity→Quotation→Converted/Lost/Do Not Contact (авто) | Не обработан→В работе→Обработан→Качественный/Некачественный [память]; режим «без лидов» | Lead → Convert (Account+Contact+Deal) | Lead object (Prospecting workspace) + Deal |
| Стадии сделки | ? | те же 4 + вероятность | Opportunity: Open/Quotation/Converted/Lost + Next Contact Date | Новая→Подготовка документов→Предварительный счёт→В работе→Финальный счёт→Успешна/Провалена [память] | Qualification→Needs Analysis→Value Proposition→Identify DM→Proposal/Quote→Negotiation→Closed Won/Lost | Appointment→Qualified→Presentation→DM bought-in→Contract sent→Closed Won/Lost |
| Объекты документов | ? (заявка, КП, договор, счёт, акт) | Quotation→Sales Order→Invoice→Delivery; Sign (договор) | Quotation→Sales Order→Delivery Note→Sales Invoice→Payment Entry; Supplier Quotation из Opportunity | КП→Счёт→(документ по шаблону: договор/акт)→Смарт-процесс | Quote→Sales Order→Invoice (CRM) / Estimate→Invoice (Books); Sign | Quote→(Signed)→Payment/Invoice; Buying room |
| Портал клиента | ? (web + Telegram Mini App) | Единый портал: все документы, подписать/оплатить/отклонить, тикеты, проекты | Orders/Invoices/Shipments, проекты; акцепта КП нет | Нет; публичные ссылки на счёт/оплату; ЛК — через Маркет | Books Client Portal (estimate accept, pay) + Desk portal | Support portal (только тикеты); quote/invoice — по ссылке |
| Подпись | ? | Встроенная на КП; Odoo Sign для договоров | Нет (сторонний модуль) | Нет встроенной (через Маркет/ЭДО) | Zoho Sign | Dropbox Sign внутри quote, лимит/мес |
| Оплата | ? | Online Payment как подтверждение КП; провайдеры | Payment Entry; портал показывает статус | Sales Center: ссылка в чат/СМС; триггер оплаты | Books: оплата счёта из портала | Payment link после подписи; Payments/Invoices |
| Мессенджеры | ? (Telegram-бот с ИИ) | Live chat, email; WhatsApp (Ent.); Telegram — модули | WhatsApp (Frappe CRM app); Telegram нет | Открытые линии: Telegram-бот нативно, чат в карточке | SalesIQ (web, WhatsApp, Telegram через каналы) | Conversations inbox (chat, email, Messenger); Telegram нет |
| ИИ | ? | Odoo 19: агенты, AI fields, Ask AI, livechat-агент | Нет нативно | AI-агент в открытых линиях + CoPilot (звонки, поля) | Zia NBX, Zia LLM, Zia Agents, Zobot | Breeze Customer/Prospecting/Handoff agents |
| Админка интеграций | ? | Settings per app + Technical; apps store | Integrations/Settings; Marketplace | Маркет + «Интеграции» + вебхуки/роботы | Marketplace + Flow | App Marketplace + Settings → Integrations |
| Первый запуск | ? | Onboarding banner (4 шага) в Invoicing/Sales; demo data | Setup wizard (компания, план счетов) | Мастер режима CRM, «С чего начать» | Zoho One setup, Quick Nav | Getting started checklist в приложении |
| Товары/услуги | ? | Product type Goods/Service/Combo; сроки доставки только для Goods (19) | Item: is_stock_item; услуги без склада | Товары + «услуги» как товары без склада | Items/Services | Products (line items), без склада |
| Локализация РУз | ? (ЭСФ, ru/uz) | Нет ЭСФ; языки ru/uz есть в переводах | Нет ЭСФ | Нет ЭСФ в коробке; русская локаль; партнёры в РУз | Нет | Нет |

---

## 6. Что заимствовать: 20 паттернов

| # | Паттерн | У кого подсмотрено | Куда в RailTech |
|---|---|---|---|
| 1 | **Один центральный объект «Сделка/Заявка» с лентой всех событий** (чат, письма, документы, смена стадии) и панелью действий сверху | Odoo chatter, Bitrix24 таймлайн, HubSpot | CRM-карточка лида/сделки; ERP-заявка — та же лента |
| 2 | **«Следующий шаг» обязателен**: закрыл действие → система просит назначить следующее; цветные часы на карточке (просрочено/сегодня/будущее) | Pipedrive, Odoo activities, OnePageCRM, ERPNext Next Contact Date | Канбан и карточка в CRM и ERP |
| 3 | **Rotting**: карточка краснеет без обновлений N дней на стадии (срок per-stage) | Pipedrive | Канбан сделок и заявок |
| 4 | **Lost — не колонка, а кнопка с причиной**; восстанавливаемо; отчёт по причинам | Odoo, ERPNext (lost reasons/competitors) | Воронка CRM |
| 5 | **Обязательные поля и чек-лист при переходе на стадию**, запрет пропуска стадий и движения назад без права | Zoho Blueprint, Bitrix24, HubSpot pipeline rules | Стадии заявки/КП/договора в ERP |
| 6 | **Автоматизация «при входе в стадию → действие»** как список в настройке стадии (задача, уведомление, сообщение клиенту) | HubSpot pipeline automations, Kommo Digital Pipeline, Bitrix24 роботы | ERP стадии + CRM воронка |
| 7 | **Smart buttons / цепочка документов «на основании»**: на заявке видно КП N / Договор / Счета N / Акт; создание следующего документа одной кнопкой | Odoo, 1С УНФ, ERPNext Connections | ERP формы заявки, КП, договора |
| 8 | **Словарь документов РУз-рынка**: Заявка → Коммерческое предложение → Договор → Счёт на оплату → Акт/ТТН → ЭСФ; статусы по 1С/Odoo: Черновик → Отправлено → Принято/Подписано → Ожидает оплаты → Оплачено → Исполняется → Выполнено | 1С, Odoo, PandaDoc | Единый глоссарий во всех трёх приложениях и в Mini App |
| 9 | **Публичная ссылка на КП с «Принять и подписать», «Отклонить (причина)», «Комментарий», PDF**; клиент отмечает опциональные позиции | Odoo Sign & Pay (+Odoo 19 optional lines), HubSpot quotes | Cabinet web + Mini App; ERP генерирует ссылку |
| 10 | **Оплата кнопкой на странице документа** (Payme/Click/Uzum) и триггер «оплата получена → стадия» | HubSpot payment link, Bitrix24 Sales Center, PandaDoc | Cabinet + ERP финансы |
| 11 | **Клиенту — только его документы и их статусы**; дашборд со счётчиками «КП 2 · Заказы 3 · Счета 1 к оплате · Обращения 0» | Odoo portal, ERPNext portal, Zoho Books | Cabinet главная / Mini App главная |
| 12 | **Чат из Telegram — в карточке сделки**; ответ из карточки уходит в Telegram; очередь «неразобранное/требует ответа» с кнопкой «взять» | Bitrix24 Открытые линии, Kommo «Неразобранное» | CRM inbox; бот пишет в ту же ленту |
| 13 | **Правила бота как конструктор WHEN → DO**: тональность/молчание/квалификация → ответить / запросить данные / передать менеджеру; лимит сообщений → автопередача | Kommo AI agent, HubSpot handoff triggers | Настройки бота CRM (settings, не код) |
| 14 | **Handoff с запиской**: запрос, собранные данные, причина, рекомендованный шаг; клиенту — «передал менеджеру, ответим до …»; бот молчит, пока менеджер в диалоге | Intercom Fin, Bitrix24 AI-агент, HubSpot | CRM бот ↔ менеджер |
| 15 | **«Explain vs commit»**: бот называет только публичные цены/условия; скидки, сроки, договорённости — менеджер; аудит-трейл | Pedowitz/Limio guardrails, HubSpot Prospecting (человек отправляет) | Промпты и правила бота; ERP согласование КП |
| 16 | **Ассистент менеджера по кнопке в ленте**: резюме диалога/звонка, заполнить поля карточки из чата, черновик ответа | Bitrix24 CoPilot, Kommo summary/suggested replies, Zoho Zia NBX | CRM карточка (кнопки в ленте), не отдельный экран |
| 17 | **Баннер-чек-лист первого запуска в самом модуле**: реквизиты компании → шаблон КП/счёта → способ оплаты → Telegram-бот → пробное КП самому себе | Odoo onboarding banner, HubSpot Getting started | ERP главная + CRM главная для админа |
| 18 | **Пустые состояния с объяснением и кнопкой «создать первый…»**, пример-данные для демо | Odoo sample data, гайды empty state | Все списки CRM/ERP/Cabinet |
| 19 | **Единая шапка: переключатель приложений + глобальный поиск + колокольчик активностей со счётчиком «просрочено/сегодня»** | Odoo home menu + clock icon, Zoho One Quick Nav + Action Panel | Общий layout CRM/ERP (ui-tokens) |
| 20 | **Роли по принципу «свои документы / все документы / админ» + Sales Team с алиасом и правилами распределения** | Odoo sales teams, ERPNext assignment rules | RBAC CRM/ERP; минимум ролей на старте |

Дополнительно (архитектурно): Supplier Quotation прямо из возможности/заявки (ERPNext) — для «под заказ» это ключевой шаг снабжения, который стоит показать как кнопку на заявке, а не отдельный модуль.

---

## 7. Чего не удалось подтвердить (проверить вручную)

- Точные названия стадий по умолчанию Bitrix24 и amoCRM — только частично; смотреть в живом портале.
- Официальная страница Odoo 18 «get_signature_to_validate» не отдалась (пустой ответ); описание — по книге Cybrosys и Odoo Online docs.
- Конкретный модуль ЭСФ в «1С для Узбекистана» и API Didox — в открытых источниках не найдены; у Faktura.uz заявлены модули для 1С (2019).
- Smartup: CRM/портал/ЭСФ на сайте не упомянуты; Billz: API/Telegram-документация не найдена.
- «Jet ERP» как продукт не существует в выдаче; Iman — финтех.
- Доля Telegram в B2B-коммуникации РУз — только косвенные данные (сайт-интеграции, слова Дурова, кейс Uzum).
