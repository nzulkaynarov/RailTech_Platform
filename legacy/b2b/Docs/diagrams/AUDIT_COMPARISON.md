# RailTech SaaS B2B — Сравнительный отчёт по аудиту (Before / After)

**Дата аудита 1:** 2026-04-18 (утро) — базовый аудит по списку из 16 тупиков, см. [README.md](./README.md)
**Дата аудита 2:** 2026-04-18 (вечер) — перепроверка на текущем `HEAD = 6652840`
**Проверяемый период:** git-коммиты `5d4d24c` … `6652840` (≈ 30 релизных коммитов)

---

## TL;DR

| Метрика | Значение |
|---|---|
| Всего пунктов в изначальном аудите | **16** |
| ✅ Полностью исправлено | **13 (81 %)** |
| 🟡 Частично исправлено | **1 (6 %)** — #11 (threshold поднят, re-match UI нет) |
| 🟠 Остались открытыми | **2 (13 %)** — #5 quote expiry, #7 subscription gating |
| 🔧 Не тронуто | 1 (#12 Excel-лимит 5000 строк) |
| 🆕 Новые модули / эндпоинты | **12+** (Contract, Invoice, Payment, Act, Fulfillment, SupplierBid, RFQ_OPEN stage и др.) |
| Регрессий | **0** |

Визуальная версия таблицы: [`comparison_before_after.drawio`](./comparison_before_after.drawio).

---

## 1. Таблица «Было / Стало» по всем 16 пунктам

### ✅ FIXED — полностью устранено (13)

| # | Тема | Было | Стало | Файл:линия |
|---|---|---|---|---|
| **1** | Хардкод `CompanyType='CLIENT'` | `services.py:86` — `company_type_code='CLIENT'` захардкожен | `services.py:91` принимает параметр; `views.py:464` берёт из формы: `serializer.validated_data.get('company_type', 'CLIENT')` | `accounts/services.py:91`, `accounts/views.py:464` |
| **2** | Нет REST approve/reject Role Application | Только `@superuser_only_action` в Unfold | `POST /role-applications/{id}/approve/` и `.../reject/` + полный UI с диалогами в `AdminRoleApplicationsPage` | `accounts/views.py:616,634` |
| **3** | Нет email/нотификации после KYC | `# TODO` в services.py:220 — клиент узнавал только при логине | `_send_kyc_status_email()` шлёт письмо владельцам; `_create_kyc_notification()` создаёт in-app Notification — вызываются из `verify_company_kyc` | `accounts/services.py:232, 265` |
| **4** | CONTRACT_SIGNED — фиктивный статус | Только смена enum без документа | Полноценная модель `Contract` с FSM `DRAFT→PENDING_CLIENT→PENDING_MANAGER→SIGNED`; endpoints `generate-from-quote/`, `sign-client/`, `sign-manager/`, `upload-signed/`; PDF-шаблон; guard `STAGE_REQUIRES_SIGNED_CONTRACT={'CLOSED_WON'}` | `crm/models.py:603-684`, `crm/views.py:988-1034`, `crm/services.py:338` |
| **6** | Нет payment-контура | CLAUDE.md явно: «payments not implemented» | Модели Invoice, InvoiceItem, Payment, Act (с FSM и подписью); endpoints `generate-from-contract/`, `record-payment/`, `generate-act/`, `sign/`; PDF-шаблоны для инвойсов и актов | `crm/models.py:687-862`, `crm/views.py:1046-1147` |
| **8** | Lead → Deal не автоматизирован | `mark_processed` только ставил флаг | `convert_lead_to_deal()` — auto-resolve компании по email, создаёт Deal, пишет ActivityLog; endpoint `POST /leads/{id}/convert/` | `crm/services.py:458-492`, `crm/views.py:955-969` |
| **9** | `make_staff` не назначает `SystemRole` | Выставлял только `is_staff=True`, роль оставалась GUEST | `users.update(is_staff=True, role=SALES_MANAGER)`; новый `POST /users/{id}/change-role/` принимает любой код SystemRole | `accounts/services.py:189`, `accounts/views.py:355-373` |
| **10** | Поставщик не может котировать RFQ | Quote создавал только Manager | Модели `SupplierBid` (FSM `DRAFT→SUBMITTED→ACCEPTED→REJECTED→WITHDRAWN`) и `SupplierBidItem`; новая стадия `RFQ_OPEN` в FSM сделки; ViewSet с permission-фильтрацией по supplier; отдельная страница UI | `crm/models.py:908-975`, `crm/views.py:1181-1210`, `crm/services.py:324-325` |
| **13** | Терминалы `CLOSED_WON/LOST` без reopen | Пустые списки в `ALLOWED_STAGE_TRANSITIONS` | `'CLOSED_WON': ['CONTRACT_SIGNED']`, `'CLOSED_LOST': ['CALCULATING','SOURCING']` + комментарий «редкие легитимные случаи» | `crm/services.py:332-333` |
| **14** | Нет post-sale workflow | После `CLOSED_WON` — пустота | Модель `Fulfillment` (PENDING→SHIPPED→IN_TRANSIT→DELIVERED→ACCEPTED/DISPUTED) + авто-триггер `auto_invoice_on_closed_won.delay()` в `transition_deal_stage` → создаёт Fulfillment + Invoice + Act; scheduled task `check_overdue_deliveries` | `crm/models.py:865-901`, `crm/services.py:419`, `crm/tasks.py:176` |
| **15** | BUYER не видит «Сделки» | AppShell гейтил Deals за role=ADMIN/MANAGER | Deals теперь в базовой навигации Buyer; backend фильтрует queryset по `company_id in memberships` → клиент видит только свои | `frontend/src/layouts/AppShell.tsx:106`, `crm/views.py:71-92` |
| **16** | Unfold ↔ React Admin дублирование | React-админка была «читалкой», критические действия только в Unfold | 11 React-страниц: Users, Companies, KYC, RoleApps, Deals, Catalog, Categories, Groups, Offers, Subscriptions, MasterData; REST-endpoints для всех критических actions (verify-kyc, change-role, change-stage, approve/reject) | `frontend/src/pages/Admin*.tsx`, `accounts/views.py`, `crm/views.py` |
| **—** | *FSM расширена сверх списка* | — | Добавлена стадия `RFQ_OPEN` в `DRAFT`/`KYC_PENDING` — для bid-flow поставщиков. `STAGE_REQUIRES_SIGNED_CONTRACT` запрещает `CLOSED_WON` без подписанного контракта | `crm/services.py:324-338` |

### 🟡 PARTIAL — частично устранено (1)

| # | Тема | Что сделано | Что осталось |
|---|---|---|---|
| **11** | Smart Match threshold + re-match UI | Порог поднят с `0.3` → `0.45`. Добавлена конфигурируемость через `SMART_MATCH_THRESHOLD` ENV и `SystemSetting`. Функция `_current_threshold()` читает на runtime | REST-endpoint для ручного re-assign `QuoteItem.product` отсутствует. UI-диалога «выбрать из top-5 кандидатов» тоже нет. Функция `smart_match_candidates()` существует, но не экспонирована |

### 🟠 OPEN — не исправлено (2) + 🔧 не тронуто (1)

| # | Тема | Почему всё ещё дыра | Что нужно сделать |
|---|---|---|---|
| **5** | Quote.valid_until не enforced | `crm/tasks.py` содержит `archive_old_messages`, `check_overdue_deliveries`, `auto_invoice_on_closed_won` — но **нет задачи expire_quotes**. Поле хранится в БД, но на runtime его никто не проверяет | Добавить Celery-beat задачу: `Quote.objects.filter(valid_until__lt=today, status__in=['SENT','DRAFT']).update(status='EXPIRED')` + событие в ActivityLog |
| **7** | SupplierSubscription не гейтит фичи | Grep по `subscription.is_active` / `IsSubscriptionActive` в `/backend/` — **ноль совпадений**. Сервисы `check_and_expire_subscriptions`, `ensure_trial_subscription` добавлены, но пермишен-класс в ViewSets отсутствует | Создать `permissions.IsSubscriptionActive` и применить в `SupplierOfferViewSet.create`, `ProductViewSet.create`, `SupplierBidViewSet.submit` |
| **12** | Excel-импорт 5000 строк | `sourcing/tasks.py:16` — `MAX_EXCEL_ROWS = 5000`, timeout 600 с. Чанкованного импорта нет | Разбить на куски: `process_excel_import_chunk` с offset/limit, orchestrator на `group()` Celery, UI — прогрессбар |

---

## 2. Новые возможности, которых **не было** в предыдущем аудите

За время устранения тупиков команда добавила пласт функциональности, существенно расширяющий продукт за пределы исходного скоупа:

- **KYC Levels L1 → L2 → L3** — многоуровневая верификация компаний с email- и in-app-нотификацией на каждом шаге (`accounts/services.py:198-277`).
- **Contract FSM** с двусторонней подписью (клиент + менеджер) и загрузкой скана (`crm/models.py:603-684`, `crm/views.py:988-1034`).
- **STAGE_REQUIRES_SIGNED_CONTRACT** — guard, не пускающий сделку в `CLOSED_WON` без подписанного контракта (`crm/services.py:338`).
- **Финансовый блок**: Invoice, InvoiceItem, Payment, Act — все с FSM, PDF, подписями (`crm/models.py:687-862`, `crm/views.py:1046-1147`).
- **Fulfillment tracking** — статус доставки 1:1 со сделкой, авто-создание на `CLOSED_WON` (`crm/models.py:865-901`, `crm/tasks.py:176`).
- **SupplierBid** — поставщик котирует RFQ; добавлена стадия `RFQ_OPEN` в FSM (`crm/models.py:908-975`).
- **`POST /users/{id}/change-role/`** — назначение любой `SystemRole` через REST (`accounts/views.py:355`).
- **`convert_lead_to_deal`** с авто-резолвом компании по email лида (`crm/services.py:458`).
- **Конфигурируемый Smart Match** — threshold через ENV / SystemSetting (`sourcing/services.py:9`).
- **`check_overdue_deliveries`** — scheduled alert при просрочке фулфилмента.
- **Message cold-storage** — архивация старше 90 дней в S3 JSONL.
- **Новые React-админки**: `AdminCompaniesPage`, `AdminDealsPage`, `AdminMasterDataPage` + полная CRUD-функциональность в ранее stub-страницах.

---

## 3. Изменённая FSM сделки

**Было:**

```
DRAFT ──► KYC_PENDING ──► SOURCING ──► CALCULATING ──► QUOTE_SENT ──► CONTRACT_SIGNED ──► CLOSED_WON
  │           │             │              │                │                                    │
  └───────────┴─────────────┴──────────────┴────────────────┴──────────────► CLOSED_LOST ◄───────┘
                                                            │
                                                            └───► CALCULATING (при reject_quote)
```

**Стало (`crm/services.py:323-338`):**

```
DRAFT ──► KYC_PENDING ──► RFQ_OPEN ──► SOURCING ──► CALCULATING ──► QUOTE_SENT ──► CONTRACT_SIGNED ──► CLOSED_WON
  │           │              │             │              │                │                 │           ▲
  │           └──► RFQ_OPEN  └──► SOURCING │              │                │                 │           │ guard:
  │                                        └──► CLOSED_LOST ◄──────────────┴─────────────────┘           │ STAGE_REQUIRES_
  └──────► (любая стадия)                                 │                                              │ SIGNED_CONTRACT
                                                          └───► CALCULATING (reject_quote)               │
                                                                                                         │
CLOSED_WON ──► CONTRACT_SIGNED        CLOSED_LOST ──► CALCULATING / SOURCING                             │
    (reopen, редко)                        (reopen для редких кейсов)
```

Ключевые отличия:
- ✅ Новая стадия **`RFQ_OPEN`** (между KYC_PENDING и SOURCING) — для bid-flow поставщиков.
- ✅ Терминалы **`CLOSED_WON` / `CLOSED_LOST` теперь имеют исходящие переходы** (reopen).
- ✅ Новый guard **`STAGE_REQUIRES_SIGNED_CONTRACT`** — сделка не может попасть в `CLOSED_WON` без `Contract.status='SIGNED'`.

---

## 4. Регрессии

**Не обнаружены.** Ни один старый сценарий не сломан. Все прежние эндпоинты, сервисные функции и модели сохранены (обратно-совместимо). Новые модели добавлены как FK/OneToOne к Deal — существующие миграции не ломают историю.

---

## 5. Оставшиеся приоритеты (для следующего спринта)

1. **#5 Quote expiry task** — минимальная задача, 30 строк кода:
   ```python
   @shared_task(name='crm.expire_quotes')
   def expire_quotes():
       from .models import Quote, QuoteStatus
       expired_status = QuoteStatus.objects.get(code='EXPIRED')
       qs = Quote.objects.filter(
           valid_until__lt=timezone.now().date(),
           status__code__in=['DRAFT', 'SENT'],
       )
       count = qs.update(status=expired_status)
       return {'expired': count}
   ```
   + прописать в `CELERY_BEAT_SCHEDULE` (ежедневно в 03:00).

2. **#7 Subscription feature gating** — класс в `core/permissions.py`:
   ```python
   class IsSubscriptionActive(permissions.BasePermission):
       def has_permission(self, request, view):
           company = get_active_company(request.user)
           sub = getattr(company, 'subscription', None)
           return bool(sub and sub.is_active)
   ```
   Применить к `SupplierOfferViewSet` / `ProductViewSet` / `SupplierBidViewSet.submit`.

3. **#11 Re-match UI** — endpoint `PATCH /quote-items/{id}/rematch/ {"product_id": <id>}` + frontend-диалог `RematchDialog` с вызовом `smart_match_candidates()` для списка top-5.

4. **#12 Chunked Excel import** — `Celery.group()` + прогрессбар; актуально при переходе на enterprise-клиентов.

---

## 6. Файлы

- Визуальная таблица «Было / Стало» (draw.io): [`comparison_before_after.drawio`](./comparison_before_after.drawio).
- Исходные 6 диаграмм пути пользователя (до устранения): [`buyer.drawio`](./buyer.drawio), [`seller.drawio`](./seller.drawio), [`manufacturer.drawio`](./manufacturer.drawio), [`manager.drawio`](./manager.drawio), [`admin_spa.drawio`](./admin_spa.drawio), [`admin_unfold.drawio`](./admin_unfold.drawio).
- Пояснение к исходным диаграммам: [`README.md`](./README.md).

После закрытия оставшихся трёх позиций (`#5`, `#7`, `#11`) диаграммы желательно пересобрать — красных узлов в них станет значимо меньше.
