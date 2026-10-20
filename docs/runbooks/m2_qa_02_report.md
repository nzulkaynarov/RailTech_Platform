# Отчёт M2-QA-02: прогон гейта M2 на стенде против настоящего ERP (FIX-51)

**Дата:** 2026-10-21 · **Стенд:** `make up` на `main @ 47df5185` (код = `20ee10c7`): `http://cabinet.localhost:8088`, `erp.localhost`, `crm.localhost`
· **Браузер:** Chromium 149 (Playwright 1.61.0), 1440×900 и 390×844, `ru-RU`, Asia/Tashkent
· **Сценарий:** [`apps/cabinet/e2e/gate-m2.spec.ts`](../../apps/cabinet/e2e/gate-m2.spec.ts) (+ `playwright.config.ts`, `e2e/helpers/`)
· **Скриншоты:** [`docs/screens/fix-51/`](../screens/fix-51/) (имена — `экран-ширина.png`) · **axe:** [`axe-summary.json`](../screens/fix-51/axe-summary.json)

Прошлый прогон ([M2-QA-01](m2_qa_01_report.md), 2026-10-16) шёл на Vite с MSW-моком, без телефона и без артефактов (аудит C-6, G-7).
Этот — против настоящих ERP и CRM стенда, магия входа — письмом из логов ERP, скриншоты и axe приложены.

## 1. Итог

| Что | Результат |
|---|---|
| Путь клиента BUSINESS §4, шаги 4–10, без звонка менеджеру | **пройден целиком** (29 шагов сценария зелёные, см. §3) |
| Вход по приглашению и по magic-link, использованная ссылка | пройдено; токены — только в адресную строку Playwright |
| axe в браузере | **0 нарушений serious/critical, 0 нарушений любой степени** на 49 экранах × 2 ширины (98 прогонов; в каждом прошло 24–43 правила) |
| Горизонтальная прокрутка на 390 px | 0 px на всех экранах Cabinet |
| ru / uz / en на одном экране | пройдено (профиль и «Запросы»); дефект D-4 (формат даты uz) |
| Права (`can_act=false`) и изоляция компаний | пройдено, **утечек нет** (§6) |
| Экраны волны 3 на стенде (CRM) | пройдены 5 экранов; 2 состояния не воспроизведены на стенде (§5) |
| Mini App на телефоне | **не проверялось агентом** — только владелец (§9) |
| Дефекты | **P0: 0 · P1: 1 · P2: 11** (§7) |

Гейт M2 с точки зрения клиентского пути **проходим**; блокирующих продуктовых дефектов Cabinet нет. P1 — переход CRM → ERP из шапки (SSO) на чистом браузере (D-1): это вход сотрудника бэк-офиса, не клиента.

## 2. Как запускался прогон

```
cd apps/cabinet
E2E_BASE_URL=http://cabinet.localhost:8088 \
E2E_STAND_ROOT=<корень репозитория со стендом и .env> \      # оттуда `docker compose logs` читает письма (почта стенда — консоль)
E2E_CRM_ADMIN_EMAIL=… E2E_CRM_ADMIN_PASSWORD=… \            # администратор CRM FIX-51 с доступом к ERP; пароль — только из окружения
npm run test:e2e                                              # E2E_RESUME=1 — продолжить с первого непройденного шага
```

- `@playwright/test` 1.61.0 — в `devDependencies`, lockfile обновлён; `playwright.config.ts` ограничен `e2e/gate-m2.spec.ts`.
- Из CI и проверок исключён: vitest (`exclude: e2e/**`), `tsc -b` проверяет e2e отдельным `tsconfig.e2e.json` (только типы, без запуска), eslint проходит по e2e как по обычному коду. `make check-cabinet` и `scripts/ci_local.sh gitleaks cabinet` зелёные.
- Данные — новые на каждом прогоне (метка `r…` в e-mail и тексте), фейковые, с префиксом FIX-51: компания «FIX-51 Тест ООО», клиент `fix51-<метка>@example.com`, коллега `fix51-<метка>-viewer@example.com`.
- Шаги бэк-офиса (КП, согласование, договор, счёт, аванс, отгрузка, акт) — подготовка данных, не прогон M1: сотрудник FIX-51 («FIX-51 Админ», CRM-админ с доступом к ERP, суперпользователь ERP) входит в ERP из CRM по SSO и вызывает те же методы API, что и ERP SPA. Вторая учётная запись (`FIX-51 Менеджер`, роль ERP `backoffice`) заведена в CRM «Пользователи» с доступом к ERP, но в сценарии не использовалась (решение по рекомендации: права менеджера проверяет FIX-50).
- Токены ссылок входа и коды принятия КП читаются из логов `erp-backend`/`erp-worker` в переменную процесса и уходят только в адресную строку и поле кода; не печатаются и не сохраняются. На скриншотах адресной строки нет (снят контент страницы).

## 3. Путь клиента (BUSINESS §4) — что пройдено

| Шаг BUSINESS §4 | Что сделано в сценарии | Результат | Скриншоты |
|---|---|---|---|
| Вход (первый) | страница входа; «Я новый клиент»: пустая отправка (ошибка), без согласия (ошибка), с согласием → «Спасибо» | пройдено | [login-1440](../screens/fix-51/login-1440.png) · [390](../screens/fix-51/login-390.png); [new-client-validation-1440](../screens/fix-51/new-client-validation-1440.png) · [390](../screens/fix-51/new-client-validation-390.png); [new-client-form-1440](../screens/fix-51/new-client-form-1440.png) · [390](../screens/fix-51/new-client-form-390.png); [new-client-sent-1440](../screens/fix-51/new-client-sent-1440.png) · [390](../screens/fix-51/new-client-sent-390.png) |
| 3→4 Передача | CRM: лид с сайта появился (согласие есть) → «Забрать» → «Передать в бэк-офис» → компания и заявка в ERP, приглашение в Cabinet | пройдено | [crm-lead-from-cabinet-form-1440](../screens/fix-51/crm-lead-from-cabinet-form-1440.png) · [390](../screens/fix-51/crm-lead-from-cabinet-form-390.png); [crm-clients-after-handoff-1440](../screens/fix-51/crm-clients-after-handoff-1440.png) · [390](../screens/fix-51/crm-clients-after-handoff-390.png) |
| Вход по приглашению | ссылка из письма ERP (`/auth/magic#token=…`) → «Запросы» | пройдено | [requests-first-login-1440](../screens/fix-51/requests-first-login-1440.png) · [390](../screens/fix-51/requests-first-login-390.png) |
| «Требует вашего решения» | КП, затем договор, затем акт — блок на «Запросах» со ссылкой на действие | пройдено | [requests-action-required-1440](../screens/fix-51/requests-action-required-1440.png) · [390](../screens/fix-51/requests-action-required-390.png); [requests-action-required-contract-1440](../screens/fix-51/requests-action-required-contract-1440.png) · [390](../screens/fix-51/requests-action-required-contract-390.png); [requests-action-required-act-1440](../screens/fix-51/requests-action-required-act-1440.png) · [390](../screens/fix-51/requests-action-required-act-390.png) |
| 5–6 КП: принять по коду | список КП, карточка, «Получить код» (письмо), неверный код → ошибка в диалоге, верный → «КП принято», договор готов | пройдено | [quotes-list-1440](../screens/fix-51/quotes-list-1440.png) · [390](../screens/fix-51/quotes-list-390.png); [quote-detail-1440](../screens/fix-51/quote-detail-1440.png) · [390](../screens/fix-51/quote-detail-390.png); [quote-accept-dialog-request-code-1440](../screens/fix-51/quote-accept-dialog-request-code-1440.png) · [390](../screens/fix-51/quote-accept-dialog-request-code-390.png); [quote-accept-dialog-wrong-code-1440](../screens/fix-51/quote-accept-dialog-wrong-code-1440.png) · [390](../screens/fix-51/quote-accept-dialog-wrong-code-390.png); [quote-accepted-1440](../screens/fix-51/quote-accepted-1440.png) · [390](../screens/fix-51/quote-accepted-390.png) |
| 6 КП: отклонить | второй запрос из каталога → КП v1 → «Отклонить» без причины (нельзя), с причиной → «КП отклонено» | пройдено | [quote-reject-dialog-1440](../screens/fix-51/quote-reject-dialog-1440.png) · [390](../screens/fix-51/quote-reject-dialog-390.png); [quote-rejected-1440](../screens/fix-51/quote-rejected-1440.png) · [390](../screens/fix-51/quote-rejected-390.png) |
| 7 Договор | «Подписать» (диалог) → «подписан вами» → бэк-офис подписал → «подписан сторонами» | пройдено | [contracts-awaiting-signature-1440](../screens/fix-51/contracts-awaiting-signature-1440.png) · [390](../screens/fix-51/contracts-awaiting-signature-390.png); [contract-sign-dialog-1440](../screens/fix-51/contract-sign-dialog-1440.png) · [390](../screens/fix-51/contract-sign-dialog-390.png); [contracts-signed-by-client-1440](../screens/fix-51/contracts-signed-by-client-1440.png) · [390](../screens/fix-51/contracts-signed-by-client-390.png); [contracts-signed-both-1440](../screens/fix-51/contracts-signed-both-1440.png) · [390](../screens/fix-51/contracts-signed-both-390.png) |
| 8 Счёт | счёт с частичной оплатой: сумма, оплачено, остаток, срок | пройдено | [invoices-1440](../screens/fix-51/invoices-1440.png) · [390](../screens/fix-51/invoices-390.png) |
| 8 Поставка по строкам | отгрузка (трек), доставлено 3 из 3; две строки приняты, по одной — «Есть замечания» (без причины нельзя) | пройдено | [deliveries-shipped-1440](../screens/fix-51/deliveries-shipped-1440.png) · [390](../screens/fix-51/deliveries-shipped-390.png); [deliveries-delivered-1440](../screens/fix-51/deliveries-delivered-1440.png) · [390](../screens/fix-51/deliveries-delivered-390.png); [delivery-dispute-dialog-1440](../screens/fix-51/delivery-dispute-dialog-1440.png) · [390](../screens/fix-51/delivery-dispute-dialog-390.png); [deliveries-accepted-and-disputed-1440](../screens/fix-51/deliveries-accepted-and-disputed-1440.png) · [390](../screens/fix-51/deliveries-accepted-and-disputed-390.png) |
| 9 Акт | принять со сканом PDF (кнопка «Скан» после приёмки); на втором акте — «Вернуть» с причиной (без причины нельзя) | пройдено | [acts-awaiting-1440](../screens/fix-51/acts-awaiting-1440.png) · [390](../screens/fix-51/acts-awaiting-390.png); [act-accept-dialog-with-scan-1440](../screens/fix-51/act-accept-dialog-with-scan-1440.png) · [390](../screens/fix-51/act-accept-dialog-with-scan-390.png); [acts-accepted-with-scan-1440](../screens/fix-51/acts-accepted-with-scan-1440.png) · [390](../screens/fix-51/acts-accepted-with-scan-390.png); [act-return-dialog-1440](../screens/fix-51/act-return-dialog-1440.png) · [390](../screens/fix-51/act-return-dialog-390.png); [acts-returned-1440](../screens/fix-51/acts-returned-1440.png) · [390](../screens/fix-51/acts-returned-390.png) |
| Сделка целиком | все объекты сделки на одном экране | пройдено | [deal-full-path-1440](../screens/fix-51/deal-full-path-1440.png) · [390](../screens/fix-51/deal-full-path-390.png) |
| 9–10 Документы и поиск | вид «Счета», поиск «КП-», скачивание PDF (`%PDF-`, не пустой) | пройдено; D-6 (накладная) | [documents-1440](../screens/fix-51/documents-1440.png) · [390](../screens/fix-51/documents-390.png); [documents-filter-invoices-1440](../screens/fix-51/documents-filter-invoices-1440.png) · [390](../screens/fix-51/documents-filter-invoices-390.png); [documents-search-1440](../screens/fix-51/documents-search-1440.png) · [390](../screens/fix-51/documents-search-390.png) |
| 10 Новый запрос | каталог → «В запрос» → «Оформить запрос» → запрос Z-… отправлен, в ERP появилась заявка | пройдено; D-5 | [catalog-1440](../screens/fix-51/catalog-1440.png) · [390](../screens/fix-51/catalog-390.png); [request-new-from-catalog-1440](../screens/fix-51/request-new-from-catalog-1440.png) · [390](../screens/fix-51/request-new-from-catalog-390.png); [request-detail-new-1440](../screens/fix-51/request-detail-new-1440.png) · [390](../screens/fix-51/request-detail-new-390.png) |
| Компания и команда | карточка, «Изменить», «Пригласить коллегу» (только просмотр) → письмо ушло, коллега вошёл | пройдено | [company-1440](../screens/fix-51/company-1440.png) · [390](../screens/fix-51/company-390.png); [company-edit-1440](../screens/fix-51/company-edit-1440.png) · [390](../screens/fix-51/company-edit-390.png); [team-invite-dialog-1440](../screens/fix-51/team-invite-dialog-1440.png) · [390](../screens/fix-51/team-invite-dialog-390.png); [team-invited-1440](../screens/fix-51/team-invited-1440.png) · [390](../screens/fix-51/team-invited-390.png) |
| Повторный вход | «Выйти» → форма «Войти» → «Письмо отправлено» → ссылка → «Запросы»; та же ссылка во второй раз → «Ссылка не действует» | пройдено | [login-sent-1440](../screens/fix-51/login-sent-1440.png) · [390](../screens/fix-51/login-sent-390.png); [magic-link-used-1440](../screens/fix-51/magic-link-used-1440.png) · [390](../screens/fix-51/magic-link-used-390.png) |
| Форма «Я новый клиент» → лид в CRM | см. первую строку: лид #… появился в «Входящих» CRM с согласием, источник «Сайт» | пройдено | [crm-lead-after-handoff-1440](../screens/fix-51/crm-lead-after-handoff-1440.png) · [390](../screens/fix-51/crm-lead-after-handoff-390.png) |
| «Написать менеджеру» | **на стенде кнопки нет**: не задано имя бота (`TELEGRAM_BOT_USERNAME`, `VITE_BOT_USERNAME` пуст — по коду кнопки без имени бота скрыты). Проверено на Vite dev-сервере с `VITE_BOT_USERNAME`, проксирующем на тот же ERP: ссылки `https://t.me/<бот>?start=deal_<id>` есть на шапке сделки, у строк договора, счёта, акта и у сделки в «Поставках» (на списке КП — нет, на карточке КП — по коду есть) | **частично** (ограничение стенда) | [deal-manager-button-1440](../screens/fix-51/deal-manager-button-1440.png) · [390](../screens/fix-51/deal-manager-button-390.png) |

Данные последнего прогона: метка `r3ylnm`, лид CRM #14, сделки ERP D-22 (путь A: КП → поставка → акт со сканом) и D-23 (путь B: отказ → v2 → акт возвращён), КП-2026-00014/…, счета INV-2026-00013/…14.

## 4. axe и вёрстка

Правила axe-core из `node_modules` (инъекция `addScriptTag`), полный набор правил, **в браузере**, на каждом экране, в том числе с открытыми диалогами, на 1440 и 390 px.
Нарушения `serious`/`critical` проваливают шаг (`expect.soft`), остальные пишутся в `axe-summary.json`.

| Метрика | Значение |
|---|---|
| Экранов Cabinet | 49 (по 2 ширины = 98 прогонов) |
| Нарушений serious/critical | **0** |
| Нарушений moderate/minor | **0** |
| Горизонтальная прокрутка (`scrollWidth − innerWidth`) | 0 px на всех 98 |
| Прошло правил на экран | от 24 до 43 (доказательство, что проверка реально отработала) |
| Экраны CRM (волна 3) | только скриншоты (axe для CRM вне гейта M2) |

Тёмная тема и тема Telegram — в браузере не проверялись (см. §9, только на телефоне).

## 5. Экраны волны 3 на стенде (CRM, ранее — подставной API)

| Задача | Экран | Результат | Скриншоты |
|---|---|---|---|
| FIX-31 (передача без потерь) | лид и клиент после «Передать в бэк-офис»: «В бэк-офисе: Компания #…», заявка; вкладки «Сделки» и «Документы» подтянуты из ERP | пройдено. **Не воспроизведено на стенде:** состояние «Передаётся» (передача идёт ≈1 с) и «ИНН уже есть у другого клиента» (нужен второй лид с согласием, а форма Cabinet ограничена по частоте) | [crm-lead-after-handoff-1440](../screens/fix-51/crm-lead-after-handoff-1440.png) · [390](../screens/fix-51/crm-lead-after-handoff-390.png); [crm-client-card-1440](../screens/fix-51/crm-client-card-1440.png) · [390](../screens/fix-51/crm-client-card-390.png); [crm-client-deals-1440](../screens/fix-51/crm-client-deals-1440.png) · [390](../screens/fix-51/crm-client-deals-390.png); [crm-client-documents-1440](../screens/fix-51/crm-client-documents-1440.png) · [390](../screens/fix-51/crm-client-documents-390.png) |
| FIX-30/33 | «Сделки»: стадии пришли событиями ERP («Выиграна», «Закрытие»/«Исполнение», суммы КП) | пройдено; D-9, D-10 | [crm-deals-1440](../screens/fix-51/crm-deals-1440.png) · [390](../screens/fix-51/crm-deals-390.png) |
| FIX-33 (вебхуки) | «Внешние сервисы»: «События из ERP» и «Передача клиентов в ERP» — «В норме», детальная страница с проверками раз в минуту | пройдено | [crm-external-services-1440](../screens/fix-51/crm-external-services-1440.png) · [390](../screens/fix-51/crm-external-services-390.png); [crm-external-services-erp-events-1440](../screens/fix-51/crm-external-services-erp-events-1440.png) · [390](../screens/fix-51/crm-external-services-erp-events-390.png) |
| FIX-35 (секрет вебхуков) | «Подключения → ERP»: «Настроен», секреты только как «····xxxx», поля пустые, длинных токенов на экране нет (проверено сценарием) | пройдено; ротацию секрета не запускали (меняет общий стенд) | [crm-integrations-erp-1440](../screens/fix-51/crm-integrations-erp-1440.png) · [390](../screens/fix-51/crm-integrations-erp-390.png) |
| FIX-34 | «Настройки → Компания»: адрес кабинета (пуст — кнопки «Кабинет» в сообщениях бота нет); «Тексты бота» с группой «События бэк-офиса (ERP)» | пройдено; сообщения бота по событиям на стенде не уходят (бот не настроен) | [crm-settings-company-1440](../screens/fix-51/crm-settings-company-1440.png) · [390](../screens/fix-51/crm-settings-company-390.png); [crm-settings-bot-texts-1440](../screens/fix-51/crm-settings-bot-texts-1440.png) · [390](../screens/fix-51/crm-settings-bot-texts-390.png) |
| FIX-34b | «Передать в бэк-офис»: кнопка на карточке лида до передачи и после («Открыть новую сделку»); состояния «локально/недоступно/ошибка» требуют переключения режима жизненного цикла (меняет общий стенд) — не воспроизводились | частично | [crm-lead-from-cabinet-form-1440](../screens/fix-51/crm-lead-from-cabinet-form-1440.png) · [390](../screens/fix-51/crm-lead-from-cabinet-form-390.png); [crm-lead-after-handoff-1440](../screens/fix-51/crm-lead-after-handoff-1440.png) · [390](../screens/fix-51/crm-lead-after-handoff-390.png) |
| FIX-34 (согласие) | лид без согласия (создан вручную) — передача отклонена: «Лид не давал согласие…» | пройдено как защита; см. D-8 | [defect-crm-handoff-no-consent-1440](../screens/fix-51/defect-crm-handoff-no-consent-1440.png) · [390](../screens/fix-51/defect-crm-handoff-no-consent-390.png) |

Ограничения стенда, влияющие на CRM-экраны: ключи ИИ-провайдеров и токен Telegram-бота не заданы (шапка CRM «Клиенты не получают ответов», «Внешние сервисы»: Telegram Bot API и Anthropic — «Сбой»); функции ИИ и бот не проверялись.

## 6. Права и изоляция (проверки утечек)

Сценарий I1–I2, на живых данных:

- Коллега, приглашённый без права «Может подтверждать»: «Новый запрос» скрыт, плашка «Только просмотр», в профиле «Только просмотр»; прямой запрос `POST /quotes/{id}/reject` → 403/409 (API решает сам) — [requests-viewer-only-1440](../screens/fix-51/requests-viewer-only-1440.png) · [390](../screens/fix-51/requests-viewer-only-390.png).
- Чужие объекты: `GET /api/portal/v1/quotes/{id чужой компании}` → **404**.
- Ответы `/quotes`, `/contracts`, `/invoices`, `/acts`, `/deliveries`, `/documents`, `/requests`, `/catalog`, `/company`, `/team`, `/me` — 200 и **без** ключей и слов `margin`, `markup`, `landed`, `cost`, `supplier`, `purchase`, «закупк», «себестоим», «поставщик» (регулярка по сырому ответу).
- Страница вне сессии (`/requests` без cookie) → `/login`.

Утечек данных, входа без прав, потери денег — **не найдено** (P0 нет).

## 7. Дефекты

Подготовка данных и поиск шли штатными путями; дефекты не чинились. P0 — 0, P1 — 1, P2 — 11.

### P1

**D-1. Переход «В бэк-офис (ERP)» из CRM в чистом браузере почти всегда заканчивается формой входа ERP (SSO, M3-CRM-06/FIX-11).**
Шаги: войти в CRM сотрудником с «Доступом к ERP» → «В бэк-офис (ERP)» в шапке (браузер без сессии ERP). Ожидание: открывается ERP под этим сотрудником. Факт: открывается «Sign in»; в 12 из 14 попыток (1 из 8 и 1 из 6). Причина по коду: страница `/sso/exchange` ERP SPA (`apps/erp/frontend/src/components/Auth/SsoExchangePage.tsx`) запускает обмен токена, а `App.tsx` параллельно вызывает `initAuth()` → `GET /accounts/users/me/` → 401 → refresh 401 → `failRefresh()` в `api/client.ts` делает `window.location.href = '/'`, потому что `/sso/exchange` нет в `PUBLIC_AUTH_PATHS`; обмен обрывается раньше `POST /auth/sso/exchange/`. В FIX-11 переход проверен только по API (PROGRESS). Скриншот: [defect-sso-erp-login-1440](../screens/fix-51/defect-sso-erp-login-1440.png) · [390](../screens/fix-51/defect-sso-erp-login-390.png).
Обход в сценарии: обмен делается тем же запросом без открытия страницы `/sso/exchange`. Дополнительно: частые обмены упираются в 429 (троттлинг обмена) — при проверке руками подождать минуту.

### P2

**D-2. `POST /api/v1/crm/fulfillments/update-status/` → 500 `Fulfillment.DoesNotExist`, если вызвать сразу после подписи договора обеими сторонами** (отгрузку создаёт Celery-задача `auto_invoice_on_closed_won` через ≈1 с). Ожидание: 404/409 с кодом (или создание отгрузки по требованию). Факт: 500, traceback в `crm/services/fulfillment.py:95` (`select_for_update().get(deal_id=…)`). Воспроизведение: подписать договор (`sign-manager`) и сразу вызвать `update-status` с `SHIPPED`.

**D-3. «Срок» в карточке КП всегда пуст.** ERP отдаёт `promised_date: null` (`portal/projections.py:201`), хотя в КП у строк и КП заданы 14 дней (`lead_time_days`, `delivery_lead_time_days`). Ожидание: срок/дата по строке. Факт: «—» в столбце «Срок» (на телефоне поле скрыто). Рядом «Действует до —» (на стенде у своей компании не задан `default_validity_days` — это настройка, не дефект). Скриншот: [quote-detail-1440](../screens/fix-51/quote-detail-1440.png) · [390](../screens/fix-51/quote-detail-390.png).

**D-4. Даты в узбекском интерфейсе показываются как «2026 M10 21».** Ожидание: «21.10.2026» или «21-oktabr, 2026». Скриншот: [requests-uz-1440](../screens/fix-51/requests-uz-1440.png) · [390](../screens/fix-51/requests-uz-390.png) (столбец «Yaratilgan»).

**D-5. Каталог на стенде — одна позиция («Железный шпала», «срок 0 дней» при «В наличии»).** В ERP ≥7 товаров, остальные (статус 1) в портал не попали — возможно, ожидаемо (не опубликованы), но «срок 0 дней» у позиции «В наличии» читается странно, а клиентский путь «запрос из каталога» на стенде упирается в одну позицию. Скриншот: [catalog-1440](../screens/fix-51/catalog-1440.png) · [390](../screens/fix-51/catalog-390.png). Нужно решение: что именно публикуется и как показывать срок 0.

**D-6. Накладная в «Документах»: размер «0 Б», при первом скачивании 202 (рендер), после рендера номер меняется (DN-9 → DN-2026-0000x).** В логе воркера при рендере: «Could not resolve recipient language for delivery_note». Ожидание: накладная сразу с итоговым номером и размером или «готовится». Факт: клиент видит нулевой файл и «чужой» номер. Скриншот: [documents-1440](../screens/fix-51/documents-1440.png) · [390](../screens/fix-51/documents-390.png).

**D-7. Мобильный вид «Поставки»: перед «Заявка: …» в шапке сделки висит «·» на отдельной строке** (разделитель после ссылки при переносе). Скриншот: [deliveries-delivered-390](../screens/fix-51/deliveries-delivered-390.png). Там же в «Документах» плейсхолдер поиска на 390 px обрезан («…названию или сдел»): [documents-390](../screens/fix-51/documents-390.png).

**D-8. Лид без согласия нельзя передать в бэк-офис, и у менеджера нет способа его получить.** Лид, заведённый вручную («Звонок», кнопка «Новый лид»), несёт «Согласие: нет»; «Передать в бэк-офис» → 422 «Лид не давал согласие… Пусть лид подтвердит согласие в боте» (поведение FIX-34 верное). Но звонок/письмо/рекомендация — именно такие каналы, а бота у клиента может не быть; повторная заявка с формы по известному контакту согласие карточки не трогает (по коду, `_repeat_request`). Ожидание: отметка согласия менеджером (с аудитом) или ссылка клиенту на форму. Скриншот: [defect-crm-handoff-no-consent-1440](../screens/fix-51/defect-crm-handoff-no-consent-1440.png) · [390](../screens/fix-51/defect-crm-handoff-no-consent-390.png). Вопрос — владельцу/архитектору (CRM, ADR-0022).

**D-9. CRM, мобильный: сумма сделки ломается посреди числа («28 000 00 0 UZS»)** в таблице «Сделки» карточки клиента. Скриншот: [crm-client-deals-1440](../screens/fix-51/crm-client-deals-1440.png) · [390](../screens/fix-51/crm-client-deals-390.png).

**D-10. Карточка лида показывает «В бэк-офисе: Заявка #23», хотя из лида передана заявка #22:** #23 — позднейшая заявка клиента, пришедшая из Cabinet (не из лида). Ожидание: заявка, созданная передачей. Скриншот: [crm-lead-after-handoff-1440](../screens/fix-51/crm-lead-after-handoff-1440.png) · [390](../screens/fix-51/crm-lead-after-handoff-390.png) (метки «Компания #52», «Заявка #23»; в ERP сделка передачи — D-22).

**D-11. Суперпользователь ERP согласует за всех: сотрудник FIX-51 («Админ») одним сеансом выполнил 6 шагов согласующих разных людей и шаг руководителя** (цепочка «Проверка ВЭД» + «Руководитель»). Ожидание: суперпользователь не подменяет согласующих или подмена явно помечена в аудите. Это зона FIX-50 (M1); внесено как наблюдение, в сценарии использовано для подготовки данных.

**D-12. Журнал ERP пишет начало токена ссылки входа: `Magic link token invalid or expired (892670…)`** (`magic_link` INFO). Для FIX-15 («токена ссылки нет в журнале») важно, что это 6 знаков префикса, а не сам токен, — но префикс одноразового секрета в журнале лучше заменить на хэш с пометкой. Источник: `docker compose logs erp-backend | grep magic_link`.

### Наблюдения (не дефекты)

- Форма «Я новый клиент»: отправка быстрее `min_fill_seconds` после загрузки токена показывает «Форма отправлена слишком быстро — проверьте поля и отправьте ещё раз» (в Cabinet тихий повтор только для `form_token_expired`/`invalid`); после ~5 заявок с одного IP за час — 429 «Слишком много запросов с вашего адреса».
- «Запросы»: у заявки, созданной клиентом из кабинета, до КП написано «Ещё без сделки», хотя в ERP сделка (черновик) уже есть.
- Счёт в «Требует вашего решения» появляется только просроченным — по коду так задумано.
- Письма стенда — консоль; каждый шаг с кодом/ссылкой зависит от Celery (письмо уходит за 1–3 с). Порядок строк разных контейнеров в логах смешивается — сценарий читает каждый контейнер отдельно (см. инцидент ниже).

## 8. Что не удалось и почему

- Вход через Telegram Mini App — только владелец, на телефоне (cookie `SameSite=None` требует TLS): §9.
- Тёмная тема Telegram, `WebApp.openTelegramLink`, скачивание в webview — только на телефоне.
- «Написать менеджеру» на стенде — нет имени бота; проверено на Vite dev-сервере с тем же ERP (§3).
- ИИ (разбор запроса, бот CRM, ответы по базе знаний): ключей провайдеров на стенде нет — функции ИИ не проверялись; сообщения бота о КП/счетах/приглашениях — тоже (токен бота пуст), клиент получает письма из консоли.
- CRM-состояния FIX-31 («передаётся», «ИНН у другого клиента») и FIX-34b (локальный режим, сбой) — не воспроизведены (§5).
- Роль «Менеджер» ERP, цепочка согласования ролями, публичная ссылка на КП — зона FIX-50.

## 9. Проверка владельцем на телефоне (Mini App)

Что агент **не** проверил: вход из Telegram Mini App. Стенд — `http://*.localhost` без TLS, а cookie сессии портала в Mini App
— `SameSite=None; Secure` (Cabinet открыт во фрейме Telegram), по `http` браузер её не сохранит (`docs/runbooks/stand.md`,
«Telegram Mini App на стенде»). Нужны: тестовый бот, туннель с HTTPS, телефон с приложением Telegram. `.env` правит владелец.

Шаги (по `stand.md`):

1. Туннель на Caddy стенда с подменой `Host` на `cabinet.localhost`: `cloudflared tunnel --url http://localhost:8088 --http-host-header cabinet.localhost`
   (порт — `HTTP_PORT` из `.env`; у ngrok — `ngrok http 8088 --host-header=cabinet.localhost`). Получится `https://<имя>.trycloudflare.com`.
2. В `.env`: `PORTAL_COOKIE_SAMESITE=None`, `CABINET_URL=https://<имя>.trycloudflare.com`, `TELEGRAM_BOT_TOKEN` и `TELEGRAM_BOT_USERNAME`
   тестового бота; затем `make up` (перезапуск `erp-backend`, пересборка `cabinet-web` с именем бота).
3. BotFather → тестовый бот → Menu Button / Mini App → адрес туннеля.
4. Клиент для проверки: контакт портала с e-mail и **привязанным Telegram** (приглашение — из CRM «Передать в бэк-офис» или «Команда → Пригласить
   коллегу» с каналом Telegram). Сидовый `client@uty.example` контактом портала не является.
5. Открыть бота на телефоне, нажать кнопку: в ответе `POST /api/portal/v1/auth/telegram` — `Set-Cookie: portal_session=…; HttpOnly; Secure;
   SameSite=None; Path=/api/portal`, открывается «Запросы». Веб Telegram и браузеры с блокировкой сторонних cookie (Safari, Chrome Incognito) cookie
   фрейма могут не принять — проверять именно на телефоне.
6. После проверки вернуть `PORTAL_COOKIE_SAMESITE=Lax`, `CABINET_URL=http://cabinet.localhost`, `make up`.

Что смотреть на телефоне (то, что браузер на 390 px не показывает):

| Что | Ожидание |
|---|---|
| Вход | без страницы входа, сразу «Запросы» компании; чужой Telegram-аккаунт — «Не удалось войти» + «Открыть бота» |
| Тема | цвета берутся из темы Telegram (светлая и тёмная); контраст кнопок `button_color` читаем, статусные бейджи различимы в тёмной теме |
| Кнопка «Назад» | на вложенных экранах (КП, сделка) системная «Назад» Telegram, а не своя; нет двойных кнопок |
| «Написать менеджеру» | на шапке сделки и КП, у строки договора / счёта / акта, у сделки в «Поставках»; нажатие открывает чат с ботом (`openTelegramLink`) с `?start=deal_<id>`; бот отвечает приветствием — разбор `/start` в боте — M3-CRM-04 |
| Скачивание | КП, договор, счёт, акт скачиваются или открываются в webview (iOS и Android); накладная «готовится» → файл (см. дефект D-6); при проблеме — `WebApp.downloadFile` |
| Код акцепта | «Получить код» приходит в Telegram (в стенде на e-mail: бот не настроен), поле кода не закрыто клавиатурой, «Принять КП» видна |
| Скан акта | выбор файла из галереи/камеры/«Файлы» в диалоге приёмки акта; файл до 10 МБ уходит |
| Клавиатура | на формах («Новый запрос», «Причина», «Пригласить коллегу») кнопка действия не прячется за виртуальной клавиатурой |
| Deep-link | кнопка бота с контекстом: `start_param=deal_<id>` → `/deals/<id>`, `quote_<id>` → `/quotes/<id>` |
| Язык | интерфейс открывается на языке Telegram (ru / uz / en); переключатель в «Профиле» |

Если вход не проходит: в Network проверить `Set-Cookie` ответа `/auth/telegram` (нет `Secure`/`SameSite=None` → `PORTAL_COOKIE_SAMESITE` не применён),
проверить, что `initData` подписан токеном **того же** бота, что в `.env` (`TELEGRAM_BOT_TOKEN`), и что `auth_date` не старше 5 минут (ERP проверяет подпись и свежесть, `portal/services/telegram_auth.py`; на телефоне должно быть верное время).

## 10. Данные и следы прогона на стенде

Только с префиксом FIX-51: лиды CRM #5 (вручную, без согласия), #6, #10, #14 и ещё лиды из отладочных прогонов; клиенты «FIX-51 Тест ООО» (по одному на прогон) с контактами `fix51-*@example.com`; сделки, КП, договоры, счета, акты в ERP; пользователи CRM «FIX-51 Админ» и «FIX-51 Менеджер» (доступ к ERP выдан). Чужие данные (FIX-50 и демо) не менялись, кроме эпизода ниже.

### Инцидент в ходе прогона (учтён, повторения исключены)

В отладочных запусках разбор писем в `e2e/helpers/mail.ts` склеивал соседние письма консоли (compose перемешивает строки двух контейнеров); поэтому в нескольких запусках сценарий вошёл по ссылкам входа контактов FIX-50 (одноразовые ссылки могли «сгореть»), запросил код принятия одного КП FIX-50 (`POST /quotes/19/request-code`, 202) и сделал одну попытку принятия **неверным кодом `000000`** (409, КП не принято). Больше под чужим контактом ничего не менялось (только чтение). Лиду доложено сразу, в ходе прогона. Исправлено: письма читаются по контейнерам, режутся по заголовку, берутся только однозначные (одна ссылка/один код на письмо, точное совпадение `To:`), а после входа сценарий сверяет e-mail контакта и останавливается при чужом. Скриншоты тех запусков удалены, финальные сняты заново под клиентом FIX-51.

## 11. Как повторить

`E2E_RESUME=1` продолжает прогон, `E2E_BOT_USERNAME` — проверка кнопок «Написать менеджеру», `E2E_SCREENS_DIR` — другой каталог для скриншотов. Состояние прогона лежит в `apps/cabinet/node_modules/.cache/gate-m2/`.
