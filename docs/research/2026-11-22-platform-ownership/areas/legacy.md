# Area F: old and new piled together (read-only, main @ 2ecd40446)

Paths are relative to ``. `web/` = `apps/platform/web/src/`, `bff/` = `apps/platform/bff/app/`, `plan` = `docs/runbooks/plan-2026-11-12.md`.

## 1. Duplicate cards and views of one object

| # | What exists (evidence) | What the user sees | Plan row |
|---|---|---|---|
| 1 | **Two lead cards.** The «Ждут ответа» view of Лиды renders the old `Conversations` page from `crm/messages` (`web/modules/crm/leads/LeadsPage.tsx:39,463-474`), with its own card `crm/messages/LeadCard.tsx:24` (inside `Dialog.tsx:176,180`, data model `ConversationCard`). The other views open `LeadPanel` (`LeadsPage.tsx:565`, data model `LeadCard` from `useGetCrmLead`). | One switch in the filter row swaps the whole layout: table + side card vs inbox list + chat + a different card | **None.** ЕД-7 names its card order (проект, заказ, счёт, согласование, КП, входящее, «остальные»); the lead card is not named |
| 2 | **Three views of one memo**: `eds/documents/DocumentCard.tsx` (side panel in the registry, via `DocumentSheet`, `DocumentsPage.tsx:644`); `eds/approvals/MemoView.tsx` (`/eds/approvals/:id`, in-page aside :173); `eds/payments/MemoView.tsx` (`/eds/payments/<uuid>`, `PaymentsScreen.tsx:16`, aside :66) | The same служебка looks different in Документы, in approval and in Финансы | Partly: ДОК-11 («карточка документа … служебная записка»), ЕД-7 PR-2 («согласование»). The payments `MemoView` is not named anywhere |
| 3 | **Inbound letter, two pages**: `eds/inbox/LetterView.tsx` (aside :337) and `eds/tasks/TasksScreen.tsx` (`/eds/tasks/:id`, aside :125) | The letter looks different when opened from «Задачи» | ЕД-7 («входящее», then «остальные»), ДОК-11 |
| 4 | **Request vs project.** `/erp/requests/:id` and `/erp/calc/:id` render the same `CalcScreen` (`erp/index.tsx:47-56`). `/eds/projects/:id` renders `ProjectView`. `docs/product/NAVIGATION.md` «Операции» says «одна карточка … номер ЗВ ведёт туда же, куда ПР» | Two cards and three URLs for one object (inference) | **None** |
| 5 | **Two side-sheet implementations.** `DocumentSheet.tsx:28-49` has its own antd `Drawer` on mobile, a copy of `shared/ui/Sheet.tsx:27-41`. Its comment still says «Drawer 360 px» (:10-11), while the standard allows only 480/640 | — | None |
| 6 | **In-page asides: 7.** `PaymentView.tsx:219`, `approvals/MemoView.tsx:173`, `payments/MemoView.tsx:66`, `QuoteView.tsx:217`, `LetterView.tsx:337`, `MailView.tsx:90`, `TasksScreen.tsx:125` | A narrow column inside the page, as well as the side panel | ЕД-7, decision (3). PR-2 covers 4 of them (invoice, approval, quote, inbound). Payments `MemoView`, `MailView` and `TasksScreen` fall under «остальные» only |

## 2. Old mechanism still present after a new one replaced it

- **`/eds/addressees` vs the counterparty picker.**
  - The old endpoints still exist: GET and POST `/eds/addressees` and `/eds/addressees/{id}/people` in the BFF (`bff/api/people_contacts.py:354,373,406`) and the contract (`platform-bff.yaml:13658-13735`). The contract text still says «Ручной ввод адресата остаётся» (:13665).
  - They still have MSW mocks: `web/mocks/peopleContacts.ts:88-111`.
  - The web app no longer calls them: `CompanyPicker` uses `useSearchCounterparties` (`shared/ui/pickers/useCompanySearch.ts:1,18`).
  - Plan: **none** (ЕД-6 replaced the usage but has no removal row).
- **RecipientField:** no remnants (grep finds nothing). But the letter form keeps a free-text «Кому (должность и ФИО)» (`NewDocumentPage.tsx:684-700`, `documents.json:409-411`) next to the new picker «Кому — человек» (:641-657), and a free-text «Почта адресата» (:660-683). This is screenshot (a).
  - Branch `fix/form-squeeze` (commit 09ab830e2, not merged) fixes only the field width.
  - Plan: ЕД-6 covers the email being filled in by selection; the duplicated «Кому» has **no row**.
- **HTML template editors.** Document templates edit `body_html` (`admin/company/tabs/DocumentTemplates.tsx:31,251-285,375`); email templates edit `html_body` (`EmailTemplates.tsx:29,315`). Plan: ДОК-10 («HTML-поля у шаблонов нет»), ДОК-15.
- **Templates in four places.**
  - `/admin/templates` has 4 tabs (`TemplatesPage.tsx:14`).
  - «Все шаблоны» also lists resolutions and bot answers (`TemplateCatalog.tsx:16-18`), which have their own pages: `/admin/resolutions` and `/admin/telegram?tab=templates` (`TelegramPage.tsx:17,41`).
  - The menu shows templates under Документы (`navigation.ts:97`). The registry keeps the entry in Settings group «Компания» (`settingsRegistry.ts:359-374`); it is hidden from the Settings menu (`navigation.ts:138`) and index (`SettingsHome.tsx:168`) but still found by settings search.
  - Plan: ДОК-10 removes resolutions and bot answers from the shared table. The two-menu placement has **no row**.
- **Integrations page vs own pages.**
  - `TelegramPanel` is rendered in 3 places: `IntegrationsPage.tsx:360`, `TelegramPage.tsx:38`, `setup/StepPanel.tsx:11`.
  - `MailPanel` in 2: `IntegrationsPage:362` and `pages.tsx:85`.
  - `SpendPanel` in 2: `IntegrationsPage:368` and `pages.tsx:152`.
  - The `CardPanel` branches for telegram, mail and spend can never run: the card links go to the own pages (`IntegrationsPage.tsx:61-65`), and `?card=` is redirected anyway (`redirects.ts:57-61,105-108`).
  - Plan: СЦ-3 («Подключения — одно состояние»). **No dedup row.**
- **Notifications in two homes.** Settings·Уведомления (`pages.tsx:121-145`; it also holds the КП reminders) and the profile (`/me?part=notifications`). ДОК-15 and ГЛ-2 each add more to these. **No consolidation row.**
- **Knowledge base in two places.** Контакты·База знаний (`crm/module.ts:31-38`, `navigation.ts:90`) and a Settings·Telegram tab that only links to `/crm/kb` (`TelegramPage.tsx:20,43-56`). **None.**
- **Справочники in two homes.** Settings·Справочники (`DictionariesPage.tsx`) and Операции·Каталог·Справочники (`CatalogScreen.tsx:16,46`; `RefsPanel.tsx:43`: ТН ВЭД, brands, category requests). Exchange rates `RatesView` live in `erp/catalog/RefsPanel.tsx:77` but are shown in Settings·Налоги (`pages.tsx:17,58`). Plan: only Х-6 (file mapping).
- **Code folders mirror the old Settings layout.**
  - `admin/docflow` (the deleted «Документооборот» page, `redirects.ts:50-54`), `admin/bot` (old «Telegram-бот»), `admin/company/tabs` (old tabs) now feed the new pages.
  - Comments still name a group «Процессы» and «пять групп»: `admin/module.ts:40-41`, `pages.tsx:120`, `TemplatesPage.tsx:17`, `platform-rbac.yaml:456-459`. The code has 4 groups (`settingsRegistry.ts:14`).
  - `NAVIGATION.md` says 20 settings screens; the registry has 21.
  - Plan: none.

## 3. Dead routes and redirects kept

The RBAC menu still lists them (`platform-rbac.yaml:421-451`).

- **7 redirect-only sections, no screen of their own:**
  - `dashboard.projects` → `/eds/projects` (`dashboard/index.tsx:35-37`)
  - `crm.messages`, `crm.requests`, `crm.channels` (`crm/index.tsx:21-33`)
  - `eds.outbox` (`eds/index.tsx:126-132`)
  - `chats.internal`, `chats.external` (`chats/index.tsx:15-20`)
- **4 sections whose list address redirects:** `eds.drafts`, `eds.approvals`, `eds.tasks` (`eds/index.tsx:24-41`), `erp.calc` (`erp/index.tsx:47-49`).
- **Old address maps:**
  - Settings: `/admin/bot`, `/admin/docflow`, `/admin/company?tab=`, `/admin/templates?tab=quote`, `/admin/tickets`, `/admin/integrations?card=` (`redirects.ts:83-110`).
  - Catalog `part=applications|suppliers` (`erp/index.tsx:20-30`).
  - Payments `show=bank_changes` (`eds/index.tsx:111-113`).
- **Help articles still bound to redirect-only addresses:** `docs/kb/help/leads.md:5`, `drafts.md:5`, `projects.md:5`, `channels-and-kb.md:5`, `admin-tickets.md:5`.
- **Menu module ≠ URL module in 4 places:** Главная·Проекты → `/eds/projects` (screenshot c), Контакты·Почта → `/eds/mail`, Документы·Шаблоны → `/admin/templates`, Органайзер·Люди → `/chats/contacts`.
- Plan: NAVIGATION «Адреса» deliberately keeps redirects. There is **no expiry or removal row** (Х-14 cleans branches and docs only).

## 4. Placeholders («Данные появятся здесь», «Скоро», empty tabs, «позже»)

| Where | Evidence | Plan |
|---|---|---|
| Органайзер·Чаты: the whole screen is a disabled mock-up | `ChatsPage.tsx:20-56`; SoonButton «Созвон» :29; `modules.json:248` | Х-9, Х-7 |
| Органайзер·Люди: SoonButtons «Написать», «Позвонить»; «Данные появятся здесь» | `PeoplePage.tsx:221,277-278`; `modules.json:262` | Х-7 covers messaging only. «Позвонить»: **none**, although `NAVIGATION.md` promises dialling |
| Главная·Сводка: 3 blocks (requests, profit, targets) with «Данные появятся здесь» | `SummaryPage.tsx:17,101-109`; `modules.json:129` | ГЛ-3, РЕФ-13, Х-9 |
| «Создать»: «Сообщение» and «Поручение» marked «вместе с чатами» | `createKinds.ts:84-97`; `CreateMenu.tsx:159-162` | Х-7 |
| Side panel fallback «Объект не выбран» (screenshot a); false text in `panel.chat`: «Чат проекта создаётся вместе с заявкой…» | `PanelContent.tsx:25-31`; `panelSlotContext.ts:61-62` (when no tab is filled, the first one is shown); `modules.json:805-811` | ЕД-7 («заглушек нет»). Merged PR-1 left this fallback |
| Tabs declared but filled by no screen: chat, documents, route, about, files | `eds/module.ts:28,73,81,89`; `erp/module.ts:4`; `chats/module.ts:3`; `types.ts:75-87`. No `PanelPortal` uses these tabs anywhere | ЕД-7 hides them. NAVIGATION promises «у каждого объекта вкладка Документы» (Х-5 covers project and counterparty only) |
| Promises of «позже» | `calc.json:266` (`TaskPanel.tsx:125`); `catalog.json:591` (`DocsScreen.tsx:453`); `catalog.json:620,628,973` (`DocPassport.tsx:116`); `documents.json:256` (`NewDocumentPage.tsx:740`, «Выбор конкретного адресата появится позже»); `shell.json:3,271-272` | СЦ-7 bans «появится позже», yet these remain after SC-7 PRs #797, #798, #799 and #811 merged |

## 5. Unused BFF endpoints and MSW mocks

The contract has 489 operations; 27 are never called from web code through a hook or function. 12 of those are reached by URL instead (downloads, images, avatar, iCal, SSE, health, console auth), so they are not dead (inference).

These 15 look dead:

| Operation | Contract line | BFF and mock |
|---|---|---|
| searchEdsAddressees, createEdsAddressee, listEdsAddresseePeople | `platform-bff.yaml:13658-13735` | see §2 |
| create/update/deleteReferenceItem | 8144-8227 | mock `adminCompany.ts:830-867`; only the list is used |
| getEdsTemplate, deleteEdsTemplate | 3114-3167 | — |
| findLetterDuplicates | 9787 | `bff/api/eds_letters.py:252`; mock `edsLetters.ts:255` |
| listExternalChats | 11470 | `bff/api/chats.py:39`; the section redirects away |
| listOverdueSupplierOrders | 12643 | `bff/api/erp_stock.py:426` |
| listQuoteApprovals (the old «КП на одобрение» list) | 3538 | mock `edsApprovals.ts:308` |
| getEmployee, getRole, getExternalService | 6793, 6989, 5837 | — |

Plan: **none** (Х-17 covers only the numbers inside mocks).

**Queue kinds never produced** (they appear only in `bff/feeds/models.py:41-74` and the RBAC catalog):
- `create_request`, `service_request`, `problem_project`, `overdue_invoice`, `integration_issue`, and `register_reply` (marked obsolete at `platform-rbac.yaml:528-530`).
- `CalendarPage.tsx:29-52` still maps them.
- The company setting «remind_overdue_invoices» (`QuoteTab.tsx:43,194`) exists, but nothing produces an `overdue_invoice` row (inference).
- Plan: none. ГЛ-2 («задач без сигнала нет») does not cover removing them.

## 6. i18n keys without users and feature flags

These have zero code references, checked one by one:
- `catalog.suppliers.{search,table,open,card,tin,columns,nearest,empty,reg,add}` — the old suppliers list
- `letters.settings.*` (`letters.json:1093-1100`) — the old «Документооборот» page
- `projects.panel.{contractLabel,actLabel,sheetContract,sheetAct,sheetContractNone,sheetActNone,journalEmpty,journalHint}` (`projects.json:241-249`)
- `projects.contract.history`, `contract.historyEmpty`, `act.historyEmpty`, `journal.bySystem`
- `shell.soonPilot` (`shell.json:4`), `calc.task.empty`, `company.tabs.platform`, `stock.order.logTitle`, `stock.order.details`, `letters.card.returned`, `letters.mail.spamEmpty`, `letters.mail.historyEmpty`

A pattern scan flagged 281 of 4178 key groups as possibly unused. Most are false positives from keys built at runtime; only the list above is confirmed. Plan: none.

**Feature flags:** none in the web app or the BFF. Only the dev-only `VITE_API_MOCKING` (`main.tsx:18`) and the `/dev/ui` showcase (`router.tsx:30`).

## 7. TODO, «хвост» and stale comments

- **BFF:**
  - `feeds/text.py:3` (uz/en translation is a «хвост P2»); `text.py:17` TODO(ERP-17), time zone is a constant
  - `activity.py:69` and `notifications.py:224` TODO(ERP-16); `queue.py:200` TODO(CRM-08)
  - `events.py:12` «хвост P2»; `numbers.py:30,79` («хвост PLT-2x», «Клиенты · Заявки — заглушка»)
- **Web:**
  - `ProofsBlock.tsx:185` (no automatic send, «хвост B-D24-1»); `features/help/articles.ts:4`
  - `shared/api/http.ts:5` («экран входа появится в фазе P1» — stale); `SoonButton.tsx:6`; `PanelContent.tsx:9`; `types.ts:46`
  - «остальные разделы пока заглушки» in `dashboard/index.tsx:14`, `crm/index.tsx:9-12`, `eds/index.tsx:19`, `chats/index.tsx:10`
  - `GlobalSearch.tsx:85-86` describes a «мост в старый экран» that is not implemented
  - `ModuleMenu.tsx:12` has a `hint` prop («ещё в старой системе») that nothing passes (`AppShell.tsx:217-247`)

## 8. Two generations of frames and windows

- **Table frame:** the header-band card `DataBlock` is used in 9 files; `DataTable` in 36. Projects uses it (`ProjectList.tsx`); People does not (`PeoplePage.tsx:223`). That is the difference between screenshots (b) and (c). Standard §9.1 does not define a frame. Plan: only UI-10 (a check).
- **Window components:**
  - In use: `FormSheet` (13 files), `Sheet` (5), `DocumentSheet`, `DecisionSlot`, direct `PanelPortal` (≈20 files), `HelpDrawer`. `ui-standard.md` §6 says there is one component, `FormSheet`.
  - The «docked» mode (`ContextPanel.tsx:31-37`) squeezes the page, while §6 says the panel «не сжимает» it. This is screenshot (a).
  - Plan: П-1 and UI-10 (both in §4.7, last).

## 9. The plan: open blocks and which owner complaint each addresses

Complaints: **I** = identity / single style, **W** = windows, **S** = settings, **IA** = module logic, **D** = duplicates / old+new.

| Block | Open rows | Addresses |
|---|---|---|
| §4.0a | СЦ-3 (readiness), СЦ-5, СЦ-6, СЦ-9, СЦ-8 (true statuses), СЦ-11 (inbound), СЦ-7 (texts and numbers, no «позже») | S (СЦ-3), I (СЦ-7) |
| §4.1 | ЕД-4, СУЩ-3, ЕД-3 (common person/item components), ЕД-6 (pick, not type), ЕД-7 (one place per fact), ГЛ-0…ГЛ-3 (home), ЕД-5 | I (ЕД-3/4), W and D (ЕД-7), IA (ГЛ: home only) |
| §4.2 | ДОК-8, ДОК-4, ДОК-5, ДОК-7, ДОК-15 (emails into Notifications), ДОК-6, ДОК-13, ДОК-14, ДОК-9 (one editor), ДОК-10 (templates), ДОК-16, ДОК-11 (document card), ДОК-12 | I (PDF), D (ДОК-9/10/11), S (ДОК-15/10) |
| §4.3 | ДВ-4б, ДВ-5, ДВ-7 | — |
| §4.4 | ДК-1…ДК-5, ЛИД-2…ЛИД-6, РЕФ-1, РЕФ-2 | — (Cabinet) |
| §4.5 | РЕФ-4…РЕФ-16 | I (partly: РЕФ-6 empty states, РЕФ-14 empty columns) |
| §4.6 | Х-1, Х-4…Х-19 | D (Х-7/Х-9 placeholders, Х-10, Х-14), S (Х-8 setup wizards) |
| §4.7 | П-1 (screen-area rules), UI-10 (standard check), 0.13 | I, W |

**Complaints with no plan row at all:**
1. **IA / module ownership.** Nothing re-homes Почта, internal documents, Проекты or Органайзер scope. Connectors wait on 13 owner questions (plan §4.0, row 2026-11-22).
2. **Settings consolidation.** Nothing covers the duplicate Telegram/Mail/Spend panels, notifications in two homes, the knowledge base in two places, templates in two menus, or справочники in two homes.
3. **Removing old+new remnants.** Nothing covers the redirect-only sections, the 15 dead endpoints and their mocks, the never-produced queue kinds, dead i18n keys, the two lead cards, or the request-vs-project cards.
4. **Identity adoption.** Only the end-of-queue check UI-10 exists; there is no row to bring all registries onto one frame (`DataBlock`).

**Inconsistencies inside the plan and docs:**
- The plan's own rule is that finished rows move to §3 (`plan:64`). Yet СЦ-3, СЦ-5, СЦ-6 and СЦ-9 are reported closed (`plan:282,284`) and still sit in §4.0a. ДОК-13 was merged (#806) and is still in §4.2. Branches `sc8-*` and `sc11-inbox` are merged but their rows remain.
- `ui-standard.md:9` places UI-10 in §4.5; it is actually in §4.7.
- `NAVIGATION.md` «Коннекторы» says «не готовое подписано «Скоро»», which contradicts СЦ-3 «без пунктов «Скоро»».
- `PROGRESS.md` has no UI-0…UI-10 entries at all (grep finds nothing).

## 10. Numbers

- **Sections:** 54 in total.
  - By module: Главная 3, Контакты 6, Документы 11, Операции 5, Органайзер 5, Настройки 24 (21 registry pages + index + setup + tickets).
  - 7 are redirect-only, 4 redirect their list, 1 is a disabled mock-up (Чаты).
  - The menu has 18 main items plus 4 Settings groups (20 pages shown as tabs).
- **UI standard adoption** (from the plan archive, `docs/history/runbooks/plan-2026-11-12-archive.md:98-108`):
  - UI-1, UI-2, UI-3, UI-4 and UI-7 are global (tokens, fonts, icons, linters).
  - UI-8 (filter row) names 21 registries; UI-6 («Столбцы») names 7; UI-5 moved forms in the catalog, warehouse and company settings.
  - Screens not named in UI-5, UI-6 or UI-8 (inference): Задачи, Сводка, Календарь, Чаты, Новый документ, and the Settings pages Реквизиты, Нумерация, Налоги, Продажи, Почта, Формы сайта, Время, Уведомления, Сервисы, Выгрузки, Роли — about 16.

## 11. Where the facts disagree with the owner's draft

- **«Лиды только с бота и сайта».** The code has 6 lead channels: telegram, cabinet, web, email, phone, referral (`LeadsPage.tsx:57`). Mail triage creates leads (`letters.json:812`). Taking Почта out of Контакты removes the triage screen for one lead source, so it needs a new home.
- **«Органайзер — общение с клиентами и партнёрами по проекту».** `NAVIGATION.md` decided «Чаты только внутри компании», and `chats.external` redirects to Лиды·Ждут ответа (`chats/index.tsx:18-20`).
- **«Убрать внутреннюю переписку из Документов».** A служебка on payment authorises money. Today it appears in Документы·Внутренние (`navigation.ts:95`) and in Финансы (`navigation.ts:73-75`), with three different cards (§1 #2).
- **Connectors.** Already decided on 2026-11-10 (`NAVIGATION.md` «Коннекторы»: Настройки·Подключения, Yandex 360 first). The calendar iCal feed is merged (branch `w22/cal-ical`). The rest waits on the 2026-11-22 research.
