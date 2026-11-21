# Проверка API-утверждений исследования от 2026-11-22

Каждое утверждение проверено на странице поставщика или в первоисточнике: WebFetch, curl, PyPI и npm JSON, `git show origin/main`. Вердикты: **подтверждено**, **неверно**, **не проверено**. Не проверено значит, что страница недоступна или факта на ней нет.

## 1. Неверно или устарело — исправить в отчёте

| Кандидат | Утверждение | Вердикт | Доказательство | Что поменять |
|---|---|---|---|---|
| Telegram Business (comms, п. 2) | Каждому подключаемому менеджеру нужен Telegram Premium | **неверно (устарело)** | Официально: «Connecting a business bot does not require Telegram Premium» — https://core.telegram.org/api/bots/connected-business-bots. Дата 08.05.2026 есть только у стороннего источника: https://sendpulse.com/en/knowledge-base/chatbot/telegram/telegram-business | Убрать Premium из затрат и рисков. Права уточнить. `can_read_messages` даёт только право отмечать сообщения прочитанными. `can_reply` — ответ в чатах, где за последние 24 ч были входящие (подтверждено, https://core.telegram.org/bots/api). Какие чаты видит бот, выбирает владелец аккаунта (https://telegram.org/blog/telegram-business) |
| Didox API (gov-uz A1, money п. 6) | Документация за логином, страница отдаёт только заголовок; тестовый контур testapi2 | **неверно (частично)** | Раздел «Логин» открыт без входа: https://api-docs.didox.uz/ru/home. Там: партнёрский токен выдаёт аккаунт-менеджер (https://t.me/Didox_account, +998 50 122 05 18). Заголовок `Partner-Authorization`. Тест — https://testapi3.didox.uz/, прод — https://api-partners.didox.uz/. Пользовательский токен действует 360 мин. Три способа входа: E-IMZO `POST /v1/auth/{taxId}/token`, пароль, вход в компанию. Канал изменений — https://t.me/didoxapiupdates. Раздел E-IMZO тоже открыт: https://api-docs.didox.uz/ru/integrators-eimzo. Угаданные адреса `/ru/documents` и `/ru/webhooks` дают 403 «Unauthorized» | Написать: «Документация открыта частично (вход, E-IMZO); партнёрский токен — у аккаунт-менеджера; тест testapi3». Есть ли вебхуки — не проверено |
| SWIFT MT (money §1 п. 4, п. 3) | Сообщения MT (FIN) не поддерживаются с 24.08.2026, MT940 устарел | **неверно (упрощено)** | С 22.11.2025 отклоняются платёжные инструкции MT101/102/103 и др. Отчётные сообщения (MT940/950) не сняты, срок не объявлен. MT в SCORE (Swift для корпоративных клиентов) остаются «no end date defined» — https://www.bny.com/content/dam/bnymellon/documents/pdf/co-existence-end-date-sheet-for-microsite.pdf. Дата 24.08.2026 — формулировка одного банка: https://aab.uz/en/press_center/news/important-swift-s-transition-to-iso-20022-what-changes-for-you/ | Снять риск «MT устарел» с разбора MT940. Оставить «позже, если банк отдаёт файл» |
| Перечень КМ № 415 в отчётах money §5 и logistics §0 | США в перечне без оговорок («в том числе Россия, США»; «в нём есть США») | **неверно (неполно)** | США в перечне со звёздочкой: только компании в EU-US Data Privacy Framework. Всего 49 позиций, Россия есть, Гонконг есть. Нет материкового Китая, Казахстана, ОАЭ, Турции. Действует с 03.08.2026 — https://lex.uz/ru/docs/8369688 | Добавить оговорку про DPF в money и logistics. Отчёты gov-uz и workspace сформулированы верно |
| Госзакупки УТЙ (gov-uz §0 п. 1) | 1 069 договоров на 1,66 трлн сум — рынок, на который можно выйти продажей | **цифры верны, вывод завышен** | В отчёте 1,12 трлн из 1,66 трлн (67 %) приходится на «Капитал қурилиш дирекцияси» (капстроительство). Из 1,1 трлн по 34 запросам предложений на неё же приходится 1,095 трлн (19 запросов). Электронный магазин — 550 договоров, всего 39,2 млрд сум. Ещё 58 договоров с единственным поставщиком и 95 прямых. Источник: https://railway.uz/upload/iblock/7e2/mt2gmkxlksbgjtn6v3sujkzzweg7laiw.pdf | Канал оставить, но рынок запчастей оценивать по электронному магазину и кооперационному порталу (177 договоров, 439 млрд), а не по 1,66 трлн |
| Телемост API (comms п. 18 и workspace) | Comms: API только для 360 для бизнеса, методы не прочитаны. Workspace: встречу может создать личный Яндекс ID | **противоречие в самих документах Яндекса** | Главная: «доступна только для пользователей Яндекс 360 для бизнеса с аккаунтами на домене организации» — https://yandex.ru/dev/telemost/doc/ru/. Метод `POST https://cloud-api.yandex.net/v1/telemost-api/conferences`. Там же: личный ID создаёт публичную встречу, 402 — трансляции не на тарифе, облачная запись — только у организаций с этим правом — https://yandex.ru/dev/telemost/doc/ru/conference-create | Метод создания встречи подтверждён. Делать на аккаунтах домена организации. В comms убрать «методы не прочитаны» |
| SWIFT gpi Tracker BRB (money п. 22) | В выдаче была цена 70 000 сум в месяц | **неверно** | На странице: «SWIFT GPI Tracker service price: free» — https://brb.uz/en/swift-gpi-tracker. У AAB «free of charge», но висит «The function is currently unavailable» — https://www.aab.uz/en/press_center/news/swift-gpi-tracker-/ | Цену 70 000 убрать. Для AAB пометить «временно недоступно» |
| onec-odata для ERP (accounting п. 1a) | Python-клиент OData под MIT подходит | **неверно для нашего стека** | onec-odata 0.1.0 требует Python ≥ 3.13 (https://pypi.org/pypi/onec-odata/json). ERP собирается на `python:3.12-slim` (`apps/erp/backend/Dockerfile:8`) | Брать python-1c-odata 0.6.0 (MIT, Python ≥ 3.10) или `httpx` |

## 2. Не проверено — не утверждать как факт

| Кандидат | Утверждение | Вердикт | Доказательство | Что поменять |
|---|---|---|---|---|
| Сервисное приложение Яндекс 360 | Optimal и Extended в Узбекистане — это Asosiy и Ilg'or; права `mail:imap_full`, `mail:smtp`, `calendar:*` | **не проверено** | Справка: только Optimal и Extended, токен на 1 ч, token-exchange по uid или e-mail, не больше 20 приложений, п. 3.6 оферты (уведомить сотрудников). В примере есть только `cloud_api:disk.*` — https://yandex.com/support/yandex-360/business/admin/en/security-service-applications. На https://360.yandex.uz/business/ тариф называется «Asosiy｜Foydali» (90 900 сум) и даёт SSO и архив, но сервисные приложения там не упомянуты | Спросить поддержку 360, есть ли сервисные приложения на Asosiy. Имена прав взять из справочника API, а не из этого отчёта |
| Telegram Gateway | Как пополнить баланс из Узбекистана | **не проверено** | На странице только «advance-paid credits», ни вывести, ни перевести их нельзя — https://core.telegram.org/gateway | Проверить по условиям Gateway (ToS §3.1) до запуска |
| DHL Unified Tracking | Не чаще 1 вызова в 5 с | **не проверено** | 250 вызовов в сутки — это «testing quota», лимит повышается по заявке — https://support-developer.dhl.com/support/solutions/articles/47001249492-is-the-dhl-shipment-tracking-unified-api-free-of-charge-. Сайт developer.dhl.com отклонил запрос | Писать «тестовая квота 250 в сутки, повышается по заявке» |
| TrackingMore | Basic $11 в месяц, Pro $74 в месяц (G2) | **не проверено** | На странице тарифов вместо цен заглушки $0. Подтверждено: API и вебхуки только с тарифа Basic; на Free 1 723 перевозчика — https://www.trackingmore.com/pricing. «Почта Узбекистана» в покрытии есть — https://www.trackingmore.com/uzbekistan-post-tracking-api.html. Эндпоинт v4 `trackings/create` есть по SDK — https://www.npmjs.com/package/trackingmore-sdk-nodejs | Цены запросить у продавца |
| Shipsgo | Годовая плата за API, кредиты действуют год | **не проверено** | Статья справки отдаёт 404: https://help.shipsgo.com/article/55-api-usage-pricing. Подтверждено: REST и вебхуки; поиск по контейнеру, коносаменту или букингу; 100 запросов в минуту; 1 кредит на отправку; больше 160 линий; 3 бесплатных кредита — https://shipsgo.com/ocean/container-tracking-api, https://shipsgo.com/faq | Убрать годовую плату или пометить [?] |
| onlinePBX | Юрлицо «Chukreev PBX»; где хранятся записи | **не проверено** | На https://pbx.uz/ ни юрлица, ни места хранения нет | Оставить условие «узнать место хранения записей» |
| UzQR | Принимаются только Uzcard и Humo | **не проверено по указанному источнику** | Статья пишет только о доле НПС в 0,15 %. Подтверждено: обязателен с 01.07 для юрлиц в торговле и услугах; до 0,65 %, у банков 0,25–0,65 %; подключение бесплатное; об опте ни слова — https://kun.uz/ru/news/2026/07/03/v-uzbekistane-zapushchen-uzqr-otvety-na-glavnyye-voprosy-ce5d99 | Для карт дать другой источник или пометить [?] |
| E-IMZO | Нет Safari | **не проверено** | В https://github.com/qo0p/e-imzo-doc этого нет; мобильное приложение там только по ссылке на Google Play. Репозиторий личный (qo0p), не официальный | Убрать Safari или найти источник. Подтверждено: E-IMZO-SERVER по лицензионному договору (правообладатель НИЦ НТ); VPN `vpn.e-imzo.uz:3443` доступен только из Узбекистана; для мобильной подписи нужны SiteID и постоянный UPLOAD URL |
| ТЭДО с Россией | Для нас входящие бесплатны; Контур | **не проверено** | Saby: единый роуминговый оператор — «Янги Технологиялар», «от него документы доставляются всем коммерческим провайдерам страны»; ДТС — «Газинформсервис» — https://saby.ru/edo/tedo/legal. Comnews: пилот, товаросопроводительные документы, ДТС в Узбекистане — UNICON.UZ, налоговые обеих стран их принимают — https://www.comnews.ru/content/240932/2025-08-28/2025-w35/1018/rossiya-i-uzbekistan-realizovali-transgranichnyy-edo-elektronnoy-podpisyu | Роуминг подтверждён. Бесплатность входящих проверить у Didox |
| 1С OData (accounting п. 1a) | Документация, гл. 18.2.1 | **существует, текст закрыт** | Разделы «Стандартный интерфейс OData» есть в документации платформы 8.3.7–8.3.27 на its.1c.ru; текст требует подписки ИТС | Ссылаться на текущую версию платформы (8.3.27, прил. 12). Состав объектов узнавать у 1С-партнёра |

## 3. Подтверждено — оставить как есть, с уточнениями

- **Telegram Gateway.** Методы `sendVerificationMessage`, `checkSendAbility`, `checkVerificationStatus`, `revokeVerificationMessage`. Подпись HMAC-SHA-256 в `X-Request-Signature`, ключ — SHA-256 от токена; время — в `X-Request-Timestamp`. До 10 повторов. $0,01 за код, недоставленные коды возвращаются. Источники: https://core.telegram.org/gateway/api, https://core.telegram.org/gateway.
  - Уточнение по репозиторию: Кабинет уже шлёт код входа письмом и привязывает Telegram через бота (`apps/cabinet/src/api/portal.d.ts:38,285`). Gateway нужен только для номеров, не привязанных к боту.
- **MCP-серверы Яндекс 360.** Подтверждено:
  - у организаций включены по умолчанию;
  - отключаются только через форму поддержки;
  - статус preview;
  - есть у Почты, Диска, Календаря, Телемоста и управления организацией.

  Источник: https://yandex.ru/dev/yandex-360/mcp/
- **Публичные ресурсы Яндекс Диска.** `GET /v1/disk/public/resources` и `/download` по `public_key`, OAuth не нужен — https://yandex.ru/dev/disk-api/doc/ru/reference/public
- **Eskiz.**
  - Подтверждено: 95 сум за SMS; 175 сум за рекламные (Ucell, Uzmobile, Mobiuz); абонплаты нет. Договор только с юрлицами-резидентами; первый взнос 300 000 сум; альфа-имя 300 000 сум — https://eskiz.uz/sms, https://eskiz.uz/knowledges/sms-service/frequently-asked-questions.
  - Уточнить: на странице цен регистрация имени занимает 1–2 месяца, а не 1 месяц.
  - API: `notify.eskiz.uz/api` — вход, `message/sms/send`, `send-batch`, `callback_url`, шаблоны `/api/user/template` (тексты проходят модерацию). Коллекция: https://documenter.gw.postman.com/api/collections/663428/RzfmES4z?segregateAuth=true&versionTag=latest
- **onlinePBX API.** `https://api2.onlinepbx.ru/<домен>/mongo_history/search.json`, запись по `download=1`, не больше недели за запрос. Есть WebSocket API 3.0.0 и вебхуки — https://kb.onlinepbx.ru/api-onlinepbx. Цены на pbx.uz: от 294 841,8 сум в месяц, номера от 223,4 сум в минуту, записи хранятся 1 год — https://pbx.uz/
- **BTS.** Документация открыта, на узбекском — https://docs.bts.uz/page/auth-login. Подтверждено:
  - токен доступа живёт 1 день, токен обновления — 30 дней;
  - заказ, калькулятор, наклейка, трекинг, международные заказы;
  - настройка вебхука;
  - фулфилмент (WMS).
- **Click.**
  - Click Business — счёт по номеру телефона (SMS и уведомление). Подключаются самозанятые, ИП, ООО, АО. Тариф «товары»: 2 % Uzcard/Humo, 2,5 % внутренняя Visa — https://business.click.uz/en.
  - Документация: Shop API, Merchant API с фискализацией, платёжная ссылка, оплата через Telegram — https://docs.click.uz/en/.
- **Uzum Bank.** Есть Checkout, Merchant API, BaaS (Payment Hub, JSON-RPC), Dynamic QR, Fiscalization. Доступ через «Become a partner»; условия договора на странице не указаны — https://developer.uzumbank.uz/en/
- **Aisha.** Синхронно `back.aisha.group/api/v1/stt/post/`, асинхронно `/api/v2/stt/post/`, заголовок `X-Api-Key`. 425 сум за минуту; установка у себя — на тарифе Enterprise. Источники: https://aisha.group/llms-api.txt, https://aisha.group/en/pricing. Где обрабатываются данные — не указано.
- **DiBank.** 24 банка и Uzcard. Условие: 1С:Бухгалтерия для Узбекистана с действующим ИТС или тариф Didox Premium. Для других систем — «обратиться в OOO Didox Tech»; документации API нет — https://dibank.uz/
- **NBU iBank.** Цитата: «API integration with 1C: Accounting and SAP»; выгрузка выписок в ISO 20022, импорт платёжек. Подключение — счёт, ЭЦП, публичная оферта — https://nbu.uz/en/corporate-clients/internet-banking
- **Ipoteka.** OpenAPI связывает ERP с банком по заявке и договору. 1С:DiBank. MT940 через SWIFT. Платы за подключение и абонплаты нет — https://www.ipotekabank.uz/en/corporate/internet-banking/
- **1CClientBankExchange.** Подтверждено: версия 1.03; кодировка DOS или Windows; секции `СекцияРасчСчет` и `СекцияДокумент`; поля `ДатаПоступило`, `ПлательщикИНН`, `НазначениеПлатежа1..6`. Спецификация открыта: https://v8.1c.ru/tekhnologii/obmen-dannymi-i-integratsiya/standarty-i-formaty/standart-obmena-s-sistemami-klient-banka/formaty-obmena/
- **Библиотеки** (PyPI и npm на 22.11.2026). Версии и лицензии совпадают с отчётами. `camt053` 0.0.26 вышла 2026-11-09.

  | Библиотека | Версия | Дата | Лицензия |
  |---|---|---|---|
  | client-bank-1c | 0.3 | 2023-05-31 | MIT |
  | mt-940 | 5.1.3 | 2026-10-28 | BSD-3 |
  | pycamt | 1.1.1 | — | MIT |
  | camt053 | 0.0.26 | 2026-11-09 | Apache-2.0 OR MIT |
  | bankstatementparser | 0.0.34 | — | — |
  | python-1c-odata | 0.6.0 | — | MIT |
  | xsdata | 26.10 | — | MIT |
  | gspread | 6.2.1 | — | — |
  | Authlib | 1.9.10 | — | BSD-3 |
  | caldav | 3.7.0 | — | GPL-3.0-or-later OR Apache-2.0 |
  | icalendar | 7.3.2 | — | BSD-2 |
  | bwip-js | 4.11.4 | — | MIT |
  | barcode-detector | 3.2.4 (на zxing-wasm 3.1.7) | — | MIT |

- **Excel Power Query (Web).** Проверка Anonymous, Windows, Basic, Web API, Organizational. Форматы CSV, JSON, Excel, XML, PDF. Источник: https://learn.microsoft.com/en-us/power-query/connectors/web/web.
  - Уточнение: при проверке «Web API» ключ уходит параметром в строке URL (`ApiKeyName`, пример `?api_key=******`) — https://learn.microsoft.com/en-us/powerquery-m/web-contents.
  - Значит, нужно маскировать этот параметр в журналах Caddy и приложения или брать Basic.
- **Google Sheets API.** 300 чтений в минуту на проект, 60 в минуту на пользователя; обычное использование бесплатно. «Exceeding the quota … is planned to incur charges … later in 2026» — https://developers.google.com/workspace/sheets/api/limits
- **Закон о ПДн (ЗРУ-547 в редакции ЗРУ-1125).**
  - Ст. 27¹: хранить в Узбекистане обязательно только биометрические и генетические данные и данные абонентов операторов связи.
  - Ст. 20: в Госреестре регистрируются только такие базы.
  - Источник: https://lex.uz/ru/docs/4396428. Русский текст — неофициальный перевод.
- **Передача данных в США.** Google LLC участвует в DPF — https://policies.google.com/privacy/frameworks. Значит, Google Drive подпадает под перечень № 415.
  - Anthropic ссылается на решения об адекватности, стандартные договорные условия (SCC) и исключения (derogations), а не на DPF — https://www.anthropic.com/legal/privacy.
  - Маскирование ПДн перед моделью оставить.
- **Список злоупотребивших правом уменьшения НДС.** Страница «…QQS summalarni kamaytirish tarzidagi huquqni suiiste'mol qilgan korxonalar ro'yxati». Выгрузка в Excel и PDF, поиск с капчей. API и даты обновления нет — https://old.soliq.uz/activities/tax-risk-analysis
- **xarid.uzex.uz.** Регистрация обязательна, бесплатна и бессрочна. Нужна узбекская ЭЦП E-IMZO, российская не подходит. Saby Тендеры показывают закупки Узбекистана, есть уведомления и сохранённые поиски — https://saby.ru/articles/tenders/zakupki_uzbekistana (04.04.2026)
- **WhatsApp Cloud API.** Хранения на территории Узбекистана нет: `data_localization_region` не включает UZ — https://developers.facebook.com/docs/whatsapp/cloud-api/reference/registration
- **Яндекс Доставка.** Хост `b2b.taxi.yandex.net`; `check-price`, `claims/create`, `claims/accept`; Bearer-токен из личного кабинета, логин выдаёт менеджер. Узбекистан в документации не назван — https://yandex.ru/dev/logistics/api/about/intro.html
- **Яндекс ID без OIDC.**
  - `oauth.yandex.ru/.well-known/openid-configuration` отдаёт HTML-страницу ошибки.
  - `login.yandex.ru/.well-known/openid-configuration` отдаёт 404.
  - У Google discovery возвращает JSON 200.

  Проверено curl 22.11.2026.
- **Недоступные страницы — подтверждено.**
  - У developer.help.paycom.uz (Payme) сертификат истёк 02.07.2026.
  - api.faktura.uz не принимает соединение.
  - Kapital API отдаёт 403.
  - Страница 1С у Anorbank отдаёт 500.
- **Факты из репозитория (origin/main) — подтверждено.**
  - `LeadSource` закрыт: telegram, web, phone, email, referral; значения «тендер» нет.
  - `uniq_payment_invoice_reference` есть (`apps/erp/backend/finance/models/billing.py:256`), с условием `reference != ''`.
  - `valid_to` в `apps/eds/app/models/signing.py:78` есть.
  - `ClientBankExchange`, `MT940` и `camt` в `apps/` не встречаются.
  - Все пути из отчётов существуют: `gdrive.py`, `imap.py`, `call_note.py`, `fx.py`, `price_list.py`, `helpArticles.ts:33`.

## 4. Что поменять в итоговых рекомендациях

1. **Telegram Business.** Premium не нужен, затрат нет. Пункт поднимается по соотношению польза и стоимость; остаются согласие сотрудника и правило журнала.
2. **Didox.** Документацию можно читать без входа. Шаг «запросить токен» конкретный: партнёрский токен у аккаунт-менеджера (https://t.me/Didox_account), тестовый контур testapi3.
3. **MT940.** Риск «устарел» убрать.
4. **Госзакупки.** Оценку рынка УТЙ уменьшить: 67 % суммы — капитальное строительство.
5. **США в перечне № 415.** Везде добавить оговорку про DPF.
6. **ERP и OData.** Не брать onec-odata (нужен Python 3.13).
7. **Выгрузки для Power Query.** Маскировать в журналах ключ из строки URL.
