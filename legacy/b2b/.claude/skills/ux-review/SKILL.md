---
name: ux-review
description: "Eyes-on проверка UI в реальном браузере (Playwright): пройти сценарий глазами, снять скриншоты, найти тупики и несостыковки. Использовать ПЕРЕД тем как объявить UI-задачу готовой (PRODUCT RULE 4: DoD = пройденный глазами сценарий), после любой UI-волны, и когда владелец просит «посмотреть глазами» / проверить флоу / показать скриншот."
---

# /ux-review — смотрим глазами, а не кодом

Цель: подтвердить или опровергнуть работоспособность флоу **тем, что реально видно в браузере**. Отчёт по коду («тесты зелёные, значит работает») — НЕ результат этого скилла. Скилл существует потому, что агенты систематически рапортуют успех, которого нет.

## Железные принципы

1. **Верить только скриншоту.** Каждое утверждение в отчёте («кнопка есть», «статус обновился») подкреплено снимком. Нет снимка — нет утверждения.
2. **Прод-сборка, не vite dev.** На этой машине vite dev (:5174) НЕ видит правки (сломан file-watcher в sandbox-ФС). Для eyes-on после правок кода: `docker compose up -d --build frontend` и работать с http://localhost:5173.
3. **Логин только через форму.** JWT-инжект в localStorage мёртв (access-токен живёт в памяти, refresh — в HttpOnly-cookie).
4. **Найденное — чинить или честно показать.** Тупик в сценарии = задача не готова, даже если фича «сделана».

## Шаг 1. Preflight

```bash
docker compose ps                       # backend, frontend, db, redis — Up
curl -s http://localhost:8000/health/   # backend + DB здоровы
# Если правился фронт: пересобрать ОБЯЗАТЕЛЬНО (иначе смотришь старый bundle):
docker compose up -d --build frontend
```

Тест-доступы (локальный seed `make seed`, пароль `Demo1234!`, env-override `SEED_USER_PASSWORD`):
- `buyer.local@railtech.uz` — покупатель, KYC L2
- `seller.local@railtech.uz` — продавец, KYC L2, entitled на quote.send
- `solo.seller@railtech.uz` — соло-продавец (company 28), для соло-флоу КП

Если логин падает 401 — проверить, что seed прогнан; при странных 429 локально — Redis копит throttle/lockout между прогонами: `docker compose exec backend python manage.py shell -c "from django.core.cache import cache; cache.clear()"`.

## Шаг 2. Playwright в scratchpad (НЕ в репо)

```bash
cd <scratchpad> && npm i playwright && npx playwright install chromium
```

Каркас прогона (`<scratchpad>/eyes-on.mjs`):

```js
import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));   // console 401/forwardRef — шум, pageerror — сигнал

await page.goto('http://localhost:5173/');
await page.fill('input[type="email"]', 'seller.local@railtech.uz');
await page.fill('input[type="password"]', 'Demo1234!');
await page.click('button[type="submit"]');
await page.waitForSelector('input[type="email"]', { state: 'detached', timeout: 15000 });

// Хэш-навигация ТОЛЬКО после логина:
await page.evaluate(() => { location.hash = 'dashboard'; });
await page.waitForTimeout(1500);
await page.screenshot({ path: 'step-01-dashboard.png', fullPage: true });
// ... дальнейшие шаги сценария, скриншот НА КАЖДЫЙ шаг ...
console.log('pageerrors:', errors);
await browser.close();
```

Нюансы:
- Секции Settings: `history.replaceState({},'','/?section=security'); location.hash='settings'`.
- 2FA-логин автоматизируется: после пароля появляется `input[maxlength="6"]`; TOTP считается в Node по RFC6238 (SHA1/6 цифр/30s). Сброс 2FA юзеру: shell `u.is_2fa_enabled=False; u.totp_secret=None`.
- PDF: рендерится в контейнере → `docker compose cp backend:<путь> .` → `sips -s format png файл.pdf --out файл.png` → посмотреть Read'ом.

## Шаг 3. Сценарий

По умолчанию — wedge-цикл целиком (обе роли):
1. **Buyer**: создать заявку → добавить позиции → отправить.
2. **Seller**: увидеть заявку в инбоксе → claim → собрать КП → отправить клиенту.
3. **Публичная страница КП** (инкогнито-контекст, без логина): открыть по токену → принять.
4. **Buyer/Seller**: убедиться, что сделка перешла по FSM, документы появились в хабе сделки (`GET crm/deals/{id}/documents/`).

Если задача уже — гонять тот флоу, который трогала правка, но всегда **от входа пользователя до следующего осмысленного шага**, не один экран.

## Шаг 4. Чек-лист критики (на каждом экране)

- **Тупики**: понятно ли, что делать дальше? Есть ли следующий шаг / CTA? Пустой экран без объяснения = дефект.
- **Состояния**: empty (нет данных) / loading / error — все три осмысленны, не «белый экран» и не вечный спиннер.
- **Слова**: одна сущность называется одним словом везде (статусы, кнопки, заголовки). RU и EN переключаются без «сырых» ключей i18n.
- **Консистентность с эталоном**: как этот экран выглядит в Odoo/Bitrix24/PandaDoc? Если наш кастом хуже паттерна — записать как gap.
- **Мобильный**: повторить ключевые экраны с viewport 375×812 — таблицы падают в карточки (ResponsiveDataTable), ничего не уезжает.
- **Тёмная тема**: прогнать хотя бы главные экраны с `document.documentElement.classList.add('dark')`.
- **pageerror**: массив пуст.

## Шаг 5. Отчёт

```
## UX Review: <флоу>

Вердикт: ✅ сценарий пройден / ❌ тупик на шаге N

| Шаг | Скриншот | Что видно | Дефекты |
|-----|----------|-----------|---------|
| 1. Логин seller | step-01.png | ... | — |

### Дефекты (по убыванию тяжести)
1. <экран>: <что не так> → <как чинить / какой паттерн у эталона>

### pageerrors: <список или «пусто»>
```

Скриншоты складывать в scratchpad и показывать владельцу ключевые (Read вернёт их визуально). Вердикт «готово» — ТОЛЬКО при пройденном сценарии без тупиков.
