# AREA 4: Document B (mobile and tablet) checked against the repository

Checkout: `` @ `2d57c5104` (merge of #818). Paths below are relative to that root. I only read code. Nothing was built or run.

## 0. Summary
- **Document B was written for a new, empty project.** It does not fit our situation. We already have two working adaptive front-ends, and Cabinet already ships as a **Telegram Mini App** (`apps/cabinet/index.html:21-23`, DECISIONS 2026-10-13 and 2026-10-14). Its "final stack" (React 19, Tailwind v4, shadcn, Zustand, TanStack Query) is roughly what Cabinet already has, except React 18. For the Platform it means replacing AntD, which conflicts with ADR-0011 §1, ADR-0013 §3 and the earlier assessment `docs/research/2026-11-18-flexible-ui-assessment.md:83,119`.
- **What is worth taking:** the engineering checklist (§5) and the idea of a tablet tier. The Platform has neither as a written rule. A tablet tier exists in code only implicitly, through thresholds at 1200, 1280 and 1440. No test and no snapshot runs at any tablet width.
- **What is not worth taking now:** PWA install, a service worker, Capacitor, App Store, Vaul, Motion, View Transitions, swipe-back. Push to phones already goes through Telegram: the employee bot (`apps/platform/bff/app/api/me_notifications.py:4-27`) and the client's Mini App or bot. That bypasses the iOS PWA push limit. All of this is one company's internal tool, with no App Store need.

## 1. Stack today

| | Platform (`apps/platform/web`) | Cabinet (`apps/cabinet`) | Document B wants |
|---|---|---|---|
| React | `^18.3.1` (package.json) | `^18.3.1` | 19 |
| Build | Vite `^8.3.4` | Vite `^7.0.0` | Vite. Confirmed. |
| UI | antd `^5.29.3` + pro-components; Lucide icons | Tailwind `^4.2.1` (`@tailwindcss/vite`) + `radix-ui` + shadcn (`src/components/ui/*`, 18 parts) + `sonner ^2.0.7` | Tailwind v4 + Radix/shadcn + Vaul + Sonner |
| Data | `@tanstack/react-query ^5.104`, `@tanstack/react-table 9.3.1` | `@tanstack/react-query ^5.90` | TanStack Query. Confirmed for both. |
| State | `zustand ^5` | none (Query + context) | Zustand |
| Router | `react-router ^7.18` | `react-router-dom ^7.18` | — |
| Tokens | `packages/ui-tokens/tokens.json` → AntD theme (`src/app/tokens.generated.*`) and shadcn CSS. `density.touchTargetMin: 44` exists (tokens.json:30), but its CSS variable `--rt-density-touch-target-min` (tokens.generated.css:84) **is not used anywhere** | same tokens | "brand tokens over native patterns": **already true**. Shared tokens are ADR-0018. |

Other stack facts:
- The current major versions are newer than ours: antd 6.7.1 (npm registry, peer React ≥18) and `@capacitor/core` 8.6.2. Document B's "Capacitor 6/7+" is out of date.
- The Vaul README says "This repo is unmaintained" (github.com/emilkowalski/vaul). So calling it "the industry standard" is **wrong as advice for 2026**.

## 2. Breakpoints, shell, master-detail

### Platform
- **Thresholds** (`src/app/shell/useViewport.ts:3-7,61-77`):
  - ≥1440: submenu expanded.
  - ≥1280: the side panel can be docked next to the page (`canDock`).
  - ≥1200: the panel on an object card is open by default.
  - <768: `mobile`.
  - The exported `Viewport` has only `mobile = !tablet` (line 77). **There is no named tablet tier.** In practice 768–1199 is the desktop layout: rail 64, collapsed submenu, panel only over the page. 1200–1279 is the same, plus the panel is open on cards.
- **Docking rule:** rail + menu + panel + 736 of working area (`useViewport.ts:45-54`, `AppShell.tsx:367-368`). On 1024 landscape: 64+480+736 = 1280 > 1024, so **a tablet can never get split view.** This is the owner's rule UX-1a (`docs/architecture/platform-frontend.md:99-100`; report rule 4).
- **Phone** (`AppShell.tsx:375-560`):
  - Shell height `100dvh` (line 375).
  - The rail becomes a bottom bar `ModuleRail variant="bottom"`, height 60 (`shell.css:79-98`). It holds **all visible modules (up to 6: `modules/registry.ts:13`) plus the profile avatar, so up to 7 tap zones**. There is no "More" and no safe-area inset.
  - The submenu becomes an AntD `Drawer` 280 on the left.
  - The panel becomes `ContextPanelSheet` (full-screen bottom sheet, only for sections with `sheetOnMobile`). That is just two ERP sections (`modules/erp/module.ts:17,28`). Every other section gets `ContextPanelDrawer`.
  - `docs/product/NAVIGATION.md:162` says "на телефоне «Настройки» уходят в меню профиля". In the code, `railItems` include `admin` when it is visible (`AppShell.tsx:241-257`), so this is **not true in code** (inference: nothing filters admin out on the phone).
- **Bottom sheets:** the report's "4 copies" is **confirmed**.
  - Shared: `shared/ui/Sheet.tsx:29-41` and `shared/ui/ContextPanel.tsx:265`.
  - Copies: `crm/messages/Dialog.tsx:155`, `eds/documents/DocumentSheet.tsx:32`, `eds/decision/DecisionSlot.tsx:69`, `eds/inbox/ResolutionPanel.tsx:222`.
  - All are AntD `Drawer placement="bottom"` at `100dvh`. That is a full-screen sheet, with **no snap points and no swipe to close**.
  - `shared/ui/Dialog` (the 448 centre window) has no phone branch (`areas/windows.md:23`).
- **"On the phone lists are cards"** (platform-frontend.md:196,279) is implemented **per screen**: 47 files in modules and features call `useViewport`/`useMediaQuery`, e.g. `erp/stock/OrdersTab.tsx:79-80` and `eds/inbox/InboxList.tsx:115-119`. Shared `DataTable` has no card mode.

### Cabinet
- One threshold, `md` (768): `SideNav` `hidden md:flex`, `w-64` or collapsed `w-16` (`components/shell/SideNav.tsx:38-39`). `BottomNav` `md:hidden` has 4 sections plus "Ещё" in a shadcn `Sheet side="bottom"` (`BottomNav.tsx:14-15,41,71-89`), `min-h-14`, with safe-area.
- Breakpoint usage in `.tsx`: `sm:` 84, `md:` 31, `lg:` 7, `xl:` 1. No tablet-specific layout.
- Note: Cabinet's layout already matches Document B's own numbers: sidebar 256 (B: 240–260), rail 64 (B: 72–80), bottom bar 4+1 (B: 4–5).

### Standards and DoD
- `ui-standard.md` mentions the phone **once**: §5, line 93, "36 px Cabinet, where people work from the phone". It says nothing about tablets, has no phone column, and its §11 checklist has no width check.
- `platform-frontend.md` covers the phone at §4 row "Узкие экраны" (:100), §4.1a (:229), the "UX-2b, 390 px" rule (:350-354) and lists→cards (:279). Its only tablet words are "768–1279: panel only over the page".
- The 1440 + 390 snapshot rule is in `ORCHESTRATOR.md:300` and DECISIONS 2026-10-29 W-27. The owner's readiness definition says "проверка глазами в 1440 и 390 px" (DECISIONS.md:301).
- Tests:
  - Playwright projects: `chromium` 1440×900 and `mobile` = Pixel 7 at 390×844, only for tests tagged `@mobile` (`playwright.config.ts:54-64`).
  - Viewport sizes used across both e2e suites: 1440 (39 setViewportSize, 49 object literals), 390 (30 / 33), and once each 1280, 1100, 1700.
  - **No 768, 820 or 1024. No WebKit/iPhone/iPad project. No `toHaveScreenshot` (0).**

## 3. Container queries versus media queries
- **Platform:** 10 `@container` rules and 9 `container-type` in 6 CSS files: `shared/ui/ui.css` (4), `eds/inbox/inbox.css`, `eds/decision/decision.css` (2), `eds/mail/mail.css`, `eds/new/new.css`, `admin/company/company.css`. Against that, 40 `@media` lines in 25 files: `max-width:767px` ×16, plus 600, 480, 575, 1199, 1023 and others. Two are not width queries: one `(hover: none)` (`ui.css:602`) and 4 `prefers-reduced-motion`.
- **Cabinet:** 1 `@container` (shadcn `card.tsx:23`), 1 CSS `@media`; everything else is Tailwind viewport prefixes.
- **PR #814** (merged 22.11, commit `09ab830e`, `eds/new/new.css`) is exactly Document B's point. The two-field row went from `1fr 1fr` to `repeat(auto-fit, minmax(min(100%,260px),1fr))`. The letter layout got `container-type: inline-size` and `@container (max-width:1039px)` on top of the old `@media (max-width:1199px)`.
  - The root cause was layout tied to the browser window while the docked panel narrowed the working area. The report's rule 9 ("пара складывается по ширине формы") is the same rule.
  - **Confirmed:** Document B's container-query thesis applies to us. Today it is used ad hoc, not as a rule.

## 4. Engineering checklist (Document B §5), item by item

| Item | Platform | Cabinet | Verdict |
|---|---|---|---|
| `100dvh` | shell `AppShell.tsx:375`, Sheet, auth pages (8 files). But `crm/messages/messages.css:16` uses `calc(100vh - …)` (on iOS the reply field may hide under the toolbar, inference) | `min-h-dvh`/`h-dvh`/`max-h-[..dvh]` (8 files) | mostly done; 1 stray `100vh` (plus dev `showcase.css`) |
| `viewport-fit=cover` + `env(safe-area-inset-*)` | **meta has no `viewport-fit`** (`index.html:5`). `safe-area-inset-bottom` only in `eds/decision/decision.css:265` and `eds/inbox/inbox.css:263`; these are inert without `viewport-fit=cover` (env() resolves to 0, inference). Bottom bar has none | `viewport-fit=cover` (`index.html:6`); BottomNav, "Ещё" sheet, TelegramBanner, UnsavedChangesBar use it | Cabinet done; Platform missing |
| `visualViewport` (keyboard) | 0 | 0. Rule exists in prose only: `docs/systems/cabinet/CONVENTIONS.md:91` | missing |
| `overscroll-behavior` | 0 | 0 | missing |
| `touch-action: manipulation` | 0 (only `touch-action:none` on column resize, `data-table.css:21`) | 0 | missing (low value: width=device-width already removes the 300 ms delay, inference) |
| `-webkit-tap-highlight-color` | 0 | 0 | missing |
| `user-select` / `-webkit-touch-callout` | 0 | 0 | missing; keep `text` on content as B says |
| 44/48 targets, `pointer: coarse` | AntD controls 32 / small 24 (`theme.ts:44`, tokens density). Bottom bar buttons 52 high. No `pointer:` media anywhere. Report's "200 small buttons" is **partly right**: there are 200 `size="small"` props in modules+features, of which about 110 `Button` + 22 `LinkButton` ≈ 132 buttons, 50 `Card`, 5 `Spin`, 4 `Pagination`, 3 `Select`… (heuristic: nearest JSX tag) | `Button` default h-9 (36), sm h-8, icon-xs 24 (`ui/button.tsx:23-31`); nav tabs `min-h-14` | missing as a rule; token exists unused |
| iOS focus zoom (not in B) | inputs 14 px (`tokens font.size.base 14`) → Safari zooms on focus (inference, known WebKit behaviour) | `text-base md:text-sm` in input/textarea (16 px on phone) | Platform gap B misses |
| `theme-color` meta | 0 | 0 (Mini App gets colours from `themeParams`, `src/telegram/theme.ts:129-139`) | missing |
| `navigator.share` | 0 | 0 | missing (useful only for client links, inference) |
| WebAuthn/passkeys | 0 | 0 (login = Telegram `initData` / magic link) | missing; Platform has a second factor (`features/profile/SecondFactorSection`) |
| Skeletons vs spinners | `Skeleton` in 60 files. `<Spin` lines: 11 in 10 files. The report's **8** = module spinners (`areas/windows.md:59`); +3 full-screen auth spinners (`AuthGate.tsx:26`, `SetupPage.tsx:61`, `LoginPage.tsx:93`) | `Skeleton` in 17 files, 0 Spin | report's count confirmed with that caveat |
| Optimistic UI | Already a rule in `ui-standard.md` §5 "Отклик без ожидания" (:94-96). In code: `onMutate` only in `features/notifications/useNotifications.ts:49,65`; `setQueryData` 41 lines in 31 files (mostly after the response, inference) | `onMutate` in `hooks/useMessagesFeed.ts:62` (pending message) | rule exists; applied in 2 places |
| Keep data on back (Query persistence) | in-memory only: `staleTime 5000`, `refetchOnWindowFocus`, `keepSamePathData` placeholder (`src/app/queryClient.ts:26-46`); no persister/idb | in-memory (`src/app/queryClient.ts:12`) | missing; low need online-only |
| Toasts | AntD `message`/`notification` (112 files) | Sonner | Cabinet = B |
| View Transitions / Motion / `vibrate` | 0 | 0 | not used |

## 5. PWA readiness
- **Platform:** no `public/` folder, no manifest, no icons, no service worker, no `vite-plugin-pwa`/Workbox, no push. Notifications go to the bell (SSE `useEventStream`, `AppShell.tsx:138-141`) and to Telegram for employees (`bff/app/api/me_notifications.py`; plan ГЛ-2, `runbooks/plan-2026-11-12.md:148`, "Telegram — для решений").
- **Cabinet:** only `favicon.svg` and `mockServiceWorker.js` (that is MSW for development, not a PWA). It runs as a Telegram Mini App:
  - `expand()` (`telegram/theme.ts:139`)
  - `BackButton` (`components/shell/useTelegramBackButton.ts:12-30`)
  - theme from `themeParams`
- **Offline:** none in either. **PWA = 0 %.**
- **Document B's iOS claims:**
  - Push only after "Add to Home Screen": **confirmed** (webkit.org/blog/13878, iOS 16.4).
  - No `vibrate` in Safari: **confirmed** (common knowledge; I did not fetch a source).
  - "Aggressive WebKit cache eviction": **partly**. The 7-day ITP cap applies to Safari browsing. Home Screen apps count their own days, and WebKit says it does not intend to delete first-party web-app data (webkit.org/blog/10218).

## 6. Decisions and plan about mobile
- **DECISIONS:**
  - 2026-10-13: Cabinet on web and Mini App.
  - 2026-10-14: M2-CAB-01 (Mini App login, Telegram back button), frame-ancestors, openTelegramLink, dark tokens.
  - 2026-10-16: M2-QA-01 (Cabinet at 1440 and 390, web and Mini App).
  - 2026-10-29: W-27 (1440 and 390 snapshots required).
  - 2026-10-31: Cabinet redesign with phone bottom navigation.
  - 2026-11-04: partner gets the Mini App; NOTIFY.
- **No row** for PWA, tablet, Capacitor, a native app, or an employee Mini App. ADR-0011 §1: "Cabinet, Mini App и Telegram-бот остаются каналами клиента". The Platform is a web SPA.
- **Plan** (`runbooks/plan-2026-11-12.md`): ГЛ-2 (:148), counter on "Главная" "в рейле и на телефоне"; Х-9 (:227), "боковое окно на телефоне" (BACKLOG B-020, `docs/BACKLOG.md:33`: move D1-3 and D1-5 onto the shell sheet and remove their own sheets). No tablet row.
- **Who uses the phone:**
  - Director approves from the phone: `docs/research/2026-10-27-ux-audit/README.md:268` ("Мобильная версия обязательна (директор согласует с телефона)").
  - Clients and partners: Mini App.
  - Warehouse and manager: **no source found**. SPEC-v3 has no role-by-device statement, only the bell sheet "на телефоне — во всю ширину" (:594) and the shell (:797).
  - Tablet use by any role: **not documented anywhere** (cannot verify).

## 7. Gestures and back navigation
- Swipe, touch or pointer gesture code: 0 in both apps. Pull-to-refresh: 0.
- Back:
  - Platform: browser history plus `UnsavedGuard` (`useBlocker` and `beforeunload`, `shared/ui/UnsavedGuard.tsx:78-101`).
  - Cabinet: same pattern (`UnsavedChangesBar.tsx:68,171`) plus the Telegram system BackButton in Mini App.
- Document B's "swipe-back only in standalone": **not applicable** today. We have no own swipe, and the Telegram back button already covers the Mini App.

## 8. Document B recommendation versus us

| Recommendation | Status | Platform (AntD) | Cabinet (shadcn) | Size |
|---|---|---|---|---|
| One brand token system over native patterns | done (ADR-0018, `packages/ui-tokens`) | — | — | — |
| PWA-First + Capacitor-Ready, App Store | missing; **conflicts** with ADR-0011 and the channel model (client = Mini App/bot; push = Telegram) | not needed for staff (inference); minimal manifest + icons only if owner wants home-screen launch | Mini App already covers install, push and back | manifest S; SW/offline L; Capacitor L+ (not recommended) |
| React 19 + Tailwind v4 + shadcn + Zustand | Cabinet ≈ done (React 18); Platform **conflicts** with AntD decision (ADR-0013 §3; flexible-ui §83,119) | React 19 needs antd 6 (antd 5 needs patch) + pro-components check | React 19 bump | Platform rewrite XL, no; React 19 bump M |
| Vaul bottom sheets | partly: full-screen AntD Drawer sheets, 4 copies; Vaul unmaintained | one shared `Sheet` (report rule 5) + Dialog phone branch; drag-to-close optional | shadcn `Sheet side=bottom` exists | S–M |
| View Transitions + Motion | missing | skip (reduced-motion rule exists, `theme.ts:15-16`) | optional | S, low value |
| Sonner | Cabinet done; Platform AntD `message` | keep AntD | done | — |
| Adaptive matrix: bottom bar 4–5 | Platform partly: up to 6 modules + avatar, no "More"; Cabinet done | cap at 4–5 + "Ещё" generated from the one menu (rule 22) | done | S |
| Navigation rail on tablet | Platform done in effect (rail 64 at ≥768); Cabinet sidebar 256 at ≥768 (can collapse to 64) | name the tier in `useViewport` | optional collapsed by default at md–lg | S |
| Master-detail split on tablet | missing; **conflicts** with UX-1a (dock only ≥1280 and ≥736 work area) | owner decision; at most for queues (inbox, approvals) at ≥1024 | n/a (client lists are small) | M |
| Filters/actions: bottom sheet on phone, popover on tablet | partly (FilterBar wraps; no sheet) | shared FilterBar phone mode | — | M |
| Lists: cards on phone, dense on tablet | partly: per-screen in about 47 files; folding rule at platform-frontend:275 | card mode in shared `DataTable` | — | M–L |
| Container queries for components | partly (10 rules; PR #814) | rule in ui-standard + convert shared parts (form row, ListFrame, panel) | Tailwind v4 `@container` built in | S rule, M conversion |
| `pointer: coarse` 44–48 targets | missing; token 44 unused | coarse-pointer override of `controlHeight`/small buttons in theme | button sizes on coarse | S–M |
| dvh / safe-area / viewport-fit | Cabinet done; Platform partly | add `viewport-fit=cover`, insets on bottom bar, sheets, save bar; fix messages.css 100vh | — | S |
| visualViewport keyboard | missing | hook for sticky footers in sheets and save bar | same (rule in CONVENTIONS:91) | S–M |
| overscroll, tap-highlight, touch-action, user-select | missing | one global CSS block | same | S |
| TanStack Query + IndexedDB persistence | missing | not before launch (security of cached personal data on shared devices, inference) | maybe for Mini App reopen | M |
| Optimistic UI + skeletons | rule exists; partial | ban `Spin` (report rule 13); apply §5 rule | mostly skeletons | S–M |
| theme-color, navigator.share, WebAuthn | missing | theme-color S; passkeys M (BFF/CRM auth change, owner decision) | Telegram covers theme; share S | S / M |
| Platform Adapter Layer, core/platform/shell/features | partly: Platform has `app/shell`, `shared`, `features`, `modules`; Cabinet `telegram/` is in effect an adapter | no new layer without Capacitor | — | — |
| Device testing iPhone Safari, iPad | missing: Chromium only, no WebKit, no tablet | add WebKit iPhone + iPad projects | same | S |

## 9. Adaptive matrix mapped onto the report's 25 rules (§7)
**Rules that should get a phone/tablet column:**
- **1 (sizes):** phone = full-screen sheet; Dialog = bottom sheet. Tablet 768–1279 = panel only over the page (already in code); state that 640 on 768 is allowed.
- **2 (panel header/footer):** phone header = back/close + title; footer sticky above the safe area and the keyboard.
- **3 (one confirmation):** phone = buttons full-width in a bottom sheet.
- **4 (panel over / docked):** tablet = over only. Write it down; this is the conflict point with B's split view.
- **5 (sheet):** keep; add "drag-to-close optional, one component, also for Dialog".
- **7–9 (forms):** phone = one column, input font ≥16 px on coarse pointer. Rule 9 becomes "pair folds by **container** width" (PR #814).
- **10 (save):** phone = bar above the bottom bar and above the keyboard.
- **11–13 (tables):** phone = cards from shared `DataTable`, "…" opens an action sheet. Tablet = table with second-line folding, no horizontal scroll at 768/1024. Rule 13 skeleton applies to cards too.
- **14–15 (header, status tabs):** phone = actions into "…", status tabs scroll sideways (UX-2b).
- **17 (small buttons):** on coarse pointer no 24 px targets; row actions only via "…" (≥44).
- **20 (settings frame):** phone = menu list → page (stack); tablet = menu left.
- **22 (one menu):** the bottom bar's 4–5 items + "Ещё" are built from the same menu.

**Rules with no device column:** 6, 16, 18, 19, 21, 23–25.

**Checks to add:**
- Reference snapshots of the four templates (list, card, panel form, window) at **390** (phone; Pixel 7 project plus a WebKit iPhone project), **768** (tablet portrait), **1024** (tablet landscape / small laptop), **1280** (dock threshold) and **1440**. Today only 1440 and 390 exist, without image comparison.
- Axe at 390.
- An automatic check under `hasTouch`/coarse pointer: interactive targets ≥44 px; input font-size ≥16; no horizontal scroll at 768 and 1024 (extend `ux-2b`/`t1-table-widths`).
- A lint ban on raw `Drawer placement="bottom"` outside `shared/ui`.
- A CSS check that new component layout uses `@container`, not `@media (max-width…)` (inference: suggested as "new violations none, old list shrinks", same mode as report §7).
- Change the DoD wording in ORCHESTRATOR:300 / W-27 from "1440 и 390" to "1440, 1024, 768, 390". **This needs an owner decision.**
