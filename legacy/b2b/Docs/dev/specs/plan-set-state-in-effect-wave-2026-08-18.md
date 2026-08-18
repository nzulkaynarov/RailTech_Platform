# Волна 2.3b: `set-state-in-effect` — 26 мест и включение правила

_Решение владельца 18-08: «переписать волной и включить правило». Волна ЧИСТО техническая: поведение остаётся прежним везде, кроме мест, где нынешний эффект даёт лишний кадр — там кадр исчезает._

## Почему это не «стиль»

`useEffect`, который синхронизирует состояние с пропсами, показывает пользователю **старое
состояние на один кадр**, потом перерисовывает. На быстрых машинах незаметно, на медленных —
мигает; при этом каждый такой эффект тянет за собой ручную защиту от рефетча (ref-гарды, списки
примитивов в зависимостях), а забытая защита стирает то, что человек печатает. Четыре настоящих
дефекта волны 2.3a (18-08) — ровно этого класса.

Канон React (react.dev, «You Might Not Need an Effect»): **derived value** → **`key` для сброса**
→ **корректировка состояния в рендере**. Последнее уже завёрнуто в наш `useDraftState`.

## Семейства (разбор по местам)

### A. Форма из `useQuery.data` / `target` → `useDraftState`

Механическая замена; там, где стоял ref-гард «пересадить только при смене id», источником
становится сам id, а `build` читает свежий объект из замыкания — семантика та же, ref не нужен.

| Место | Сейчас | Станет |
|---|---|---|
| `CompanyDefaultsSettings.tsx:92` | `if (settings) setForm(toForm(settings))` | `useDraftState(settings ?? null, …)` |
| `CompanyDocumentProfileSettings.tsx:164` | то же с `profile` | то же |
| `CompanyNumberingSettings.tsx:89,93` | два эффекта (`settings`, `scheme`) | два `useDraftState` |
| `UserDetailSheet.tsx:58` | `if (user) setDraft({...user})` | `useDraftState(user, …)` |
| `AdminMasterDataPage.tsx:47`, `AdminEntitlementsPage.tsx:73`, `AdminSubscriptionsPage.tsx:100`, `AdminEmailTemplatesPage.tsx:131,198` | `setDraft(target ? … : blank())` | `useDraftState(target, …)` |
| `useProductForm.ts:167,175,192` | 3 ref-гарда (`seededTargetId`, `seededFullId`, `seededOfferId`) | `useDraftState` по `id` как источнику; ref-гарды уходят |
| `QuoteSettingsDialog.tsx:94` | ref-гард `seededQuoteIdRef` + 9 сеттеров | один `useDraftState(open ? quote.id : null, …)` на объект формы |
| `InvoicesPage.tsx:81` | ключ = `selectedId` + примитивы счёта | `useDraftState` по составному ключу (семантика 1:1) |
| `SectionNoteRow.tsx:50`, `SpecificationsSection.tsx:44` | ре-синк буфера строки | `useDraftState` (у `SpecificationsSection` сохраняется гард «наша же запись вернулась кругом») |
| `RecordPaymentDialog.tsx:79,88`, `SendQuoteDialog.tsx:59` | сид при открытии | `useDraftState` по сессии открытия |

### B. Сброс при закрытии диалога → сессия открытия

`CommandPalette:94`, `DocumentSearchDialog:59`, `ConfirmActionDialog:88`, `ExcelPasteDialog:55,64`,
`RequestItemsEditor:76` (сброс AI-подсказок), `AICatalogMatchDialog:45`.

Канон — **размонтировать** содержимое: Radix и так снимает `DialogContent` при закрытии, поэтому
состояние, живущее ВНУТРИ содержимого, сбрасывается само. Где выносить тело в подкомпонент дорого —
`useDraftState(open ? sessionId : null, …)`: тот же сброс без эффекта и без лишнего кадра.

### C. Производные значения — состояние вообще не нужно

| Место | Сейчас | Станет |
|---|---|---|
| `PasswordSetupPage:64`, `ResetPasswordPage:55` | эффект пишет `serverError` при кривой ссылке | `linkError` вычисляется в рендере, показывается `serverError ?? linkError` |
| `DealChatPanel:61` | эффект подставляет единственную «дорожку» | `effectiveLane = lane ?? (единственная)` |
| `MyProductsPage:103` | сброс выбора при смене выборки | `useDraftState(selectionKey, () => new Set())` |
| `MyProductsPage:109` | клампинг страницы эффектом | `effectivePage = min(page, lastPage)` |

### D. Остаются эффектами — с точечным `eslint-disable` и обоснованием

- `App.tsx:234,265,290` — гейт страницы: это НЕ синхронизация, а навигация с побочными
  действиями (toast, `history.replaceState`, инвалидация кэша).
- `ContractsPage:36`, `InvoicesPage:35` — разбор deep-link из URL при монтировании.
- `CompanyTab:65` — императивная загрузка полной карточки компании (правильный ремонт —
  перевести на `useQuery`; выносится в отдельную задачу, чтобы волна осталась поведенчески пустой).
- `AdminDataTable:170,193,316` — фокус/выбор строк, завязаны на DOM.

## Порядок и DoD

1. A и C — механические, покрыты существующими тестами форм; добавить тест «правки переживают
   рефетч» там, где ref-гард уходит (`useProductForm`, `QuoteSettingsDialog`).
2. B — по одному диалогу, проверяя, что второе открытие пустое.
3. Включить `react-hooks/set-state-in-effect` в `eslint.config.js`, оставив только точечные
   disable из §D **с текстом причины**.
4. **Гейт проверить ломаным входом**: вернуть один `setState` в эффект → линтер красный.
5. Прогон глазами по затронутым экранам (настройки компании, карточка товара, билдер КП,
   диалоги оплаты/отправки) — волна поведенчески пустая, значит на экране НИЧЕГО не должно
   измениться, кроме исчезнувшего мигания.
