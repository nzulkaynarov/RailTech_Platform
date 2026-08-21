# Вердикты второй волны скептиков — прогон 20-08

Проверено 16, вердикты: {'confirmed': 14, 'by_design': 2}.

Каждый скептик обязан был ОПРОВЕРГНУТЬ находку: воспроизвести своей песочницей и своим замером,
отличить артефакт инструмента от дефекта продукта и определить происхождение через `git blame`.
У шести находок тяжесть исправлена (в основном вниз), две опровергнуты целиком.

## Подтверждённые

### 1. Оператор без права platform.settings открывает «Справочники» и «Email-шаблоны» по прямому хэшу

**Тяжесть уточнена:** major, не blocker. Эксплуатировать может только уже заведённый сотрудник платформы (`SystemRole=ADMIN`); арендаторских данных, чужих денег и анонимного доступа дефект не касается — это нарушение least privilege ВНУТРИ операторской плоскости, а не пробой тенантной изоляции (сравнить с #593, где арендатор выгружал 42 компании с ИНН — вот там blocker). Но занижать тоже нельзя: радиус — вся платформа. Активная строка `EmailTemplate` немедленно подменяет файловый шаблон ДЛЯ ВСЕХ получателей (произвольный HTML в письме клиенту от имени платформы), а `test-send` реально отправляет письмо и пишет `Ema

**Чем подтверждено:** Песочница (создал и удалил за собой; общие демо-аккаунты не трогал): пользователь `skeptic.thin.op@example.com` / `Demo1234!`, `SystemRole=ADMIN`, `OperatorRole=SUPPORT` (права ровно `users.view, companies.view, kyc.view, billing.view`), `is_superuser=False`, memberships=0. Сервис-проверка: `operator_has_permission(u, 'platform.settings') → False`.

ЗАМЕР ЧЕРЕЗ API (`POST /api/v1/auth/token/` → Bearer):
| запрос | HTTP |
|---|---|
| `POST /api/v1/master-data/currencies/` {"code":"SKP",...} | **201** — валюта создана |
| `POST /api/v1/master-data/units/` | **201** |
| `POST /api/v1/master-data/countries/` | **201** |
| `DELETE /api/v1/master-data/currencies/6/` | **204** |
| `GET /api/v1/admin/email-templates/` | **200** |
| `POST /api/v1/admin/email-templates/` {"key":"skeptic_probe"} | **201** |
| `PATCH /api/v1/admin/email-templates/2/` {"subject":"SKEPTIC-PROBE"} | **200** |
| `DELETE

**Происхождение:** Давний код, к волнам 20-08 отношения не имеет.
- `backend/master_data/views.py` — `permission_classes = [IsPlatformAdminOrReadOnly]` введён коммитом **bf352562 от 2026-04-19** («Refactor user roles and permissions to introduce Platform Admin role») и с тех пор не менялся. Это на два месяца РАНЬШЕ появления `OperatorRole` (ADR-0004 G1, `accounts/0027_seed_operator_roles`), поэтому суб-права там физически не могли быть учтены.
- `backend/notifications/views.py` — `[IsAuthenticated, IsPlatformAdmin]` введён **6e8af4aa от 2026-06-26** (ADR-0004 Phase 1, платформенные шаблоны писем), тоже до гранул

**Починка:** Чинить надо в двух местах, и бэкенд — первый: сейчас единственный контроль это скрытая строка меню.

1. `backend/master_data/views.py` — на `CountryViewSet`, `CurrencyViewSet`, `UnitOfMeasureViewSet`, `DeliveryBasisViewSet` заменить `permission_classes = [IsPlatformAdminOrReadOnly]` на уже существующий в проекте образец из `backend/catalog/views/lookups.py:77,121`:
```python
operator_permission = "platform.settings"

def get_permissions(self):
    if self.action in ("list", "retrieve"):
        return [permissions.AllowAny()]
    from core.permissions import OperatorScoped
    return [OperatorScoped()]
```
Публичное чтение справочников сохраняется (его ждут все экраны), закрывается только запись.

2. `backend/notifications/views.py`, `EmailTemplateViewSet` — `permission_classes = [permissions.IsAuthenticated, OperatorScoped]` и `operator_permission = "platform.settings"`. Важно: `Operato

### 2. «Экспорт → XLSX/CSV» не отдаёт файл — открывает пустую вкладку приложения

**Тяжесть уточнена:** major (в находке — blocker). Фича мертва на 100 % и обходного пути в UI у Platform Operator без `is_superuser` нет — после #593 дверь в Unfold ему закрыта. Но клин заявка→КП→контракт это не останавливает, данные не теряются и не портятся, чужого ничего не показывает. Это полностью сломанная вспомогательная функция операторской плоскости, а не блокер продукта.

**Чем подтверждено:** ЗАМЕР 1 — сырой curl по обоим origin (тот URL, который реально открывает `window.open`):

```
$ curl -sD- "http://localhost:5173/api/v1/accounts/companies/export/?fmt=xlsx"
HTTP/1.1 200 OK
Server: nginx/1.30.4
Content-Type: text/html          <-- НЕ xlsx
Content-Length: 1118
<!doctype html><html lang="en">...   <-- index.html SPA

$ curl -sD- "http://localhost:8000/api/v1/accounts/companies/export/?fmt=xlsx"
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer realm="api"
{"detail":"Учетные данные не были предоставлены."}
```

ЗАМЕР 2 — живой браузер (Playwright), вход оператором `admin@railtech.uz`, перехват document-запросов на уровне BrowserContext + счётчик событий `download`. Клик по кнопке Export → пункт меню:

```
### Компании (#admin-companies) → «Export to Excel (XLSX)»
REQ  http://localhost:5173/api/v1/accounts/companies/export/?fmt=xlsx  Authorization=НЕТ
RESP 200 ct=text/html c

**Происхождение:** Давний код: коммит `92565688` от 2026-04-23 («feat: add AdminDataTable component for enhanced data management»), функция `triggerExport` в `frontend/src/components/Admin/AdminDataTable.tsx`. `git blame -L 266,281` показывает, что ВСЕ строки функции — из этого коммита, ни одной более поздней правки. Волны 20-08 (#593 дверь Unfold, #594 мёртвые операторские пути, #595 аудит действий, #596 постраничка реестров, #597 журнал доступа) к этому отношения не имеют; последнее касание файла вообще — `575d8a7e` (#590, 19-08), по другим строкам. Кнопка не работала с момента появления — ~4 месяца. Стенд пол

**Починка:** Файл: `frontend/src/components/Admin/AdminDataTable.tsx`, функция `triggerExport` (строки 268–282).

Суть: выгрузка должна идти ТЕМ ЖЕ каналом, что и все остальные приватные файлы — через `apiClient` (у него верный `baseURL` из `VITE_API_URL` и интерсептор, вешающий `Authorization: Bearer`), а не через `window.open`. Канон уже есть и написан ровно про этот класс ошибки: `frontend/src/lib/download.ts` → `downloadFile(path, filename)` — тянет ответ как blob и сохраняет через временный `<a download>`.

1. В `triggerExport` собрать не абсолютный URL, а ОТНОСИТЕЛЬНЫЙ путь API со строкой запроса (фильтры `search` / `ordering` / `tab.params` / `fmt` собираются как сейчас, через `URLSearchParams`), и вызвать `await downloadFile(path, `${filename}.${fmt}`)`. Ошибку не глотать — показать toast (Self-Check п.7), сейчас у пользователя вообще нет обратной связи об отказе.
2. Сменить контракт пропа `e

### 3. Заявку на роль, поданную из продукта, невозможно одобрить — форма арендатора не даёт приложить документы

**Чем подтверждено:** Шаги (локальный стенд, своя песочница):
1. `docker compose exec -T backend python manage.py shell` — создать компанию с типом CLIENT и владельца (WorkspaceRole OWNER).
2. Playwright: войти этим владельцем → `#settings` → пункт «Company» → карточка «Company role on the platform».
   ЗАМЕР: `card.querySelectorAll('input[type=file]').length` = **0**; интерактивные элементы карточки = `["BUTTON:button:Choose a role","BUTTON::Submit application"]`.
3. Выбрать «Supplier» → «Submit application».
   ЗАМЕР сети: `POST accounts/role-applications/`, multipart, тело содержит только `company=72` и `requested_type=2`. Ответ **201**, `contract_file:null, nda_file:null, partnership_agreement:null`, id=15.
4. Войти оператором (суперадмин) → `#admin-role-apps` → меню строки.
   ЗАМЕР пунктов меню: `["Approve","Reject"]` — пункта «нужны документы» нет, хотя статус `DOCUMENTS_REQUIRED` в модели есть.
5. «Ap

**Происхождение:** Давний код, НЕ волны 20-08 (#593–#597).
• Серверный гейт документов существует минимум с 2026-04-19 (коммит 35c9415f «feat(i18n): add API error messages…» уже переводит `ROLE_APPLICATION_MISSING_CONTRACT_NDA`); в нынешний файл `backend/accounts/services/applications.py:31-36` он переехал коммитом 9c669488 от 2026-06-02 («refactor(accounts): split 875-line services.py into a services/ package (T4)»).
• Форма подачи у арендатора, которая производит заявки БЕЗ документов, добавлена коммитом 93c47bdb от 2026-07-31 — «feat(accounts): волна U11 — заявку на роль компании стало откуда подать (#484)». 

**Починка:** Фронтенд, серверных изменений не требуется (новых гейтов не добавлять — PRODUCT RULE 2).

1. `frontend/src/components/Settings/CompanyRoleSection.tsx` — после выбора роли показывать поля вложений, которых требует сервер: для `SUPPLIER` — «Договор» (`contract_file`) и «NDA» (`nda_file`), для `MANUFACTURER` — «Договор о партнёрстве» (`partnership_agreement`); передавать их в `create.mutateAsync({ company, requested_type, contract_file, nda_file, partnership_agreement })`. Клиент API это уже поддерживает — `frontend/src/api/accountsApi.ts:672-681` кладёт файлы в FormData; бэкенд принимает и на create, и на PATCH (замерено: PATCH → 200). Тексты — в `ru.json`/`en.json`, компоненты — shadcn.
2. Там же: для заявки со статусом `DOCUMENTS_REQUIRED` дать заявителю догрузить недостающее (PATCH разрешён, пока заявка не рассмотрена — `CompanyRoleApplicationViewSet.perform_update`), иначе этот статус 

### 4. Инженер выдаёт себе права суперпользователя тремя кликами — форма пользователя в Unfold открыта на запись

**Тяжесть уточнена:** major, а не blocker. Эксплуатация требует предварительной выдачи `accounts.change_customuser` суперпользователем — этого не делает ни один код-путь репозитория, и на стенде права нет ни у кого. Латентная дыра в эшелоне защиты + прямое расхождение с ADR-0001, а не живая эскалация «тремя кликами из коробки».

**Чем подтверждено:** Все замеры — реальный HTTP через `django.test.Client` внутри `docker compose exec -T backend python manage.py shell` (полный стек middleware/urls/view, отличие от браузера только в CSRF-cookie). Скрипты: /private/tmp/claude-501/-Users-nurbekgbm5-Downloads-My-Apps-RailTech-SaaS-B2B/ddbab24b-690c-4e03-bf23-468cce592ff0/scratchpad/skeptic/{repro,plain_member_sweep,viewonly_probe,mixin_probe}.py

ШАГ 0 — состояние стенда (замер): группа `system_engineers` permissions=0; `change_customuser` — держателей 0 (ни личных, ни групповых); не-суперпользователей с is_staff=True — 1 (`unfold.staff@qa.local`, песочница аудитора); суперпользователь один — `admin@railtech.uz`.

ШАГ 1 — контрольный опыт, чистый член группы (`skeptic.plain@qa.local`, is_staff=True, в группе, user_permissions=0):
  200  /admin/
  403  /admin/accounts/customuser/<id>/change/   ← находка НЕ воспроизводится
  403  /admin/accoun

**Происхождение:** ДАВНИЙ КОД, не волны 20-08. Фейсет «Доступ» с тройкой `("is_active", "is_staff", "is_superuser")` в `backend/accounts/admin.py` появился в c2504a1d от 2026-03-25 (`git log -S`); сам файл последний раз правился 6287d02b от 2026-07-30 — форму пользователя тот коммит не касался. `ReadOnlyInspectionMixin` и Phase 4 ADR-0001 (2026-04-16) перечисляют покрытые модели — Company, Deal, Lead, Message, Product, SupplierOffer, CompanyRoleApplication, SupplierSubscription: `User` в списке НЕТ, хотя таблица того же ADR требует по нему READ-ONLY. То есть пробел ровесник самого миксина, ~4 месяца.

Волна 20-0

**Починка:** Файл: `backend/accounts/admin.py`, класс `UserAdmin` (регистрация `@admin.register(CustomUser)`, фейсет «Доступ»).

Суть: для не-суперпользователя привилегированный блок должен ИСЧЕЗАТЬ из формы, а не просто становиться серым. Переопределить `get_fieldsets`/`get_form` и при `not request.user.is_superuser` выбрасывать `is_staff`, `is_superuser`, `role`, `groups`, `user_permissions` — Django валидирует POST по форме, поэтому удалённое поле нельзя подсунуть телом запроса (readonly-путь этого не гарантирует так же чисто). Это же соответствует эталону O-HIDE-NOT-DISABLE, который проект уже применял в волне U1.

Важно (замерено, иначе починка будет ложной): одного `ReadOnlyInspectionMixin` НЕ хватит — его `get_readonly_fields` фильтрует `not f.many_to_many and not f.one_to_many`, поэтому `groups` и `user_permissions` останутся редактируемыми (контрольный замер на `CompanyAdmin`: `types` в read

### 5. Мастер компании открыт члену группы без единого модельного права и ставит KYC

**Тяжесть уточнена:** major (не blocker). Тяжесть в находке завышена на одну ступень: путь НЕ доступен рядовому арендатору — контрольный замер показал, что `is_staff` без группы `system_engineers` бросается на `/admin/login/` (это и закрыл #593). Предусловие — членство в инженерной группе, которое суперпользователь выдаёт руками через `manage.py grant_engineer`. Но это не смягчающее до minor: `grant_engineer` и миграция `accounts/0006` НЕ выдают ни одного модельного права, то есть каноничный «инженер» — ровно тот самый ноль-правовой аккаунт из находки, и по замыслу он не может ни создать компанию, ни отредактироват

**Чем подтверждено:** Стенд локальный, Django-админка http://localhost:8000/admin/.

1. Песочный пользователь (manage.py shell): `create_user(email="skeptic.engineer@sandbox.local", password=...)`, `is_staff=True`, `is_superuser=False`, `groups.add(Group.objects.get(name="system_engineers"))`. Замер прав: `user_permissions=[]`, `group perms=[]`, `get_all_permissions()=[]`, `has_perm("accounts.add_company")=False`.
2. Реальный HTTP через Daphne (curl с cookie jar): GET `/admin/login/` → POST логина → 302 на `/admin/`.
3. ЗАМЕР доступов в одной сессии: `/admin/` → 200; `/admin/accounts/company/` → 403; `/admin/accounts/company/add/` → 403; `/admin/accounts/company/export/` → 403; `/admin/accounts/company/wizard/` → 200.
4. Четыре POST по шагам мастера (префикс `company_wizard_view-current_step`): requisites (name+inn) → contacts → role (`role-types=2` SUPPLIER, `role-verification_status=3` = L2_VERIFIED, kyc_no

**Происхождение:** Давний код: `backend/accounts/wizard.py` появился 2026-03-25 (c2504a1d, «feat: add Zustand stores…» — мастер приехал в том же коммите) и с рождения гейтился голым `request.user.is_staff`. Волна 20-08, PR #593 (029bdb32, 2026-08-20, «арендатор заходил в инженерную админку и выгружал 42 компании с ИНН») заменила эту строку на дверь `EngineeringAdminSite.has_permission` — проверку модельных прав НЕ добавила. Так что дефект старый по происхождению, но остаточный зазор — недоделанная часть #593: тот же PR из соображений «мимо сервисов и аудита» убрал `verification_status` из `CompanyResource` (XLSX

**Починка:** `backend/accounts/wizard.py`, `CompanyWizardView.dispatch` — дверь оставить, но добавить проверку права на СОЗДАНИЕ поверх неё, приведя мастер к тому же уровню, что штатная админка: либо `request.user.has_perm("accounts.add_company")` (и заодно `accounts.add_companymember`, `accounts.add_customuser` — мастер создаёт всё трое), либо прямо `is_superuser`, чтобы совпасть с `ReadOnlyInspectionMixin.has_add_permission`, которым уже закрыт `CompanyAdmin` (`backend/core/admin_mixins.py:85`, `backend/accounts/admin.py:206`). Второе честнее: сейчас не-суперпользователь не может изменить у компании НИ ОДНО поле (все readonly), так что право создавать её целиком у него быть не должно.

Второй, отдельный шов — KYC: убрать `verification_status` из `Step3RoleForm` (как #593 убрал его из `CompanyResource`), либо проводить установку через `accounts/services/kyc.verify_company_kyc(company, approver=reque

### 6. Плитки на «Тикетах поддержки» считают только текущую страницу — «Срочных 0» при живом срочном тикете

**Чем подтверждено:** 1. Подготовка песочницы (docker compose exec -T backend python manage.py shell): создать пользователя skeptic.sandbox@qa.test и 24 тикета SupportTicket с subject «SKEPTIC sandbox #NN», все OPEN, у самого старого priority='URGENT'; created_at выставить возрастающим шагом, чтобы срочный оказался ниже 20-й строки при сортировке -created_at.
2. ЗАМЕР ПО БАЗЕ: всего 57; по статусам {OPEN: 55, IN_PROGRESS: 1, RESOLVED: 1}; срочных не CLOSED/RESOLVED — 2; позиции срочных в сортировке -created_at — 24-я и 57-я, то есть на страницах 2 и 3.
3. Войти оператором (SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD), открыть #admin-support.
4. ЗАМЕР СТРАНИЦЫ 1 (значения сняты из DOM: подпись p.text-xs + число p.text-2xl в каждой карточке, плюс разбор строк tbody):
   плитки [Total 57, Open 20, In progress 0, Urgent 0]; пейджер «Showing 1–20 of 57»; строк 20, из них по статусу {Open: 20}, по приоритету {Normal: 20}.

**Происхождение:** Давний код, НЕ регрессия волн 20-08. Строки счётчиков лежат с самого рождения экрана: git blame → 68d00bfc «feat: add support ticket system for client-to-admin communication», 2026-04-20 (строки 264–268). Серверная постраничка (page/page_size + Pager по data.count) была в том же первом коммите — значит счётчики были постраничными изначально, а не сломались позже.

Волны 20-08 файл не трогали: последняя правка AdminSupportPage.tsx — c8a0aafd от 2026-08-18 (Fast Refresh, #574), в истории файла всего 4 коммита. При этом #594 (63aceb6f) и #596 (deb0990d) чинили ровно этот класс на соседних экранах

**Починка:** Файл: /Users/nurbekgbm5/Downloads/My Apps/RailTech_SaaS_B2B/frontend/src/pages/AdminSupportPage.tsx — строки openCount/inProgressCount/urgentCount считают по `tickets` (= `data?.results`, одна страница), а `total` рядом берётся из `data?.count`. Считать надо по ВЫБОРКЕ, а не по странице.

Предпочтительный путь — серверные счётчики, ровно тот, что назван правильным в теле #596 («реестру, который дорастёт до тысяч, нужна серверная постраничка вместе с серверными счётчиками вкладок»): добавить в /Users/nurbekgbm5/Downloads/My Apps/RailTech_SaaS_B2B/backend/core/views/support.py экшен `@action(detail=False, methods=["get"], url_path="stats")` на SupportTicketViewSet, который считает ОДНИМ `aggregate(Count("id", filter=Q(...)))` по `self.filter_queryset(self.get_queryset())` — то есть с теми же search/status/priority/category, что и список; фронт рисует плитки из ответа этого экшена (новый ху

### 7. Единственное действие экрана «Лиды» — «Конвертировать в сделку» — у штатного оператора всегда отказ

**Тяжесть уточнена:** major подтверждаю (не завышено). Это тот же класс, что пять путей, починенных волной #594: экран отгружен, действие единственное, запрос уходит, стена. Границы честно: данные не портятся, дыры в безопасности нет, обход существует — но только через суперадмина, которому ADR-0002 бизнес-операции от лица компаний запрещает; сам поток лидов маломощный (публичный POST /api/v1/crm/leads/ с внешнего лендинга, продюсера внутри SPA нет). Ниже major опускать не стал: для штатного оператора экран «Лиды» сейчас на 100 % нефункционален.

**Чем подтверждено:** Песочница (создана и удалена мной; общие демо-данные не трогал): компания «SKEPT Lead Sandbox Co» (CLIENT, L2), её сотрудник skept.lead.buyer@example.com, оператор skept.lead.op@example.com (SystemRole=ADMIN, operator_role=SUPER_OPERATOR, is_superuser=False, 0 членств → `is_platform_admin=True`), два лида (#5, #6) на email сотрудника.

ЗАМЕР A — сырой API (curl, localhost:8000):
- POST /api/v1/auth/token/ оператором → access получен;
- POST /api/v1/crm/leads/5/convert/ → **HTTP 400, {"detail":"ADMIN_VIEWER_CANNOT_ACT"}**;
- GET /api/v1/crm/leads/ тем же токеном → **HTTP 200**, count=6 (список оператору виден);
- тот же POST /api/v1/crm/leads/5/convert/ суперадмином (admin@railtech.uz из .env) → **HTTP 201, {"deal_id":44,"stage":"DRAFT"}**;
- тот же POST лидом #6 от сотрудника компании → **HTTP 403** «Access restricted to platform administrators».

ЗАМЕР B — SPA глазами (Playwright, local

**Происхождение:** Давний код, к волнам 20-08 отношения не имеет.
- Гард: коммит 11690915 «feat: Implement role responsibilities and access control updates», 2026-04-19 — та же правка добавила ADR-0002 и разом навесила `is_platform_admin_viewer` на десяток сервисов (transition_deal_stage, generate_contract_from_quote, cancel_contract, convert_lead_to_deal…). Текущая строка backend/crm/services/deals.py:345 blame даёт 2ed499e8 (2026-06-02) — это лишь распил services.py на пакет.
- Экран: коммит c6cdb246 «feat(admin): leads inbox page (ADR-0006 Leads=KEEP)», 2026-07-08 — операторская страница появилась через три м

**Починка:** Развилка продуктовая, но одну сторону чинить обязательно — сейчас функция недоступна никому из штатной аудитории.

Предпочтительно (соответствует ADR-0006: лид приходит НА ПЛАТФОРМУ с лендинга, квалифицирует его оператор — это модерация/маршрутизация, а не «купить/продать/подписать/заплатить» от лица арендатора):
1. backend/crm/services/deals.py, `convert_lead_to_deal` (строки 343-346) — снять `is_platform_admin_viewer`-гард для этого сервиса и оформить действие как операторскую эскалацию по образцу ADR-0002 §Force-actions: пометить ActivityLog `[FORCE_ADMIN]`/`admin.*` кодом, чтобы аудит отделял его от обычного потока. Заодно перестанет быть мёртвой строка `manager=actor if (actor and actor.is_platform_admin) else None`.
2. backend/crm/views/leads.py, `LeadViewSet` — заменить `IsPlatformAdmin` на `OperatorScoped` и объявить `operator_permissions = {"convert": OperatorPermission.MODERATI

### 8. Удаление справочной строки, на которую ссылаются данные арендаторов, падает в 500

**Тяжесть уточнена:** medium (в находке — major, завышено, но «minor» тоже было бы неверно).

Почему не major: путь только операторский (`platform.settings` / суперадмин), арендаторы его не видят; данные НЕ теряются — опасное действие как раз корректно заблокировано на уровне БД; утечки нет (трассировка видна только локально при `DJANGO_DEBUG=true`, на проде `DEBUG=False`). В самом репозитории близнец этого дефекта (`TEMPLATE_IN_USE`) был отнесён к волне «Гигиена» (F3, `#390`) — и тот был обращён к арендатору, то есть тяжелее.

Почему не minor: (а) бьёт по всем ЧЕТЫРЁМ справочникам, а не по одной вкладке; (б) кажда

**Чем подтверждено:** Стенд локальный, HEAD = d5259616 (main), дерево чистое.

1) API, без браузера:
```
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/token/ -H 'Content-Type: application/json' \
  -d '{"email":"admin@railtech.uz","password":"<SUPERADMIN_PASSWORD>"}' | jq -r .access)
curl -s -o /tmp/b -w "HTTP=%{http_code} CT=%{content_type}\n" \
  -X DELETE localhost:8000/api/v1/master-data/units/1/ -H "Authorization: Bearer $TOKEN"
```
ЗАМЕР: `HTTP=500 CT=text/html`, тело — страница Django с заголовком `ProtectedError at /api/v1/master-data/units/1/`.

2) Состояние БД до/после (правда о стенде):
`UnitOfMeasure` id=1, code=H87, name=«шт.», ссылается 35 товаров (в находке было 34 — стенд с тех пор прирос одним, на суть не влияет). После DELETE: `UnitOfMeasure.objects.filter(code='H87').exists() → True` — строка цела, PROTECT сработал, потеряна только внятность отказа.

3) Глазами (Playwright, роль operat

**Происхождение:** ДАВНИЙ КОД, не волны 20-08.

- Кнопка корзины и операторский CRUD справочников — `aaf7d79d` от 2026-04-18 («feat: add AdminCompaniesPage, AdminDealsPage, and AdminMasterDataPage with CRUD functionality»); вьюсеты `master-data/*` зарегистрированы ещё раньше.
- `Product.uom` с `on_delete=models.PROTECT` — с `c2504a1d` (2026-03-25), при расщеплении моделей переехал в `catalog/models/products.py` коммитом `6fa0f948` (2026-06-02).
- Волна 20-08 `#594` (`63aceb6f`, «пять операторских путей не работали ВООБЩЕ») ФАЙЛ ТРОГАЛА, но мимо: диффом добавлены только `def perform_destroy(self, instance): super

**Починка:** 1. `backend/master_data/views.py` — общий гард на удаление, один на все четыре вьюсета. В `_CachedLookupListMixin` (или отдельным маленьким миксином рядом) переопределить `destroy`, повторив уже принятый в проекте паттерн из `crm/views/documents.py:150-155`:
```python
from django.db.models.deletion import ProtectedError

def destroy(self, request, *args, **kwargs):
    try:
        return super().destroy(request, *args, **kwargs)
    except ProtectedError:
        # Строку справочника печатают документы всех арендаторов; PROTECT её бережёт.
        # Оператору — деактивация (is_active=False), не удаление.
        return Response({"detail": "LOOKUP_IN_USE"}, status=400)
```
Класть именно в миксин, а не в один `UnitOfMeasureViewSet`: PROTECT-ссылки есть и у Country (1), и у Currency (2), и у DeliveryBasis (2) — точечная починка одной вкладки оставит три таких же пятисотки.

2. `frontend/sr

### 9. Действия оператора на четырёх из пяти экранов не оставляют следа в «Журнале доступа»

**Тяжесть уточнена:** minor (пробел покрытия аудита), не major. Ничего не сломано и ничего не видно пользователю: путь работает, данные не теряются, арендатор не затронут. Речь о полноте следа на операторской плоскости, где действующее лицо — сотрудник платформы. Плюс охват находки завышен вдвое: из четырёх названных экранов реальных пробела два (справочники — следа нет вовсе; письма — только «кто трогал последним»), а по support и leads след пишется и виден в ленте дашборда. Ближайший ориентир по тяжести — волна #595, где аналогичные «действия без следа» шли как обычные починки, а по-настоящему тяжёлой находкой то

**Чем подтверждено:** Локальный стенд, оператор admin@railtech.uz.

ЗАМЕР 1 (API). Базовая величина: `GET /api/v1/admin/access-log/?limit=500` → **count = 22**. Затем 8 реальных мутаций оператором: создание единицы измерения `SKEPTIC_TST` и её переименование (`POST`/`PATCH master-data/units/`), правка темы шаблона письма `quote_sent` (`PATCH admin/email-templates/2/` → 200, тема изменилась), тикет поддержки (создание, `assign` 200, `add-message` 201, `change-status` 200), лид (создание, PATCH). Повторный запрос журнала → **count = 22, ни одной новой строки**. Разбор `ActivityLog` за 20 минут: **новая запись ровно одна** — `support.ticket_status_changed`, и та в ленту доступа не попадает (отбор `event_code startswith "admin."`). По справочнику, письму и лиду — 0 записей.

ЗАМЕР 2 (глазами, Playwright, тот же стенд). Вход оператором → `#admin-access-log`: **22 строки в `tbody`**. Далее `#admin-master-data` → вк

**Происхождение:** Давний код, не регрессия волн 20-08.
- Бэкенд справочников `backend/master_data/views.py` — c2504a1d, 25-03-2026; операторский экран `AdminMasterDataPage.tsx` — aaf7d79d, 18-04-2026. Аудита у этого пути не было никогда.
- `EmailTemplateViewSet` — 6e8af4aa, 26-06-2026 (ADR-0004 Phase 1). Аудита не было никогда, только штамп `updated_by`.
- Сам «Журнал доступа» — 56f9b232, 29-06-2026 (G2 break-glass); отбор расширен до `admin.*` 20-08 волной #597 (3f4d27fc).
- След тикета поддержки — #468, 29-07-2026 (6287d02b).
Волны 20-08 (#595 «след действий», #597 «журнал показывал не то») касались именно эт

**Починка:** Два места, обе точки записи уже существуют — нужен вызов `core.audit.log_admin_action` в них (тем же приёмом, что волна #595).

1. `backend/master_data/views.py` — у `_CachedLookupListMixin` уже есть единственная развилка записи для всех четырёх справочников: `perform_create` / `perform_update` / `perform_destroy` (они дергают `_bump_version`). Туда же добавить `log_admin_action(entity_type=self.queryset.model._meta.model_name, entity_id=obj.pk, actor=self.request.user, event_code="admin.lookup.created|changed|deactivated", event_params={"model": ..., "code": obj.code}, before=..., after=...)`. Одна правка закрывает страны, валюты, единицы и базисы поставки. Для `before` брать снимок полей до `serializer.save()` (`code`, `name`, `is_active`, `sort_order`) — у `AbstractLookup` их четыре, дифф дешёвый.

2. `backend/notifications/views.py`, `EmailTemplateViewSet.perform_create/perform_updat

### 10. Деактивированная строка справочника исчезает из списка навсегда — вернуть её через интерфейс нельзя

**Тяжесть уточнена:** minor (в находке заявлен major). Данные не теряются: запись жива, `retrieve`/`PATCH` по id работают, суперпользователь возвращает её в Unfold за полминуты (`UnitOfMeasureAdmin` имеет `list_filter=["is_active"]` и `list_editable=["is_active"]`). Само скрытие из выпадающих списков — заявленное поведение («deactivate hides everywhere»). Тупик ограничен операторским инструментом и только откатом; арендаторов он не ломает и денег не касается. Но и не trivial: гасить может тот, кто не может включить, промах бьёт по всем арендаторам сразу (валюта/единица пропадает из форм всей платформы), а попытка и

**Чем подтверждено:** Стенд локальный, песочница своя (создал и убрал за собой: единицы `SBX-UOM-A1`/`SBX-UOM-B2`, пользователь `skeptic.op@sandbox.local`).

Шаги (Playwright, интерфейс в EN):
1. Вход `admin@railtech.uz` → `#admin-master-data` → вкладка «Units» → фильтр `SBX`.
   ЗАМЕР до: строк в таблице 1 — `SBX-UOM-A1 | Песочница агента A1 | 999 | Yes`.
2. Карандаш → в шторке переключатель «Active»: `aria-checked` true → click → false → «Save».
   Сеть: `200 PATCH master-data/units/25/`.
3. ЗАМЕР после: строк в таблице 0; текст страницы не содержит `SBX-UOM-A1`; после очистки фильтра на вкладке 18 кодов, моего среди них нет.
4. ЗАМЕР API тем же токеном: `GET master-data/units/` → 18 элементов, `SBX-UOM-A1` отсутствует. `?is_active=false`, `?is_active=0&page_size=100`, `?all=1` → те же 18, строки нет.
5. ЗАМЕР БД: `UnitOfMeasure.objects.get(code="SBX-UOM-A1")` → id 25, `is_active=False`; всего 20, активных 

**Происхождение:** Давний код, НЕ волны 20-08.
- Фильтр списка: `4c17e095`, 2026-06-23, «fix(master-data): lookup list endpoints serve ACTIVE-only (deactivate hides everywhere)» — единственный коммит, трогавший `_ActiveOnlyListMixin`.
- Сама страница с переключателем «Active»: `aaf7d79d`, 2026-04-18 (AdminMasterDataPage с CRUD). Поверхности для просмотра неактивных не было НИКОГДА.
Волны 20-08 к причине непричастны, но одна из них убрала теоретическую лазейку: `#593` (`029bdb32`, 20-08) закрыл дверь Unfold гейтом «суперпользователь или `system_engineers`», а миграция `accounts/0045_strip_staff_flag_from_non_engi

**Починка:** Суть: право `platform.settings` названо «Системные настройки и справочники» и даёт запись в справочники, поэтому у той же роли должна быть видимость неактивных записей. Возвращать `objects.all()` в общий список НЕЛЬЗЯ — на нём висят выпадающие списки всех арендаторов и общий кэш.

1) `backend/master_data/views.py` — в `_ActiveOnlyListMixin.get_queryset` снимать фильтр, когда запрос пришёл от платформенного админа И явно просит скрытые (`?include_inactive=1`), а в `_CachedLookupListMixin.list` добавить этот признак в ключ кэша (`lookup:{model}:{version}:{lang}:{scope}`), иначе привилегированный ответ осядет в общем кэше и утечёт всем. Гейт брать тем же предикатом, что и в `IsPlatformAdminOrReadOnly`, а не `request.user.is_staff`.
2) `frontend/src/pages/AdminMasterDataPage.tsx` + `frontend/src/hooks/useMasterData.ts` + `frontend/src/api/masterDataApi.ts` — переключатель «Показывать неактив

### 11. «Подтвердить KYC (L2)» из меню строки обходит обязательное обоснование

**Чем подтверждено:** Стенд локальный, оператор = суперадмин, интерфейс в EN. Песочница: две компании с НУЛЁМ KYC-документов, заполненным ИНН, статус PROFILE_SUBMITTED (id 77 «ZZZ Скептик Строка», id 78 «ZZZ Скептик Карточка»); после замеров удалены вместе с их записями журнала.

ЗАМЕР 1 — путь из строки (#admin-kyc → поиск → меню строки «Actions» → «Approve KYC (L2)»):
- диалог: «Approve KYC to L2 | … | KYC level PROFILE_SUBMITTED → L2_VERIFIED | Comment (optional)» — предупреждения о нехватке доказательств НЕТ;
- `confirmBtn.isDisabled()` до ввода причины = **false** (кнопка активна сразу);
- перехват сети: `POST accounts/companies/77/verify-kyc/` с телом `{"status_code":"L2_VERIFIED"}` — поля `reason` в теле НЕТ ВООБЩЕ;
- БД после: `Company 77 → verification_status=L2_VERIFIED, is_verified=True, kyc_documents=0`;
- журнал: `ActivityLog(entity_type='company', entity_id=77)` → `action='KYC: подтверждение', r

**Происхождение:** Давний код, не волны 20-08. Дыра появилась вместе с самим гардом: ab05b097 «fix(kyc): F4 — no-evidence KYC verification requires a warning + justification» (2026-07-02) добавил ровно одну строку `requireReason={missingEvidence}` — в диалог карточки. В том же файле AdminKYCPage.tsx на момент коммита-предка (`ab05b097^`) уже существовал путь из меню строки (`id: 'approve-l2'`, строка 577) со своим диалогом на `showReason` (строка 625) — его F4 не тронул. Сам ряд действий строки живёт с 17a0000c (2026-04-23). Рефактор 6d8a7c0f (#371, 2026-07-21) разнёс файл на `admin-kyc/index.tsx` + `DetailSheet

**Починка:** Чинить в сервисе, а не в четвёртом диалоге — иначе следующий путь снова обойдёт (уже сейчас путей четыре, включая аварийное действие Unfold `backend/accounts/admin.py:246`).

1. `backend/accounts/services/kyc.py` → `verify_company_kyc`: рядом с существующей проверкой понижения добавить проверку ПОВЫШЕНИЯ без доказательств — если целевой уровень ≥ L2, `require_documents=False`, и у компании нет ни одного `kyc_documents` и/или пустой `inn`, то при пустом `reason` возвращать код (например `KYC_REASON_REQUIRED_WITHOUT_EVIDENCE`) вместо тихого подтверждения. Это разом закрывает меню строки, массовое действие (`bulk_verify_kyc` — там ошибка сама попадёт в `skipped`), очередь триажа и сырой POST по API. Обязательно тест на КАЖДЫЙ путь, а не только на сервис.
2. Признак нехватки доказательств вынести из `frontend/src/pages/admin-kyc/DetailSheet.tsx` (строки 68–76) в общий хелпер и подключить `re

### 12. Массовое «Одобрить L2» обещает пропускать компании без документов, а на деле их одобряет

**Тяжесть уточнена:** major остаётся, но направление починки в находке нужно перевернуть: «начать пропускать компании без документов» — ЗАПРЕЩЕНО (прямо противоречит owner policy 2026-06-03 и CLAUDE.md:526). Вес находке даёт не сам факт одобрения без документов, а то, что массовый путь одновременно (1) врёт про несуществующий предохранитель и (2) в отличие от одиночного пути не берёт обязательного обоснования — в журнале остаётся reason='' по выдаче уровня L2, который открывает подачу заявок и отправку/экспорт КП. Если бы дело было только в устаревшей строке — это был бы minor.

**Чем подтверждено:** 1. Создал в БД две компании с НУЛЁМ документов: id 79 «ZZSANDBOX NoDocs Alpha» (L1_UNVERIFIED), id 80 «ZZSANDBOX NoDocs Beta» (PROFILE_SUBMITTED). Замер до: docs=0, is_verified=False.
2. Playwright, вход оператором (admin@railtech.uz), #admin-kyc, поиск «ZZSANDBOX» → в таблице ровно 2 строки, колонка «Документы» = 0 у обеих.
3. Отметил обе строки, нажал «Approve L2 (bulk)» (кнопка видима: BULK BTN visible: true).
4. ЗАМЕР ТЕКСТА диалога (innerText): «Approve L2 (bulk) | KYC will be approved to L2 for 2 companies. Skipped items (missing documents, etc.) will be listed separately. | Comment (optional) | Cancel | Approve». Предупреждения «без документов» нет, причина помечена как необязательная.
5. Подтвердил С ПУСТОЙ причиной. ЗАМЕР СЕТИ (page.on('response')): 200 POST /api/v1/accounts/companies/bulk-verify-kyc/ → {"approved":2,"skipped":[]}. Тост: «Approved: 2, skipped: 0».
6. ЗАМЕР БД по

**Происхождение:** Давний код, НЕ волны 20-08.
— Текст диалога kycManager.bulkApproveDesc появился в 17a0000c (2026-04-23, «feat: enhance admin pages…»), когда документы для одобрения ТРЕБОВАЛИСЬ, и тогда был правдой.
— Расхождение внёс 407e8d5a (2026-06-03, «fix(kyc): approve without requiring documents + unstick Radix pointer-events»): коммит поменял только backend/accounts/services/kyc.py и backend/accounts/views/company.py (+ App.tsx), i18n-строку и массовый диалог не тронул. git blame по bulk_verify_kyc подтверждает: строки «Owner decision 2026-06-03» и require_documents=False — из 407e8d5a.
— Волны 20-08 н

**Починка:** Бэкенд НЕ трогать: require_documents=False в backend/accounts/services/kyc.py:193 — утверждённая политика владельца.

1) frontend/src/i18n/locales/ru.json + en.json, ключ kycManager.bulkApproveDesc — убрать обещание про пропуск «нет документов». Текст должен называть правду: одобряется N компаний, наличие документов НЕ проверяется, среди них M без документов/ИНН.

2) frontend/src/pages/admin-kyc/index.tsx (массовый диалог, ~строки 280-300 + runBulkApprove) — довести до той же владельческой политики, что и одиночный путь: посчитать по выборке компании с kyc_documents.length === 0 и с пустым inn, показать тот же warning-блок kycManager.approveWithoutEvidence со списком имён, поставить requireReason (сейчас showReason) и variant='warning', когда такие компании в выборке есть. Эталон — frontend/src/pages/admin-kyc/DetailSheet.tsx:72-76 (evidenceGaps/missingEvidence) и :350-366 (requireReason

### 13. «Отозвать верификацию» на компании в L1 пишет в журнал зелёную запись об успехе

**Чем подтверждено:** Стенд локальный. Песочница создана и удалена мной.

1. Создал компанию `SKEPTIC-L1-SANDBOX` (id 82), ИНН 907070707, `verification_status=L1_UNVERIFIED`, `is_verified=False`, документов 0, записей журнала 0.
2. Вошёл оператором (admin@railtech.uz), `#admin-kyc`, поиск «SKEPTIC». Строка: `SKEPTIC-L1-SANDBOX | 907070707 | Pending | 0 | 8/21/2026`.
3. Открыл меню действий строки. ЗАМЕР доступности пунктов (`data-disabled` / `aria-disabled`):
   `[{"text":"Approve KYC (L2)","disabled":false},{"text":"Revoke verification (L1)","disabled":false}]`
   → «Отозвать верификацию (L1)» на компании в L1 АКТИВНА (в карточке компании та же кнопка disabled — расхождение налицо).
4. Клик по ней. Диалог сам печатает признак пустого действия:
   `KYC level | L1_UNVERIFIED → L1_UNVERIFIED | Reason * …`
5. Ввёл причину, нажал «Revoke». Ответ сервера 200, тост: `KYC revoked` (успех).
6. ЗАМЕР В БД сразу после 

**Происхождение:** ДАВНИЙ КОД, не волны 20-08 (#593–#597 к этому пути не прикасались).
- Логика `LEVEL_RANK` / `is_downgrade` со строгим `<` появилась в `92565688` (2026-04-23, `backend/accounts/services.py`), переехала в `backend/accounts/services/kyc.py` при `9c669488` (2026-06-02, распил services.py), правилась только косметически в `ba2e5d3f` (2026-06-11) и `05debc39` (2026-07-13).
- Строковое действие «Отозвать верификацию» без гарда и одновременно гард в карточке компании пришли одним коммитом `17a0000c` (2026-04-23), перенесены как есть в `frontend/src/pages/admin-kyc/index.tsx` при распиле `6d8a7c0f` (20

**Починка:** 1. `backend/accounts/services/kyc.py`, функция `verify_company_kyc` (строки ~50–60). Отсечь равный уровень ДО записи: если `level_code == current_code` — вернуть `(None, "KYC_LEVEL_UNCHANGED")` и не делать ничего (ни save, ни log_admin_action, ни on_commit-письма/уведомления, ни `auto_populate_history`). Менять только знак сравнения на `<=` нельзя — тогда «подтверждение» L2→L2 поедет по ветке понижения; нужен именно ранний выход на равенстве.
2. `frontend/src/pages/admin-kyc/index.tsx`, `rowActions` → пункт `id: 'revoke'`: дать ему тот же гард, что уже стоит в `DetailSheet.tsx:283` — скрывать/дизейблить, когда `getStatusCode(c) === 'L1_UNVERIFIED'`. Плюс обработка нового кода в `translateApiError` и ключи в `ru.json`/`en.json` (Rule 5).
3. Тест в `backend/accounts/tests/test_kyc_service.py` (рядом с `test_verify_company_kyc_downgrade_needs_reason`): L1→L1 возвращает `KYC_LEVEL_UNCHANGED`

### 14. «Удалить» компанию физически стирает её и обезличивает участников — диалог о людях не предупреждает

**Чем подтверждено:** Стенд локальный, песочница создана и убрана за собой.
1. Создал компанию «SBX Delete Probe» (id 87, ИНН 903471288), двух участников owner@sbx-delete.test (id 80, OWNER) и mate@sbx-delete.test (id 81), сделку id 48 (company=87, client=80) и сообщение в ней.
2. ЗАМЕР ДО (manage.py shell): company_87_exists=True · user 80 memberships=1 primary_company=«SBX Delete Probe» · user 81 memberships=1 · memberships_of_87=2 · deal_48_exists=True · messages_of_deal_48=1.
3. Прошёл путь глазами оператором (admin@railtech.uz), Playwright: #admin-companies → меню строки (пункты: Edit company / Merge duplicates / Delete) → Delete. Текст диалога снят дословно: "Delete company?\n\nCompany \"SBX Delete Probe\" and all related data will be removed.\n\nCancel\nDelete".
4. Подтвердил. Перехват сети: 204 DELETE http://localhost:8000/api/v1/accounts/companies/87/ (ни 409, ни 500).
5. ЗАМЕР ПОСЛЕ: company_87_exis

**Происхождение:** Давний код, не волны 20-08. Кнопка «Удалить» на экране компаний пришла с самим экраном — aaf7d79d, 2026-04-18, «feat: add AdminCompaniesPage, AdminDealsPage, and AdminMasterDataPage with CRUD functionality». Бэкендовый `destroy` — дефолтный `ModelViewSet` без переопределения с самого начала (файл backend/accounts/views/company.py выделен распилом 83412b30, 2026-04-25, поведение перенесено как есть). Волны 20-08 к дефекту не причастны, но прошли рядом и его не закрыли: #594/#595 чинили и аудировали ровно соседние операторские действия (удаление пользователя получило гард `can_delete_user`, деак

**Починка:** Три части, порядок по важности.

1) Гард на бэкенде — зеркало того, что уже сделано для пользователя. backend/accounts/views/company.py: добавить `destroy`, который зовёт новый сервис (Rule 8) `can_delete_company(company)` рядом с `can_delete_user` (backend/accounts/services/members.py:159) и при непустой истории отдаёт 409 `{"detail": "COMPANY_HAS_HISTORY_DEACTIVATE_INSTEAD"}`. Признаки истории: любые Deal (company / DealSellerRouting.seller_company), Quote, SupplierOffer, GeneratedDocument, активная SupplierSubscription, активные CompanyMember. Эталон уже процитирован в докстроке `can_delete_user` (Salesforce — удалить нельзя, Odoo — архив), так что это не новая блокировка, а приведение к заявленному. У `Company` нет флага для архива — если владелец выберет путь «архивировать», нужна миграция с `is_active`/`archived_at` и фильтрация в выборках; минимальный вариант без миграции — запрет


## Опровергнуто

### Отключение права поверх оплаченной подписки отрезает продавца, а причина ему показывается локализованной строкой чужого языка

`by_design` — Находка склеена из двух утверждений: первое — осознанное решение, второе не воспроизводится вовсе.

1) «DISABLED поверх подписки отрезает продавца» — ЭТО И ЕСТЬ НАЗНАЧЕНИЕ значения DISABLED, зафиксированное в трёх местах:
• backend/accounts/services/entitlements.py, has_entitlement: «row.is_currently_granted()  # an explicit grant/revoke/demo ALWAYS wins»;
• backend/accounts/models/subscriptions.p

### Поле «Название» в справочниках стран и единиц ничего не меняет для арендатора

`by_design` — Замер опровергает находку в обеих её половинах.

ЕДИНИЦЫ — утверждение ПЕРЕВЁРНУТО. Переименовал `UnitOfMeasure` DAY «сутки» → «SKEPTIC-СУТКИ-21» (PATCH /api/v1/master-data/units/17/, 200; БД подтверждает). Пикер арендатора действительно показал «day» — это i18n-подпись `t('uoms.day')`. НО дальше: покупатель выбрал эту опцию, строка сохранилась как `QuoteItem#144 unit='SKEPTIC-СУТКИ-21', unit_code

