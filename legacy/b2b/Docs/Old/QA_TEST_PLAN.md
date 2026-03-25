# RailTech B2B Ecosystem — План сквозного тестирования (E2E & Integration)

> **Аудитория:** Junior QA / Junior Developer
> **Стек автотестов:** Pytest (бэк) · Playwright (E2E)
> **Уровни:** Unit → Integration → E2E → Smoke (prod)

---

## 0. Подготовка окружения

```bash
# 1. Запустить инфраструктуру
cp .env.example .env   # заполнить реальные значения
docker compose up -d --build

# 2. Проверить что все контейнеры Healthy
docker compose ps
# Ожидаемый статус: db(healthy), redis(healthy), backend(healthy)

# 3. Создать тестового пользователя для E2E
docker compose exec backend python manage.py shell -c "
from accounts.models import CustomUser, Company
c = Company.objects.create(name='TestCo', inn='1234567890', status='L3_CONTRACTED')
u = CustomUser.objects.create_user(email='qa@railtech.uz', password='QAtest123!', role='CLIENT', company=c, kyc_status='L3_CONTRACTED')
print('Created:', u.email)
"
```

---

## БЛОК A — Аутентификация и авторизация

### A-1. JWT логин (базовый флоу)
- [ ] `POST /api/v1/auth/token/` с `{email, password}` → 200, тело содержит `access` и `refresh`
- [ ] `POST /api/v1/auth/token/` с неверным паролем → 401
- [ ] `POST /api/v1/auth/token/refresh/` с валидным refresh → 200, новый `access`
- [ ] `POST /api/v1/auth/token/refresh/` с истёкшим refresh → 401
- [ ] Запрос к защищённому эндпоинту без токена → 401
- [ ] Запрос с `Authorization: Bearer <access>` → 200

### A-2. Ролевая модель (CompanyMember + Roles)
- [ ] Пользователь с ролью `CLIENT` не может открыть `/crm/deals` (редирект или 403)
- [ ] Пользователь с ролью `SALES_MANAGER` видит все сделки в `/crm/deals`
- [ ] Пользователь с ролью `ADMIN` видит пункт "Расчёт Цен" в навигации
- [ ] `ACCOUNT_MANAGER` не видит кнопку "Расчёт Цен"
- [ ] После logout токен не принимается: повторный запрос → 401

### A-3. KYC-статусы
- [ ] Пользователь `L1_UNVERIFIED` не видит цены в каталоге (отображается `RESTRICTED`)
- [ ] Пользователь `L2_VERIFIED` видит цены в каталоге
- [ ] Пользователь `L3_CONTRACTED` видит цены + может создавать сделки
- [ ] API: `GET /api/v1/catalog/products/` для L1 → цены скрыты (поле `base_price` отсутствует или null)

### A-4. Регистрация нового клиента
- [ ] `POST /api/v1/auth/register/` с полными данными → 201, пользователь в статусе L1
- [ ] Повторная регистрация с тем же email → 400 с понятным сообщением
- [ ] `POST /api/v1/auth/setup-password/` с валидным token → 200
- [ ] `POST /api/v1/auth/submit-profile/` с данными компании → 200, статус переходит в L2

---

## БЛОК B — Каталог (Product / Offer / Справочники)

### B-1. Справочники Master Data (динамические, без хардкода)
- [ ] `GET /api/v1/master-data/currencies/` → 200, список не пустой, каждый объект содержит `id`, `code`, `name`
- [ ] `GET /api/v1/master-data/units/` → 200, есть `pcs` / `kg` / `m`
- [ ] `GET /api/v1/master-data/countries/` → 200
- [ ] `GET /api/v1/master-data/delivery-basis/` → 200, есть `FCA`, `CIF`, `DAP`

### B-2. Продукты (Product — мастер-данные)
- [ ] `GET /api/v1/catalog/products/` → 200, поля: `id`, `name`, `sku`, `category_data`, `manufacturer_data`, `uom_data`, `stock_status`, `domain_type`
- [ ] `GET /api/v1/catalog/products/?domain_type=RAILWAY_MACHINERY` → только ж/д техника
- [ ] `GET /api/v1/catalog/products/?search=подшипник` → фильтрация по названию
- [ ] `GET /api/v1/catalog/products/?stock_status=IN_STOCK` → только в наличии
- [ ] `GET /api/v1/catalog/products/1/` → детальная карточка с вложенными объектами (не плоскими ID)

### B-3. Офферы (Offer — коммерческие данные)
- [ ] `GET /api/v1/catalog/offers/?product=1` → офферы для конкретного продукта
- [ ] Каждый оффер содержит: `product`, `supplier`, `base_price`, `currency_data` (объект, не ID)
- [ ] Менеджер может создать оффер: `POST /api/v1/catalog/offers/`
- [ ] Клиент не может создать оффер → 403

### B-4. Каталог на фронтенде (ручная проверка)
- [ ] Таблица отображает колонки: #, Название, SKU/GOST, Производитель, UOM, Наличие, Цена
- [ ] Переключение вид-таблица / вид-сетка работает без ошибок
- [ ] Фильтр по домену (RAILWAY / GENERAL / SERVICES) меняет список
- [ ] Клик на строку открывает ProductDetailModal с вкладками META_DATA и TECH_SPECS
- [ ] Для L1-пользователя ячейка цены показывает `🔒 RESTRICTED`, а не число

---

## БЛОК C — CRM: Сделки, Квоты, Расчёты

### C-1. Сделки (Deal)
- [ ] `GET /api/v1/crm/deals/` → 200, список с полями: `id`, `company_name`, `stage_name`, `total_value`, `created_at`
- [ ] `POST /api/v1/crm/deals/` → создаёт сделку, возвращает `id`
- [ ] Каждая сделка связана с компанией (не прямым пользователем)
- [ ] Менеджер видит сделки всех компаний; клиент — только своей компании
- [ ] `PATCH /api/v1/crm/deals/1/` → обновление стадии сделки
- [ ] Переход стадии `Quote Sent` показывает предупреждающий баннер на фронте

### C-2. Квоты и Quote Items (финансовый расчёт)
- [ ] `GET /api/v1/crm/quotes/?deal=1` → список квот для сделки, активная квота имеет `is_active=true`
- [ ] `GET /api/v1/crm/quote-items/?deal_id=1` → список позиций с полями: `product_name`, `quantity`, `frozen_base_price`, `logistics_cost`, `customs_duty`, `margin_percent`, `landed_cost`, `final_price_excl_vat`
- [ ] **Критичная проверка:** изменить `quantity=5`, `margin_percent=15` → `PATCH /api/v1/crm/quote-items/1/` → в ответе пересчитался `landed_cost` и `final_price_excl_vat`
- [ ] Итоги квоты: `subtotal_excl_vat`, `vat_amount`, `total_incl_vat` пересчитываются корректно
- [ ] `GET /api/v1/crm/deals/1/export_pdf/` → 200, Content-Type: application/pdf, файл скачивается

### C-3. QuoteBuilderGrid на фронтенде
- [ ] Открыть сделку → вкладка Specification → таблица загружается
- [ ] Изменить число в колонке Qty → поле обновляется локально (без API-запроса)
- [ ] Нажать SAVESpec → в DevTools Network видна PATCH-запись с правильным payload
- [ ] Нажать EXPORT.PDF → скачивается PDF-файл
- [ ] Footer показывает GRAND_TOTAL_PAYABLE — сумма соответствует API

### C-4. Импорт Excel (Sourcing)
- [ ] Загрузить `.xlsx` файл через ExcelUpload → `POST /api/v1/sourcing/import-deal/<id>/`
- [ ] Ответ содержит `task_id`
- [ ] `GET /api/v1/sourcing/import-status/<task_id>/` → статус `PENDING` → `SUCCESS`
- [ ] После успеха в QuoteBuilderGrid появились новые строки
- [ ] Строки без маппинга на Product имеют флаг `⚠` (иконка AlertTriangle)

### C-5. Чат (WebSocket)
- [ ] Открыть сделку → вкладка Chat → WebSocket устанавливается (статус 101 в DevTools)
- [ ] Отправить сообщение → мгновенно появляется в чате без перезагрузки страницы
- [ ] Сообщение сохранено: `GET /api/v1/crm/messages/?deal=1` → в списке

---

## БЛОК D — Интеграционные JSON-флоу (критические точки)

### D-1. Полный флоу "Создать сделку с позициями"

```
Выполнить последовательно через Postman / httpx:

1. POST /api/v1/auth/token/
   Body: {"email": "manager@railtech.uz", "password": "..."}
   Сохранить: access_token

2. POST /api/v1/crm/deals/
   Headers: Authorization: Bearer <access_token>
   Body: {"company": 1, "title": "Integration Test Deal"}
   Сохранить: deal_id

3. POST /api/v1/crm/quote-items/
   Body: {
     "deal": <deal_id>,
     "product": 1,
     "quantity": 10,
     "frozen_base_price": "150.00",
     "frozen_currency": "USD",
     "logistics_cost": "20.00",
     "customs_duty": "15.00",
     "margin_percent": "12.00"
   }
   Ожидать: 201, поле landed_cost = frozen_base_price + logistics + customs

4. GET /api/v1/crm/quotes/?deal=<deal_id>
   Ожидать: active_quote с total_incl_vat > 0

5. GET /api/v1/crm/deals/<deal_id>/export_pdf/
   Ожидать: Content-Type: application/pdf
```

### D-2. Проверка маппинга вложенных справочников

```python
# pytest — integration test
def test_quote_item_has_nested_currency(auth_client, deal, product):
    response = auth_client.post('/api/v1/crm/quote-items/', {
        'deal': deal.id,
        'product': product.id,
        'quantity': 1,
        'frozen_base_price': '100.00',
        'frozen_currency': 'USD',
    })
    assert response.status_code == 201
    # Не плоский ID, а вложенный объект
    assert isinstance(response.data.get('currency_data'), dict)
    assert 'code' in response.data['currency_data']
```

---

## БЛОК E — Автотесты (инструменты и примеры)

### E-1. Pytest (бэкенд)

```bash
# Запуск всех тестов с coverage
cd backend
pytest --cov=. --cov-report=html -v

# Запуск только CRM-тестов
pytest crm/tests.py -v

# Запуск с маркером интеграционных
pytest -m integration -v
```

**Ключевые тест-файлы:**
```
backend/
  accounts/tests.py   — регистрация, логин, KYC
  catalog/tests.py    — CRUD продуктов, фильтры
  crm/tests.py        — сделки, квоты, расчёты, PDF
  master_data/tests.py — справочники
  sourcing/tests.py   — Excel импорт
```

**Шаблон теста (crm/tests.py):**
```python
import pytest
from django.test import TestCase
from model_bakery import baker

class QuoteItemCalculationTest(TestCase):
    def setUp(self):
        self.company = baker.make('accounts.Company', status='L3_CONTRACTED')
        self.manager = baker.make('accounts.CustomUser', role='SALES_MANAGER')
        self.deal = baker.make('crm.Deal', company=self.company, owner=self.manager)
        self.client.force_login(self.manager)

    def test_landed_cost_calculated_on_save(self):
        item = baker.make(
            'crm.QuoteItem',
            deal=self.deal,
            frozen_base_price='100.00',
            logistics_cost='20.00',
            customs_duty='15.00',
        )
        item.refresh_from_db()
        self.assertEqual(float(item.landed_cost), 135.00)

    def test_quote_totals_update_on_item_change(self):
        item = baker.make('crm.QuoteItem', deal=self.deal,
                          frozen_base_price='100.00', quantity=5,
                          margin_percent='10.00')
        quote = self.deal.active_quote
        self.assertGreater(float(quote.total_incl_vat), 0)
```

### E-2. Playwright (E2E фронтенд)

```bash
# Установка
npm install -D @playwright/test
npx playwright install chromium

# Запуск E2E тестов
npx playwright test

# Запуск с UI (визуальный дебаг)
npx playwright test --ui
```

**Структура E2E-тестов:**
```
frontend/
  e2e/
    auth.spec.ts          — логин/логаут
    catalog.spec.ts       — каталог, фильтры, модалка
    deal-splitview.spec.ts — CRM сделки
    quote-builder.spec.ts  — финансовый расчёт
```

**Пример E2E-теста (auth.spec.ts):**
```typescript
import { test, expect } from '@playwright/test';

test.describe('Authentication', () => {
  test('Manager can login and see CRM', async ({ page }) => {
    await page.goto('http://localhost:3000/login');

    await page.fill('[name="email"]', 'manager@railtech.uz');
    await page.fill('[name="password"]', 'TestPass123!');
    await page.click('button[type="submit"]');

    // Должен перенаправить на /crm/home
    await expect(page).toHaveURL(/crm\/home/);
    await expect(page.locator('text=Operations Center')).toBeVisible();
  });

  test('Client cannot access CRM deals', async ({ page }) => {
    // Логин как клиент
    await page.goto('http://localhost:3000/login');
    await page.fill('[name="email"]', 'client@railtech.uz');
    await page.fill('[name="password"]', 'ClientPass123!');
    await page.click('button[type="submit"]');

    // Прямой переход на CRM
    await page.goto('http://localhost:3000/crm/deals');
    // Должен быть редирект или 403
    await expect(page).not.toHaveURL(/crm\/deals/);
  });
});
```

---

## БЛОК F — Smoke-тесты (после деплоя в production)

```bash
#!/bin/bash
# scripts/smoke_test.sh — запускать после каждого деплоя
BASE_URL="https://api.railtech.uz"

check() {
  local endpoint=$1
  local expected=$2
  local status=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL$endpoint")
  if [ "$status" -eq "$expected" ]; then
    echo "✓ $endpoint → $status"
  else
    echo "✗ $endpoint → $status (expected $expected)" >&2
    exit 1
  fi
}

echo "=== RailTech Smoke Tests ==="
check "/api/v1/health/"                      200
check "/api/v1/catalog/products/"            401   # требует auth
check "/api/v1/master-data/currencies/"      200   # публичный
check "/api/v1/auth/token/"                  405   # GET не разрешён, только POST
check "/admin/"                              200
echo "=== All checks passed ==="
```

---

## Чек-лист финальной интеграции

```
ИНФРАСТРУКТУРА
[ ] docker compose up → все 7 сервисов healthy
[ ] nginx роутит /api/v1/ → backend (проверить curl localhost/api/v1/health/)
[ ] nginx роутит / → frontend (открыть в браузере)
[ ] /ws/ → WebSocket работает (проверить в DevTools → Network → WS)
[ ] staticfiles и media смонтированы в nginx-контейнер

БЭКЕНД
[ ] Все миграции применены (docker compose exec backend python manage.py showmigrations)
[ ] Суперадмин существует (войти на /admin/)
[ ] Seed-данные загружены (currencies, units, categories не пустые)
[ ] Celery worker получает задачи (docker compose logs celery_worker)
[ ] PDF-экспорт работает (WeasyPrint не падает с ошибкой шрифтов)

ФРОНТЕНД
[ ] VITE_API_URL указывает на правильный бэкенд (Network tab → requests не на localhost)
[ ] Логин работает и токен сохраняется в localStorage
[ ] Каталог загружает данные из API (не пустой)
[ ] QuoteBuilderGrid загружает позиции сделки
[ ] SAVESpec → PATCH-запрос уходит с правильным payload

БЕЗОПАСНОСТЬ
[ ] DJANGO_DEBUG=False в production
[ ] CORS_ALLOWED_ORIGINS не содержит localhost в production
[ ] Секреты не захардкожены в docker-compose.yml или коде
[ ] HTTPS настроен (nginx + Let's Encrypt)
```
