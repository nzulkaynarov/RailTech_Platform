# apps/cabinet — Cabinet (кабинет клиента)

SPA клиента RailTech Platform без собственного бэкенда (ADR-0004): все данные — ERP `/api/portal/v1/*`
(`docs/CONTRACTS.md` §4, схема `packages/contracts/openapi/erp-portal.yaml`). Один и тот же SPA открывается
как сайт `cabinet.railtech.uz` и как Telegram Mini App клиентского бота CRM. Состав — `docs/ARCHITECTURE.md` §5,
входы — §17, правила агента — `CLAUDE.md` рядом.

Стек: React 18 · TypeScript · Vite 7 · Tailwind CSS 4 · shadcn/ui (примитивы из `apps/erp/frontend`) ·
React Query · react-router 7 · i18next (ru / uz — латиница / en) · openapi-typescript · MSW · Vitest + Testing Library + axe.

## Команды

```
make -C apps/cabinet install        # npm ci
make -C apps/cabinet dev            # http://localhost:5175 с моком портального API (VITE_PORTAL_MOCK=1)
make -C apps/cabinet dev-stand      # без мока: /api/portal → стенд (VITE_PORTAL_PROXY_TARGET, по умолчанию erp.localhost)
make -C apps/cabinet check          # eslint, tsc, i18n, токены, типы API, vitest + axe  (= make check-cabinet из корня)
make -C apps/cabinet build          # статика в dist/
make -C apps/cabinet gen-api-types  # src/api/portal.d.ts из erp-portal.yaml; src/api/crm-form.d.ts из OpenAPI CRM
```

## Устройство

| Путь | Что |
|---|---|
| `src/api/portal.d.ts` | типы портального API — **только генерация** (`make gen-api-types`; `check` сверяет с контрактом) |
| `src/api/crm.ts`, `crm-form.d.ts` | публичная форма CRM «Запрос» (`GET /api/v1/leads/web/token`, `POST /api/v1/leads/web`; база `VITE_CRM_URL`, без cookie); типы — генерация из `apps/crm/docs/api/openapi.json` (`scripts/gen-crm-form-types.mjs`, только пути формы) |
| `src/api/portal.ts`, `errors.ts` | клиент: `fetch`, `credentials: 'include'`, база `/api/portal/v1`, `Idempotency-Key` на POST; `{"detail": CODE}` → `PortalApiError` → ключ `apiErrors.<CODE>` |
| `src/mocks/` | MSW: `fixtures.ts` (все данные мока одним модулем, типизированы схемами контракта), `handlers.ts` (все эндпоинты), `crmForm.ts` (форма CRM «Запрос»), `browser.ts` (dev), `server.ts` (тесты) |
| `src/session/` | сессия `GET /me` (`useMe`, `useCanAct`, `<CanAct>`, `useLogout`), режим `miniapp` / `web` |
| `src/telegram/` | Telegram Web App SDK: `initData`, тема поверх переменных shadcn, `start_param` → маршрут |
| `src/app/` | маршруты, guards, React Query, разделы навигации |
| `src/components/shell/` | оболочка: нижняя навигация (телефон), боковая (десктоп), «Назад» Telegram |
| `src/pages/` | экраны по домену: `requests`, `quotes`, `billing` (договоры, счета, акты), `deliveries` (поставки, документы), `catalog`, `company` (компания, команда), `deal`; вход, magic-link, «Я новый клиент», профиль |
| `src/api/queries.ts` | React Query-хуки экранов: ключи по эндпоинту, после действия — инвалидация связанных списков |
| `src/components/` | общие части экранов: `ResponsiveList`, `StatusBadge`, `QueryStates`, `ActionDialog`, `ReasonDialog`, `DocumentButton`, `Details`, `TelegramLinkButton` / `ManagerButton` («Написать менеджеру» → `t.me/<бот>?start=deal_<id>`, в Mini App — `openTelegramLink`); `ui/` — shadcn из ERP |
| `src/lib/` | `format.ts` (деньги, даты Asia/Tashkent, размеры), `status.ts`, `invoice.ts`, `quotes.ts`, `download.ts` (202 + Retry-After), `catalog.ts`, `company.ts`, `leadForm.ts` (проверка формы «Я новый клиент», тело для CRM, повтор с новым токеном) |
| `src/i18n/locales/{ru,uz,en}.json` | словари; симметрия — `scripts/check_i18n_symmetry.py` |
| `src/styles/tokens.generated.css` | копия `packages/ui-tokens/dist/shadcn.css` (`make tokens`), подключается в `src/index.css` |

Маршруты: `/login`, `/login/sent`, `/new-client` (только веб), `/auth/magic/:token`; за сессией —
`/requests[/new|/:id]`, `/quotes[/:id]`, `/contracts`, `/invoices`, `/acts`, `/deliveries`, `/documents`,
`/catalog[/:id]`, `/company`, `/team`, `/deals/:id`, `/profile`.

## Проверка в браузере (мок)

1. `make -C apps/cabinet dev` → http://localhost:5175 — страница входа (DevTools → режим устройства 390 px).
2. «Войти»: любой e-mail → «Письмо отправлено» → «Открыть ссылку из письма (мок)» (`/auth/magic/demo`) → «Запросы».
3. Ссылки мока: `/auth/magic/viewer` — контакт без права действовать (`can_act=false`: нет «Новый запрос», плашка
   «Только просмотр», язык контакта uz); `/auth/magic/expired` — «Ссылка не действует» (410).
4. «Профиль» — язык ru / uz / en, «Выйти». Сессия мока живёт в `sessionStorage` вкладки, **данные мока — в памяти
   вкладки**: перезагрузка страницы возвращает фикстуры (принятое КП снова «ждёт решения»).
5. `/auth/magic/empty` — компания без единого объекта: пустые состояния всех разделов.

Сценарии разделов на моке («сегодня» фикстур — 2026-10-14; от системной даты зависят просрочка и срок КП):

| Экран | Что проверить |
|---|---|
| Запросы | список из 5; «Новый запрос» → суть + строки (количество `2,5` принимается, `много` — ошибка) → карточка нового запроса |
| КП | «2 КП ждут решения»; KP-2026-0042 → «Принять» → код `0000` — «Код подтверждения неверен» (409), код **`2468`** — «КП принято», «Договор D-2026-0042 готов»; KP-2026-0057 (этапы услуги) → «Отклонить» без причины — подсказка, с причиной — «Отклонено»; KP-2026-0033 — «срок истёк» без кнопок |
| Договоры | «Подписать» D-2026-0048 → «Подписан вами»; D-2026-0029 → «Подписан сторонами» |
| Счета | S-2026-0124 — «Просрочен», «просрочен на 7 дней» (статус ERP `issued`, просрочка из срока); «К оплате» в UZS и USD отдельно |
| Акты | A-2026-0090 — «Принять» или «Вернуть» с причиной; A-2026-0084 — уже возвращён с причиной |
| Поставки | три сделки, «Доставлено N из M», ожидаемая дата, трек |
| Документы | фильтр «Счета»; «Скачать» договор D-2026-0048 — «Документ готовится…» (202), через секунду файл; «Акт сверки» — 202 всегда → «Документ ещё готовится» |
| Каталог | 24 позиции, 2 страницы; поиск «ремень»; категория «Услуги»; «Цена по запросу»; карточка → «Запросить» → новый запрос с позицией |
| Компания, команда | «Изменить» → ИНН `12` — ошибка 422; «Пригласить коллегу» — каналы e-mail/Telegram (для Telegram нужен телефон) |
| Сделка | `/deals/35` — всё по сделке; `/deals/999` — «не найдено» |
| «Написать менеджеру» | `/deals/35` в шапке, `/quotes/301` в шапке, иконка в строках договоров / счетов / актов, кнопка у каждой сделки в «Поставках» → `https://t.me/<бот>?start=deal_<id>` в новой вкладке; без `VITE_BOT_USERNAME` кнопок нет |
| «Я новый клиент» (`/new-client`, без входа) | пустая отправка — «Укажите, как к вам обращаться»; без телефона и e-mail — подсказка на обоих полях; без галочки согласия — «Без согласия…», запрос не уходит; успех — «Спасибо! Запрос отправлен» + «Написать в Telegram» (`start=web`). Сценарии мока по тексту «Что нужно»: `#expired` — первая отправка получает `form_token_expired`, форма тихо берёт новый токен и через ~1 с отправляет снова (успех); `#fast` — `form_too_fast`; `#limit` — 429; телефон `12345` — «Номер не распознан» |

## Проверка как Mini App

**Без Telegram (эмуляция).** SDK `telegram-web-app.js` читает параметры запуска из `#tgWebAppData=…`. В консоли
открытой вкладки dev-сервера:

```js
const data = new URLSearchParams({ user: JSON.stringify({ id: 42, language_code: 'ru' }), auth_date: '1760400000', start_param: 'deal_42', hash: 'demo' });
const theme = JSON.stringify({ bg_color: '#17212b', text_color: '#f5f5f5', hint_color: '#708499', button_color: '#5288c1', button_text_color: '#ffffff', secondary_bg_color: '#232e3c' });
location.href = '/#tgWebAppData=' + encodeURIComponent(data) + '&tgWebAppVersion=8.0&tgWebAppPlatform=tdesktop&tgWebAppThemeParams=' + encodeURIComponent(theme);
```

Ожидаемо: страницы входа и шапки сайта нет, тёмная тема Telegram, открыта «Сделка №42» (`start_param=deal_42`).
«Написать менеджеру» в Mini App вызывает `Telegram.WebApp.openTelegramLink` (в эмуляции вне Telegram SDK ничего не открывает — это ожидаемо).
Мок принимает любой `init_data`; содержащий `bad` → 401 («Не удалось войти»), `viewer` → контакт без права действовать.
SDK запоминает параметры в `sessionStorage` — для возврата в веб-режим откройте новую вкладку.

**В Telegram (тестовый бот).** Mini App требует HTTPS:

1. Туннель к dev-серверу: `cloudflared tunnel --url http://localhost:5175` или `ngrok http 5175`
   (домены `*.trycloudflare.com`, `*.ngrok-free.app` разрешены в `vite.config.ts`). К стенду —
   `cloudflared tunnel --url http://localhost:80 --http-host-header cabinet.localhost`.
2. В @BotFather у **тестового** бота: `/newapp` (или Bot Settings → Menu Button) → URL туннеля.
3. Откройте Mini App из бота (Telegram Desktop: Settings → Advanced → Experimental → Enable webview inspecting
   — DevTools). С моком вход проходит сразу; против стенда — после M2-ERP-01 (подпись `initData` проверяет ERP).
   Deep-link: `https://t.me/<бот>/<app>?startapp=deal_42`.

## Ансамбль

`make up` из корня: сервис `cabinet-web` (этот Dockerfile: Vite → nginx, `/health`), Caddy
`http://cabinet.localhost` — `/api/portal/*` → `erp-backend:8000` (до M2-ERP-01 — 404), остальное → `cabinet-web`.
Имя бота для сборки — `TELEGRAM_BOT_USERNAME` из корневого `.env`. Форма «Я новый клиент» ходит в CRM напрямую:
адрес — build-arg `VITE_CRM_URL` = `CABINET_CRM_URL` корневого `.env` (по умолчанию `http://crm.localhost:${HTTP_PORT}`),
CRM разрешает CORS на `/api/v1/leads/web*` только origin из `CABINET_ORIGIN` (`crm-api` в `infra/compose/base.yml`;
по умолчанию `http://cabinet.localhost`, `http://cabinet.localhost:${HTTP_PORT}`, `https://${CABINET_DOMAIN}`).
Прод: `CABINET_CRM_URL=https://crm.railtech.uz`, `CABINET_ORIGIN=https://cabinet.railtech.uz`.
`make dev-stand` без `VITE_CRM_URL` ведёт форму через прокси Vite на CRM стенда (`VITE_CRM_PROXY_TARGET`, по умолчанию `http://crm.localhost`).
