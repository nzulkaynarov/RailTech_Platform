# Session Handoff — 2026-07-12/13 — полное закрытие долгового бэклога + eyes-on wedge-цепочки

**База:** main @ merge PR #307 (2026-07-13). Рабочее дерево чистое, открытых PR НЕТ.
Кросс-машинный handoff: память `~/.claude` этой машины НЕ переезжает — этот документ = источник истины.

## TL;DR

За две сессии закрыт ВЕСЬ долговой бэклог, закрываемый кодом: **7 PR смержены (#301–#307)**.
Wedge-цепочка заявка→КП→контракт **валидирована глазами end-to-end** в реальном браузере (deal #25:
создание → routing → claim → билдер → approval → send → buyer approve → CONTRACT_SIGNED + контракт
CT-2026-00001, QR на боевом КП, конфиденциальность соблюдена, 0 pageerror).
Остаток — только owner-решения и deferred-треки (см. «Что осталось»).

## Что смержено (все в main, прод деплоится автоматически)

| PR | Суть |
|----|------|
| **#301** | Adversarial-ревью внешнего AI-вклада (#287–#300, вливался без CI) → 7 фиксов: HIGH 2FA-disable UI-ловушка (`userStore` не грузил `is_2fa_enabled` из /me), replay-защита 2FA (одноразовый login-ticket jti + used-code кэш в Redis DB0), step-up пароль на enable/disable 2FA, doc-profile override при `use_company_defaults` (регрессия #287), CompanyTab OWNER→`settings.edit` (ADR-0005 U2), валидация `preferences` JSONField, ключ `auth.invalidResponse`. + autouse-фикстура очистки default-кэша в conftest (Redis DB0 общий с throttle/lockout → локальные прогоны были негерметичны). 8-я находка (2FA backup-коды / SECRET_KEY-rotation) — задокументированное решение автора, отложена как фича. |
| **#302** | Гигиена: удалены `nginx/` (мёртв; реальный конфиг `frontend/nginx.conf`) и `uv.lock` (чужероден, проект на pip-compile); `HANDOFF.md` → `Docs/old/handoffs/`. CLAUDE.md touch-up: миграционные головы, 2FA/сессии, Settings Hub, U3-деприкация ЗАКРЫТА (#255). |
| **#303** | e2e: `frontend/e2e/2fa-and-settings.spec.ts` — регрессионная сеть на 2FA-логин-брейкер (self-contained: включает 2FA через API + вычисленный TOTP, проверяет появление формы кода и полный вход, выключает). Фикс пароля в `review-fixes.spec.ts` (`Test1234!`→seed `Demo1234!`, env-override `E2E_SEED_PASSWORD`). |
| **#306** | 🚨 **CRITICAL: 2FA-логин был ПОЛНОСТЬЮ сломан на бою с 07-10** — после пароля форма 6-значного кода не появлялась НИКОГДА. Корень: `App.tsx` гейтил всё приложение на `isLoading` стора → `login()` поднимал isLoading → App размонтировал LoginPage, стирая `twoFactorRequired`/`tempToken`. Фикс: флаг `initializing` (только cold-load session check). Recovery-PR, т.к. исходный фикс осиротел из-за merge-timing (см. «Уроки»). |
| **#304** | QR-код на КП-CTA «Принять онлайн» (F-09, Ф2): `public_quote_qr()` — SVG data-URI (WeasyPrint не ходит в сеть), табличная вёрстка, деградация до текст-ссылки. `qrcode` уже был в локе. |
| **#305** | MANUAL_MODE-полнота для подписи АКТА: `sign_act` не писал ActivityLog → добавлен `[MANUAL_MODE]`-лог; ActsPage без баннера → добавлен `ManualModeBanner kind=esign`. Остальная инфра (record_payment/подписка/контракты + баннеры на 4 экранах) УЖЕ была. |
| **#307** | **E1: локализуемый таймлайн (structured events, GitHub/Stripe-паттерн)** — «История» показывала покупателю сырые ключи (`quote.approval_approve`…) и RU-хардкод на EN-UI. `ActivityLog` + `event_code`/`event_params` (crm/0058), 30+ продьюсеров, все 4 отдающие поверхности (`TimelineEntrySerializer`, `ActivityLogSerializer`, AdminActivityView, дашборд), ~40 кодов ru+en, `lib/activityText.ts` с renderability-guard (шаблон с `{{placeholder}}` не интерполируется пустыми params), **backfill crm/0059** (сырые ключи копились на проде с approval-chain; детерминированные RU-титулы локализуются ретроактивно). **E2: капы ввода КП** — билдер принимал qty=1 500 000; теперь settings-капы `QUOTE_ITEM_MAX_QUANTITY`=1e6 / `QUOTE_ITEM_MAX_UNIT_PRICE`=1e10 (env-override) в `QuoteItemSerializer` c кодами `QUOTE_ITEM_QTY_TOO_LARGE`/`QUOTE_ITEM_PRICE_TOO_LARGE` (KP-04-конвенция; осознанное отклонение: validate_<field> вместо MaxValueValidator — машинный код важнее OpenAPI-максимума, задокументировано в спеке). **E3:** aria-label qty-инпута → `t('quote.quantity')`. Спека: `Docs/dev/specs/spec-timeline-i18n-input-caps-2026-07-12.md`. |

**Миграционные головы после #307: `crm/0059`, `accounts/0039`.** Обе применяются прод-деплоем через INF-04 backup-gate.

## Проверки (CI на GitHub ЛЕЖИТ — биллинг; всё гонялось локально)

- Backend: **940 passed, 0 failed** (полный `pytest --create-db`).
- Frontend: `npm run build` ✓, vitest 185/185, eslint 0 errors.
- i18n: симметрична (4086 RU / 4082 EN), все static t() резолвятся.
- api-contract: schema.json + schema.d.ts регенерированы, нулевой drift.
- deps-lock: идемпотентен (проверено в linux py3.12 контейнере).
- Eyes-on: 2FA-вход/выход, Settings Hub buyer+seller, полная цепочка сделки, EN/RU-таймлайн, КП-PDF с QR (sips).

## Уроки сессии (ВАЖНО для следующего агента)

1. **Merge-timing:** владелец мержит БЫСТРО. Если пушишь доп-коммит в ветку уже-смерженного PR — коммит осиротеет. После каждого пуша проверяй `git branch --contains <sha>`. Так чуть не потерялся CRITICAL 2FA-фикс (спасён recovery-PR #306).
2. **Adversarial-verify обязателен для мультиагентных правок:** в #307 агенты обновили `ActivityLogSerializer` буквально по ТЗ, но живые таймлайны питает ДРУГОЙ сериализатор — `TimelineEntrySerializer` (`crm/views/timeline.py`), плюс `transition_deal_stage` и admin-dict-эндпоинты (`core/admin_api/activity.py`, `core/views/stats.py::_get_recent_activity`) не передавали код. Верификация поймала до PR.
3. **Мультиагентный workflow переживает session-limit:** resume с `resumeFromRunId` — готовые агенты из кэша; частичные правки упавших агентов сбрасывай `git checkout --` перед resume.
4. **Локальная среда (эта машина):** vite dev в sandbox-ФС НЕ видит правки (watcher сломан, кэш в памяти) — для eyes-on фронта пересобирать контейнер (`docker compose up -d --build frontend`, :5173). JWT-инжект в localStorage МЁРТВ (authStore.partialize не персистит токены; access в памяти, refresh в HttpOnly cookie) — только реальный логин через форму. TOTP для Playwright считается в Node по RFC6238 (паритет с pyotp подтверждён). Пароль seed-юзеров: **`Demo1234!`** (`core_seed` DEFAULT_SEED_PASSWORD; buyer.local@railtech.uz / seller.local@railtech.uz, оба L2, seller entitled). Celery на bind-mount — рестартовать после model-правок.
5. Pylance-варнинги на Django ORM (`*_id`, `memberships`) — ложные (нет django-stubs); истина — flake8+pytest.

## Что осталось (кодом НЕ закрывается / owner)

1. **CI-биллинг GitHub** — единственный системный блокер (hosted CI + nightly e2e стоят; self-hosted deploy работает). После восстановления: прогнать полный CI на main, затем INF-12 (required checks) и F0.3 (deploy-on-green).
2. **P3 по спросу:** (a) обязательное обоснование при отправке КП ниже margin-floor — продукт-решение (сейчас self-approve в 1 клик с варнингом); (b) локализация имён стадий/справочников — lookup'ы хранят только RU `name`, всплывает в интерполяции событий и бейджах; (c) Ф5 EN-локаль PDF (owner-gated по спеке PDF-рефактора).
3. **Deferred по канону:** payment/e-sign интеграции Click/Payme/E-IMZO (модели PaymentProviderEvent/DigitalSignature — «до готовности продукта», tech_debt_payment_esign); staging (3 owner-шага); калибровка `AI_DRAFT_MATCH_CONFIDENCE` (телеметрия #241 live, ждёт трафика).
4. Мелочь: 1 pre-existing падение `review-fixes.spec.ts` (каталожная форма, UI-дрейф 06-23, не связан с текущими работами); опционально django-stubs для Pylance.

## Верификация прод-деплоя #307 (первым делом на другой машине)

Деплой после мержа #307 должен был примениться автоматически. Проверить: `gh run list --workflow=deploy-b2b.yml --limit 3` (success) → на проде таймлайн любой сделки на EN-UI показывает английские титулы и НЕ показывает `quote.approval_*`-ключи (backfill 0059 отработал).
