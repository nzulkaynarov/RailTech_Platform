# AREA 3 — external fact-check of DOCUMENT B (mobile / tablet web app), 2026-11-23

Method: primary pages fetched today (WebKit, caniuse, W3C, Apple, Google, Ionic, shadcn, TanStack, GitHub, npm registry), plus read-only greps in ``. "(memory)" means well-known but not re-fetched today. "(inference)" means my conclusion.

## 0. Headline findings

1. **Document B's "final stack" is, minus four libraries, what Cabinet already runs.** `apps/cabinet/package.json`: Tailwind `^4.2.1`, `radix-ui`, `sonner ^2.0.7`, TanStack Query, Vite, bottom nav with safe-area, `viewport-fit=cover`. For the Platform (AntD 5) the stack would mean a rewrite: 386 non-test `.tsx` files, 74,765 lines, 289 files importing antd, 123 e2e specs.
2. **Three library claims are outdated.**
   - Vaul is unmaintained: last npm release 1.1.2 on 2024-12-14, and shadcn/ui Drawer moved to Base UI.
   - "Capacitor 6/7+": v6 is end-of-support, v7 leaves extended support 2026-12-08, v8 is active, v9 is at rc.0.
   - Ionic React supports React Router 6 only; both apps are on React Router 7.18.
3. **Two engineering claims are wrong or half-wrong for iOS.**
   - iOS standalone web apps also have the system edge-swipe back, so "own swipe-back only in standalone" still conflicts.
   - `theme-color` no longer tints Safari 26 toolbars (secondary sources).
4. **"Optimistic UI for any action" plus an IndexedDB-persisted cache is unsafe for approvals and money.** It also contradicts the invariant "код решает". It is acceptable only for reversible, low-stakes actions.
5. **The push argument for Capacitor is weak here.** Staff decisions go through Telegram (`docs/history/runbooks/plan-2026-11-12.md:148`), and Cabinet in the Mini App gets notifications from the bot (`docs/systems/cabinet/README.md:160`). No project document decides on PWA, native apps or offline (grep of `docs/` found none).
6. **Most of Document B's value is the checklist and the adaptive matrix, and those are stack-independent.** About half is already in the code; the gaps are listed in section 3.
7. **AntD 5 is frozen.** Last release 5.29.3 on 2025-12-18; v6 shipped 2025-11-22 with a "1-year maintenance period" for v5, so the window has just closed (inference on the exact date). This is a real risk the document does not mention, and it is independent of mobile.

## 1. Verdict table

### (1) iOS PWA limits

| # | Claim | Verdict | Note / evidence |
|---|---|---|---|
| 1.1 | Web Push on iOS only after manual "Add to Home Screen" | confirmed | WebKit 16.4 post: a web app "added to the Home Screen can request permission… in response to direct user interaction" (https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/). Still required per OneSignal's iOS guide (https://documentation.onesignal.com/docs/en/web-push-for-ios). iOS 26 softens install: every site added to Home Screen opens as a web app by default (https://www.macrumors.com/how-to/save-safari-bookmark-web-app-iphone-home-screen/). iOS 27 changes: cannot verify, nothing found. |
| 1.2 | Declarative Web Push (not in the document) | document omits | Shipped for testing in iOS 18.4; works "without requiring an installed service worker" (https://webkit.org/blog/16535/meet-declarative-web-push/). Whether it still needs Home Screen: the post does not say. |
| 1.3 | No `navigator.vibrate()` in Safari | confirmed | caniuse: unsupported in every Safari and iOS Safari version listed, up to 27.x (https://caniuse.com/vibration). |
| 1.4 | "Aggressive WebKit cache eviction on inactivity" | partly | The 7-day cap is for Safari use without interaction with the site. Home-screen web apps "have their own counter" and "we do not expect the first-party… to have its website data deleted" (https://webkit.org/blog/10218/full-third-party-cookie-blocking-and-more/). Since 2023, storage is best-effort, evicted least-recently-used under pressure; `persist()` is granted by heuristics, Home Screen being one factor (https://webkit.org/blog/14403/updates-to-storage-policy/). The claim is true for a browser tab and overstated for an installed app. |
| 1.5 | EU DMA and home-screen web apps (not in the document) | no impact | Apple reversed the removal in March 2024; web apps stay WebKit-based (https://www.theregister.com/2024/03/02/apple_reverses_pwa_decision/). Not relevant to Uzbekistan. 2026 status of alternative engines: cannot verify. |
| 1.6 | Badges, background sync (not in the document) | document omits | Badging API: 16.4+, Home Screen web apps only (https://webkit.org/blog/14112/badging-for-home-screen-web-apps/). Background Sync: unsupported in every Safari and in Firefox through 160 (https://caniuse.com/background-sync). An offline write queue therefore cannot rely on the service worker on iOS. |

### (2) Capacitor, Expo, store policy

| # | Claim | Verdict | Note / evidence |
|---|---|---|---|
| 2.1 | "Capacitor 6/7+" | wrong (outdated) | Support policy: v8 active (released 2025-12-08, min iOS 15, Android API 24); v7 extended support ends 2026-12-08; v6 end of support 2026-01-20 (https://capacitorjs.com/docs/main/reference/support-policy). Latest stable 8.6.2 (2026-11-12); 9.0.0-rc.0 same day (npm, https://github.com/ionic-team/capacitor/releases). |
| 2.2 | Capacitor is the right wrapper for an existing React SPA; Expo/RN costs more | confirmed (inference on cost) | Adding Capacitor is six CLI steps on an existing build output (https://capacitorjs.com/docs/getting-started). Expo reuses web code only through "DOM components", which run in a webview with a separate React tree (https://docs.expo.dev/guides/dom-components/). |
| 2.3 | "1–2 weeks to package without touching business logic" | partly | The technical wrap is short. Not counted: developer accounts, signing, APNs/FCM, review cycles. Platform-specific blocker (inference): the session is an `HttpOnly`, `SameSite=Lax` cookie on the BFF (`apps/platform/bff/app/cookies.py:3-5`). A bundled Capacitor app runs from a local origin, so requests become cross-site. The fix is either loading the live site (exactly the "repackaged website" case) or changing auth. Cabinet auth not checked. |
| 2.4 | Guideline 4.2 rejects primitive WebView wrappers | confirmed | "Your app should include features, content, and UI that elevate it beyond a repackaged website" (https://developer.apple.com/app-store/review/guidelines/). |
| 2.5 | A Capacitor app with tab bar, offline, haptics, push "stably passes" review | cannot verify | No source can guarantee this; review is discretionary. |
| 2.6 | Distribution for an employee-only app (not in the document) | document omits | Unlisted distribution exists for "employee resources", is link-only, and still goes through App Review (https://developer.apple.com/support/unlisted-app-distribution/). |
| 2.7 | Google Play and WebView apps | confirmed, low risk | Banned: "a webview of a website without permission from the website owner" (https://support.google.com/googleplay/android-developer/answer/9899034). Own site is allowed. Minimum-functionality text not fetched. |
| 2.8 | Similarity percentages "85–90 / 95–98 / 100 / 75–85 %" | cannot verify | No source; not measurable. |

### (3) UI libraries

| # | Claim | Verdict | Note / evidence |
|---|---|---|---|
| 3.1 | Tailwind CSS v4 | confirmed | 4.3.5 on 2026-11-06 (npm). Cabinet already on `^4.2.1`. |
| 3.2 | Vaul is "the industry standard" for bottom sheets | wrong (outdated) | README: "This repo is unmaintained" (https://github.com/emilkowalski/vaul). Last npm release 1.1.2, 2024-12-14. shadcn: "The drawer component now uses Base UI instead of Vaul" (https://ui.shadcn.com/docs/components/drawer). Replacement: Base UI Drawer with snap points (https://base-ui.com/react/components/drawer; `@base-ui/react` 1.9.0, 2026-10-09). Cabinet has no Vaul; it uses a Radix sheet (`apps/cabinet/src/components/shell/BottomNav.tsx:89`). |
| 3.3 | Sonner | confirmed | 2.0.8, 2026-08-09 (npm). Already in Cabinet. Same author as Vaul (inference: watch it). |
| 3.4 | Motion (ex Framer Motion) | confirmed | `motion` 14.14.0, 2026-11-13 (npm). Not in either app. |
| 3.5 | View Transitions "Chromium and Safari 18+" | confirmed, incomplete | Same-document: Chrome 111, Safari 18.0, Firefox 144, Firefox Android 160; 93.17 % global (https://caniuse.com/view-transitions). Cross-document: Chrome 126, Safari 18.2, Firefox partial; 89.6 % (https://caniuse.com/cross-document-view-transitions). An SPA needs only same-document. Zero uses in either app. |
| 3.6 | Ionic React: ready mobile router | partly | Ionic 9 (August 2026) rebuilt routing for React Router 6; "React Router 7 is next on our roadmap" (https://ionic.io/blog/?p=6843). Both apps use React Router `^7.18.4`, so Ionic means a router downgrade. `@ionic/react` 9.0.13, 2026-11-20 (npm). |
| 3.7 | Konsta UI: visual components only, weak for tables | confirmed (scope from memory) | v5.5.0, 2026-09-28 (npm); v5 updated for Tailwind 4 and React 19 (https://konstaui.com). |
| 3.8 | Framework7: "closed ecosystem" | partly | It is MIT open source (https://github.com/framework7io/framework7), 9.3.0 on 2026-10-30 (npm). "Tightly coupled to its own router" is fair (memory); "closed" is not. |
| 3.9 | Mantine as an alternative | not checked | — |

### (4) CSS and input

| # | Claim | Verdict | Note / evidence |
|---|---|---|---|
| 4.1 | Container Queries as "the key technology" | confirmed | Chrome 106, Safari 16.0, Firefox 110; 96.03 % (https://caniuse.com/css-container-queries). Limits (memory): the container needs `container-type`, an element cannot query itself, and shell-level navigation still needs viewport queries. Already a Platform rule (`docs/architecture/platform-frontend.md:115`), used in 8 CSS files. Cabinet: one use. |
| 4.2 | `100dvh` instead of `100vh` | confirmed | Already used: `apps/platform/web/src/app/shell/AppShell.tsx:375`, Cabinet `min-h-dvh`. Whether `dvh` reacts to the iOS keyboard: cannot verify. |
| 4.3 | `viewport-fit=cover` plus `env(safe-area-inset-*)` | confirmed (memory) | Cabinet has both (`apps/cabinet/index.html:6`). Platform uses `env()` in two CSS files (`modules/eds/inbox/inbox.css:263`, `modules/eds/decision/decision.css:265`) but `apps/platform/web/index.html:5` has no `viewport-fit=cover`. Harmless in a browser tab; matters only if installed (inference). |
| 4.4 | `visualViewport` for the iOS keyboard | confirmed | Safari has no `interactive-widget` (https://bugs.webkit.org/show_bug.cgi?id=259770); Chrome 108+ and Firefox 132+ do (https://developer.chrome.com/blog/viewport-resize-behavior). Zero uses in either app. `@capacitor/keyboard` mode: not re-checked. |
| 4.5 | `overscroll-behavior-y: none` on root stops pull-to-refresh and rubber-banding | partly | Not re-checked today; Safari support only from 16 (memory). Zero uses in either app. |
| 4.6 | `touch-action: manipulation` "removes click delay" | partly | The delay is already gone on pages with a device-width viewport (memory, https://webkit.org/blog/5610/more-responsive-tapping-on-ios/). The real effect is disabling double-tap zoom. |
| 4.7 | tap-highlight, `user-select` with copyable content | confirmed (memory) | The exception for copyable data is right for a business app. |
| 4.8 | Targets 44×44 (Apple) and 48×48 (Material) | confirmed, incomplete | WCAG 2.2 SC 2.5.8 (AA): "at least 24 by 24 CSS pixels" with a spacing exception (https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html); 44×44 is 2.5.5, level AAA. Platform theme has `controlHeightSM: 24` (`apps/platform/web/src/app/theme.ts:44`): meets AA, below 44. Cabinet nav rows are `min-h-12` (`BottomNav.tsx:151`). |
| 4.9 | `pointer: coarse` / `pointer: fine` and `hover: hover` | partly | These report the primary input only; hybrids need `any-pointer` / `any-hover` (memory). Zero uses in either app. |
| 4.10 | Dynamic `theme-color` sync | partly (outdated on iOS 26) | "Safari 26 has dropped support for the theme-color meta tag"; tint comes from page background (https://developer.apple.com/forums/thread/801239, https://benfrain.com/ios26-safari-theme-color-tab-tinting-with-fixed-position-elements/). Secondary sources. Still valid on Android. |
| 4.11 | Own swipe-back only in standalone or Capacitor | partly wrong | iOS standalone web apps have had system edge-swipe back since iOS 12.2 (https://firt.dev/ios-12.2/), so the double gesture also occurs there. Valid inside Capacitor (inference). Not addressed: Telegram Mini App, Cabinet's main phone channel, which has its own Back button (`apps/cabinet/src/components/shell/useTelegramBackButton.ts`). |
| 4.12 | `navigator.share`, WebAuthn | confirmed (memory) | Passkeys inside the Telegram in-app webview: cannot verify. |

### (5) Offline and optimistic UI

| # | Claim | Verdict | Note / evidence |
|---|---|---|---|
| 5.1 | TanStack Query with IndexedDB persistence for "zero-flicker back" | partly | The plugin is real; default `maxAge` is 24 hours; the IndexedDB persister is an example built on third-party `idb-keyval` (https://tanstack.com/query/latest/docs/framework/react/plugins/persistQueryClient). In-session back navigation is already served by the in-memory cache (inference); persistence only helps cold start and offline. |
| 5.2 | Fit for a business app with money and approvals | partly, with risks (inference) | (a) A restored cache can show an approval state up to 24 hours old; Platform today uses `staleTime` 5 s with refetch on focus (`apps/platform/web/src/app/queryClient.ts:31`). (b) Paused mutations "will be retried in the same order when the device reconnects" and cannot resume after reload without a default `mutationFn` (https://tanstack.com/query/latest/docs/framework/react/guides/mutations); a replayed "approve" needs server idempotency and a state precondition. (c) Prices, counterparties and personal data would sit unencrypted on the device and survive logout unless cleared. (d) No Background Sync on iOS (1.6). |
| 5.3 | "Any user action must update instantly (optimistic)" | wrong for this domain | Acceptable for reversible actions; Platform already does it for notification read state (`apps/platform/web/src/features/notifications/useNotifications.ts:49,65`). For sign, approve and pay it contradicts "код решает, модель предлагает" (ORCHESTRATOR §3) and the owner rule to confirm irreversible actions. The document's examples are consumer ones (like, cart). |
| 5.4 | Skeletons instead of spinners | confirmed as a rule | Already rule 13 of the report (8 spinners remain). |

### (6) Adaptive navigation

| # | Claim | Verdict | Note / evidence |
|---|---|---|---|
| 6.1 | Breakpoints <768 / 768–1024 / >1024 | partly | These are Tailwind defaults, not a platform standard. Material: compact <600, medium 600–839, expanded 840–1199, large 1200–1599, extra-large ≥1600 dp, and classes follow the window, not the device (https://developer.android.com/develop/ui/compose/layouts/adaptive/use-window-size-classes). Consequence (inference): 600–767 px windows get the phone layout. The repo already uses 768 and 1024 in Cabinet (`apps/cabinet/src/app/App.tsx:29`, `apps/cabinet/src/hooks/useMediaQuery.ts`) and 768/1200/1280/1440 in Platform (`apps/platform/web/src/app/shell/useViewport.ts`). No reason to change. |
| 6.2 | Bottom bar on phone, rail on tablet, sidebar on desktop | confirmed in direction | Android guidance: navigation bar in compact, rail in expanded (https://developer.android.com/develop/adaptive-apps/guides/build-adaptive-navigation). Exact figures (4–5 items, 72–80 px, 240–260 px): cannot verify today. Platform: rail 64 px, menu 200 px, bottom bar below 768. |
| 6.3 | Apple HIG: tab bars, split view on iPad | cannot verify today | The HIG page returned no body text. |
| 6.4 | Split view on tablet; bottom sheet / popover / modal by size; cards / grid | confirmed as a pattern | Platform already has lists as cards below 768 (`docs/architecture/platform-frontend.md:279`) and sheets on phone (`:229`). There is no tablet two-column tier: at 768–1279 the side panel is overlay-only (`:100`). |

### (7) AntD 5 versus the document's stack

| # | Question | Verdict | Note / evidence |
|---|---|---|---|
| 7.1 | Is AntD 5 adequate on phones? | partly (inference; no primary source lists the gaps) | Adequate for "read, decide, approve on a phone", which is what the project requires (390 px snapshots, cards, sheets). Not adequate for "indistinguishable from native": no draggable bottom sheet (Platform has six files with a static bottom `Drawer`, e.g. `apps/platform/web/src/shared/ui/Sheet.tsx:31`), no card mode in Table, 32/24 px controls, hover-driven popups. No project document sets the native-like goal for the Platform. |
| 7.2 | Ant Design Mobile as the fix | not recommended (inference) | `antd-mobile` 5.43.0, 2026-09-14 (npm), is a separate package with separate components. It would create a second component system, against report rule 7. |
| 7.3 | AntD 5 lifecycle | risk the document omits | v6 announced 2025-11-22; v5 "will… enter a 1-year maintenance period" (https://github.com/ant-design/ant-design/issues/55804). Last v5 release 5.29.3, 2025-12-18; current antd 6.7.1 (npm). v6 supports React 18+. |
| 7.4 | "React 19" in the final stack | not a prerequisite | Both apps are on React 18.3.1. AntD 5 on React 19 needs `@ant-design/v5-patch-for-react-19` (https://5x.ant.design/docs/react/v5-for-19). |

### (8) Roadmap "2–3 + 2 + 1–2 weeks"

| Reading | Verdict | Note |
|---|---|---|
| Greenfield skeleton with no business screens | plausible | Not our case. |
| Applied to Cabinet | overstated (inference) | Stage 1 mostly exists. Missing: manifest and service worker (zero occurrences), touch hygiene, a rail tier, and a Telegram adapter the document does not foresee. |
| Applied to Platform as a stack change | wrong by an order of magnitude | 386 files, 74,765 lines, 289 files on antd, 123 e2e specs. It also collides with the report's programme: Q1 is "почти целиком" taken (report §1 item 13). |
| Stage 3 (Capacitor) | partly | See 2.3: store, signing, push and auth work are not counted. |
| Any stage before launch | does not fit | Report §1 item 13: launch already slips to about 27 Dec – 5 Jan. |

## 2. Stack-independent rules versus stack-specific items

**Adoptable on both AntD and shadcn (rules, not libraries):**
- Viewport and safe areas: `100dvh`, `viewport-fit=cover` with `env()` insets.
- Keyboard: `visualViewport` handling on forms with a sticky action bar.
- Scroll and touch: root `overscroll-behavior`, `touch-action: manipulation`, tap-highlight, `user-select` with copyable business data.
- Targets: at least 24 px always (WCAG AA), 44–48 px for primary actions under coarse pointers; never hover-only functionality (`any-hover`).
- Container Queries for reusable cards (already a Platform rule).
- The adaptive matrix as a pattern: bottom bar, rail, sidebar; sheet, popover, modal; cards, table. Tablet split view is the one piece neither app has.
- One adaptive modal component (sheet on phone, dialog or panel on desktop). This is report rule 5.
- Skeletons; same-document View Transitions as progressive enhancement.
- A platform adapter interface for share, haptics and storage. For Cabinet it needs three implementations (web, Telegram Mini App, Capacitor), not two.
- Optimistic updates only for reversible actions; server idempotency for any queued write.
- Module layout `core / platform / shell / features` (architecture, not stack).

**Require the document's specific stack:**
- Tailwind v4 with Radix/shadcn: Cabinet already has it; Platform would need a rewrite.
- Vaul: do not adopt. Use Base UI Drawer on shadcn; on AntD use `Drawer` at the bottom or a single shared sheet.
- Sonner (AntD has its own `message` / `notification`), Motion, Zustand: optional; Platform already has Zustand.
- Ionic, Konsta, Framework7: replace the component layer; Ionic also forces React Router 6.
- `vite-plugin-pwa` and Capacitor: stack-neutral (any Vite SPA), but a product decision with no basis in project documents yet. `vite-plugin-pwa` 2.0.0, 2026-10-03 (npm).
- Persisted TanStack cache: stack-neutral technically, but needs a data-at-rest and stale-approval policy first.

## 3. Gaps against the document's own checklist

| Item | Platform | Cabinet |
|---|---|---|
| `dvh` | yes (8) | yes (8) |
| safe-area `env()` | 2, without `viewport-fit=cover` | 4, with `viewport-fit=cover` |
| `@container` | 10 uses, written rule | 1 |
| `visualViewport`, `overscroll-behavior`, tap-highlight, `pointer: coarse`, `hover: hover` | 0 | 0 |
| `touch-action` | 1 (table resize handle) | 0 |
| manifest, service worker, `theme-color`, `navigator.share`, View Transitions, persisted query cache | 0 | 0 |
| Optimistic updates (`onMutate`) | 2 (notifications) | 1 (messages) |
| Bottom navigation on phone | yes, below 768 | yes, `BottomNav` |
| Telegram Mini App integration | n/a | Back button, theme, expand; no haptics wrapper |

## 4. Not verified

- iOS 27 / Safari 27 changes to web push or web apps.
- Apple HIG tab-bar and iPad guidance; Material figures for bar item count and rail width.
- Google Play minimum-functionality text.
- `overscroll-behavior` and `dvh` behaviour with the iOS keyboard on current versions; iOS 26 `visualViewport` bugs.
- Passkeys and service workers inside the Telegram in-app webview.
- Cabinet's auth model with respect to Capacitor.
- The document's similarity percentages and "stably passes moderation".

Files referenced (all under ``): `apps/cabinet/package.json`, `apps/platform/web/package.json`, `apps/platform/web/index.html`, `apps/cabinet/index.html`, `apps/platform/web/src/app/shell/useViewport.ts`, `apps/platform/web/src/app/shell/AppShell.tsx`, `apps/platform/web/src/shared/ui/Sheet.tsx`, `apps/platform/web/src/app/theme.ts`, `apps/platform/web/src/app/queryClient.ts`, `apps/platform/bff/app/cookies.py`, `apps/cabinet/src/components/shell/BottomNav.tsx`, `apps/cabinet/src/telegram/webapp.ts`, `docs/architecture/platform-frontend.md`, `docs/systems/cabinet/CONVENTIONS.md`, `docs/systems/cabinet/README.md`, `docs/history/runbooks/plan-2026-11-12.md`, `docs/research/2026-11-22-platform-ownership/README.md`.
