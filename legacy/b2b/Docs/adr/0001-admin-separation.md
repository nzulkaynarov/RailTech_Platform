# ADR-0001: Разделение Django Unfold Admin и React Admin

**Status:** Accepted
**Date:** 2026-04-12
**Deciders:** Product owner + Engineering

## Контекст

В проекте RailTech B2B существуют два административных интерфейса:

1. **Django Unfold Admin** (`/admin/`) — автогенерируемая админка Django поверх ORM, тематизированная через `django-unfold`. Содержит CRUD для всех моделей, custom actions для бизнес-операций (verify_kyc, publish_products, mark_closed_lost и др.), inline-редакторы.

2. **React Admin** (`/admin/*` в SPA) — кастомный React-интерфейс с собственными страницами (AdminDashboard, AdminUsers, AdminNomenclature, KYCManagerDashboard, SystemSettings и др.).

На момент написания ADR функциональность дублируется и частично пересекается. Бизнес-логика (например, одобрение KYC) реализована и в Django admin custom actions, и в DRF-эндпоинтах, что создаёт риск рассинхрона: изменение в одном месте не отражается в другом.

## Решение

**Принцип разделения:**

> **Django Unfold Admin = инструмент для инженеров (dev / DBA / support) для редких операций и аварийных ситуаций.**
>
> **React Admin = рабочий инструмент для бизнес-пользователей (admin, KYC-менеджер, sales-manager) для ежедневных операций.**

### Что остаётся в Unfold

| Категория | Модели / функции | Обоснование |
|---|---|---|
| **Master data CRUD** | `SystemRole`, `WorkspaceRole`, `CompanyType`, `VerificationStatus`, `KYCDocType`, `DomainType`, `ProductStatus`, `StockStatus`, `DealStage`, `QuoteStatus`, `Country`, `Currency`, `UnitOfMeasure`, `DeliveryBasis`, `NotificationType`, `DomainKeyword` | Справочники, меняются раз в квартал, для dev/DBA |
| **Read-only audit** | `ActivityLog`, `QuoteItemHistory`, `ImportTask`, `MessageHistory` (Phase 6) | Инспекция инцидентов |
| **Bulk debug view** | `User`, `Company`, `Deal`, `Quote`, `Message` | Только READ-ONLY (`has_change_permission=False`). Инженер видит, но не правит руками. |
| **Celery Beat schedule** | `django_celery_beat.PeriodicTask`, `CrontabSchedule` | Управление периодическими задачами |
| **Django auth** | `Group`, `Permission` | Чисто инфраструктурное |

### Что переезжает в React Admin

| Функция | Принимающая страница React |
|---|---|
| KYC verification (L1→L2→L3) | `KYCManagerDashboard` (`/admin/kyc`) |
| User management (CRUD, invite, role) | `AdminUsers` (`/admin/users`) |
| Company management | новая `CompanyManagement` (`/admin/companies`) |
| Product / catalog (PIM) | `AdminNomenclature` (`/admin/nomenclature`) |
| System settings (бизнес-параметры) | `SystemSettings` (`/admin/settings`) — wire to backend |
| Subscription management | новая `SubscriptionManagement` (`/admin/subscriptions`) |
| Role application approval | новая `RoleApplications` (`/admin/role-applications`) |
| Deal management & stage transitions | `ManagerDashboard` (`/crm/*`) |
| Analytics | `AnalyticsDashboard` (`/admin/analytics`) |

### Архитектурное правило (см. CLAUDE.md IRON RULE 8)

**Вся бизнес-логика живёт в `<app>/services.py`. `admin.py` и `views.py` — тонкие обёртки, которые только вызывают сервисы.**

```python
# accounts/services.py — единственный источник правды
def verify_company_kyc(company, approver, level, comment): ...

# accounts/admin.py — Unfold action — обёртка
@admin.action(description="Подтвердить KYC (L2)")
def verify_kyc_action(self, request, queryset):
    for c in queryset:
        services.verify_company_kyc(c, request.user, 'L2_VERIFIED', '')

# accounts/views.py — DRF endpoint — обёртка
class CompanyViewSet(viewsets.ModelViewSet):
    @action(detail=True, methods=['post'])
    def verify_kyc(self, request, pk=None):
        services.verify_company_kyc(self.get_object(), request.user, ...)
```

Оба интерфейса вызывают **одну и ту же функцию**. Логика — в одном месте.

## Роли и права доступа

| Роль | Где работает | Что делает | Частота |
|---|---|---|---|
| **System Engineer** (dev, DBA) | Django Unfold | Миграции, master data, аварийный debug | Редко |
| **Platform Admin** | React Admin (`/admin/*`) | Пользователи, KYC, каталог, настройки | Ежедневно |
| **KYC Manager** | React Admin (`/admin/kyc`) | Верификация компаний | Ежедневно |
| **Sales Manager** | React CRM (`/crm/*`) | Сделки, квоты, клиенты | Ежедневно |
| **Account Manager** | React CRM (`/crm/*`) | Клиенты | Ежедневно |
| **Client** | React Cabinet (`/cabinet/*`) | Каталог, запросы, профиль | Ежедневно |

**Доступ к Unfold**: только для пользователей в Django group `system_engineers` ИЛИ с `is_superuser=True`. `admin@railtech.uz` НЕ должен нуждаться в Unfold — он работает в React Admin.

## Последствия

### Положительные
- Один источник правды для бизнес-логики (`services.py`)
- Бизнес-пользователи получают тематический UX вместо generic Django admin
- Изоляция: ошибка в React не ломает Unfold (и наоборот)
- Чёткое разделение ответственности — каждый инструмент для своей роли
- Безопасность: меньше людей имеет доступ к Unfold (потенциально опасный инструмент)

### Отрицательные / риски
- Двойная поддержка некоторых компонентов в переходный период
- Нужна дисциплина: новые фичи не должны попадать в Unfold
- Требуется единый RBAC, чтобы права совпадали

### Митигация рисков
- ADR + IRON RULE 8 в CLAUDE.md закрепляют правило для будущих разработчиков
- Каждая custom action в admin.py покрывается тестом до и после рефакторинга
- pghistory ловит изменения от обоих интерфейсов — единый audit trail

## План миграции

1. **Phase 0 — Аудит** ✅ (выполнено 2026-04-12)
2. **Phase 1 — ADR + IRON RULE 8** ✅ (выполнено 2026-04-12)
3. **Phase 2 — Рефакторинг бизнес-логики из admin.py в services.py** ✅ (выполнено ранее)
4. **Phase 3 — Закрытие пробелов в React Admin** ✅ (KYC, Subscriptions, Role apps — реализованы)
5. **Phase 4 — Урезание Unfold до read-only inspection** ✅ (выполнено 2026-04-16)
   - `ReadOnlyInspectionMixin` на всех бизнес-моделях (Company, Deal, Lead, Message, Product, SupplierOffer, CompanyRoleApplication, SupplierSubscription)
   - Все бизнес-экшены помечены `[Emergency]` и доступны только для `is_superuser=True`
   - Декоратор `@superuser_only_action` в `core/admin_mixins.py`
   - Справочники (master_data, lookups) — полный CRUD без ограничений
6. **Phase 5 — Hardening доступа (`system_engineers` group)** — TODO
7. **Phase 6 — Message history archive в S3 (через Unfold + Celery)** ✅ (выполнено)
8. **Phase 7 — Финальная верификация и документация** — TODO

## Связанные документы

- [CLAUDE.md](../../CLAUDE.md) — IRON RULE 8 (services.py only)
- [Phase 0 audit findings](../audits/phase-0-audit.md) (TODO)
