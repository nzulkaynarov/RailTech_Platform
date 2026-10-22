# CLAUDE.md — Cabinet (кабинет клиента), `apps/cabinet`

Ты работаешь над **Cabinet** ансамбля RailTech Platform: одно окно клиента — запросы, КП, договоры,
счета, акты, поставки, документы, опубликованный каталог. Один главный пользователь — **клиент**
(контакт компании-контрагента). Сотрудники сюда не входят. **Собственного бэкенда нет** (ADR-0004):
SPA ходит в ERP `/api/portal/v1/*`, всё, что он показывает, сделал ERP; всё, что клиент делает, исполняет ERP.
Тот же SPA открывается как Telegram Mini App бота CRM и как сайт `cabinet.railtech.uz`.

**Статус (2026-10-20): M2 — «готово к гейту», гейт владельца после прогона FIX-51.** Есть маршруты, вход (Mini App /
magic-link), тема Telegram, i18n ru/uz/en, все экраны §4 с действиями клиента, кнопка бота с контекстом сделки, форма
запроса → лид CRM `web`. Cabinet работает с настоящим портальным API ERP по контракту 0.3.0 (FIX-24, FIX-25); мок MSW
остался для dev и тестов. Обходы контракта, если остались, — в QUESTIONS (вложения «Нового запроса» — Q-14).
Устройство и запуск — `README.md` рядом.

## 1. Карта документов — читай в этом порядке

| Документ | Что в нём | Когда читать |
|---|---|---|
| `ORCHESTRATOR.md` (корень) | инварианты §3, роль агента Cabinet §4, веха M2 §6, протокол §7 | первым в каждой сессии |
| `docs/PROGRESS.md`, `docs/QUESTIONS.md`, `docs/DECISIONS.md` | состояние, вопросы, решения | в начале сессии |
| `docs/ARCHITECTURE.md` §5 | **состав Cabinet**; §17 — входы клиента (Mini App, веб, приглашение); §8 — ИИ (у Cabinet своего нет) | перед любой реализацией |
| `docs/CONTRACTS.md` §4 | **портальный API — единственный источник данных**; §0 — форматы | перед каждым экраном |
| `packages/contracts/openapi/erp-portal.yaml` | **схема портального API**; типы Cabinet — `src/api/portal.d.ts` (`make gen-api-types`, сверка в `make check`) | перед каждым экраном |
| `docs/adr/0004-cabinet-without-backend.md`, `0005` | без бэкенда; без своего ИИ | перед любым «а давайте тут свой…» |
| `docs/BUSINESS.md` §3.2, §4 | ценность и границы Cabinet, путь клиента | перед продуктовой задачей |
| тег `b2b-final` (`git show b2b-final:legacy/b2b/frontend/src/<путь>`) | история: покупательские страницы и фронтовые конвенции B2B, откуда экраны Cabinet. Папки `legacy/b2b` в репозитории нет (удалена в M2-INF-01) — рабочим источником история не служит | когда нужно понять происхождение экрана; **только чтение** |

Противоречия: `BUSINESS` > `ARCHITECTURE` > `CONTRACTS` > этот файл > код. Нашёл — в `docs/QUESTIONS.md`, не угадывай.

## 2. Правила (нарушение = PR не принимается)

1. **Только `/api/portal/v1/*`** (CONTRACTS §4). Единственное исключение — публичная форма «Я новый клиент» на странице входа: `GET /api/v1/leads/web/token` и `POST /api/v1/leads/web` CRM (M3-CRM-05, M2-CAB-03; `src/api/crm.ts`, база — `VITE_CRM_URL`, без cookie, CORS — `CABINET_ORIGIN` в CRM). Других вызовов CRM нет; вызовов internal- или integration-API ERP из Cabinet нет и не будет.
2. **Нет своего бэкенда, базы, серверных функций.** Нужны данные, которых нет в портальном API, — задача агенту ERP через `docs/QUESTIONS.md` и описание PR (лид переносит в `docs/PROGRESS.md`), не обход и не «пока захардкодим».
3. **В Cabinet нет:** сотрудников, ролей компании-исполнителя, настроек бизнеса, внутреннего слоя каталога, себестоимости, маржи, поставщиков. Клиент видит только опубликованный слой и проекцию сделки — это обеспечивает ERP, но Cabinet не рисует полей, которых в контракте нет.
4. **Своего ИИ нет** (ADR-0005). Вопросы клиента — бот CRM; «Написать менеджеру» → `t.me/<bot>?start=deal_<id>` с контекстом сделки (`ManagerButton`, `app/links.ts`; в Mini App — `WebApp.openTelegramLink`; без имени бота кнопки нет). Позже — веб-виджет того же агента CRM.
5. **Режимы входа:** Mini App — `initData` → `POST /auth/telegram`, без страницы входа, тема Telegram; веб — magic-link по e-mail (`POST /auth/magic-link` → ссылка `/auth/magic#token=…` → `POST /auth/magic {token}`; токен во фрагменте, не в пути), необязательный пароль. Регистрации «с улицы» нет: первый вход — по приглашению.
6. **Телефон — основной экран.** Каждый экран на 390 px без горизонтальной прокрутки; axe — 0 нарушений; DoD — скриншоты в Mini App и в браузере.
7. **Контракт раньше кода:** недостающее поле или эндпоинт — сначала `packages/contracts` (PR агента ERP в той же вехе), потом экран.
8. **Секретов нет.** Токен бота Cabinet не знает — подпись `initData` проверяет ERP. В сборку попадают только `VITE_*`-переменные без секретов.

## 3. Стек

```
React 18 · TypeScript · Vite · Tailwind CSS 4 · shadcn/ui · React Query · i18next (ru / uz / en) ·
openapi-typescript (типы из packages/contracts/openapi/erp-portal.yaml; форма лида — из OpenAPI CRM) · Vitest + Testing Library · Playwright (смоук) ·
Telegram Web App SDK (initData, themeParams, start_param, MainButton/BackButton — где уместно)
```

- Версии — как в `apps/erp/frontend` (`package.json`): React 18.3, Vite 7, Tailwind 4.3, React Query 5, i18next 25, TypeScript 5.6, Vitest 4; плюс react-router-dom 7, MSW 2, vitest-axe. shadcn-примитивы `src/components/ui/` скопированы из ERP без правок.
- Токены дизайна — копия `packages/ui-tokens/dist/shadcn.css` в `src/styles/tokens.generated.css` (`make tokens` из корня пишет её сама; `make check` сверяет). В Mini App цвета `themeParams` Telegram ложатся на те же переменные (`src/telegram/theme.ts`), не на компоненты.
- Глобальное состояние минимально: сессия (`GET /me`: контакт, компания, `can_act`), язык, тема. Данные — только React Query над портальным API.
- Маршрутизатор — react-router 7 (`src/app/routes.tsx`). Deep-link Mini App: `start_param=deal_<id>` → `/deals/<id>`, `quote_<id>` → `/quotes/<id>` (`src/telegram/start-param.ts`), разрешается до создания маршрутизатора; на вложенных экранах — системная «Назад» Telegram.
- Деплой: сервис `cabinet-web` (Vite → nginx, `/health`) за Caddy на `cabinet.localhost` / `cabinet.railtech.uz`; `/api/portal/*` Caddy ведёт с того же домена на ERP (cookie same-origin, CORS не нужен).

## 4. Экраны (ARCHITECTURE §5, M2-CAB-02) и их происхождение из B2B (тег `b2b-final`, `legacy/b2b/frontend/src`; история, не рабочий источник)

| Экран | Портальный API | Происхождение в B2B (`b2b-final`) | В Cabinet (M2-CAB-02) |
|---|---|---|---|
| Запросы, «Новый запрос» (суть + строки свободным текстом с количеством/единицей; вложений нет до загрузки файлов в контракте — Q-14) | `GET/POST /requests` | `pages/MyRequestsPage.tsx`, `pages/RequestDetailPage.tsx` (покупательская часть) | `src/pages/requests.tsx`: список, карточка из списка (строк в контракте нет — Q-16), форма с проверкой количества |
| КП: список, карточка, принять (код по запросу) / отклонить (причина) | `GET /quotes`, `GET /quotes/{id}`, `POST …/request-code`, `POST …/accept`, `POST …/reject` | `pages/QuotesPage.tsx`, `components/CRM/BuyerAcceptedPanel.tsx`, `components/CRM/RejectQuoteDialog.tsx` | `src/pages/quotes.tsx`: строки (позиции/разделы/заметки/этапы), итог, срок, обещанные даты; «срок истёк» по `valid_until`; после акцепта — панель «договор формируется / готов» |
| Публичная страница акцепта КП (по ссылке из бота/письма) | страница в `portal` ERP, 202 + PDF (M2-ERP-03) | `backend/crm/views/documents_public.py`, `templates/public/quote_generating.html`; в Cabinet — свой экран по той же ссылке | deep-link `quote_<id>` ведёт в карточку КП |
| Договоры, подписать | `GET /contracts`, `POST /contracts/{id}/sign` | `pages/ContractsPage.tsx` | `src/pages/billing.tsx`: подписи обеих сторон, «Подписать» с подтверждением |
| Счета (платежи — внутри счёта; отдельного `/payments` в контракте нет) | `GET /invoices` | `pages/InvoicesPage.tsx` | `src/pages/billing.tsx`: сумма, оплачено, остаток, срок, просрочка из `due_date`, «к оплате» по валютам |
| Акты: принять (со сканом или без) / вернуть с причиной | `GET /acts`, `POST /uploads`, `POST /acts/{id}/accept {upload_id?}`, `POST …/return` | `pages/ActsPage.tsx`, `components/Billing/RejectActDialog.tsx` | `src/pages/billing.tsx` |
| Поставки по строкам: статус, ожидаемая дата, трек; принять / «Есть замечания» у доставленной | `GET /deliveries`, `POST /deliveries/{id}/accept`, `POST …/dispute {reason}` | `pages/FulfillmentsPage.tsx` (как основа; статусы — проекция ERP, M4-ERP-04) | `src/pages/deliveries.tsx`: группы по сделке, «доставлено N из M» |
| Документы, скачать | `GET /documents`, `GET /documents/{id}/file` | `pages/CompanyFilesPage.tsx` | `src/pages/deliveries.tsx` (`DocumentsPage`): фильтр по виду в `?kind=`, 202 + `Retry-After` — «документ готовится» (`lib/download.ts`) |
| Компания и команда клиента, приглашение коллеги | `GET/PUT /company`, `GET /team`, `POST /team/invite` | `pages/SettingsPage.tsx` (разделы профиль и команда), `components/Settings/` | `src/pages/company.tsx`: в `PUT` — только изменённые поля; приглашение с каналами e-mail/Telegram |
| Каталог с ценами и наличием (решение владельца: только здесь) | `GET /catalog`, `GET /catalog/{id}` | `pages/ProductDetail.tsx` как основа карточки; список — новый экран | `src/pages/catalog.tsx`: поиск/категории/страница в URL; категории — обход Q-15; «Запросить» → новый запрос с позицией |
| Сделка (deep-link бота `deal_<id>`) | списки выше по `deal.id` | — | `src/pages/deal.tsx` (своего `GET /deals/{id}` нет); клиенту сделка — `deal.number` и `deal.title`, внутренний id только в адресе; чтение `deal_id` снято (охраняет `no-legacy-deal-id.test.ts`) |
| Страница входа (веб): «Войти» / «Я новый клиент» | `POST /auth/magic-link`; форма → CRM `GET /api/v1/leads/web/token`, `POST /api/v1/leads/web` | новое (M2-CAB-01, M2-CAB-03) | `src/pages/auth/NewClientPage.tsx`: имя, компания, телефон / e-mail (хотя бы одно), «что нужно», язык интерфейса, согласие на обработку ПДн (обязательно, Q-12), скрытое honeypot-поле `website`; `form_token_expired`/`invalid` — тихий повтор с новым токеном (после его `min_fill_seconds`); успех — «Спасибо» + «Написать в Telegram» (`start=web`); без `VITE_CRM_URL` в сборке — только Telegram |
| «Написать менеджеру» (M2-CAB-03) | — (ссылка на бота) | новое | `components/TelegramLinkButton.tsx` (`ManagerButton`): шапка сделки и КП, строка договора / счёта / акта (иконка с `aria-label` «…о счёте S-…»), шапка сделки в «Поставках» |

- Общие части экранов: `components/ResponsiveList.tsx` (по образцу B2B `ResponsiveDataTable`: таблица от `lg`, карточки ниже, одна раскладка по media-запросу, строка — ссылка), `StatusBadge` (`lib/status.ts`: код → `status.<сущность>.<код>` и тон токена), `QueryStates` (скелетоны, ошибка `detail` → `apiErrors.*` + «Повторить»), `EmptyState`, `ActionDialog` / `ReasonDialog` (ошибка ERP остаётся в диалоге), `DocumentButton`, `Details`. Форматирование — только `lib/format.ts` (`formatMoney`, `formatDate`, `formatDateTime`, `formatQuantity`, `formatFileSize`, суммы в копейках `BigInt`). Данные — хуки `src/api/queries.ts`.
- Оболочка — своя, не `AppShell` ERP: без боковой навигации бэк-офиса, нижняя навигация / простое меню под телефон; в Mini App — без шапки входа и без дублирования кнопок Telegram.
- Осторожно с именами: папка B2B `components/Cabinet/` — это разделы Settings Hub (профиль, 2FA, реквизиты, нумерация), а не кабинет клиента. Переносить оттуда только профиль компании и команду; 2FA, нумерация, шаблоны, формулировки — в ERP.
- Корзина B2B (`store/cartStore.ts`) не переносится без решения: «Новый запрос» по контракту — свободные строки и вложения; «нет нужной позиции» → свободная строка (MIGRATION-MAP).

## 5. Конвенции фронтенда (из B2B; остаются)

- **Только shadcn/ui + семантические токены**: `bg-primary`, `text-foreground`, `bg-destructive`, `bg-success`…; никаких `bg-emerald-500`, `text-white`, hex, inline-стилей, кастомного CSS. Размеры текста — только шкала Tailwind (`text-xs` минимум).
- **Весь текст через i18n**: `t()` из `useTranslation()`, ключи одновременно в `ru.json`, `uz.json`, `en.json` (симметрия проверяется скриптом по образцу B2B `scripts/check_i18n_symmetry.py`; `uz` — новый словарь, M2-CAB-01). Язык по умолчанию — из `GET /me` (язык контакта) или `Telegram.WebApp.initDataUnsafe.user.language_code`, переключатель — в профиле.
- **Типы API только сгенерированные** из `erp-portal.yaml` (`make -C apps/cabinet gen-api-types` → `src/api/portal.d.ts`); форма лида — `src/api/crm-form.d.ts` из `apps/crm/docs/api/openapi.json` (только пути `/api/v1/leads/web*` и их схемы, `scripts/gen-crm-form-types.mjs`); ручных типов и «временных» интерфейсов ответа нет. Статусы сравниваются по `code`, показываются по `name`.
- Ошибки API — `{"detail": "<CODE>"}`; код → ключ i18n, показ toast'ом; 401 → повторный вход (в Mini App — повторный `POST /auth/telegram`), 404 — «не найдено», без утечки существования чужих сущностей. Форма лида — формат CRM `{"code", "message", "details": {"reason", "field"}}` → `newClient.errors.<reason>`.
- Правила React Compiler включены; `useDraftState` / `useNow` / `useLatestRef` из B2B вместо самоделок; хелперы и константы — вне файлов компонентов.
- Деньги — строка из API с валютой; форматирование — одной утилитой по локали, не вручную. Даты — ISO из API, показ в Asia/Tashkent.
- Доступность: фокус-состояния, `aria-label` на иконках, контраст темы Telegram проверяется axe так же, как светлая/тёмная веб-тема.
- Проверяй на телефоне: Mini App в тестовом боте (DevTools Telegram Desktop) и браузер на 390 px; виртуальная клавиатура не должна прятать кнопку действия.

**Тесты.** Vitest + Testing Library с настоящим `ru.json`; моки — только на границе HTTP: MSW (`src/mocks/handlers.ts` + `fixtures.ts`, те же обработчики в dev и в `msw/node`), не внутри компонентов. `renderApp(path)` (`src/test/render.tsx`) поднимает приложение целиком на memory-router; `signedIn(role)` / `asMiniApp()` задают сессию и режим. axe (`vitest-axe`) на каждом новом экране. Матрица прав клиента: `can_act=false` → кнопки действий скрыты (`<CanAct>`), API всё равно решает. Playwright-смоук обоих входов — M2-QA-01.

## 6. Команды

| Команда | Что делает |
|---|---|
| `make check-cabinet` (из корня) | `make -C apps/cabinet check`: eslint, tsc, i18n ru/uz/en, сверка токенов, сверка типов портала, vitest + axe |
| `make -C apps/cabinet install` | `npm ci` |
| `make -C apps/cabinet dev` | Vite на :5175 с MSW-моком портального API (`VITE_PORTAL_MOCK=1`) |
| `make -C apps/cabinet dev-stand` | Vite на :5175 без мока, `/api/portal` → `erp.localhost` |
| `make -C apps/cabinet build` | прод-сборка статики |
| `make -C apps/cabinet gen-api-types` | `src/api/portal.d.ts` из `erp-portal.yaml` и `src/api/crm-form.d.ts` из OpenAPI CRM (после `make -C apps/crm openapi`) |
| `make up` (из корня) | `cabinet.localhost` за Caddy (`cabinet-web`) вместе с ERP и CRM |

Mini App локально: эмуляция через `#tgWebAppData=…` или тестовый бот в BotFather с туннелем — `README.md`, раздел «Проверка как Mini App».

## 7. Чего здесь нет — не ищи и не воссоздавай

- Регистрации, KYC, подписок, тарифов, «продавец/покупатель» — вход только по приглашению.
- Страниц бэк-офиса и администратора: `Dashboard`, `DealsPage`, `DealQuotePage`, `QuoteBuilder`, `Admin*`, `PlatformAdminShell`, `PaymentsPage` как регистр, `CounterpartiesPage`, `CatalogImportPage`, `HSDirectoryPage`, `MyProductsPage`.
- Чата и поддержки (`ChatDrawer`, `SupportButton`, `Message`) — их заменяет бот CRM.
- Уведомлений в приложении как системы (`NotificationCenter` B2B) — сообщает бот и письма ERP; в Cabinet — только статусы на экранах (решение об ином — ADR).
- Zustand-сторов B2B `userStore`/`authStore`/`cartStore`/`currencyStore` в прежнем виде: сессия портала — cookie и `GET /me`, валюта — из API.

## 8. Self-check перед PR

- [ ] Задача по ID из ORCHESTRATOR §6; зависимости (M2-ERP-01 или мок из контракта) закрыты; ветка `m<N>/cabinet-<NN>-<slug>`.
- [ ] `make check-cabinet` зелёный; типы сгенерированы, ручных нет; `grep -r "/api/v1/" src` пусто (кроме формы лида `leads/web`).
- [ ] Ни одного поля, которого нет в `erp-portal.yaml` (форма лида — в OpenAPI CRM); недостающее — задача агенту ERP в `docs/QUESTIONS.md`.
- [ ] Весь текст через `t()`, ключи в трёх словарях; только shadcn и семантические токены.
- [ ] Экран на 390 px без горизонтальной прокрутки; axe 0; скриншоты в Mini App **и** в браузере в описании PR.
- [ ] `can_act=false` скрывает действия; 401/404 обработаны без утечек.
- [ ] Секретов и токена бота нет; `.env.example` актуален.
- [ ] Статус и хвосты — в описании PR (`docs/PROGRESS.md` ведёт лид, ORCHESTRATOR §4.1); открытые вопросы — в `docs/QUESTIONS.md`.

## 9. Открытые точки для M2 (не решать молча)

- Сессия портала — **решено (M2-CAB-01, по рекомендации, DECISIONS):** `/api/portal/*` проксируется Caddy с домена Cabinet на ERP, cookie same-origin (`SameSite=Lax` по контракту), CORS не нужен. ERP в M2-ERP-01 должен принимать Host `cabinet.*` (`ALLOWED_HOSTS`) и не требовать CSRF-токен Django для портальной сессии (или выдать его способом, доступным SPA).
- Коды ошибок `detail` портала — перечень `ErrorCode` контракта (Q-17; текущая версия портала — 0.3.0); у каждого кода есть текст `apiErrors.*` на ru/uz/en, при входе 403/429 — `auth.errors.*` (`loginErrorKey`). Новый код в контракте → ключ в трёх словарях в том же PR.
- Недостающее в контракте после M2-CAB-02 (агенту ERP, обходы — в QUESTIONS): загрузка файлов для вложений запроса (Q-14), id и справочник категорий каталога (Q-15), строки запроса и номер сделки для клиента (Q-16). Снять обходы сразу после правки контракта.
- Тёмная тема Mini App: статусные токены переопределены в `src/index.css` (`.dark`) до тёмных токенов в `packages/ui-tokens`; контраст `button_color` самого Telegram проверяется на M2-QA-01.
- Скачивание в Mini App: файл сохраняется через `<a download>` (blob); поведение в webview Telegram на iOS/Android проверить на M2-QA-01 (при проблеме — `WebApp.downloadFile`, Bot API 8.0, но ему нужна ссылка без cookie).
- Имя бота — `VITE_BOT_USERNAME` (в ансамбле `TELEGRAM_BOT_USERNAME`). URL CRM для формы лида — `VITE_CRM_URL` (в ансамбле `CABINET_CRM_URL`, по умолчанию `http://crm.localhost:${HTTP_PORT}`); CRM пускает origin из `CABINET_ORIGIN` (по умолчанию `http://cabinet.localhost`, вариант с `HTTP_PORT` и `https://${CABINET_DOMAIN}`) — **решено M2-CAB-03**.
- Бот CRM пока не разбирает параметр `/start` (`deal_<id>`, `web`) — отвечает приветствием. Контекст сделки в диалоге (лента, сервисный режим «где мой счёт») — M3-CRM-04 / M3-CRM-07 (`deal_<id>` — `erp_deal_id`, сопоставление — `deals.erp_deal_id` из M3-CRM-03).

## Правило тестов: роль ищется внутри `within(…)`

Поиск по роли (`getByRole`, `findByRole`) по всему документу в jsdom занимает ~1 с, а на раннере CI даёт таймауты. В тестах сначала берём контейнер (`list`, `dialog`, `group`, `table`), потом ищем внутри него через `within(контейнер)`; `screen.getByRole` по всему документу — только для самого контейнера, `h1` и единственных кнопок страницы.
