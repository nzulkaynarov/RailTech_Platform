# Аудит и План Рефакторинга кодовой базы RailTech B2B

**Дата:** 2026-03-14
**Статус:** Требует согласования

## 1. Результаты системного аудита

### 1.1. Frontend: Интеграции и Типизация
🚨 **Критическое нарушение:** В проекте присутствуют 25 ошибок `eslint` и `tsc`, связанных с использованием типа `any`. Это прямо нарушает правило `Strict Typing` из технической спецификации B2B Ecosystem.
- Проблемы найдены в `api/accountsApi.ts`, `api/catalogApi.ts`, `hooks/useAccounts.ts` и в UI-компонентах админ-панели (`AdminDashboard.tsx`, `NomenclatureSlidePanel.tsx` и др.).
- Отсутствуют интерфейсы или они не синхронизированы с Django DRF сериализаторами.

### 1.2. Frontend: Бизнес-логика фильтрации (Хардкод / TODO)
⚠️ **Средний приоритет:** В компоненте `DomainAdaptiveSidebar.tsx` присутствует комментарий-заглушка:
`// TODO: Backend should support domain_type filter for categories`.
Из-за этого боковой фильтр Каталога загружает **все** категории для любого домена, нарушая UX (Domain-Adaptive).

### 1.3. Backend: Архитектура БД и Бизнес-логика
⚠️ **Высокий приоритет:** В модели `Category` (приложение `catalog`) отсутствует связь с `DomainType`. 
Также в модели `Product` отсутствует строгая валидация (метод `clean()`), которая бы блокировала сохранение товара домена `RAILWAY_MACHINERY` без указания `EquipmentGroup`. Это грозит "загрязнением" БД ("database chaos", запрещенного правилом *Domain-Driven Taxonomy*).

### 1.4. Backend / Инфраструктура
✅ **Исправлено в рамках текущей сессии:** 
- Устранены хардкоды в `docker-compose.yml` и конфигурациях Nginx. Отработан корректный роутинг SPA для React (добавлен `try_files` в nginx).
- Выполнена оптимизация `getProductsCount`, убран хардкод счетчика "4.2k+" на витрине.
- Разрешены PermissionErrors для Volumes при запуске non-root воркера в Docker.

### 1.5. UI/UX и Django Admin
✅ **Полное соответствие:** 
- Цветовая палитра (`slate-900`, `blue-600`) во фронтенде полностью соответствует бренд-буку RailTech.
- Django Admin (Unfold) настроен корректно (в `settings.py`), иконки `lucide/material` прописаны, Dashboard Callback и структура меню (Справочники, Каталог, CRM) соответствуют UX Brief.

---

## 2. План Рефакторинга (Refactoring Plan)

### Фаза 1: Устранение хардкода и TypeScript долга (Frontend)
1. **Строгая Типизация API:** Заменить все вхождения `any` в `accountsApi.ts` и `catalogApi.ts` на строгие DTO (Data Transfer Objects), зеркально соответствующие DRF Сериализаторам.
2. **Типизация Компонентов:** Описать `Props` интерфейсы для компонентов (`AdminDashboard`, `NomenclatureSlidePanel`, `DealSplitView`).

### Фаза 2: Валидация Domain-Driven Taxonomy (Backend)
1. **Обновление БД:** Добавить поле `domain_type = models.ForeignKey(DomainType)` в модель `Category` (возможна поддержка `null=True`, но для ЖД товаров домен обязателен).
2. **REST API Фильтрация:** В `CategoryViewSet` включить `DjangoFilterBackend` и добавить `filterset_fields = ['domain_type']`.
3. **Строгая валидация Django:** Добавить метод `clean()` внутри `Product`, который будет выбрасывать `ValidationError`, если `domain_type == 'RAILWAY_MACHINERY'`, а поле `equipment_groups` пустое.

### Фаза 3: Обновление Frontend Фильтров
1. Подключить новый фильтр в хук `useCategories({ domain_type: activeDomain })`.
2. Убрать отключенный `// TODO` фильтр в `DomainAdaptiveSidebar.tsx`.

### Фаза 4: Синхронизация документации
1. Внести свежие изменения архитектуры в `Docs/Technical_Specification.md` и `Docs/Business_Logic.md`.
