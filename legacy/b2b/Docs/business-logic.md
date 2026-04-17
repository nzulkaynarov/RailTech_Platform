---
title: Бизнес-логика и процессы — RailTech B2B
project: RailTech B2B Ecosystem
type: business-logic
version: 6.0 (Actualized)
status: Active
date: 2026-04-17
---

# Архитектура бизнес-процессов

Документ описывает пользовательские сценарии и доменную логику RailTech B2B. Вся бизнес-логика реализована в `backend/<app>/services.py` (см. IRON RULE 8 в CLAUDE.md и [adr/0001-admin-separation.md](adr/0001-admin-separation.md)). ViewSets и admin-действия — тонкие обёртки.

---

## 1. Воронка привлечения и KYC

### 1.1. Регистрация

1. Пользователь заполняет форму на `/register` (email, пароль-черновик не требуется).
2. Бэкенд (`POST /api/v1/auth/register/`):
   - Создаёт `CustomUser(is_active=False)` + `Company` со статусом `PROFILE_SUBMITTED`.
   - Отправляет email со ссылкой `/setup-password?uid=...&token=...`. В DEBUG-режиме ссылка уходит в логи backend-контейнера (`docker compose logs backend | grep setup-password`).
3. Пользователь переходит по ссылке → `PasswordSetupPage` → `POST /api/v1/auth/setup-password/` → `is_active=True`.

### 1.2. Верификация компании

- **L1_UNVERIFIED** — базовый статус после активации.
- **PROFILE_SUBMITTED** — заполнен профиль, загружены документы (`POST /api/v1/accounts/companies/{id}/upload-document/` → MinIO private bucket).
- **L2_VERIFIED** — KYC-менеджер подтверждает через React Admin (`KYCManagerDashboard`) или Django Unfold action. Оба интерфейса вызывают `accounts.services.verify_company_kyc(company, approver, 'L2_VERIFIED')`.
- **L3_CONTRACTED** — подписан рамочный договор + загружен `contract_file` через `CompanyRoleApplication`.
- **REJECTED** — отказ с причиной в `kyc_notes`; клиент может повторно загрузить документы.

### 1.3. Workspace-роли (внутри одной компании)

Membership хранится в `CompanyMember` (`user`, `company`, `role` → `WorkspaceRole`):

- **OWNER** — полный контроль, приглашения, управление подписками.
- **PROCUREMENT_MANAGER** (Снабженец) — создаёт сделки, ведёт переписку.
- **ACCOUNTANT** — финансы, закрывающие документы, счета.

Приглашение сотрудников: `POST /api/v1/accounts/companies/{id}/invite/` — отправка email со ссылкой setup-password.

---

## 2. Формирование потребности (Domain-Aware Smart Match)

### 2.1. Источники спецификации

| Способ | API |
| --- | --- |
| Каталог (PIM) | `POST /api/v1/crm/quote-items/` после `GET /api/v1/catalog/products/` |
| Excel-импорт в сделку | `POST /api/v1/sourcing/import-deal/<int:deal_id>/` |
| Массовый импорт каталога (для админа) | `POST /api/v1/sourcing/import-catalog/` |

### 2.2. Алгоритм Smart Match

`sourcing.tasks.process_excel_import` (Celery, очередь `imports`, `time_limit=600s`, `soft=540s`):

1. Валидация XLSX magic bytes (защита от подделок).
2. Base64-декодирование → временный файл.
3. `pandas.read_excel()` → нормализация колонок.
4. Классификация по `DomainType`:
   - Совпадение с `DomainKeyword.keyword` → явный домен.
   - Иначе fallback на `GENERAL_GOODS`.
5. PostgreSQL `pg_trgm` similarity по `Product.name` (порог `> 0.3`).
6. Создание `QuoteItem` пакетом:
   - Совпадение → `product` + `offer` связаны.
   - Нет совпадения → `product=null`, `imported_raw_name=<строка из Excel>`.
7. `ImportTask.status = 'SUCCESS'`.

### 2.3. Sourcing Hub (ручной маппинг)

Страница `SourcingMatchPage` (`/pages/SourcingMatchPage.tsx`) через React Query:

- `GET /api/v1/sourcing/requests/` — позиции с `product=null`.
- `PATCH /api/v1/crm/quote-items/{id}/` — менеджер связывает позицию с существующим `Product` + `SupplierOffer`.

---

## 3. Финитный автомат сделки (Deal FSM)

Стадии хранятся как справочник `crm.DealStage` (см. seed_data). Код-сравнение — по полю `stage_code`, не по `stage_name` (см. IRON RULE 2).

| Код | Описание | Следующие стадии |
| --- | --- | --- |
| `DRAFT` | Черновик, клиент только собирает спецификацию | `KYC_PENDING`, `CLOSED_LOST` |
| `KYC_PENDING` | Профиль подан, ждёт L2 | `SOURCING`, `DRAFT`, `CLOSED_LOST` |
| `SOURCING` | KYC утверждён, идёт поиск поставщиков / мапинг Excel | `CALCULATING`, `CLOSED_LOST` |
| `CALCULATING` | Менеджер собирает цены в Quote Builder | `QUOTE_SENT`, `CLOSED_LOST` |
| `QUOTE_SENT` | КП выставлено, клиент видит Action Banner | `CONTRACT_SIGNED`, `CLOSED_LOST` |
| `CONTRACT_SIGNED` | КП принято, договор подписан | `CLOSED_WON` |
| `CLOSED_WON` | Заказ выполнен | terminal |
| `CLOSED_LOST` | Отказ клиента или отмена | terminal |

Переходы валидирует матрица `ALLOWED_STAGE_TRANSITIONS` в `crm/services.py`. Вызов: `POST /api/v1/crm/deals/{id}/change-stage/` → `crm.services.change_deal_stage(deal, new_stage_code, user)`.

---

## 4. Финансовая модель (Landed Cost + Quote Builder)

Все расчёты — в `crm.services`. Поля хранятся как `DecimalField`; immutable snapshot — `QuoteItemHistory`. Финансовые модели (`Deal`, `Quote`, `QuoteItem`) декорированы `@pghistory.track`.

Формула по каждой позиции:

1. `frozen_base_price` (FCA завода-изготовителя или базовая ставка подрядчика для `SERVICES`).
2. `logistics_cost + customs_duty` (для `SERVICES` игнорируются).
3. **Landed Cost** = `frozen_base_price + logistics_cost + customs_duty`.
4. **Final Price Excl VAT** = `landed_cost × (1 + margin_percent / 100)`.
5. **Total Incl VAT** = `final_price_excl_vat × (1 + tax_country.vat_rate)`.

НДС хранится на уровне `Quote.vat_rate` (копируется из `Country.vat_rate` при создании, можно переопределить).

На уровне Quote агрегируется:

- `subtotal_excl_vat` = сумма всех `final_price_excl_vat × quantity`.
- `vat_amount` = `subtotal × vat_rate`.
- `total_incl_vat` = `subtotal + vat_amount`.

---

## 5. Жизненный цикл КП

1. **Генерация PDF** — `POST /api/v1/crm/quotes/{id}/generate-pdf/` → Celery очередь `pdf`, WeasyPrint рендер шаблона `crm/templates/quote_pdf.html`. PDF сохраняется в MinIO `railtech-private` bucket; `Quote.pdf_file` — presigned URL (15 мин).
2. **Отправка клиенту** — `POST /api/v1/crm/quotes/{id}/send-to-client/`:
   - `Quote.status = SENT`, `Deal.stage = QUOTE_SENT`.
   - Email с ссылкой на PDF (Celery очередь `default`).
   - Notification клиенту (`notifications.Notification`).
3. **Клиент видит Amber Action Banner** на странице сделки — кнопки «Принять КП» / «Написать в чат».
4. **Одобрение** — `POST /api/v1/crm/quotes/{id}/approve/`:
   - `Quote.status = APPROVED`, `Quote.approved_at = now()`, `Quote.approved_by = user`.
   - `Deal.stage = CONTRACT_SIGNED`.

---

## 6. Real-time коммуникация

### 6.1. Deal Chat

- **Транспорт:** WebSocket (`ws/chat/<deal_id>/`) через Django Channels + Redis channel layer.
- **Консьюмер:** `crm.consumers.ChatConsumer` (AsyncWebsocketConsumer).
- **Room:** `chat_deal_{deal_id}`.
- **Изоляция:** consumer проверяет `deal.manager == user`, `deal.client == user` или членство в `CompanyMember` компании-владельца. Неавторизованный доступ → close code 4003.
- **Лимит сообщения:** 5000 символов.
- **История:** `GET /api/v1/crm/messages/?deal_id=...`.

Сообщения старше 90 дней архивируются Celery-таском `crm.tasks.archive_old_messages` в MinIO JSONL (`Message.is_archived=True`, `archive_path` = путь в бакете).

### 6.2. Notification Center

- `notifications.Notification` создаётся сигналами/сервисами на события: смена стадии сделки, одобрение КП, смена KYC-статуса, назначение менеджера.
- Фронтенд — polling `GET /api/v1/notifications/` в header (`NotificationCenter` в `components/Layout/`).
- WebSocket push уведомлений — запланирован (см. [ROADMAP.md](ROADMAP.md) Sprint 2).

---

## 7. Multi-tenancy на уровне изоляции данных

Все ViewSets переопределяют `get_queryset()`:

```python
# DealViewSet (упрощённо)
def get_queryset(self):
    user = self.request.user
    if user.role.code == 'ADMIN':
        return Deal.objects.all()
    if user.role.code in ('SALES_MANAGER', 'ACCOUNT_MANAGER'):
        return Deal.objects.filter(Q(manager=user) | Q(manager__isnull=True))
    # CLIENT
    member = CompanyMember.objects.filter(user=user, is_active=True).first()
    if not member:
        return Deal.objects.none()
    return Deal.objects.filter(company=member.company)
```

Object-level permission (`IsOwnerOrManagerOrAdmin`) дублирует проверку на detail-endpoint'ах для защиты от IDOR.

---

## 8. Audit trail

| Сущность | Механизм |
| --- | --- |
| `Deal`, `Quote`, `QuoteItem` | `@pghistory.track` + `django-pgtrigger` — полные DB-level snapshot'ы |
| `QuoteItem` (финансы) | дополнительно immutable модель `QuoteItemHistory` с полями `change_reason` |
| `ActivityLog` | User actions (видимый через Django Unfold read-only) |
| `Message` history archive | `Message.is_archived`, JSONL в MinIO |
| `ImportTask` | Celery task ownership tracking (IDOR fix) |

---

## 9. См. также

- [role-model.md](role-model.md) — разграничение прав.
- [architecture-diagrams.md](architecture-diagrams.md) — Mermaid-диаграммы (Deal FSM, KYC flow, Sourcing).
- [technical-specification.md](technical-specification.md) — API endpoints и модели.
- [websocket-messages.md](websocket-messages.md) — WebSocket-протокол чата.
