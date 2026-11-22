
# AREA B: Settings. Inventory, duplicates, dead settings and health signals

**Path abbreviations** (all absolute):
- R = `/home/umarbek/projects/RailTech_Platform/.claude/worktrees/research-main`
- W = `R/apps/platform/web/src`
- A = `W/modules/admin`
- B = `R/apps/platform/bff/app`
- RBAC = `R/packages/contracts/platform-rbac.yaml`

All findings are from fresh main (HEAD 2ecd40446). Anything inferred rather than read directly is marked **(inference)**. Work still in flight (ГЛ, ЕД-7 PR-2) is not in this checkout.

---

## 1. Inventory of every Settings page

**Where the structure comes from**
- One registry, `A/settingsRegistry.ts:44-551`, defines all 21 entries. It drives the submenu, the `/admin` index, and the settings group in Ctrl K search (`W/features/global-search/GlobalSearch.tsx:156`).
- There are 4 groups (`settingsRegistry.ts:14-23`): people «Сотрудники», company «Компания», channels «Подключения», system «Журнал».
- The menu builds one item per group, and the pages of a group become shell tabs above the page (`W/modules/navigation.ts:39-61, 136-141`).
- Menu access per item comes from `RBAC:455-483`.
- Access levels:
  - Director: `admin: read` plus `company.settings: full` (`RBAC:49-50`).
  - Administrator: everything (`RBAC:26`).
  - No role template has `admin` or `company.settings` (`RBAC:405-406`).

**Inventory table.** "Page shell" means whether the page uses the shared `SettingsPage` frame (title from the registry, «Только просмотр» tag, «Подробнее» link to help, `A/settings/SettingsPage.tsx:94-147`) or its own `PageHeader`.

| # | Page (route, registry line) | Group · access | Page shell | What the controls change → BFF endpoint → store | Who reads the value |
|---|---|---|---|---|---|
| 1 | Сотрудники `/admin/org` (:45) | people · admin | own PageHeader (`A/org/OrgPage.tsx`) | invite, deactivate, roles via `AssignRoleForm` (`A/org/EmployeeCard.tsx:87`) → `B/api/admin_users.py` → CRM | CRM RBAC → ERP and EDS rights |
| 2 | Роли и права `/admin/roles` (:62) | people · admin | own PageHeader | role CRUD → `B/api/admin_roles.py` → CRM | all systems |
| 3 | Права подписи `/admin/signing` (:79) | people · `eds.signing.manage` | SettingsPage | signing authorities: basis, limit, `valid_to`, revoke → `B/api/eds_signing.py:58-198` → EDS | EDS signer resolution |
| 4 | Реквизиты и бланк `/admin/company` (:114) | company · company.settings | SettingsPage | (a) `DetailsTab`: name, INN, country, legal address, phone, email, contact person, website, ISO, company logo, bank accounts → `/admin/company`, `/admin/company/logo`, `/bank-accounts` → ERP `Company` (`B/api/admin_company.py:170-222, 464-509`)<br>(b) `BrandTab`: brand logo, signatory, footer, colour, wording, uz/en variants → `/admin/company/brand` → ERP `CompanyDocumentProfile` (`:229-282`)<br>(c) bot section `company`, shown only with `admin` (`A/company/CompanyPage.tsx:73-77`) → `PUT /admin/bot/settings/company` → CRM `company` (name, phone, site, address, `cabinet_url`, `crm_base_url`) (`R/apps/crm/backend/app/schemas/settings.py:35-77`) | ERP: document seller block (`R/apps/erp/backend/crm/services/generated_documents.py:110-131`)<br>CRM: bot contact replies (`settings.py company_contacts`); name goes to ERP `platform_name` by bus (`R/apps/erp/backend/integration/services/company_profile.py:1-32`) |
| 5 | Нумерация `/admin/numbering` (:141) | company · company.settings | SettingsPage | one editor fans out to ERP `crm/numbering-scheme/` + prefix in ERP settings, EDS labels, CRM ticket label (`admin_company.py:351-400`) | ERP, EDS, CRM number generators |
| 6 | Налоги и валюты `/admin/taxes` (:158) | company · company.settings | SettingsPage | (a) `PlatformTab`: `vat_rate`, `support_email` → `/admin/company/platform-settings` → ERP `SystemSetting` (`admin_company.py:884-900`)<br>(b) `FxRateSection`: manual rate → `/admin/company/fx-rate` → ERP `exchange-rates/manual/` (`:933-950`)<br>(c) `QuoteSettings group="taxes"`: `default_cost_currency`, `default_vat_rate`, `fx_rate_max_age_days` → `/admin/company/quote-defaults` → ERP `CompanySettings`<br>(d) `RatesView` from the ERP catalog, with its own «Ввести курс» (`A/settings/pages.tsx:46-62`) | see §2 and §3 |
| 7 | Продажи `/admin/sales` (:175) | company · company.settings | SettingsPage | `QuoteSettings` «sales»: basis, margins, validity, payment days, warranty, payment terms, `offer_confirm_days`, `offer_expiring_days`; «catalog»: price visibility, publish threshold (`A/company/tabs/QuoteTab.tsx:30-44`) → ERP `CompanySettings` | ERP quote defaults (`R/apps/erp/backend/crm/services/quotes/access.py:61-123`), catalog, supplier-price freshness |
| 8 | Статьи компании `/admin/articles` (:212) | company · admin | own PageHeader | articles → `B/api/company_articles.py` → CRM | all employees, in Помощь |
| 9 | Telegram `/admin/telegram` (:229) | channels · admin | SettingsPage + `SectionTabs` | 5 tabs (`A/settings/TelegramPage.tsx:238`):<br>• Подключение: token, team channel, bot profile → `B/api/admin_integrations.py:282-341`<br>• Тексты, Поведение (`bot`, `qualification`, `stop_words`, `competitors`), Шаблоны ответов, База знаний (`kb` section + link to `/crm/kb`) → CRM settings (`A/bot/sections.ts:12-29`) | CRM bot; reply templates also read in the lead card |
| 10 | Почта `/admin/mail` (:263) | channels · admin | SettingsPage, no tabs | SMTP, test send, mail log, missed mail (`admin_integrations.py:397-446`); IMAP: folders, `assist_enabled`, personal rule, trusted auth servers (`A/integrations/InboundMailBlock.tsx:40-47`) → CRM `integrations.smtp/imap` | CRM sending; «Входящая почта» queue |
| 11 | Формы сайта `/admin/web-forms` (:280) | channels · admin | SettingsPage | CRM `web_form` (anti-spam plus `first_response_sla_minutes`) (`settings.py:517-548`) | CRM `services/web_lead_sla.py` |
| 12 | Справочники `/admin/dictionaries` (:297) | company · admin or company.settings | SettingsPage + left `SettingsNav` | Продажи: CRM `deals` (loss reasons, `currency`). Документы, Почта: `/dictionaries` catalog + `MailRules`. Расчёт: ERP lists, `CategoriesTab`, `ChargesTab` (`A/settings/DictionariesPage.tsx:43-137`) | each domain |
| 13 | Шаблоны резолюций `/admin/resolutions` (:341) | company · admin | SettingsPage | → `B/api/eds_resolution_templates.py` → EDS | EDS resolution of incoming letters |
| 14 | Шаблоны документов `/admin/templates` (:358) | registry group company · company.settings; hidden from the Settings menu and index; shown as «Документы · Шаблоны» (`navigation.ts:97, 138`) | SettingsPage + `SectionTabs` | 4 tabs (`A/settings/TemplatesPage.tsx`): Все шаблоны, ERP document templates, EDS letter templates, ERP email templates (`admin_company.py:570-735`, `B/api/eds_templates.py`) | ERP and EDS document generation |
| 15 | Время и сроки `/admin/timing` (:375) | company · admin | SettingsPage | CRM `business_hours` + `escalation` (SLA, reminder, trigger thresholds, human-request terms, dry run) (`settings.py:233-284`) | CRM bot handoff, timers |
| 16 | Уведомления `/admin/notifications` (:392) | company · admin | SettingsPage | CRM `notifications` (duty staff, DM throttle; `channel_id` hidden, `A/bot/SettingsForm.tsx:32`), CRM `service_alerts`; ERP `remind_overdue_invoices`, `act_reminder_hours` (`pages.tsx:122-143`) | CRM notify tasks; ERP `crm/tasks.py:545` |
| 17 | Сервисы `/admin/integrations` (:434) | channels · admin | own PageHeader | 8 cards. ERP pairing and rotation, services, models, storage/offsite backup and system open in the side panel; Telegram, Mail and Spend open their own pages (`A/integrations/IntegrationsPage.tsx:61-69, 354-374`). Also «Требует внимания» and `CabinetAddress` → `/setup/cabinet` → CRM `company.cabinet_url` (`:441-446`, `B/api/setup.py:164-180`) | CRM, ERP |
| 18 | Расходы на ИИ `/admin/ai-spend` (:460) | channels · admin | SettingsPage | spend report; CRM `budget`; CRM `ai.pii_policy` (`PiiPolicyCard`); EDS `docflow-settings.recognize_scans` (`AiTab` → `B/api/eds_letter_intake.py:118-124`) (`pages.tsx:148-161`) | CRM, EDS (policy via event `crm.ai_policy.changed`) |
| 19 | История `/admin/audit` (:500) | system · admin | own PageHeader | read only; CRM audit only (`B/api/admin_audit.py:1-8`) | — |
| 20 | Выгрузки `/admin/exports` (:517) | system · admin | SettingsPage | deals CSV only (`B/api/admin_bot.py:42-49`) | — |
| 21 | Обмен между системами `/admin/bus` (:534) | system · admin **full** | own PageHeader | bus journal of 3 domains plus retry (`B/api/admin_bus.py:1-6`) | — |
| hidden | Первый запуск `/admin/setup`; Обращения `/admin/tickets/:id` (`A/module.ts:44-69`) | admin | own PageHeader | the wizard reuses the same panels (`A/setup/StepPanel.tsx`) | — |

**Settings that live outside `/admin`**

| Where | What |
|---|---|
| Профиль `/me` (`W/features/profile/ProfilePage.tsx:21-35, 63-77`) | personal data, Telegram link, personal notification subscriptions (`B/api/me_notifications.py`), personal iCal link (`CalendarLinkSection`), deputy (`DeputySection`, CRM), second factor |
| Контакты · База знаний `/crm/kb` | KB content; admin edits it here (`W/modules/crm/module.ts:31-37`) |
| Операции · Каталог · Справочники (`W/modules/erp/catalog/RefsPanel.tsx:43-71`) | ТН ВЭД, производители, category requests |
| Gear (⚙) in module submenus (`A/moduleSettings.ts:9-13`, `W/app/shell/AppShell.tsx:276-284`) | eds → company group, crm → channels group, erp → company group; shown only to holders of `admin` |
| Deep links from work screens into Settings | `/admin/signing` from `W/modules/eds/documents/LetterSection.tsx:105`; `/admin/company?part=brand` from `W/modules/eds/new/NewDocumentPage.tsx:580`; `/admin/mail` from `W/modules/eds/mail/mailModel.ts:17`; `/crm/channels` redirects to `/admin/telegram` (`W/modules/crm/index.tsx:21`) |

---

## 2. Duplicates: the same fact editable in more than one place

| Fact | Places | Same field or two that can diverge? |
|---|---|---|
| **VAT rate** | (1) Налоги и валюты · «Платформенные настройки · Ставка НДС, %» → ERP `SystemSetting.vat_rate` (`A/company/tabs/PlatformTab.tsx:110-125`)<br>(2) the same page · «Ставка НДС в новом КП, %» → ERP `CompanySettings.default_vat_rate` (`QuoteTab.tsx:42, 151`) | **Two fields on one page.** Pricing reads only `default_vat_rate` (`quotes/access.py:64, 121`; `catalog/desk/items.py:194-203`). See §3. |
| **FX rate, manual entry** | `FxRateSection` (in `PlatformTab`) and `RatesView` «Ввести курс» (`W/modules/erp/catalog/RefsPanel.tsx:119-129`), both on Налоги и валюты (`pages.tsx:51, 58`) | **Same store.** Both call `useCreateFxRate` → ERP `exchange-rates/manual/`. Two forms for one fact on one page. `RateForm` defaults its date to the literal `"2026-10-28"` (`RefsPanel.tsx:178`). |
| **Customer cabinet address** | (1) Реквизиты и бланк → bot `company` form (`cabinet_url` is not hidden: `SettingsForm.tsx:32` hides only `notifications.channel_id`)<br>(2) Сервисы → `CabinetAddress` (`IntegrationsPage.tsx:444`)<br>(3) Первый запуск wizard (`A/setup/SetupWizardPage.tsx`) | **Same CRM field** `company.cabinet_url` (`R/apps/crm/backend/app/api/v1/setup.py:142`). Three places, two different controls; only one of them has «Проверить доступность». |
| **Company name and contacts** | ERP `Company` name, phone, email, website, legal address (DetailsTab); CRM `company` name, phone, site, address (bot form on the same page); ERP `SystemSetting.support_email` (Налоги и валюты) | **Different stores that can diverge.** The CRM name is pushed to ERP `platform_name` (`company_profile.py:1-32`); the ERP `Company.name` is a separate record. Known debt: B-SETIA-1 (`R/docs/BACKLOG.md:228`), research L5 (`R/docs/research/2026-11-02-flexibility/4-settings-ia.md` §5). |
| **Logo** | «Логотип компании» (DetailsTab → `/admin/company/logo`) and «Логотип бланка» (BrandTab → `/admin/company/brand/logo`), same page | **Two ERP fields** (`Company.logo` and `CompanyDocumentProfile.logo`, `admin_company.py:182, 244`). |
| **Who signs** | BrandTab «Подписант / Должность» → ERP `CompanyDocumentProfile.signatory_*`; Права подписи → EDS registry | **Different stores.** ERP prints the brand signatory on generated documents (`generated_documents.py:129-130`). After EDS signs, the actual signer overwrites it (`R/apps/erp/backend/integration/services/eds_inbound.py:147, 277`). Unsigned or preview documents can name a different person **(inference)**. |
| **Lead first-response SLA** | `escalation.sla_minutes` (Время и сроки) and `web_form.first_response_sla_minutes` (Формы сайта) | Two fields, one per channel, on two pages (`settings.py:239, 541-546`). |
| **Working days** | CRM `business_hours.weekdays/holidays` (Время и сроки) vs. EDS deadline counting hard-coded as Mon–Fri with no holidays (`R/apps/eds/app/services/letter_intake.py:159-165`) | Not two settings: one setting plus a constant that ignores it. |
| **Currency** | CRM `deals.currency` (Справочники · Продажи); ERP currencies list (Справочники · Расчёт); ERP `default_cost_currency` (Налоги и валюты) | Three different fields (`R/apps/crm/backend/app/schemas/settings_deals.py`). |
| **ERP AI daily budget** | CRM `budget.erp_daily_usd` (Расходы на ИИ form) vs. ERP env `AI_DAILY_BUDGET_USD` | Two values. ERP enforces only the env value (`R/apps/erp/backend/core/settings/ai.py:43-48`). See §3. |
| **Team channel** | Chosen in Telegram · Подключение (`ChannelBlock`, `A/integrations/TelegramPanel.tsx:89-160`). Уведомления describes itself as «Канал команды и оповещения о сбоях» (`settingsRegistry.ts:398`) but hides the field (`SettingsForm.tsx:31-32`, whose comment still says «Внешние интеграции») | One field; the page that is named for it cannot set it. |
| **Templates** (5 kinds, 3 homes) | Документы · Шаблоны (ERP documents, EDS letters, ERP emails), Настройки · Шаблоны резолюций, Telegram · Шаблоны ответов. «Все шаблоны» already lists all five and links out (`B/api/templates_catalog.py:97-179`) | Different objects, scattered. ДОК-15 plans to move emails again, to Уведомления (`R/docs/runbooks/plan-2026-11-12.md:161`). |
| **AI switches** (4 pages) | `bot.assist_enabled` and persona (Telegram · Поведение); `imap.assist_enabled` (Почта); `recognize_scans` and `pii_policy` (Расходы на ИИ); models (Сервисы panel) | Different fields, no single AI page. |

Checked and not duplicated: role assignment exists only in the employee card (`A/roles/RolesPage.tsx:38-40` only links to it). Numbering is one editor that writes to three systems.

---

## 3. Dead or no-effect settings

1. **`SystemSetting.vat_rate`.**
   - It is editable on Налоги и валюты, and the form note promises «Новые расчёты и документы пойдут с этой ставкой» (`W/shared/i18n/ru/company.json`, `platform.note`).
   - No ERP business code reads it. Outside its API/admin it appears only in `__str__` (`R/apps/erp/backend/core/models/settings.py:100`).
   - The pricing engine reads `CompanySettings.default_vat_rate`.
   - A precedent exists: the sibling field `standard_margin` was removed from the API for exactly this reason (`R/apps/erp/backend/core/views/settings.py:42-45`).
2. **`service_alerts.repeat_minutes`.**
   - The CRM schema says «Устарело и не используется» (`R/apps/crm/backend/app/schemas/settings_alerts.py:33-41`), and nothing in CRM reads it.
   - The Уведомления form still shows it with a promising hint (`W/shared/i18n/ru/bot.json:639, 667`).
   - It was introduced by DECISIONS 2026-10-14 M3-CRM-12 (`R/docs/DECISIONS.md:84`) and made obsolete later.
3. **`budget.erp_daily_usd`.**
   - CRM uses it only for display (`settings.py:364-367`; `R/apps/crm/backend/app/services/ai_spend.py:134`).
   - ERP enforces env `AI_DAILY_BUDGET_USD` (`core/settings/ai.py:43-48`).
   - ERP's docstring claims the CRM console provisions it (`R/apps/erp/backend/ai/services/provision.py:16`), but CRM has no `key/update` code.
   - Effect: changing it in the UI changes only the displayed limit.
4. **Not editable in the Platform at all:** ERP `SystemSetting.is_two_factor_required` and `maintenance_mode` (superuser only, `core/views/settings.py:72-79, 136-139`). There is no admin-level 2FA policy in the Platform; 2FA is personal only, in Профиль.

---

## 4. Settings placed against their meaning

All rows are facts: each pairs the page with what the field actually does.

| Setting | Where it is | What it actually is |
|---|---|---|
| `support_email` (address in letters to clients) | Налоги и валюты, card «Платформенные настройки» (`PlatformTab.tsx:126-137`; commit d95388f27) | A company contact; read by ERP emails (`R/apps/erp/backend/notifications/emails.py:237-241`) |
| `offer_confirm_days`, `offer_expiring_days` | Продажи · «Условия нового КП» (`QuoteTab.tsx:38-39`) | Supplier price freshness for purchasing (`R/apps/erp/backend/parties/models/company_settings.py` help texts at :95-106 within the model) |
| `escalation` trigger thresholds (`high_score_threshold`, `kb_gap_streak`, `qualifier_min_confidence`, `human_request_terms`, `price_always_to_manager`, `require_phone_for_human_request`) | Время и сроки, group «Компания» (`A/bot/sections.ts:21`) | Bot dialog behaviour (`EscalationSettings.triggers()`, `settings.py:271-281`) |
| Bot `company` section (contacts the bot names) | Реквизиты и бланк | A bot answer source |
| `cabinet_url`, `crm_base_url` | Inside that same bot «Компания» form | System addresses |
| Шаблоны резолюций, Статьи компании, Время и сроки, Уведомления | Group «Компания» | Document-flow content, staff content, bot timing, alerting |
| Расходы на ИИ (includes the data-protection policy) | Group «Подключения» | The code's own comments call it «Система · Расходы на ИИ» (`pages.tsx:147`) |
| Выгрузки | Group «Журнал» | An action. Its place in Settings is an owner decision (DECISIONS 2026-11-11, `DECISIONS.md:308`). |

**Conflicts with the agreed documents**
- **SPEC-v3 §7.6** (`R/docs/product/SPEC-v3.md:716-718`) says «Админ не ведёт бизнес-процессы». Settings nevertheless holds commercial policy: margins, quote terms, payment, catalog price visibility. Only director and admin hold `company.settings` (`RBAC:405-406`).
- **SPEC-v3 §7.6, last paragraph** asks for one journal with a filter «Действия людей / Обмен между системами». The code has two separate pages (registry :500, :534).
- **DECISIONS 2026-10-28** (`DECISIONS.md:231`) asks for one page per channel with identical tabs: Подключение · Направления · Автоответы и шаблоны · Рабочее время · ИИ-помощник · Журнал.
  - Telegram has 5 different tabs.
  - Почта has no tabs.
  - Формы сайта is one form.
  - Working hours sit on a separate page.
  - Mail routing (types, sender rules) sits in Справочники · Почта (`DictionariesPage.tsx:56-62, 114-118`).
- **NAVIGATION, role table** (`R/docs/product/NAVIGATION.md`, «Что видит роль»):
  - It says Director: «компания; сотрудники и журнал — чтение». In code, `admin: read` gives the director every `admin` page read-only (Telegram, Почта, Сервисы, Расходы на ИИ…). Only `bus` requires full.
  - It says Lawyer: «Документы … шаблоны». The Шаблоны page requires `company.settings` (`RBAC:475`), which the lawyer lacks (`RBAC:160-171`).
  - EDS letter templates can be edited with `eds.inbox.register` (`A/company/tabs/LetterTemplates.tsx`, `editable =` line). The registrar has that right but cannot open the page.

---

## 5. Settings index, grouping and search

**Is the grouping one consistent principle? No.** The four groups use four different principles:
- «Сотрудники» is a subject. The group and its first page share the same name (`ru/modules.json` `admin.groups.people` = `admin.sections.org` = «Сотрудники»).
- «Компания» is a catch-all of 9 tabs: identity, tax, commerce, staff content, lists, document-flow templates, bot timing, alerts.
- «Подключения» is technology plus AI money.
- «Журнал» mixes logs with an export action.

**The documentation describing the grouping disagrees with itself:**
- `A/module.ts:28-31` and `RBAC:456-459` say «пять групп — Люди и доступ · Компания · Каналы связи · Процессы · Система».
- `A/moduleSettings.ts:4-8` says «Документы — Процессы».
- `pages.tsx:100, 112, 121, 147` label pages «Процессы ·» and «Система ·».
- The registry and NAVIGATION (`NAVIGATION.md`, Настройки table) have 4 groups.

**The index `/admin` has no menu entry.**
- The admin submenu has only the 4 group items (`navigation.ts:136-141`).
- The rail opens the first item, `/admin/org` (`AppShell.tsx:253`).
- The index is reachable only through ⚙ from Документы, Контакты or Операции (`?group=`), Ctrl K, or the «Все группы» link.
- Research §4.1 intended the rail to open the index (`4-settings-ia.md:155-160`).

**Search inconsistencies**
- The index hides «Шаблоны документов» (`A/settings/SettingsHome.tsx:168`), but search does not (`:182-185`) and global search does not either. That card appears under group «Компания».
- No keywords exist for:
  - «поддержк» / «support». The field is on Налоги и валюты; a search for «адрес» lands on Реквизиты.
  - «кабинет» / «cabinet».
- «канал команды» finds Уведомления, which cannot set the channel.

**Status badges on index tiles** exist only for telegram, mail, spend and integrations (`SettingsHome.tsx:46-69`). Signing, FX and readiness have none.

**Consistency between pages ("zoo" evidence)**
- 7 of 22 pages use their own `PageHeader` instead of `SettingsPage`: org, roles, articles, integrations, audit, bus, setup. They have no help link and mark read-only on their own.
- `ui-standard.md` §9 p.4 requires «меню разделов слева, форма до 768 px» (`R/docs/architecture/ui-standard.md:154`). In code:
  - Settings pages use top shell tabs; «Компания» has 9 of them.
  - Only Справочники uses a left nav.
  - Telegram and Templates use inner `SectionTabs`.
  - `.pf-set-page` has no max-width (`A/settings/settings.css:4-10`).
- `platform-frontend.md` asks for a `ContextualSaveBar` with no save button under the form (`R/docs/architecture/platform-frontend.md:204`). Расходы на ИИ alone mixes four save models:
  - a report (`SpendPanel`)
  - a form submit (`SettingsForm.tsx:144`)
  - explicit buttons (`PiiPolicyCard.tsx:110-127`)
  - a toggle that saves instantly (`AiTab.tsx:64-65`)
- Налоги и валюты has three save points plus a modal.
- Read-only marking is wrong or duplicated:
  - Реквизиты shows both an Alert and the tag (`CompanyPage.tsx:66` plus `SettingsPage.tsx:131-140`).
  - On Уведомления the director sees «Только просмотр» (page access `admin`) but can edit the ERP reminders card (`company.settings`, `pages.tsx:138-142`).
  - On Реквизиты the director can edit the ERP parts but not the bot contacts block.
- On Сервисы, connector configuration has two patterns: 5 cards open the side panel, 3 open their own page (`IntegrationsPage.tsx:61-69`).

---

## 6. Health and readiness: what exists for "admin watches the foundation"

| Signal | Source (API) | Where it is shown today |
|---|---|---|
| First-run checklist, 10 visible steps: admin, erp, company, bank, cabinet, bot, mail, models, first_employee, signing (`W/entities/setup/steps.ts:104-160`) | `GET /setup/checklist` (`B/api/setup.py:139`) | Index (only while unfinished, `SettingsHome.tsx:258`); global `SetupBanner` for admin only, not director (`W/features/first-run/SetupBanner.tsx:14-31`) |
| Per-service status, uptime 24h/7d, failures, flaps, incident, owner (admin / owner / hosting / provider), next action (`B/schemas_integrations.py:370-397`) | CRM external-services registry. Causes include `cert_expiring`, `bus_dlq`, `backlog`, `queue_stuck`, `checks_stale`, `smtp_*`, `erp_*_failed`, `offsite_*`, `key_rejected`, `quota`, `budget_*`, `webhook_*`, `eds_rights`, `erp.cbu_rates`, `erp.customs_tariff`, `erp.s3`, `erp.sentry` (`R/apps/crm/backend/app/domain/external_cause.py:112-160`) | Сервисы → «Требует внимания» and the Сервисы panel |
| Attention kinds: `not_configured`, `service`, `model_problem`, `backup_stale`, `component`, `budget_over`, `budget_near`, `rotation_pending`, `paused`, `bot_not_running` (`B/schemas_integrations.py:31-42`) | `GET /admin/integrations/overview` (`B/integrations_overview.py`) | Сервисы; index tiles |
| System components: bot, token, erp, ai_budget, external_services | `GET /system` (`R/apps/crm/backend/app/api/v1/system_status.py:76-80`) | Сервисы · Состояние системы panel |
| Backups and offsite copy check | `/backups`, `/offsite/check` | Сервисы · Хранилище panel |
| Bus: `outbox_pending`, `oldest_undelivered_age_seconds`, `dlq_size`, `inbox_retrying`, `inbox_failed` per domain (`B/schemas_bus.py:118-126`) | `/admin/bus` | Обмен между системами, admin full only |
| Mail log, missed mail | `/smtp/log`, `/smtp/missed` | Почта |
| Expiring signing authority: `status=expiring`, `expires_in_days` (`B/schemas_eds_signing.py:19, 148`) | EDS. A 14-day reminder event goes to holders via bell and Telegram (`R/apps/eds/app/services/signing_reminders.py:1-8`) | Права подписи list only (`A/signing/SigningPage.tsx:132-136`) |
| Stale FX rate | `GET /admin/company/fx-rate` («missing» state); service `erp.cbu_rates` | Налоги и валюты; Сервисы |
| Bank details ready | `checklist.company.bank_details_ready` | Checklist and banner |
| Staff tickets | queue kind `ticket` (`B/feeds/queue.py:683-698`) | Мои задачи; counter on the index |
| Audit | CRM audit only (`B/api/admin_audit.py:1-8`); role journal; FX journal | История; Роли; Налоги и валюты (three separate journals) |

**What is missing for a "risks and incidents" view**
- **Readiness has gaps.**
  - It does not include бланк, нумерация or адрес поддержки. All three are required by `ui-standard.md` §14 p.5 (`:236-239`) and plan row СЦ-3 (`plan-2026-11-12.md:124`), which is marked closed (`:282`).
  - Steps are presence-based. For example, «mail» means only "SMTP is set" (`R/apps/crm/backend/app/services/setup_checklist.py:6`).
  - The checklist disappears once complete (`SettingsHome.tsx:258`).
- **«Красная строка на Главной»** is implemented as the admin-only global banner. There is nothing in `W/modules/dashboard` (grep shows no setup or integration usage). Health endpoints are consumed only inside `modules/admin`, so there is no health indicator anywhere outside Settings.
- **Queue kind `integration_issue`** is declared (`B/feeds/models.py:65`, `RBAC:531`), but no producer exists in `B/feeds`.
- **The audit covers CRM only.** ERP settings history (pghistory on `SystemSetting`, `settings.py:22-24`) and EDS changes are not in История **(inference: no BFF proxy found)**.
- **No external uptime check with an alert** to the owner (`R/docs/research/2026-11-22-connectors/README.md:50`; risk register С2, `R/docs/research/2026-11-17-risk-register.md` §2.6).
- **No error tracking in BFF** (grep shows no sentry in `B`). ERP has `erp.sentry`.
- **No admin view of security posture**: who has 2FA, last login. The org list shows only `telegram_linked` (`B/schemas_admin.py:36`).
- **Expiring signing authority and FX freshness** are not on the index or in «Требует внимания».

---

## 7. Against the owner's draft («Настройки — админ, фундамент, риски»)

- **Supported by the facts:**
  - SPEC-v3 §7.6 already says the admin does not run business processes.
  - A real foundation-monitoring layer exists. CRM external services, system status, bus and backups (§6) form a solid base, but it is spread over Сервисы, Обмен, История, Права подписи and the checklist.
- **Where the facts disagree:**
  - Today Settings is mostly business configuration owned by other roles: quote terms, margins, catalog policy, supplier-price freshness, resolution templates, bot texts and SLA.
  - Its only editors are admin and director (`RBAC:405-406`).
  - Making Settings purely "admin, foundation" means deciding who edits commercial policy. Today no non-admin role can.
- **Connectors** (owner item 6, Органайзер). NAVIGATION (accepted 2026-11-10, «Коннекторы») puts company connections in «Настройки · Подключения». Personal bindings already live in Профиль: iCal link, Telegram link.

---

## 8. Setting → one proposed home → why

Only existing settings are listed; nothing new is invented. "Keep" means the current home is already right.

| Setting (current place) | Proposed home | Why (evidence) |
|---|---|---|
| Employees, invites, employee roles | Keep: Настройки · Сотрудники | SPEC-v3 §7.6 «единое место выдачи ролей» |
| Roles and permissions | Keep: Настройки · Роли и права | admin-only RBAC (`RBAC:363`) |
| Signing authorities | Keep: Настройки · Права подписи; add its `expiring` status to «Требует внимания» | ADR-0024 p.1; the signal already exists (§6) |
| Brand signatory / position (BrandTab) | Права подписи | Signed documents already take the signer from EDS (`eds_inbound.py:277`) **(inference)** |
| ERP company details, bank accounts, company logo | Keep: Реквизиты и бланк | ERP is the planned owner (B-SETIA-1, research L5) |
| Brand logo (second logo) | Реквизиты и бланк, one logo control | Two ERP logo fields on one page (§2) |
| CRM `company` name, phone, site, address (bot contacts) | Fed from the ERP details on Реквизиты; remove the second form | B-SETIA-1 (`BACKLOG.md:228`) |
| `cabinet_url` | Сервисы (`CabinetAddress`), only there | Same CRM field in 3 places; only `CabinetAddress` can check it (`CabinetAddress.tsx:26-29`) |
| `crm_base_url` | Сервисы | A system address, not a contact (`settings.py:37, 49-70`) |
| `support_email` | Реквизиты и бланк (contacts) | Read in client letters (`emails.py:237-241`) |
| `SystemSetting.vat_rate` | Remove from the UI; the single VAT field is `default_vat_rate` on Налоги и валюты | Not read by pricing (§3) |
| FX manual entry (`FxRateSection` and `RatesView`) | Налоги и валюты, one widget | Same ERP endpoint, two forms (§2) |
| `default_cost_currency`, `default_vat_rate`, `fx_rate_max_age_days` | Keep: Налоги и валюты | read by `quotes/access.py`, `finance/services/fx.py:109` |
| Numbering (ERP, EDS, CRM ticket label) | Keep: Нумерация | Already one editor (`admin_company.py:359-400`) |
| Quote terms, margins, payment, warranty, basis | Keep: Настройки · Продажи; reachable by ⚙ from Операции (already `erp → company`) | ERP `CompanySettings`; `company.settings` access |
| `offer_confirm_days`, `offer_expiring_days` | Продажи page, own card beside «Каталог» (not inside «Условия нового КП») | Model help texts: supplier price freshness |
| Catalog price visibility and publish threshold | Keep: Продажи · Каталог | DECISIONS 2026-10-14 M1-ERP-07 |
| ERP invoice and act reminders | Keep: Уведомления; fix the read-only tag | `pages.tsx:138-142` |
| `notifications.duty_user_ids`, DM throttle; `service_alerts` | Keep: Уведомления; drop `repeat_minutes` | §3 p.2 |
| Team channel | Telegram · Подключение (single); the Уведомления description stops claiming it | `TelegramPanel.tsx:89`; `SettingsForm.tsx:32` |
| `business_hours`, `escalation.sla_minutes` / `reminder_minutes`, `web_form.first_response_sla_minutes` | Время и сроки | Both SLA fields are «срок первого ответа» (§2); research L2 |
| `escalation` trigger thresholds and human-request terms | Telegram · Поведение | Bot dialog triggers (`settings.py:271-281`) |
| Bot texts, behaviour, qualification, stop words, competitors, KB search, reply templates, bot profile | Keep: Telegram | DECISIONS 2026-10-28 |
| SMTP, IMAP, mail log, inbox assist | Keep: Почта | DECISIONS 2026-10-28 «Почта — канал» |
| Mail types and sender rules (now Справочники · Почта) | Почта, as the channel's «Направления» | DECISIONS 2026-10-28 channel tabs |
| Web-form anti-spam | Keep: Формы сайта | CRM `web_form` |
| Deal loss reasons, deal currency | Keep: Справочники · Продажи | Research §4.1 «Сделки → Справочники» |
| Models, ERP pairing, storage, backups, system | Keep: Сервисы | CRM external-services registry |
| AI budget, data-protection policy, scan recognition | Keep: Расходы на ИИ; mark `erp_daily_usd` as display-only or wire it to ERP | §3 p.3 |
| Document, letter and email templates | Keep: Документы · Шаблоны; align the gate with NAVIGATION (lawyer) and with the `eds.inbox.register` edit right | §4 |
| Resolution templates | Документы · Шаблоны | Already listed and linked by «Все шаблоны» (`templates_catalog.py:137`); EDS only **(inference)** |
| Справочники (documents, calculation, categories, charge types) | Keep: Настройки · Справочники | DECISIONS 2026-11-11, one BFF `/dictionaries` |
| Статьи компании | Keep: Настройки | SPEC-v3 §7.6 |
| История + Обмен между системами | One «Журнал» page with a filter | SPEC-v3 §7.6, last paragraph |
| Выгрузки | Keep: Настройки · Журнал | Owner decision 2026-11-11 (`DECISIONS.md:308`) |
| First-run steps | Keep on the index, extended into a readiness list (бланк, нумерация, адрес поддержки, signing expiry) | `ui-standard.md` §14 p.5; plan СЦ-3 |
| Personal notifications, Telegram link, iCal, deputy, 2FA | Keep: Профиль | NAVIGATION «Коннекторы»; `ProfilePage.tsx:21-35` |
