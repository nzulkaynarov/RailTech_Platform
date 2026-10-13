# CLAUDE.md — Cabinet (кабинет клиента), `apps/cabinet`

Ты работаешь над **Cabinet** ансамбля RailTech Platform: одно окно клиента — запросы, КП, договоры,
счета, акты, поставки, документы, опубликованный каталог. Один главный пользователь — **клиент**
(контакт компании-контрагента). Сотрудники сюда не входят. **Собственного бэкенда нет** (ADR-0004):
SPA ходит в ERP `/api/portal/v1/*`, всё, что он показывает, сделал ERP; всё, что клиент делает, исполняет ERP.
Тот же SPA открывается как Telegram Mini App бота CRM и как сайт `cabinet.railtech.uz`.

**Статус документа: заготовка (M0-DOC-01).** Кода в `apps/cabinet` ещё нет — появляется на вехе **M2**
(M2-CAB-01…03), после портального API ERP (M2-ERP-01). Всё, что помечено «появится в <ID>», пока не существует.

## 1. Карта документов — читай в этом порядке

| Документ | Что в нём | Когда читать |
|---|---|---|
| `ORCHESTRATOR.md` (корень) | инварианты §3, роль агента Cabinet §4, веха M2 §6, протокол §7 | первым в каждой сессии |
| `docs/PROGRESS.md`, `docs/QUESTIONS.md`, `docs/DECISIONS.md` | состояние, вопросы, решения | в начале сессии |
| `docs/ARCHITECTURE.md` §5 | **состав Cabinet**; §17 — входы клиента (Mini App, веб, приглашение); §8 — ИИ (у Cabinet своего нет) | перед любой реализацией |
| `docs/CONTRACTS.md` §4 | **портальный API — единственный источник данных**; §0 — форматы | перед каждым экраном |
| `packages/contracts/openapi/erp-portal.yaml` | **схема портального API**, из неё генерируются типы (`packages/contracts/generated/erp-portal.d.ts`) | есть (M0-INF-02); перед каждым экраном |
| `docs/adr/0004-cabinet-without-backend.md`, `0005` | без бэкенда; без своего ИИ | перед любым «а давайте тут свой…» |
| `docs/BUSINESS.md` §3.2, §4 | ценность и границы Cabinet, путь клиента | перед продуктовой задачей |
| `legacy/b2b/CLAUDE.md`, `legacy/b2b/frontend/src/` | покупательские страницы и фронтовые конвенции B2B | когда переносишь экран; **только чтение** |

Противоречия: `BUSINESS` > `ARCHITECTURE` > `CONTRACTS` > этот файл > код. Нашёл — в `docs/QUESTIONS.md`, не угадывай.

## 2. Правила (нарушение = PR не принимается)

1. **Только `/api/portal/v1/*`** (CONTRACTS §4). Единственное исключение — публичная форма «Я новый клиент» на странице входа, которая отправляет лид в CRM (`POST /api/v1/leads/web`, появится в M3-CRM-05 / M2-CAB-03). Вызовов internal- или integration-API ERP из Cabinet нет и не будет.
2. **Нет своего бэкенда, базы, серверных функций.** Нужны данные, которых нет в портальном API, — задача агенту ERP через `docs/QUESTIONS.md` / `docs/PROGRESS.md`, не обход и не «пока захардкодим».
3. **В Cabinet нет:** сотрудников, ролей компании-исполнителя, настроек бизнеса, внутреннего слоя каталога, себестоимости, маржи, поставщиков. Клиент видит только опубликованный слой и проекцию сделки — это обеспечивает ERP, но Cabinet не рисует полей, которых в контракте нет.
4. **Своего ИИ нет** (ADR-0005). Вопросы клиента — бот CRM; «Написать менеджеру» → `t.me/<bot>?start=deal_<id>` с контекстом сделки (M2-CAB-03). Позже — веб-виджет того же агента CRM.
5. **Режимы входа:** Mini App — `initData` → `POST /auth/telegram`, без страницы входа, тема Telegram; веб — magic-link по e-mail (`POST /auth/magic-link` → `GET /auth/magic/{token}`), необязательный пароль. Регистрации «с улицы» нет: первый вход — по приглашению.
6. **Телефон — основной экран.** Каждый экран на 390 px без горизонтальной прокрутки; axe — 0 нарушений; DoD — скриншоты в Mini App и в браузере.
7. **Контракт раньше кода:** недостающее поле или эндпоинт — сначала `packages/contracts` (PR агента ERP в той же вехе), потом экран.
8. **Секретов нет.** Токен бота Cabinet не знает — подпись `initData` проверяет ERP. В сборку попадают только `VITE_*`-переменные без секретов.

## 3. Стек

```
React 18 · TypeScript · Vite · Tailwind CSS 4 · shadcn/ui · React Query · i18next (ru / uz / en) ·
openapi-typescript (типы из packages/contracts/openapi/erp-portal.yaml) · Vitest + Testing Library · Playwright (смоук) ·
Telegram Web App SDK (initData, themeParams, start_param, MainButton/BackButton — где уместно)
```

- Версии — те же, что у ERP-фронтенда после копирования из B2B; точные — M2-CAB-01.
- Токены дизайна — из `packages/ui-tokens` (появится в M0-INF-05); в Mini App цвета темы Telegram накладываются на те же семантические токены, не на компоненты.
- Глобальное состояние минимально: сессия (`GET /me`: контакт, компания, `can_act`), язык, тема. Данные — только React Query над портальным API.
- Маршрутизатор и deep-link по `start_param` (например, открыть сделку из кнопки бота) — решение M2-CAB-01; учитывай, что бот CRM шлёт кнопки «Открыть КП» и «Кабинет» (M3-CRM-04).
- Деплой: статика за Caddy на `cabinet.railtech.uz` / `cabinet.localhost` (`infra/caddy`, есть с M0-INF-03; до M2-CAB-01 `cabinet.localhost` — заглушка); своего контейнера с логикой нет.

## 4. Экраны (ARCHITECTURE §5, M2-CAB-02) и откуда они из `legacy/b2b/frontend/src`

| Экран | Портальный API | Источник в B2B |
|---|---|---|
| Запросы, «Новый запрос» (строки свободным текстом + вложения) | `GET/POST /requests` | `pages/MyRequestsPage.tsx`, `pages/RequestDetailPage.tsx` (покупательская часть) |
| КП: список, карточка, принять (код) / отклонить (причина) | `GET /quotes`, `GET /quotes/{id}`, `POST …/accept`, `POST …/reject` | `pages/QuotesPage.tsx`, `components/CRM/BuyerAcceptedPanel.tsx`, `components/CRM/RejectQuoteDialog.tsx` |
| Публичная страница акцепта КП (по ссылке из бота/письма) | страница в `portal` ERP, 202 + PDF (M2-ERP-03) | `backend/crm/views/documents_public.py`, `templates/public/quote_generating.html`; в Cabinet — свой экран по той же ссылке |
| Договоры, подписать | `GET /contracts`, `POST /contracts/{id}/sign` | `pages/ContractsPage.tsx` |
| Счета (платежи — внутри счёта; отдельного `/payments` в контракте нет) | `GET /invoices` | `pages/InvoicesPage.tsx` |
| Акты: принять / вернуть с причиной | `GET /acts`, `POST /acts/{id}/accept`, `POST …/return` | `pages/ActsPage.tsx`, `components/Billing/RejectActDialog.tsx` |
| Поставки по строкам: статус, ожидаемая дата, трек | `GET /deliveries` | `pages/FulfillmentsPage.tsx` (как основа; статусы — проекция ERP, M4-ERP-04) |
| Документы, скачать | `GET /documents`, `GET /documents/{id}/file` | `pages/CompanyFilesPage.tsx` |
| Компания и команда клиента, приглашение коллеги | `GET/PUT /company`, `GET /team`, `POST /team/invite` | `pages/SettingsPage.tsx` (разделы профиль и команда), `components/Settings/` |
| Каталог с ценами и наличием (решение владельца: только здесь) | `GET /catalog`, `GET /catalog/{id}` | `pages/ProductDetail.tsx` как основа карточки; список — новый экран |
| Страница входа (веб): «Войти» / «Я новый клиент» | `POST /auth/magic-link`; форма → лид CRM `web` | новое (M2-CAB-01, M2-CAB-03) |

- Адаптивная таблица КП и любых списков — `components/ResponsiveDataTable.tsx` из B2B (карточки на мобильном, строки доступны с клавиатуры).
- Оболочка — своя, не `AppShell` ERP: без боковой навигации бэк-офиса, нижняя навигация / простое меню под телефон; в Mini App — без шапки входа и без дублирования кнопок Telegram.
- Осторожно с именами: папка B2B `components/Cabinet/` — это разделы Settings Hub (профиль, 2FA, реквизиты, нумерация), а не кабинет клиента. Переносить оттуда только профиль компании и команду; 2FA, нумерация, шаблоны, формулировки — в ERP.
- Корзина B2B (`store/cartStore.ts`) не переносится без решения: «Новый запрос» по контракту — свободные строки и вложения; «нет нужной позиции» → свободная строка (MIGRATION-MAP).

## 5. Конвенции фронтенда (из B2B; остаются)

- **Только shadcn/ui + семантические токены**: `bg-primary`, `text-foreground`, `bg-destructive`, `bg-success`…; никаких `bg-emerald-500`, `text-white`, hex, inline-стилей, кастомного CSS. Размеры текста — только шкала Tailwind (`text-xs` минимум).
- **Весь текст через i18n**: `t()` из `useTranslation()`, ключи одновременно в `ru.json`, `uz.json`, `en.json` (симметрия проверяется скриптом по образцу B2B `scripts/check_i18n_symmetry.py`; `uz` — новый словарь, M2-CAB-01). Язык по умолчанию — из `GET /me` (язык контакта) или `Telegram.WebApp.initDataUnsafe.user.language_code`, переключатель — в профиле.
- **Типы API только сгенерированные** из `erp-portal.yaml` (`make contracts`); ручных типов и «временных» интерфейсов ответа нет. Статусы сравниваются по `code`, показываются по `name`.
- Ошибки API — `{"detail": "<CODE>"}`; код → ключ i18n, показ toast'ом; 401 → повторный вход (в Mini App — повторный `POST /auth/telegram`), 404 — «не найдено», без утечки существования чужих сущностей.
- Правила React Compiler включены; `useDraftState` / `useNow` / `useLatestRef` из B2B вместо самоделок; хелперы и константы — вне файлов компонентов.
- Деньги — строка из API с валютой; форматирование — одной утилитой по локали, не вручную. Даты — ISO из API, показ в Asia/Tashkent.
- Доступность: фокус-состояния, `aria-label` на иконках, контраст темы Telegram проверяется axe так же, как светлая/тёмная веб-тема.
- Проверяй на телефоне: Mini App в тестовом боте (DevTools Telegram Desktop) и браузер на 390 px; виртуальная клавиатура не должна прятать кнопку действия.

**Тесты.** Vitest + Testing Library с настоящим `ru.json`; моки — только на границе HTTP (мок портального API из `erp-portal.yaml`, инструмент — M2-CAB-01), не внутри компонентов. Playwright-смоук обоих входов. Матрица прав клиента: `can_act=false` → кнопки действий скрыты, API всё равно решает.

## 6. Команды

| Команда | Что делает | Появится в |
|---|---|---|
| `make check-cabinet` (из корня) | делегирует в `make -C apps/cabinet check`: eslint + tsc + vitest | M2-CAB-01 |
| `make -C apps/cabinet dev` | Vite dev-сервер против `erp.localhost` или мока портального API | M2-CAB-01 |
| `make -C apps/cabinet build` | прод-сборка статики | M2-CAB-01 |
| `make contracts` (из корня) | регенерация типов из `erp-portal.yaml` | есть (M0-INF-02) |
| `make up` (из корня) | `cabinet.localhost` за Caddy вместе с ERP и CRM | есть (M0-INF-03); до M2-CAB-01 — заглушка Caddy |

Mini App локально: тестовый бот в BotFather указывает на туннель к `cabinet.localhost` (как — runbook M2-CAB-01).

## 7. Чего здесь нет — не ищи и не воссоздавай

- Регистрации, KYC, подписок, тарифов, «продавец/покупатель» — вход только по приглашению.
- Страниц бэк-офиса и администратора: `Dashboard`, `DealsPage`, `DealQuotePage`, `QuoteBuilder`, `Admin*`, `PlatformAdminShell`, `PaymentsPage` как регистр, `CounterpartiesPage`, `CatalogImportPage`, `HSDirectoryPage`, `MyProductsPage`.
- Чата и поддержки (`ChatDrawer`, `SupportButton`, `Message`) — их заменяет бот CRM.
- Уведомлений в приложении как системы (`NotificationCenter` B2B) — сообщает бот и письма ERP; в Cabinet — только статусы на экранах (решение об ином — ADR).
- Zustand-сторов B2B `userStore`/`authStore`/`cartStore`/`currencyStore` в прежнем виде: сессия портала — cookie и `GET /me`, валюта — из API.

## 8. Self-check перед PR

- [ ] Задача по ID из ORCHESTRATOR §6; зависимости (M2-ERP-01 или мок из контракта) закрыты; ветка `m<N>/cabinet-<NN>-<slug>`.
- [ ] `make check-cabinet` зелёный; типы сгенерированы, ручных нет; `grep -r "/api/v1/" src` пусто (кроме формы лида `leads/web`).
- [ ] Ни одного поля, которого нет в `erp-portal.yaml`; недостающее — задача агенту ERP в `docs/QUESTIONS.md`.
- [ ] Весь текст через `t()`, ключи в трёх словарях; только shadcn и семантические токены.
- [ ] Экран на 390 px без горизонтальной прокрутки; axe 0; скриншоты в Mini App **и** в браузере в описании PR.
- [ ] `can_act=false` скрывает действия; 401/404 обработаны без утечек.
- [ ] Секретов и токена бота нет; `.env.example` актуален.
- [ ] Строка в `docs/PROGRESS.md`; открытые вопросы — в `docs/QUESTIONS.md`.

## 9. Открытые точки для M2 (не решать молча)

- Сессия портала — cookie HttpOnly (CONTRACTS §4) при SPA на `cabinet.*` и API на `erp.*`: кросс-доменная cookie (`SameSite=None` + CORS с credentials) или проксирование `/api/portal` через Caddy с домена Cabinet — решение агентов ERP и Infra в M2-ERP-01 / M2-CAB-01, при необходимости ADR.
- Имя бота для «Написать менеджеру» и URL CRM для формы лида — переменные сборки, имена появятся в M2-CAB-03.
