# Область G — внешние ориентиры (22.11.2026)

Метки: **[Ф]** — страница открыта и прочитана; **[В]** — только выдержка поисковой выдачи (страница не открылась или не открывалась); **(вывод)** — моё заключение, не факт.
Пути репозитория — от `R = `.

## 0. Коротко

- Ни один из просмотренных продуктов не делит главное меню по принципу «модуль = одна роль-владелец». Меню делят по функции; роль управляет видимостью и составом стартовой страницы. Исключения — SAP и Business Central, но там «рабочее место роли» — это подборка ссылок на общие приложения, а не исключительное владение модулем.
- NN/g прямо предупреждает против навигации «по аудитории»: одна из пяти названных проблем — пересечение содержимого между группами. Это риск черновика владельца: в `R/docs/product/NAVIGATION.md:99-108` большинство ролей работает в 4–5 модулях.
- Почту никто не кладёт в модуль лидов. Её дом — раздел общения или личное пространство, а с лидом и документом письмо связывается действием. Предложение убрать «Почту» из «Контактов» внешней практикой подтверждается.
- Внутренние документы (служебные записки, приказы) у 1С и Directum живут в документообороте рядом с входящими и исходящими. Отдельно от них стоят чат, лента и обсуждение. Убирать из «Документов» стоит переписку, но не «Внутренние».
- Для настроек общая схема: личное, функции, администрирование; отдельно — страница состояния со статусом каждой настройки и переходом к ней. Дублирование решают одним экраном с несколькими входами.
- Строгая айдентика у зрелых команд держится на линтере, проверке токенов, визуальном сравнении и замере покрытия, а не на чек-листе. У нас машина ловит `Modal`, значки, цвет в CSS и карты статусов, но не `Drawer` и его ширину, не `<table>`, не инлайн-стили; визуального сравнения нет.
- Главная: практика и NN/g сходятся на «очередь моих дел + несколько показателей роли, анализ отдельно». Реестр бизнес-объектов внутри «Главной» у просмотренных вендоров не встретился.

## 1. Верхняя навигация

| Продукт | Как делится верхний уровень | Что говорит вендор | Люди в нескольких модулях |
|---|---|---|---|
| Bitrix24 | По инструментам, сгруппированным в разделы: Collaboration, Tasks and Projects, CRM, Employees, Automation [Ф] https://helpdesk.bitrix24.com/open/18981242/ | «the messenger becomes the central section» [Ф] https://helpdesk.bitrix24.com/open/25409295/ | Каждый сам переставляет и скрывает пункты; администратор задаёт меню всем и отключает инструмент на всю компанию [Ф] https://helpdesk.bitrix24.com/open/15596824 |
| Kommo (amoCRM) | По функции: Home, Communication, Pipelines, Calendar, Lists, AI agent, Automations, Insights, Settings [Ф] https://support.kommo.com/docs/kommos-new-left-menu | Старое меню «wasn't keeping up», функции были «buried several clicks deep»; группировка сделала навигацию «more consistent and predictable» [Ф] там же | Закрепление своих воронок и списков [Ф] |
| Zoho One (ноябрь 2025) | Три вида пространств: Personal (Mail, Calendar, Tasks, Cliq, WorkDrive, Vault), Organization (Feeds, Forums, Townhall), Functional по отделам (Sales, Marketing, Service, HR, Finance, Legal) [Ф] https://www.zoho.com/blog/index.php/one/why-work-loses-structure-across-apps-and-how-spaces-restore-it.html | «Work is no longer arranged primarily by tool category» [Ф] | Personal и Organization есть у всех; функциональные «appear automatically based on role». Что видит человек с несколькими ролями — не описано [Ф] |
| SAP Fiori | Пространство — точка входа бизнес-роли; называть его советуют по области работы, а не по роли; одно приложение можно ставить на несколько страниц [В] https://www.sap.com/design-system/fiori-design-web/v1-139/foundations/integration-and-services/sap-fiori-launchpad/sap-fiori-launchpad-spaces (отдаёт 403) | «one space per role» [В] https://blogs.sap.com/2021/02/25/recommendation-for-structuring-roles-spaces-and-pages-in-the-sap-fiori-launchpad-based-on-common-user-behaviors/ (403) | Несколько ролей — несколько пространств [В] |
| Business Central | Role Center — домашняя страница профиля; меню внутри — по областям дела: «a business manager's root items could include finance, sales, and purchasing» [Ф] https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-designing-role-centers | «Role centers are based on a user-centric design model» [Ф] | «Users who work across multiple roles can switch role centers»; профиль не даёт прав сам по себе [Ф] |
| ELMA365 | По функции: Задачи, Сообщения, Почта, Файлы, Компания, Линии, Календарь, Администрирование, плюс разделы решений (CRM и др.) [Ф] https://latest.help.elma365.com/platform/360016631091.html | — | «Администрирование» видит только группа администраторов [Ф] |
| Odoo | По приложениям; доступ задаётся по каждому приложению уровнями (нет / свои / все / администратор) [В] https://www.odoo.com/documentation/19.0/applications/general/users/access_rights.html | — | Видит те приложения, на которые есть права [В] |
| 1С:Документооборот | Блоки: договоры, управление документами, процессы, почтовый клиент, учёт времени, проекты и контроль исполнения, совместная работа [Ф] https://v8.1c.ru/doc8/ | — | Есть основной рабочий стол, рабочий стол руководителя и стол по умолчанию [В, оглавление] https://its.1c.ru/db/doc30/content/19/hdoc ; видимость команд и начальная страница настраиваются по ролям [В] https://its.1c.ru/db/content/pubdevguide83/src/text/417.html |
| Directum RX | Группы решений: управление компанией, договоры и закупки, управление делами, кадровые процессы, цифровая бухгалтерия, проекты и команды, архивы [Ф] https://www.directum.ru/products/directum | — | Виджеты главной настраиваются под пользователя [Ф] |
| monday | Рабочие области → доски; отдельный пункт «My work» [В] https://support.monday.com/hc/en-us/articles/7278527605906-Understanding-monday-com-s-structural-hierarchy | — | Подписка на области [В] |

**«Один модуль — одна роль-владелец».** В навигации не встретилось нигде. Ближайшее — SAP и Business Central, но там роль получает набор ссылок на общие приложения (вывод по строкам выше).

Опубликованное исследование — NN/g, «Audience-Based Navigation» (2015) [Ф] https://www.nngroup.com/articles/audience-based-navigation/ :
- пять проблем, среди них «Users don't know which group to choose» и «overlapping content… creates a greater workload for users (and content maintainers)»;
- рекомендация: «Prioritize topics and tasks over audience categories»;
- исключение: «Role-based navigation works best when the content is unique to that audience group».
- Оговорка: исследование про сайты; перенос на внутреннюю систему — (вывод).

Сверка с нами:
- В каталоге ролей шесть кодов: MANAGER, DIRECTOR, SUPPLY, ENGINEER, ACCOUNTANT, ADMIN (`R/packages/contracts/platform-rbac.yaml:181-187`). Роли HR нет (поиск по файлу — 0 совпадений); «менеджер по работе с клиентами» и «менеджер по продажам» отдельными ролями не существуют.
- Один менеджер ведёт и лид, и заявку: `NAVIGATION.md:102`, `:123-126`.
- Создавать документы может каждый сотрудник: `NAVIGATION.md:110`.
- Вопрос «по модулям или по ролям» уже ставился 2026-11-09, тогда данных не нашли: `R/docs/research/2026-11-09-module-map.md:28`, `:53`.
- (вывод) «Овнер» работает как ответственный за порядок в модуле и как главный пользователь, под которого собирается его главная. Как принцип деления меню он создаст пересечения, о которых пишет NN/g.

## 2. Официальная корреспонденция, внутреннее общение, почта

| Продукт | Официальные документы | Внутреннее общение | Почта |
|---|---|---|---|
| 1С:Документооборот | «Корреспонденция и внутренние документы» названы одной парой, рядом с календарём, процессами, проектами, мероприятиями [Ф] https://v8.1c.ru/upload/static/1s-dokumentooborot-kak-pochtovaya-sistema.pdf (слайд 5) | Форум, чат [В] | Свой раздел «Почта» внутри системы; «Письма – такие же учетные единицы»; письмо из документа и документ «на основании письма» с цепочкой «письмо – документ – письмо» [Ф] там же, слайды 5 и 7 |
| Directum RX | «Делопроизводство»: «Упорядоченная работа с корреспонденцией, приказами, ОРД. Выдача и контроль исполнения поручений» [Ф] https://www.directum.ru/products/directum | Чат на странице продукта не упомянут [Ф] | — |
| ELMA365 | Решение «Документооборот» ставится отдельно [Ф] https://latest.help.elma365.com/platform/360016631091.html | «Сообщения»: лента, каналы, чаты | Отдельный раздел «Почта» (личный ящик); «Линии» — общение с клиентами и партнёрами, отдельно от внутренних сообщений [Ф] |
| Odoo | — | На записи: «Log note» — «only accessible to internal users»; «Send message» — наружу; «Outside contacts are not able to log in to view the entire chatter thread» [Ф] https://www.odoo.com/documentation/19.0/applications/productivity/discuss/chatter.html | Письмо привязано к записи, ответ попадает в её ленту [Ф] |
| Kommo | — | Team chat | Email inbox — в «Communication» вместе с Chat inbox и Team chat; воронки лидов — отдельный раздел; настройки почты — в Settings [Ф] https://support.kommo.com/docs/kommos-new-left-menu |
| Bitrix24 | — | Мессенджер — центральный раздел [Ф] | Webmail — свой пункт меню; связь с CRM включается в настройках ящика и сама создаёт лид или сделку [В] helpdesk.bitrix24.com (конкретная статья не открыта) |
| Zoho One | — | Organization Space | Mail — в Personal Space [Ф] |

Опора на стандарт: ISO 15489 отделяет запись («created, received, and maintained as evidence… in pursuance of legal obligations or in the transaction of business») от документа; многие системы требуют явно объявить документ записью [В, вторичные источники] https://www.dpconline.org/digipres/implement-digipres/edrms-preservation-toolkit/edrms-toolkit-what-is-a-record . У нас этому соответствует «Регистрация официального письма создаёт входящий документ со ссылкой на письмо» (`NAVIGATION.md:31`).

Сверка с черновиком владельца:
- **П. 3, «убрать почту из Контактов» — подтверждается.** Сейчас «Почта» стоит в «Контактах» (`NAVIGATION.md:15`, `:31`), куда её перенесли из «Документов» (`:179`). В каталоге прав она до сих пор числится в модуле документов (`platform-rbac.yaml:438`). То есть почта уже побывала в двух модулях и ни в одном не прижилась.
- Условие (вывод): шаг процесса П1.1 принимает обращения из «Лидов» и «Почты» (`NAVIGATION.md:123`). Действия «в лид» и «зарегистрировать входящее» должны остаться на самом письме, как у 1С и Bitrix24.
- **П. 4, «убрать внутрикорпоративную переписку из Документов» — подтверждается наполовину.** Чат и обсуждения у всех отдельно, и у нас «Чаты» уже в «Органайзере» (`NAVIGATION.md:18`, `:49`). Но служебные записки, заявления и приказы у 1С и Directum — часть документооборота. Пункт «Внутренние» принят владельцем 2026-11-10 (`R/docs/DECISIONS.md:301`, `NAVIGATION.md:36`); внешняя практика его поддерживает. Различать нужно «документ с номером и маршрутом» и «сообщение».
- **П. 6, «общение с клиентами и партнёрами в Органайзере»** расходится с действующим решением: «Чаты только внутри компании», переписка с контрагентом — в его карточке (`NAVIGATION.md:18`, `:29`, `:188`). У вендоров есть оба варианта: общий раздел общения (Kommo), отдельный внешний канал (ELMA365 «Линии»), лента записи (Odoo). Однозначного ответа практика не даёт.

## 3. Настройки

| Образец | Факт | Источник |
|---|---|---|
| Linear | Четыре раздела: Account, Features, Administration («admins only»), Your teams; «consolidated all of a team's settings into a single view» | [Ф] https://linear.app/changelog/2024-12-18-personalized-sidebar |
| Linear | Главная страница настроек показывает, что вообще можно настроить | [Ф] https://linear.app/blog/settings-are-not-a-design-failure |
| Android, правила настроек | «Users should be able to glance at settings screens and understand all of the individual settings and their values»; «more than 10-15 items can be overwhelming»; частые — наверху | [Ф] https://source.android.com/docs/core/settings/settings-guidelines |
| Android, дубли | «For duplicate settings, create a separate screen for the setting and have entry points from different places»; поиск показывает путь к настройке | [Ф] там же |
| Google Workspace | Security health: одна страница, статус каждой настройки, значок с рекомендациями или зелёная отметка, прямой переход к настройке | [Ф] https://knowledge.workspace.google.com/admin/security/get-started-with-the-security-health-page |
| Google Workspace | Alert center: оповещения с уровнем High / Medium / Low | [В] https://knowledge.workspace.google.com/admin/security/about-the-alert-center |
| Microsoft 365 | Раздел Health: Service health и Message center; карточка состояния на главной администратора | [В] https://learn.microsoft.com/en-us/microsoft-365/enterprise/view-service-health |
| Atlassian Admin | Overview со сводкой; разделы Directory, Apps, Security, Data management, Insights, Billing, Organization settings; видимость разделов по роли администратора | [В] https://support.atlassian.com/organization-administration/docs/explore-an-atlassian-organization/ |
| Business Central | Чек-лист первого запуска ставится на домашнюю страницу роли средствами платформы | [Ф] https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-designing-role-centers |
| Bitrix24 | Меню компании настраивает только администратор; у каждого инструмента своя кнопка настроек и прав | [Ф] https://helpdesk.bitrix24.com/open/18981242/ |
| Kommo | Экран работы (ящик) и его настройка разведены: Email inbox в Communication, параметры почты в Settings | [Ф] https://support.kommo.com/docs/kommos-new-left-menu |

Сверка с нами:
- Группировок три, и они разные. В карте — четыре группы: Сотрудники, Компания, Подключения, Журнал (`NAVIGATION.md:19`, `:58-67`). В каталоге прав записано решение 2026-11-03 о пяти: Люди и доступ, Компания, Каналы связи, Процессы, Система (`platform-rbac.yaml:456`). В коде четыре ключа: people, company, channels, system (`R/apps/platform/web/src/modules/admin/settingsRegistry.ts:47-536`).
- Роль «администратор следит за фундаментом» уже сформулирована: страница готовности и красная строка на «Главной» (`R/docs/architecture/ui-standard.md:237-239`), чек-лист «Первый запуск» (`NAVIGATION.md:67`). Это тот же приём, что Security health и Service health.
- (вывод) От образцов нас отличает не идея, а её место: у Google, Microsoft и Atlassian состояние — первый экран администратора, у нас — строка в чек-листе. Проверка покрывает только настройку: внешней проверки доступности с уведомлением нет (`R/docs/research/2026-11-22-connectors/README.md`, §1, строка «Экран „Подключения“…»).
- (вывод) Правило Android «один экран настройки, несколько входов» — готовый ответ на дубли.

## 4. Как удерживают строгую айдентику

| Практика | Кто | Источник |
|---|---|---|
| Линтер: значения только из токенов | Atlassian: `ensure-design-token-usage` — «Enforces usage of design tokens rather than hard-coded values»; `use-tokens-typography` | [Ф] https://unpkg.com/@atlaskit/eslint-plugin-design-system@16.13.6/README.md |
| Линтер: запрет «сырого» HTML в пользу компонента | Atlassian: `no-html-button`, `-anchor`, `-checkbox`, `-code`, `-heading`, `-image`, `-radio`, `-range`, `-select`, `-text-input`, `-textarea` | [Ф] там же |
| Линтер: запрет устаревшего | Atlassian: `no-deprecated-apis`, `no-deprecated-imports`, `no-deprecated-design-token-usage` | [Ф] там же |
| Линтер стилей с замером покрытия | Shopify: правила сгруппированы по категориям, чтобы «measure the Polaris design system's coverage in the Shopify admin code base» | [В] https://www.npmjs.com/package/@shopify/stylelint-polaris |
| Визуальное сравнение на каждом PR | Storybook и Chromatic: снимок каждой истории сравнивается с эталоном; проверка красная, пока различие не принято | [В] https://storybook.js.org/docs/writing-tests/visual-testing |
| Замер внедрения по коду | Productboard (предупреждения линтера → панель), Pinterest (доля компонентов системы на странице) | [В] https://productboard.com/blog/how-we-measure-adoption-of-a-design-system-at-productboard , https://www.designsystems.com/how-pinterests-design-systems-team-measures-adoption |
| Правило приёма нового компонента | GOV.UK: критерии «useful» и «unique», рабочая группа голосует | [В] https://design-system.service.gov.uk/community/contribution-criteria |
| Центральный владелец системы | Nathan Curtis: у успешных систем всегда есть центральная команда | [В] https://nathanacurtis.substack.com/p/the-fallacy-of-federated-design-systems-23b9a9a05542 |
| Единый формат токенов | Design Tokens Community Group: первая стабильная версия 2025.10 (не стандарт W3C) | [В] https://www.w3.org/community/design-tokens/2025/10/28/design-tokens-specification-reaches-first-stable-version/ |

Что у нас уже проверяет машина:
- запрет `Modal` из antd в модулях — `R/apps/platform/web/eslint.config.js:162-189`;
- значки только через `shared/ui/lucide` — `:141-161`;
- родные `select`, дата и файл — `:39-53`;
- цветной `Tag` и свои карты статусов — `:55-85`;
- литералы цвета, но только в CSS — `R/apps/platform/web/src/shared/ui/colorLiterals.test.ts:18-30`;
- контраст токенов — `shared/ui/contrast.test.ts`, `R/packages/ui-tokens/contrast.test.mjs`;
- axe в e2e — `R/apps/platform/web/package.json:55`.

Чего машина не ловит (стандарт §10 сам оговаривает «по мере внедрения», `ui-standard.md:162-164`):

| Пробел | Факт |
|---|---|
| `Drawer` из antd в модулях не запрещён | 11 файлов импортируют его напрямую: `erp/stock/ProductDrawer.tsx:1`, `erp/catalog/ItemsPanel.tsx:1`, `erp/docs/DocsScreen.tsx:2`, `crm/messages/Dialog.tsx:1`, `admin/signing/AuthorityDrawer.tsx:2`, `chats/people/PeoplePage.tsx:1`, `eds/documents/DocumentSheet.tsx:1`, `eds/mail/MailBody.tsx:1`, `eds/mail/SentMail.tsx:2`, `eds/inbox/ResolutionPanel.tsx:1`, `eds/decision/DecisionSlot.tsx:1` (все под `R/apps/platform/web/src/modules/`) |
| Ширина панели | Стандарт: только 480 или 640 (`ui-standard.md:107-108`). В коде: 400 (`chats/people/PeoplePage.tsx:236`), 520 (`admin/signing/AuthorityDrawer.tsx:242`), 560 (`erp/stock/ProductDrawer.tsx:39`, `eds/mail/SentMail.tsx:221`), 760 (`erp/docs/DocsScreen.tsx:358`), 960 (`eds/mail/MailBody.tsx:83`); по стандарту — только 640 (`erp/catalog/ItemsPanel.tsx:438`). Это измеримая часть «зоопарка окон» |
| `<table>` в модулях | Правила нет; 2 файла: `erp/calc/LinesTable.tsx`, `admin/roles/RoleMatrix.tsx` |
| Цвет в TS/TSX | Тест смотрит только CSS; в модулях 6 строк с литералом цвета в 3 файлах: `eds/mail/frameDoc.ts` (4), `admin/company/common.tsx` (1), `admin/company/tabs/BrandTab.tsx` (1) |
| Инлайн-стили | 212 вхождений `style={{` в 78 файлах модулей; правила нет |
| Визуальное сравнение | В `apps/platform/web/e2e` нет `toHaveScreenshot` и `toMatchSnapshot` (поиск — 0 файлов). Снимки делаются как доказательство для PR (68 вызовов `screenshot(`), с эталоном не сравниваются. Storybook и stylelint в `package.json` нет |
| Общая проверка стандарта | UI-10 — ручной проход по чек-листу, ещё не закрыт (`R/docs/runbooks/plan-2026-11-12.md:45`, `:242`) |

(вывод) Стандарт написан по тем же эталонам, что у зрелых команд (`ui-standard.md:5-7`, закон 5 — `:19`). Расхождение — в принуждении: у Atlassian и Shopify правило живёт в линтере и в показателе покрытия, у нас значимая часть §6, §7 и §10 держится на ревью. Поэтому новый и старый код расходятся незаметно.

## 5. Главная как ситуационный центр

| Источник | Факт |
|---|---|
| NN/g, дашборды [Ф] https://www.nngroup.com/articles/dashboards-preattentive/ | Дашборд — «single-page view that imparts at-a-glance information on which users can act quickly». Оперативный — для «time-sensitive tasks», аналитический — без такой срочности. Цель — не исследование: информация должна восприниматься «with a minimum of interaction» |
| NN/g, порталы (2014) [Ф] https://www.nngroup.com/articles/intranet-portals/ | Состав главной по ролям и месту работы пользователи приняли хорошо; аналитики составляли матрицу «роль — функции». Настройки, которые упрощают задачу, используются; цвета, темы и раскладки «often fail» |
| Business Central [Ф] https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-designing-role-centers | Порядок: заголовки → показатели → остальное. Действия создания — в верхней строке. Второстепенное советуют скрывать |
| SAP My Home [В] https://www.sap.com/design-system/fiori-design-web/v1-139/discover/sap-products/sap-s4hana-only/s4hana-product-home-page-my-home | Первым стоит To-Dos: задачи и «ситуации» со счётчиками; раздел скрыт, если приложений у роли нет. Дальше страницы, приложения и показатели с жёсткими пределами (до 8 страниц, до 10 карточек) |
| Salesforce [В] https://trailhead.salesforce.com/content/learn/modules/lightning_app_builder/lightning_app_builder_homepage | Главная назначается на связку «приложение + профиль»; блоки Assistant, Today's Tasks, Key Deals; видимость блока по профилю |
| Bitrix24 [Ф] https://helpdesk.bitrix24.com/open/25409295/ | После входа человек попадает в чаты |
| Kommo [Ф] https://support.kommo.com/docs/kommos-new-left-menu | Home — обзор аккаунта и чек-лист настройки; показатели вынесены в Insights |
| monday [В] https://support.monday.com/hc/en-us/articles/115005934045-Glossary | «My work» — вся моя работа в одном месте |

- Прямого опубликованного сравнения «ролевой дашборд против личной очереди» с замерами я не нашёл; то же отмечено в `R/docs/research/2026-11-09-module-map.md:28`.
- (вывод) Практика и NN/g сходятся: наверху — то, что ждёт моего действия; затем несколько показателей роли; анализ — отдельным экраном. Блок «Что ждёт вас» и раскладка «Задачи · Проекты · Сводка» (`NAVIGATION.md:14`, `:23`) этому соответствуют.
- (вывод) Формулу «здесь вся правда» источники не поддерживают буквально: все ограничивают главную одним экраном и сигналами.
- (вывод, по скриншоту (c)) Реестр проектов внутри «Главной» у просмотренных вендоров не встретился: у Bitrix24 это «Tasks and Projects», у Directum — «Проекты и команды», в Business Central списки открываются из меню области. У нас «Проекты» в «Главной» — решение владельца 2026-11-10 (`NAVIGATION.md:14`, `:42`).

## 6. Где факты расходятся с черновиком владельца

| Тезис | Что показывают факты | Оценка (вывод) |
|---|---|---|
| У каждого модуля роль-владелец | В навигации такого нет ни у кого; NN/g против деления по аудитории; у нас роли работают в 4–5 модулях | Годится как ответственность за порядок и как основа ролевой главной; не годится как принцип меню |
| Контакты — менеджер по работе с клиентами, Операции — менеджер по продажам | Таких ролей нет: один MANAGER ведёт и лид, и заявку (`platform-rbac.yaml:181-187`, `NAVIGATION.md:102`) | Сначала решить, появляются ли две роли |
| Органайзер — HR-менеджер | Роли HR нет. У Zoho HR — отдельное функциональное пространство, а почта, календарь и задачи — личное пространство каждого | Набор «общение, календарь, задачи, люди» подтверждается; владелец-HR — нет |
| Убрать почту из Контактов | Подтверждается всеми, у кого есть почта | Сохранить действия на письме: в лид, зарегистрировать входящее |
| Убрать внутреннюю переписку из Документов | Чат отдельно — да; внутренние документы у 1С и Directum в документообороте | Убирать сообщения, оставить «Внутренние» |
| Общение с клиентами и партнёрами — в Органайзере | Действует решение «Чаты только внутри компании»; практика вендоров разная | Нужно отдельное решение владельца |
| Главная — вся правда | Источники требуют одного экрана сигналов; анализ отдельно | Очередь и сигналы — да, «всё» — нет |
| Настройки — администратор следит за фундаментом | Совпадает с Security health, Service health, Atlassian Overview; у нас есть страница готовности | Вынести состояние на первый экран администратора; свести три группировки в одну |

## 7. Ограничения

- SAP: страницы руководства и блог отдают 403, факты взяты из выдержек поиска.
- 1С: тексты ИТС закрыты входом; открыто прочитаны страница продукта и презентация о почте (старая, интерфейс редакции 2.0).
- Directum RX: веб-справка закрыта входом. Устройство интерфейса («обложки модулей», папка «Входящие») не подтверждено; использована только страница продукта.
- amoCRM: русская справка по меню не найдена, взята справка Kommo (международная версия продукта). Совпадает ли меню — не проверял.
- Bitrix24: состав раздела Collaboration (Feed, чаты, Webmail, Drive, календарь) и автосоздание лидов из почты — только из выдержек; статья `open/14836912` отдаёт 404.
- Odoo: стартовый экран и устройство настроек не подтверждены; подтверждены лента записи и права по приложениям.
- Notion: структура настроек по официальной справке не подтверждена, в отчёт не включена. Stripe и GitHub Primer не проверялись.
- Цифры по нашему коду — подсчёт по `src/modules` без тестовых файлов; полный аудит экранов — в других областях.
