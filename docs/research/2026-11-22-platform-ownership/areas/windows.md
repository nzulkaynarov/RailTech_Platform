# AREA A: why the windows look like a zoo, and how components drift from the identity rules

Source: read-only checkout `/home/umarbek/projects/RailTech_Platform/.claude/worktrees/research-main` (HEAD 2ecd40446, after ЕД-6 and ЕД-7 PR-1). All paths below are relative to `apps/platform/web/src/` unless they start with `docs/` or `packages/`. Nothing was built or run. Counts come from grep over 385 non-test `.tsx` files. Points marked **(inference)** are my reasoning, not something the code states directly.

## 0. Short answer
- The identity standard is real and mostly enforced for **centre dialogs, status tags, icons and colours in CSS**.
- It is **not** enforced for **side drawers, table appearance, form fields, pagination or page headers**. Each module brings its own CSS or its own copy of a wrapper there. That is where the "zoo" comes from.
- Three root causes:
  1. **The shared `DataTable` has no look of its own.** Every module adds its own CSS class for the header band, borders and alignment. There are 10 near-identical classes, and 23 table screens get no class at all. That is the bare «Люди» table.
  2. **The linter blocks `Modal` but not `Drawer`, `Popconfirm`, `Descriptions` or `<table>`.** It also covers only `src/modules`, not `features`.
  3. **The two governing docs disagree.** `platform-frontend.md` still states the old widths, field-count thresholds and colours. `ui-standard.md` overrides them only by a precedence sentence (ui-standard.md:8-9).

## 1. Windows and containers

Standard (ui-standard.md §6, lines 101-117):
- Centre window: 448 px, for 1–3 fields (`Dialog`; a simple question uses `modal.confirm`).
- Side panel: 4–15 fields, width «**480** или **640** — других ширин нет».
- Page with `StepSections`: more than 15 fields.
- Panel has a fixed header (title 16/600, status, ✕) and a fixed footer («Отмена», then «Сохранить» on the right). One shared component: `FormSheet`.

| Pattern | Component | Width | Title / buttons | Close | Phone | Where used | Verdict |
|---|---|---|---|---|---|---|---|
| Centre dialog | `shared/ui/Dialog.tsx:15-73` (AntD Modal) | 448 | title in header; footer «Отмена» + primary on the right | ✕, Esc, «Отмена»; outside click off; content cleared on close | **no bottom sheet** (no mobile branch; only 2 `.ant-modal` CSS rules exist, neither for this) | 20 files: erp/catalog/common, erp/calc/MatchModal, crm/messages/HandOver, admin/signing/RevokeModal, eds/inbox/ResolutionTemplatePicker, eds/new/LetterAssist, eds/drafts/ClientDecision, erp/catalog/PartnerApplicationsPanel, eds/approvals/SigningList, eds/payments/BankChangesPanel, eds/tasks/LetterOutcomes (×4), eds/documents/LetterSection, eds/mail/BulkArchive, erp/stock/OrderModals (×4), erp/stock/AdjustModal, erp/calc/Rejection, admin/company/common, eds/inbox/MarkDuplicate, eds/projects/DeliveryMarks, features/profile/SecondFactorSection | Compliant. Every Dialog I checked has ≤3 fields. platform-frontend §4.1a says the phone should get a bottom sheet; it does not. |
| Module wrappers around Dialog | admin `FormModal` (admin/company/common.tsx:338), admin `ConfirmModal` (:444), catalog `FormModal` (erp/catalog/common.tsx:156) | 448 | admin shows errors **above** the fields, catalog **below** | — | — | admin settings tabs, catalog | Module-level copies of shared wrappers (§10). The names `FormModal`/`ConfirmModal` come from plan UI-4 (history/runbooks/plan-2026-11-12-archive.md:102) but never landed in `shared/ui`. |
| Raw AntD Modal | `app/shell/CreateMenu.tsx:87` | **680**, top 56; full screen on phone | no footer | ✕ | full screen | «Создать» | Allowed by platform-frontend §4.1a, but conflicts with §6 (448 only). |
| | `features/tickets/WriteToAdminModal.tsx:84,112` | AntD default (inference: 520) | after send: «Открыть» + **primary «Закрыть»** | ✕, Esc | default | «Написать администратору» | Deviates. |
| | `features/profile/AvatarCropper.tsx:107` | **340** | Cancel + Apply | ✕ | default | Profile | Deviates. |
| | `features/onboarding/Onboarding.tsx:249` | default | text «Больше не показывать», «Пропустить», primary «Тур»; `closeIcon={null}` | — | default | first login | Deviates. |
| | `features/profile/TelegramSection.tsx:133` | **360** | only «Закрыть» | ✕ | default | Profile | Deviates. |
| Confirmation (3 styles) | `useConfirmAction` (shared/ui/useConfirmAction.ts:17-38; title «Действие объект?», no icon) | AntD confirm (inference: 416) | Cancel + verb | — | — | 7 files: eds/payments/ConfirmForm, eds/inbox/ResolutionForm, eds/drafts/ApprovalForm, eds/approvals/AgreeForm, eds/payments/PayMemoForm, erp/catalog/RequestsQueue, eds/approvals/SigningList | OK |
| | direct `modal.confirm` (default AntD icon) | same | own texts | — | — | admin/articles/ArticlesPage.tsx:106,120; admin/articles/ArticleEditor.tsx:122; features/profile/TelegramSection.tsx:96 | Inconsistent with the line above. |
| | `Popconfirm` (not in the standard) | popover | — | — | — | features/profile/CalendarLinkSection.tsx:80; erp/stock/ProductDrawer.tsx:109; erp/calc/LinesTable.tsx:444 | Deviates. |
| Panel form | `shared/ui/FormSheet.tsx:144-248`, `layer="panel"` | shell panel 480/640 | title `h3` **not sticky** (form-parts.css:42-48; only the footer is sticky, :77-89); «Отмена» + primary on the right; unsaved-changes guard via `modal.confirm` | «Отмена» (with guard) | full-screen bottom sheet (`Sheet`) | 15 files: admin/company/{common, tabs/BankAccounts, tabs/CategoriesTab, tabs/ChargesTab}, admin/docflow/{DictionaryFile, TemplatesTab}, crm/clients/CounterpartyCard, crm/kb/CreateDocumentPanel, eds/new/LetterAssist, eds/tasks/LetterOutcomes ×2, erp/catalog/common, erp/catalog/supplierForms, shared/ui/pickers/CompanyPicker, erp/stock/OrderModals, erp/calc/ParseModal, erp/calc/PreviousModal | Compliant, except §6 asks for a fixed header. |
| Drawer form | `FormSheet layer="drawer"` | 480 / 640 (`wide`), max 100vw (form-parts.css:91) | AntD header ✕, footer on the right | ✕, Esc, outside click when not dirty | 100vw | erp/stock/OrderModals.tsx:337,464; erp/catalog/common.tsx:233; erp/calc/ParseModal.tsx:99; erp/catalog/supplierForms.tsx:498; erp/calc/PreviousModal.tsx:43 | Compliant |
| Bare panel (each screen draws its own header and buttons) | `shared/ui/Sheet.tsx` | panel | none built in | own | bottom sheet | crm/leads/LeadsPage.tsx:539,553; erp/calc/CalcScreen.tsx:343,352,357; admin/docflow/DictionariesTab.tsx:420; erp/catalog/PriceImportPanel.tsx:327; crm/clients/ClientsPage.tsx:417,422,436,441 | Partly compliant; no shared header or footer. |
| Object card in the panel | `PanelPortal` directly | 480/640 | **no shared header** (ContextPanel draws tabs and controls only) | panel «›» | ContextPanelSheet/Drawer (AppShell.tsx:508-525) | ~22 files, e.g. admin/{org/OrgPage:247, audit/AuditPage:188, roles/RolesPage:401-408, tickets/TicketsPage:267, integrations/IntegrationsPage:473, bus/BusJournalPage:184, company/CompanyPage:78, articles/ArticlesPage:414, bot/*, setup/SetupWizardPage:351}, crm/kb/KbPage:109, crm/messages/Dialog:179, eds/{documents/DocumentSheet:46, decision/DecisionSlot:53, inbox/ResolutionPanel:203, projects/Slots:21,41}, erp/{calc/TaskPanel:167, stock/OrderScreen:328,369} | The header shape differs on every screen. |
| **Raw AntD Drawer in modules** | `Drawer` | **400** chats/people/PeoplePage.tsx:233 · **520** admin/signing/AuthorityDrawer.tsx:239 · **560** erp/stock/ProductDrawer.tsx:39 · **560** eds/mail/SentMail.tsx:219 · **640** erp/catalog/ItemsPanel.tsx:436 · **760** erp/docs/DocsScreen.tsx:356 · **min(100vw, 960)** eds/mail/MailBody.tsx:77 | AuthorityDrawer: `closeIcon={null}`, «Закрыть» button in the header plus a footer with danger «Отозвать» + «Отмена» + primary. SentMail: **primary «Переотправить» in the header** | default ✕, Esc, outside click | only ItemsPanel and DocsScreen set 100% on phone; the others have no phone branch | 7 screens | **Six of the seven widths are outside 480/640** (§6). |
| Phone bottom sheet copied per module | `Drawer placement="bottom"` | 100% | own | — | — | eds/documents/DocumentSheet.tsx:30, eds/decision/DecisionSlot.tsx:66, eds/inbox/ResolutionPanel.tsx:219, crm/messages/Dialog.tsx:153 | Four copies of what `shared/ui/Sheet.tsx:26-41` already does. |
| Shell drawers | Help 480 (features/help/HelpDrawer.tsx:77), bell 420 (shared/ui/TopBar.tsx:228), phone menu 280 (app/shell/AppShell.tsx:541) | | | | | | Allowed by platform-frontend §4.1a. |
| Popover | `DataTable/ColumnsMenu.tsx:168`, `ModuleRail.tsx:153` | | | | | | Menus; fine. |
| Long forms with steps | `StepSections` | page or panel | one primary button at the end | | | eds/new/NewDocumentPage:1017, eds/register/RegisterLetterPage:554, erp/stock/OrderCreatePage:183, admin/company/tabs/DetailsTab:186, crm/request/RequestForm:488 (panel), erp/catalog/supplierForms:133 (drawer) | Compliant |
| Wizards outside StepSections | admin/setup/SetupWizardPage (`?step=` plus panel tab «step»), Onboarding (Modal + Steps), admin/integrations/OffsitePanel (Steps) | | | | | | platform-frontend §4.1a forbids «мастер вне StepSections». |
| Full-page editor | admin `EditorPage` (admin/company/common.tsx:397) | page | «К списку» + title; footer «Отмена» + primary | | | 3 users | Lives in a module, not in `shared/ui`. |

**Widths in use:** centre windows come in 340 / 360 / 448 / ~416 / ~520 / 680; drawers and panels in 280 / 400 / 420 / 480 / 520 / 560 / 640 / 760 / 960. The standard allows 448, 480 and 640.

**Same button, many translations:** «Отмена» is translated separately as `"cancel": "Отмена"` in 38 places across the ru namespaces. Three more `cancel` keys say «Закрыть».

## 2. Forms
| Pattern | Where | Rule | Verdict |
|---|---|---|---|
| `FormField` (label above, hint below, **no error slot**) | shared/ui/FormParts.tsx:12-35; 41 files | §8 «подпись над полем» | OK, but because there is no error slot it gets copied (next row). |
| Local `Field` copies with an error slot | eds/new/NewDocumentPage.tsx:83, eds/register/RegisterLetterPage.tsx:87, eds/tasks/TaskActions.tsx:24, admin/integrations/parts.tsx:24 (own class `pf-int-field`) | §10 «только общие компоненты» | 4 duplicates |
| AntD `Form.Item`, vertical layout | 27 files (features/invite-employee, features/profile/*, admin/company/tabs/* ×11, admin/docflow/*, admin/signing/*, admin/setup/CompanyStep, admin/bot/SchemaField, erp/calc/{AddLineForm, MatchModal, ParseModal, Terms}, erp/stock/{AdjustModal, OrderCreatePage}) | — | Second form system |
| Required fields | `Form.Item` with `rules required: true` (32 places) shows a red asterisk; it is switched off with `requiredMark={false}` in 10 places (auth pages, profile, admin/setup/CompanyStep:160). EDS, payments and catalog forms instead write «Необязательно.» into the hint (19 strings in 6 namespaces). | §8 has no rule | Two opposite conventions |
| Two columns | `1fr 1fr` + `@media` in eds/new/new.css:10-14,37-40; erp/catalog/catalog.css:88-96 (unit+VAT, brand+manufacturer code in a 640 drawer); eds/decision/decision.css:243; eds/inbox/inbox.css:244. `minmax(0, 1fr)` in admin/signing/signing.css:18, admin/company/company.css:70,263, erp/stock/stock.css:137, eds/projects/projects.css:36 | ui-standard §6: two columns only for «цена и валюта», «количество и единица». platform-frontend.md:115: two-column grids follow the card's width (`@container`), not the screen's (`@media`). | 4 files break both rules |
| Gap between fields | 12 px in catalog.css:86-92; 16 px elsewhere | §4: 16 | Drift |
| Error placement | FormSheet and admin wrappers above the fields; catalog `FormModal` below | §8: error without a field = banner | Inconsistent |
| Loading indicator | 8 `Spin` (crm/messages/MessagesPage:47, Thread:178, Dialog:101; erp/calc/ParseModal:184, PreviousModal:57; admin/company/tabs/LetterTemplates:375,380; eds/new/LetterAssist:155); AntD `Skeleton` in 48 files vs `ListSkeleton` in 8 | §7: skeleton shaped like the table | Mixed |

## 3. Tables
**Facts**
- There are 0 AntD `<Table>` and 35 `DataTable` call sites in 33 files. On top of them sit module-level wrappers: `ListTable` (admin/company/common.tsx:492, 11 settings screens), `DataList` / `PanelTable` / `Pager` (erp/catalog/common.tsx:37,101,130) and `ReportTable` (admin/integrations/parts.tsx:254).
- Raw `<table>` remains in admin/roles/RoleMatrix and erp/calc/LinesTable (documented exceptions, archive UI-6).
- `DataTable` gives structure only. Its CSS (shared/ui/DataTable/data-table.css) and `.pf-fixed-table` (shared/ui/data-block.css:89-171) set the fixed layout, padding 12/16, header typography 11/600 caps and ellipsis. They set **no header background, no row borders, no `text-align`**, and there is no card wrapper.
- The AntD theme's `Table.headerBg` (app/theme.ts:56-63) goes unused because no AntD Table is left.

Each module supplies the look itself:

| Module class (CSS) | Header band | Header text | Cell vertical align | DataTable call sites |
|---|---|---|---|---|
| `pf-dec-table` (eds/decision/decision.css:76-101) | yes | 600 | top | ProjectList:229, QuoteParts:31, InvoiceRows:222, MemoRows:191, PaymentView:44,103 (6) |
| `pf-calc-table` (erp/calc/calc.css:49-70) | yes | 600 | top | RequestsScreen:209, BalancesTab:182, OrderScreen:136, OrdersTab:183, ReceiptsTab:147, ShipmentsTab:307 (6) |
| `pf-kb-table` (crm/kb/kb.css:21-40) | yes | 600 | top | DocumentsView:47, GapsView:40 |
| `pf-letters-table` (eds/inbox/inbox.css:62-84) | yes | 600 | top | InboxList:252 |
| `pf-bot-table` (admin/bot/bot.css:112-131) | yes | 600 | top | TemplatesView:213, TextsSection:95 |
| `pf-int-table` (admin/integrations/integrations.css:199-215) | yes | 600, padding 6/8 | top | ReportTable (parts.tsx:269) |
| `pf-crm-table` (crm/crm.css:9-26) | **no** | 12/500 secondary | middle | ClientsPage:398, LeadsPage:272 |
| `pf-docs-table` (eds/documents/documents.css:8-28) | **no** | 12/500 | middle | DocumentsPage:341 |
| `pf-cat-table` / `pf-cat-offers` (erp/catalog/catalog.css:14-34, 115-126) | **no** | 12/500 | top | catalog/common:76,115 |
| **none (bare)** | **no**; header left to the browser default, which is **centred** (global.css has no reset) | 11 caps | browser default | admin/articles/ArticlesPage:264, admin/audit/AuditList:60, admin/bus/{DeliveriesView:211, InboxView:159, SubscribersView:142}, admin/docflow/DictionaryFile:163, admin/org/EmployeeList:76, admin/settings/TemplateCatalog:110, admin/tickets/TicketsPage:141, **chats/people/PeoplePage:223**, eds/mail/SentMail:116, admin/company/common:519 (`ListTable` → SigningPage, CategoriesTab, docflow/TemplatesTab, LetterTemplates, FxRateSection, BankAccounts, docflow/MailRules, DocumentTemplates, EmailTemplates, ChargesTab, DictionariesTab) |

**Tally (call sites):** 18 have a header band, 5 have no band but left-aligned headers, and **12 direct plus 11 through `ListTable` render bare**.

**More drift**
- The selected-row style uses two different selectors: `tr[data-selected] td` versus `tr[data-selected]`.
- Dead selectors left over from AntD Table: `.ant-table-wrapper … tr.pf-org-table-row-selected` (admin/org/org.css:52-55) and `pf-audit-table-row-selected` (admin/audit/audit.css:43-46). EmployeeList.tsx:82 and AuditList.tsx:67 still set these classes, so (inference) the selected row is not highlighted in Сотрудники or Журнал. `.pf-bus-scroll .ant-table` (admin/bus/bus.css:43) and `.ant-modal .pf-co-split` (admin/company/company.css:69) are also dead.
- The card wrapper is an AntD `<Card>` added per screen (ProjectList.tsx:410). 20 table screens have no Card in the same file.
- Pagination: `DataTable pageSize` paginates on the client (DataTable.tsx:441). There are 9 module pagers: catalog/common:143, ProjectList:340, PaymentList:172,233, InboxList:384, DocumentsPage:539, LeadsPage:414, GapsView:139, TicketsPage:254, AuditPage:174.
- Empty states: some screens use `<p class=pf-hint>` (PeoplePage:221, admin/bus/SubscribersView:117) instead of `EmptyState` with an action (§7).
- Guard coverage: e2e `t1-table-widths.spec.ts:20-32` checks 13 registries only (EDS, ERP, CRM). It does not cover Люди, settings or admin tables.

## 4. Page headers, statuses, buttons
- **`PageHeader`** (shared/ui/PageHeader.tsx:5-32: title, subtitle, extra) is used in 42 files, and no page draws its own `h1`. It has **no slot for a count or a status/number**, although §9.1 says «заголовок со счётчиком» and ЕД-7 says «шапка = статус и номер». So object pages put the number into the title string and the status into `extra`, each in its own way (ProjectView:299, QuoteView:161, LetterView:232, PaymentView:185, MemoView:45, OrderScreen:226, CalcScreen:249, MailView:32).
- Pages without `PageHeader`: settings tabs use the module's own `TabHeader` (admin/company/common.tsx:24); Company, Dictionaries, Telegram and Templates pages use `h2`.
- **Status filter style:** `Segmented` in 26 files; `TabsBar` in 4 (LeadsPage, DocumentsPage, MailScreen, StockScreen); `SectionTabs` in 4. §9.1 says «вкладки статусов».
- **Statuses:** `StatusTag` is used in 97 files and is guarded by lint (eslint.config.js:59-85). Raw neutral `<Tag>` appears in 6 places (CounterpartyCard:195,262,296; ClientsPage:55; IdentitySection:188; help/Markdown:79). The status map has **7 tones** (shared/lib/statuses.ts:8, `memo` purple and `external` cyan at :65,:69) and hex literals in TS (:32-34). §2 allows 5 pastel meanings, and colorLiterals.test.ts scans only `.css`. `StatusBadge`, which §11 item 6 mentions, does not exist in Platform.
- **Buttons:** 200 `size="small"` buttons in modules and features (§5 allows 24 px only inside a table row). The bordered «Показать» button sits in every row of PeoplePage (:127-137), which §7 forbids («кнопки в рамке в каждой строке не ставятся»). `SoonButton` (permanently disabled «скоро») is still live on Органайзер (chats/inbox/ChatsPage.tsx:29, PeoplePage.tsx:277-278), against §14.2.

## 5. The three screenshots: exact causes

**(a) «Почта адресата» squeezed in modules/eds/new**
1. The row is `.pf-newdoc-row { grid-template-columns: 1fr 1fr }` (eds/new/new.css:10-14). It holds `PersonPicker` (an AntD Select, shared/ui/pickers/PersonPicker.tsx:37-65) and the email field (NewDocumentPage.tsx:642-685). `1fr` means `minmax(auto, 1fr)`, so a track never shrinks below its content's minimum width. If the person cell's unbreakable content is wider than half the row, the email track collapses to the width of the longest word in its hint («Необязательно. С почтой письмо уйдёт…», documents.json:414-418). The text then wraps one word per line. Elsewhere the repo already uses `minmax(0, 1fr)` (signing.css:18, company.css:70).
2. The row collapses to one column only below 767 px of *screen* width (new.css:37-40). platform-frontend.md:115 requires `@container`, so the row should react to the form's own width.
3. The outgoing-letter layout reserves the PDF column first: `minmax(0, 760px) minmax(360px, 1fr)` (new.css:62-67). The form column absorbs all of the narrowing.
4. (inference) The narrowing comes from the panel docked beside the page. Docking is allowed from 1280 px with the menu collapsed (app/shell/useViewport.ts:42-53; usePanels.ts:60-65). At 1280 px the main area is 1280−64−480 = 736 px, before page padding. The form column is then about 736−48−16−360 ≈ 312 px, and the two-column row gets about 296 px for both fields. In overlay mode the form keeps ~760 px and is not squeezed. ui-standard §6 says «панель лежит поверх страницы и не сжимает её», while platform-frontend.md:108-110 keeps docking as a user choice. The docs contradict each other here.

**(b) The bare «Органайзер / Люди» table (chats/people/PeoplePage.tsx)**
1. `DataTable` is called without `className` (:223-231). `DataTable` itself has no header band, row borders or `text-align` (data-block.css:105-117), so headers fall back to the browser's centred default and there are no row lines.
2. «Главная / Проекты» looks right because it gets all of that from `className="pf-dec-table"` (ProjectList.tsx:233 → decision.css:76-92) plus `<Card>` + `DataBlock` + `ListSkeleton` + `EmptyState` (ProjectList.tsx:362-413).
3. All six columns have `width: null` (:147-194). They split the width equally and ignore the width-by-type table (platform-frontend.md §4.2: person 120–136, status by its tag, and so on). That is why the columns look unaligned.
4. Other deviations on the same screen:
   - no Card or `DataBlock` (§11 item 1 «блоки — белые с рамкой»);
   - AntD `Skeleton` (:219) and `<p class=pf-hint>` (:221) instead of `ListSkeleton` / `EmptyState`;
   - the name is a hand-made `<button>` (:152-161), not `PersonCell` (§12);
   - a bordered button in every row (:127-137);
   - the card opens in a raw `Drawer` 400 px (:233) using AntD `Descriptions` (the only use in modules; 50 files use `DefinitionList`);
   - dead `SoonButton`s (:277-278).

**(c) The empty side panel open on a form («Объект не выбран»)**
1. The `/eds/new` section declares no `tabs` and has `defaults.panelOpen: false` (eds/module.ts:110-117). It therefore inherits `DEFAULT_TABS` card/chat/documents (modules/types.ts:83-87).
2. The TopBar panel button is enabled for every section the user can open: `hasPanel = match !== undefined && sectionAllowed(...)` (AppShell.tsx:365 → TopBar.tsx:249-258).
3. ЕД-7 (commit 51ea2ecb0) blocks only *automatic* opening of an empty panel: `explicitOpen` skips the block (AppShell.tsx:97-103).
4. With nothing filling any tab, `visiblePanelTabs` falls back to the first tab (app/shell/panelSlotContext.ts:62). `PanelContent` then renders the generic placeholder `modules:panel.card` (app/shell/PanelContent.tsx:25-31; ru text modules.json:805-807: «Объект не выбран / Выберите строку в таблице…»), which talks about a table on a page that has none.
5. Fixing this needs two things: `hasPanel` should also require `panelHasContent`, and sections without a panel should not show the button.

## 6. The standard against the code: what was replaced but is still used
| Already replaced by the standard | Still in use |
|---|---|
| raw `Modal` → `Dialog` | 6 sites (features ×5, CreateMenu). Lint bans it only in `src/modules` (eslint.config.js:165-185). |
| widths 440/600, Modal 440–520, «до 6 полей → панель» | platform-frontend.md:99 and §4.1a; app/shell/panelsStore.ts:15 comment «440px vs 600px» |
| AntD Table | dead CSS in org.css:52, audit.css:43, bus.css:43 |
| colours #1668dc / #595959 / #f0f0f0 (old v3 palette) | still the spec in platform-frontend.md §5 and in docblocks: ui.css:1-5, PageHeader.tsx:4, QueueList.tsx:34, History.tsx:19, RequestSteps.tsx:30, CounterCard.tsx:18, DefinitionList.tsx:20, EmptyState.tsx:19, eds/new/new.css:1, admin/settings/settings.css:1 |
| one panel component (`FormSheet`) | 7 raw desktop drawers, 4 copied phone sheets, 6 `Sheet` callers with their own headers |
| `FormModal` / `ConfirmModal` / `ListTable` / `DataList` / `PanelTable` / `ReportTable` / `EditorPage` belong in shared | they live in admin/company/common.tsx and erp/catalog/common.tsx, and admin even defines its own `FormSheet` (:287) that shadows the shared one |
| ui-standard §9.4 settings template «меню разделов слева, форма до 768 px» | settings are a card index (admin/settings/settings.css:24-48) plus `SettingsPage` (SettingsPage.tsx:19-70); no 768 px width limit exists anywhere in the CSS |

Fully compliant areas: centre-dialog content (all 20 shared Dialog files), statuses (97 files), icons (lint), colour literals in CSS (test), `StepSections` long forms (6).

## 7. What would make a deviation impossible to ship

**Guards that already exist:**
- ESLint: no `Modal` in modules (eslint.config.js:165-185); no `@ant-design/icons` (:145-160); no coloured `Tag`, computed `tone` or local status maps (:59-85); no native date, file or select fields (:41-57).
- Tests: `colorLiterals.test.ts` (CSS only); `contrast.test.ts` and `packages/ui-tokens/contrast.test.mjs`; the `humanText` guard that scans the screen after every vitest test (test/setup.ts:107-125, test/humanText.ts); `statuses.test.ts`.
- e2e: `t1-table-widths` (13 screens), `stable-data`, `ux-2b` (390 px), `a11y` (axe).
- There are **0 `toHaveScreenshot`** (no visual regression tests).

**Shared components that are missing (smallest set, each backed by the evidence above):**
1. **`RegistryTable`**: Card + `DataBlock` + `DataTable` with **one built-in look** (header band, left headers, row lines, selected row), plus `ListSkeleton`, `EmptyState` and one pager. Then delete the 10 module table classes and drop `className` from `DataTable`.
2. **`FormField` with `error` and an `optional` mark**, plus **`FieldPair`** using `minmax(0, 1fr)` and `@container`. Then delete the 4 local `Field` copies and the `1fr 1fr` rows.
3. **`RecordDrawer`** (480/640, header with title + status/number + ✕, phone mode through `Sheet`) to replace the 7 raw drawers and 4 copied phone sheets. A **shared panel header** to go with it, so `PanelPortal` cards look the same.
4. **One confirmation** (`useConfirmAction` only; no `Popconfirm`, no direct `modal.confirm`), and a **phone bottom sheet inside `Dialog`**.
5. **`PageHeader` slots** for `count`, `number` and `status`.
6. **Shell:** disable or hide the panel button when `!panelHasContent`.

**Guards that are missing:**
- ESLint `no-restricted-imports` from `antd` across `modules`, `features` and `entities`: `Modal`, `Drawer`, `Popconfirm`, `Descriptions`, `Table`, `Spin`. `no-restricted-syntax`: JSX `<table>` (allow-list RoleMatrix and LinesTable, as §10 already requires) and `className` on `DataTable`.
- A CSS test in the style of colorLiterals: in `modules/**/*.css`, no `table`, `th`, `td` or `.ant-*` selectors, and no `grid-template-columns` with a bare `1fr` next to another track. Extend the hex-literal scan to `.ts` and `.tsx`.
- A DOM identity guard in the `afterEach` of test/setup.ts, next to humanText:
  - every `table.pf-dt-table` sits inside the shared table look;
  - `.ant-drawer-content-wrapper` width is 480, 640 or 100%;
  - `.ant-modal` width is 448, with an allow-list for «Создать»;
  - an open panel always has a filled tab.
- e2e: add Люди, settings and admin registries to `t1-table-widths`; add `toHaveScreenshot` baselines at 1440 and 390 for the registry, object page, panel form and Dialog templates.
- Docs: align platform-frontend.md §4, §4.1a and §5 with ui-standard (480/640, 448, field-count thresholds, palette, whether docking is allowed), so the agents who build screens stop reading conflicting numbers.

## Cross-area facts found along the way (for other areas)
- **Two menu definitions disagree.** The contract `menu:` (packages/contracts/platform-rbac.yaml:418-445) lists for EDS: documents/inbox/mail/outbox/projects/drafts/approvals/payments, and for CRM: messages/leads/clients/requests/channels/kb. The web menu (modules/navigation.ts:81-98) lists for Документы: inbox/outbox/internal/archive/templates, and for CRM: leads/clients/mail/kb.
- **Projects sit under Главная:** navigation.ts:83 (and rbac `menu.dashboard.projects`).
- **The same settings page is in two menus:** «Документы → Шаблоны» targets the settings page `admin.templates` (navigation.ts:97).
- **Mail is in two places:** «Контакты → Почта» targets `eds.mail` (navigation.ts:89).
