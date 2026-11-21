# Рабочие пакеты, календарь и вход сотрудников: Яндекс 360 и альтернативы

Документы проекта сверены по origin/main @ 9801bfe57. Внешние источники проверены 2026-11-22. Лимит веб-поиска закончился в конце работы, поэтому в конце отчёта есть раздел «Не проверено».

## Главное

1. **В API Яндекс 360 есть один механизм, который открывает доступ к Календарю, Диску, Почте, Телемосту, Трекеру, Формам и Вики.** Это «сервисное приложение» с обменом токена (token exchange) по e-mail сотрудника.
   - Токен действует 1 час.
   - Пароли приложений у каждого сотрудника становятся не нужны.
   - Приложение доступно только на тарифах Optimal и Extended. В Узбекистане им, по набору функций, соответствуют Asosiy и Ilg'or.
   - Администратор обязан уведомить сотрудников, а при необходимости получить их письменное согласие (п. 3.6 оферты).
   - Источники: https://yandex.com/support/yandex-360/business/admin/en/security-service-applications , https://yandex.ru/dev/yandex-360/api360/ru/ref/ServiceApplicationsService/ServiceApplicationsService_Create.md
   - На этом механизме стоит строить все коннекторы Яндекс 360, а не на паролях приложений, как сейчас сделаны Яндекс Диск и SMTP.
2. **MCP-серверы Яндекс 360 для Почты, Диска, Календаря, Телемоста и каталога у организаций включены по умолчанию.** Любой сотрудник может подключить к корпоративной почте и диску внешний ИИ-инструмент. Отключить их для всех можно только через форму поддержки. Серверы в статусе preview.
   - Источники: https://yandex.ru/dev/yandex-360/mcp/ , https://yandex.ru/dev/yandex-360/mcp/ru/security.md
   - Это решение владельца без кода, и пользы от него больше, чем от любого коннектора.
3. **Хранение персональных данных.** Яндекс 360 хранит данные в дата-центрах в России (https://yandex.ru/support/yandex-360/business/admin/ru/security/personal-data).
   - По ст. 27¹ в редакции ЗРУ-1125 от 26.03.2026 (https://lex.uz/docs/8099215) в Узбекистане обязательно хранятся только биометрические и генетические данные и данные абонентов операторов связи.
   - Остальные персональные данные можно хранить за рубежом, если страна есть в перечне КМ № 415 от 29.07.2026 (https://lex.uz/ru/docs/8369688). Россия в перечне есть; США — только для компаний в EU-US DPF. Так записано в docs/research/2026-11-02-lifecycle/legal-lex.md §6.
   - Значит, Яндекс 360, Google и Microsoft закону не противоречат. Компания при этом остаётся оператором данных.
   - Формулировка из задачи «персональные данные граждан РУз должны храниться в РУз» устарела с 27.03.2026. Наши базы и так стоят в Ташкенте (PRO DATA).
4. **Яндекс 360 официально продаётся в Узбекистане с 23.10.2025** (https://www.uzdaily.uz/ru/yandex-uzbekistan-predstavil-virtualnyi-ofis-yandex-360-s-iskusstvennym-intellektom/).
   - Цены на https://360.yandex.uz/business/ за сотрудника в месяц: Minimal 49 900 сум, Asosiy 90 900 сум (есть SSO и защищённый архив), Ilg'or 274 900 сум.
   - Оплата в сумах — картой или по счёту.
   - Санкционных препятствий нет. Менять пакет на Google Workspace или Microsoft 365 смысла нет.
5. **Вход сотрудников.** Свой вход (CRM как поставщик идентичности + TOTP) оставляем.
   - Яндекс ID не публикует OpenID Connect discovery: на https://oauth.yandex.ru/.well-known/openid-configuration отдаётся HTML-страница ошибки (проверено curl 2026-11-22). У Google и Microsoft discovery отвечает 200.
   - «Войти через Яндекс» — это обычный OAuth 2.0 и запрос к https://login.yandex.ru/info (https://yandex.ru/dev/id/doc/ru/user-information).
   - Вердикт «позже». Делать сразу общим OAuth2/OIDC-клиентом на Authlib (BSD-3), чтобы Google и Microsoft добавлялись настройкой, а не кодом.

## Таблица кандидатов

Усилие: S — до 3 дней, M — 1–2 недели, L — больше 2 недель.

### A. Яндекс 360

| Кандидат | Процесс | Польза | API / стандарт и документация | Доступность в РУз | Стоимость | Усилие | Система | Риски | Вердикт |
|---|---|---|---|---|---|---|---|---|---|
| Почта SMTP/IMAP, DNS, Диск по WebDAV для бэкапов | почта, лиды, бэкапы | — | см. базовую линию | работает | в тарифе | — | CRM | пароль приложения привязан к человеку: уволился — почта и копии ломаются | **уже есть/решено**. Добавить: перевести на OAuth через сервисное приложение (права `mail:imap_full`, `mail:smtp`, `cloud_api:disk.*`) — https://yandex.com/support/yandex-360/business/admin/en/security-service-applications |
| **Сервисное приложение 360** (token exchange: `grant_type` token-exchange, `subject_token` = e-mail или uid) | основа всех коннекторов 360 | администратор подключает один раз, сотрудникам ничего настраивать не надо | https://yandex.com/support/yandex-360/business/admin/en/security-service-applications ; методы `/security/v1/org/{orgId}/service_applications` — https://yandex.ru/dev/yandex-360/api360/ru/ref/ServiceApplicationsService/ServiceApplicationsService_Create.md | да | только Optimal/Extended (Asosiy/Ilg'or) — https://yandex.com/support/yandex-360/business/purchase/plans/payment-plans | S | CRM (реестр `external_registry`, Настройки · Подключения) | токен владельца и client_secret дают доступ ко всем ящикам и календарям; не больше 20 приложений; нужно уведомить сотрудников | **подключить готовое** — первым шагом перед календарём |
| **Решение по MCP-серверам 360** | безопасность данных | закрыть канал утечки почты и диска во внешние ИИ | https://yandex.ru/dev/yandex-360/mcp/ ; правила — https://yandex.ru/dev/yandex-360/mcp/ru/security.md | да | 0 | 0 кода (действие владельца) | — | сейчас включены у всех; preview, формат может меняться без обратной совместимости | **подключить готовое**: владелец решает «отключить» (форма https://yandex.ru/dev/yandex-360/mcp/ru/support.md) или «разрешить по правилам». В продукт не встраивать: противоречит DECISIONS 2026-11-11 п.1 (в модель — только текст с маскированием ПДн) |
| Каталог API 360: сотрудники, отделы, группы; создание сотрудника; выход из всех сессий | приём и увольнение | при увольнении в Платформе сотрудник одной кнопкой блокируется и разлогинивается в 360, почта не остаётся открытой; один раз импортировать сотрудников и отделы | https://yandex.ru/dev/yandex-360/api360/ru/directory/index.md ; `UserService_Create` — https://yandex.ru/dev/yandex-360/api360/ru/ref/UserService/UserService_Create.md ; `DomainSessionsService_UserLogout` — https://yandex.ru/dev/yandex-360/api360/ru/ref/DomainSessionsService/DomainSessionsService_UserLogout.md ; хост `cloud-api.yandex.net`, роль «User Manager» — https://yandex.ru/dev/yandex-360/api360/ru/access.md | да | в тарифе | S (импорт и выход из сессий), M (полная синхронизация) | CRM (сотрудники и вход) | отдельного метода «заблокировать» в индексе нет, только `UserService_Update` (https://yandex.ru/dev/yandex-360/api360/ru/llms.txt); подписки на события каталога в документации не найдено — только опрос | **позже** (после календаря). Импорт и выход из сессий — S |
| Календарь по CalDAV, двусторонний (`caldav.yandex.ru`) | встречи, сроки задач | встреча из CRM появляется в календаре сотрудника, ответ «приду» возвращается | CalDAV — https://yandex.ru/support/calendar/sync/sync-desktop.html ; права `calendar:*` у сервисного приложения, в том числе создание события со ссылкой Телемоста — https://yandex.com/support/yandex-360/business/admin/en/security-service-applications ; библиотеки `caldav` 3.7.0 (GPL-3.0-or-later OR Apache-2.0 — брать по Apache) https://pypi.org/project/caldav/ , `icalendar` 7.3.2 (BSD-2) https://pypi.org/project/icalendar/ | да | в тарифе | M–L | CRM | удаление календаря через API безвозвратно (тот же источник); личные события не храним (DECISIONS 2026-11-03) | **уже есть/решено** (этап 3, после пилота). Добавить: доступ через сервисное приложение, а не через пароли приложений |
| Личная iCal-подписка (RFC 5545) | «Мои задачи», сроки | срок задачи виден в любом календаре (Яндекс, Google, Outlook, Apple) без API | подписка по .ics в Яндекс Календаре — https://yandex.com/support/yandex-360/business/calendar/en/create , https://yandex.com/support/calendar/common/create.html | да | 0 | S | Платформа BFF (собирает задачи всех доменов) | Яндекс обновляет подписку раз в несколько часов, до 1–2 дней (те же страницы) — годится для сроков, не годится для встреч «через 30 минут»; ссылка с токеном = секрет | **уже есть/решено** (этап 1); на `icalendar` (BSD) |
| Приглашение .ics в письме (iTIP, RFC 5546) | встреча с клиентом или поставщиком | приглашение приходит в календарь контрагента в любой системе, ничего подключать не надо | стандарт; отправка через существующий SMTP CRM | да | 0 | S | CRM | без подтверждения обратно (только письмом) | **уже есть/решено** (этап 2 — «.ics и „Назначить встречу“»); делать раньше CalDAV |
| **API Телемоста** (`POST cloud-api.yandex.net/v1/telemost-api/conferences`) | «Встреча» в CRM, звонок с клиентом | ссылка на видеовстречу одной кнопкой; есть зал ожидания, соорганизаторы, автосаммари, облачная запись (по праву организации) | https://yandex.ru/dev/telemost/doc/ru/conference-create ; OpenAPI — https://yastatic.net/s3/doc-binary/docs/dev/telemost/api-specification.yaml | да; публичную встречу может создать и личный Яндекс ID (тот же источник) | в тарифе; трансляции не на всех тарифах (ответ 402) | S | CRM | на рабочем экране — «Видеовстреча», без бренда (правило владельца); запись и саммари — данные клиента в России, это допустимо (п. 3) | **подключить готовое** вместе с этапом 2 календаря |
| Бот Яндекс Мессенджера (Bot API: сообщения, файлы, чаты, опросы, вебхук) | уведомления сотрудникам, копии из Чатов | второй канал уведомлений, если команда живёт в Мессенджере | https://yandex.ru/dev/messenger/doc/ru/llms.txt ; вебхук — https://yandex.ru/dev/messenger/doc/ru/api-requests/update-webhook.md | да; бот доступен на большинстве тарифов 360 для бизнеса — по статье https://habr.com/en/articles/965558 (неофициально) | в тарифе | M | CRM (по образцу `staff_telegram`) | дублирует Telegram, который у нас уже работает | **уже есть/решено** («мессенджер со звонками» — позже). Делать, только если сотрудники реально пользуются Мессенджером |
| Яндекс Диск REST API (вместо WebDAV) | электронный архив, горячая папка сканов и прайсов, выгрузки бухгалтеру | метаданные, перемещение, асинхронные операции; токен сервисного приложения вместо пароля | https://yandex.ru/dev/disk-api/doc/ru/ ; права `cloud_api:disk.*` — https://yandex.com/support/yandex-360/business/admin/en/security-service-applications | да | Диск 1 ТБ на сотрудника в Asosiy (https://360.yandex.uz/business/) | M | CRM (интеграция `yadisk`) / EDS (архив) | работа с общими дисками организации в документации не описана | **уже есть/решено** (позже). Добавить: REST и сервисное приложение |
| Аудит-логи API (Почта, Диск) | безопасность | кто входил, что скачивал | https://yandex.ru/dev/yandex-360/api360/ru/audit-logs/index.md | да | Optimal — хранение 3 мес., Extended — 6 мес. (https://yandex.com/support/yandex-360/business/purchase/plans/payment-plans) | M | — | дублирует админку 360 | **не нужно** (смотреть в админке 360) |
| DNS, домены, DKIM, маршрутизация, антиспам через API | — | автоматизация разовых действий | https://yandex.ru/dev/yandex-360/api360/ru/ref/DomainDNSService/index.md | да | в тарифе | S | — | — | **не нужно**: DMARC и CAA — разовые действия владельца в админке (OWNER-CHECKLIST) |
| Вход в Яндекс 360 через наш поставщик идентичности (федерация SAML) | вход сотрудников в 360 | один пароль | только SAML 2.0 с внешним поставщиком: Keycloak, AD FS, Entra, Multifactor — https://yandex.com/support/yandex-360/business/admin/en/sso/setup , https://yandex.com/support/yandex-360/business/admin/en/sso/keycloak-preset-19 | да | Asosiy и выше | L | — | нужен SAML-поставщик идентичности, а Keycloak отклонён | **не нужно** |
| Яндекс Трекер (API v3, триггеры с HTTP-запросом) | задачи, проекты | — | https://yandex.ru/support/tracker/ru/about-api ; HTTP-действие триггера — https://yandex.ru/support/tracker/ru/user/set-action | да | тариф с Трекером или дополнение — https://yandex.ru/support/tracker/ru/pricing (цену в сумах не нашёл) | M | — | дублирует задачи Платформы | **не нужно** (виза, подпись и резолюция — только в Платформе, DECISIONS 2026-11-10) |
| Яндекс Формы (HTTP-запрос из формы, API) | лиды с сайта | — | https://yandex.ru/support/forms/ru/send-request ; API — https://yandex.ru/support/forms/ru/api-ref/access | да | в тарифе | S | — | исходящие запросы только по IPv6 из сети `2a02:6b8:c00::/40` (тот же источник); дублирует «Формы сайта» | **не нужно** |
| Яндекс Вики (API `api.wiki.yandex.net`, заголовок X-Org-Id) | регламенты | загрузить готовые регламенты в базу знаний | https://yandex.ru/support/wiki/ru/api-ref/access | да | в тарифе | S | CRM (база знаний) | — | **позже** — только если компания уже ведёт регламенты в Вики |

### B. Альтернативные пакеты и сервисы задач

| Кандидат | Процесс | Польза | API / документация | Доступность в РУз | Стоимость | Усилие | Система | Риски | Вердикт |
|---|---|---|---|---|---|---|---|---|---|
| Google Workspace | почта, календарь, диск | — (компания на 360) | Calendar API и CalDAV — https://developers.google.com/calendar/caldav/v2/guide ; делегирование на домен для сервисного аккаунта — https://knowledge.workspace.google.com/admin/apps/control-api-access-with-domain-wide-delegation | Узбекистана нет в списке ограничений (https://knowledge.workspace.google.com/admin/support/troubleshooting/countries-or-regions-where-google-workspace-is-available); местная оплата — документации не найдено | от €6,80 за пользователя в месяц при годовой оплате (страница показала евро) — https://workspace.google.com/pricing | — | — | двойные расходы; США в перечне КМ № 415 только для компаний в DPF | **не нужно** как замена. Google Drive для бэкапов — **уже есть**. Календарь Google покроется тем же модулем CalDAV |
| Microsoft 365 / Entra ID | то же | — | Graph — https://learn.microsoft.com/graph/outlook-calendar-concept-overview (CalDAV у Exchange Online не подтверждён) | через партнёров; Beeline Business — сертифицированный партнёр (https://www.spot.uz/ru/2026/07/29/beeline-uzbekistan/ , по публикации) | Business Basic $7, Standard $14 с 01.07.2026 — https://www.pax8.com/blog/microsoft-update-february-2026/ ; Entra Free включает SSO — https://learn.microsoft.com/en-us/training/modules/configure-azure-active-directory/5-select-editions | L (своя ветка на Graph) | — | отдельный API вместо стандарта | **не нужно**. Клиентам с Outlook хватит приглашений .ics |
| Jira | задачи, проекты | — | https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/ | да | Free до 10 пользователей; Standard $9,70 при 1–100 пользователях с 13.10.2026 — https://www.atlassian.com/licensing/future-pricing/cloud-pricing/pricing-tables | M | Платформа | дублирует Задачи | **уже есть/решено** («по потребности») |
| Trello | — | — | REST API Atlassian | да; в списке санкционных стран Узбекистана нет — https://support.atlassian.com/trello/docs/sanctioned-countries/ | Standard $5/$6, Free до 10 участников — https://trello.com/pricing | M | Платформа | дубль | **не нужно** |
| Notion | вики, проекты | — | https://developers.notion.com/reference/intro | да | Plus $10, Business $20 за место — https://www.notion.com/pricing | M | Платформа | с 09.09.2024 пользователи в России отключены (https://www.notion.com/help/restrictions-for-customers-based-in-russia): российских поставщиков не пригласить | **уже есть/решено** («по потребности»), учесть этот риск |

### C. Вход сотрудников (SSO)

| Кандидат | Польза | Стандарт и документация | Усилие | Система | Риски | Вердикт |
|---|---|---|---|---|---|---|
| Свой вход: CRM как поставщик идентичности, JWT, TOTP | — | ADR-0003, CRM ADR-0005 | — | CRM, BFF | — | **уже есть/решено** |
| «Войти через Яндекс» (Яндекс ID, OAuth 2.0) | один пароль; политика 2FA компании в 360; блокировка в 360 закрывает и вход в Платформу | https://yandex.ru/dev/id/doc/ru/ , https://yandex.ru/dev/id/doc/ru/user-information ; без OIDC (проверено curl); готовые клиенты: Authlib 1.9.10 (BSD-3) https://pypi.org/project/Authlib/ , в social-auth-core (BSD-3) есть бэкенд Яндекса — https://github.com/python-social-auth/social-core/blob/master/social_core/backends/yandex.py | M | CRM + экран входа BFF | вход зависит от доступности Яндекса — оставить свой вход для администратора; уже открытые сессии живут до конца срока токена | **позже**. Делать общим OAuth2/OIDC-клиентом: провайдеры — в настройках, не в коде |
| Google / Microsoft Entra через OIDC | то же для другой экосистемы | discovery отвечает 200: https://accounts.google.com/.well-known/openid-configuration , https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration | S поверх общего клиента | CRM | — | **позже**, по потребности |
| Keycloak / Authentik | — | — | L | — | — | **уже есть/решено** (отклонено) |

### D. Попутная находка (для B-P8B-2)

Праздники Узбекистана: публичный .ics-канал Google — https://calendar.google.com/calendar/ical/en.uz%23holiday%40group.v.calendar.google.com/public/basic.ics (проверено curl: ответ 200).
- Плавающие праздники в нём помечены «(tentative)».
- Переносов рабочих дней в нём нет.
- Годится только как черновик, который администратор подтверждает. Вердикт — **позже**, решать в задаче B-P8B-2.

## Что даёт больше всего пользы за меньше работы

1. **Решение по MCP-серверам 360.** 0 кода, действие владельца: отключить для организации или разрешить по правилам. Закрывает утечку почты и диска во внешние ИИ.
2. **Узнать тариф и включить сервисное приложение 360 (S).** Нужен Asosiy или выше. Это основа для всех коннекторов 360 и убирает пароли приложений, которые ломаются при увольнении.
3. **Приглашение .ics + ссылка Телемоста для «Встречи» в CRM (S + S).** Работает у любого клиента и поставщика без настройки на их стороне.
4. **Личная iCal-подписка «Мои задачи» (S, Платформа BFF).** Сроки видны в календаре сотрудника. Обновление занимает часы, поэтому только для сроков.
5. **Выход из сессий и блокировка в 360 при увольнении, разовый импорт сотрудников (S).** Безопасность при увольнении.
6. **Перевести SMTP/IMAP и Яндекс Диск на OAuth сервисного приложения (S–M).** Надёжнее существующих каналов.
7. **Двусторонний CalDAV (M–L).** Как и решено, после пилота.
8. **«Войти через Яндекс» общим OAuth2/OIDC-клиентом (M).** После пилота.

**Не делать:** Трекер, Формы, Аудит-логи, DNS API, федерацию SAML, переход на Google или Microsoft, Entra, Keycloak, Trello. Jira и Notion — только при реальной потребности.

## Поправки к базовой линии

- Утверждение «персональные данные граждан РУз должны храниться в РУз» устарело (ЗРУ-1125, КМ № 415; в проекте уже разобрано в docs/research/2026-11-02-lifecycle/legal-lex.md §6). Остаются в силе два условия:
  - при включении сервисного приложения уведомить сотрудников (п. 3.6 оферты 360);
  - не отдавать наружу суммы, цены и условия сделок (DECISIONS 2026-11-10).
- В решениях 2026-11-03 и 2026-11-10 календарь подключается через пароль приложения сотрудника. Предлагаю перейти на сервисное приложение. Ограничение — тариф Asosiy или выше; какой тариф у компании, в репозитории не найдено, уточнить у владельца.
- Названия сервисов показывать только в «Настройки · Подключения». На рабочих экранах писать «Видеовстреча», «Календарь».

## Не проверено (лимит поиска исчерпан) / документации не найдено

- Подписка на события каталога 360 (вебхуки) — документации не найдено.
- Отдельный метод блокировки сотрудника — в индексе API нет, вероятно через `UserService_Update`, не проверено.
- Какой тариф даёт доступ к Bot API Мессенджера — официального источника нет, только Habr.
- Работа Disk REST API с общими дисками организации — документации не найдено.
- Цена Трекера в сумах — не найдена.
- Местная оплата Google Workspace из РУз — не найдено.
- Участие Google и Microsoft в EU-US DPF не проверял. Это условие для США в перечне КМ № 415; проверить на dataprivacyframework.gov.
- CalDAV у Exchange Online: официальной позиции Microsoft не нашёл.
- Поддержка CardDAV для общей адресной книги организации 360 официально не описана. Для личных контактов CardDAV есть: `carddav.yandex.ru` (https://yandex.com/support/yandex-360/business/mail/en/web/abook).
