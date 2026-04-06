---
title: Техническое задание (ТЗ) — RailTech B2B Ecosystem
project: RailTech B2B Ecosystem
type: technical-specification
version: 5.0 (Enterprise)
status: Final Approved
tags: [django, react, postgresql, celery, ddd, architecture, rbac, channels, websockets]
date: 2026-03-10
---

# Техническая спецификация: Backend, Frontend и Архитектура БД

## 1. Технологический стек
### 1.1. Backend (API & Core)
- **Язык:** Python 3.11+
- **Фреймворк:** Django 4.2+ / 5.x + Django REST Framework (DRF)
- **База данных:** PostgreSQL 15+ (Расширения: `pg_trgm` для нечеткого поиска, `JSONB` для гибких атрибутов)
- **Очереди задач:** Celery + Redis (Парсинг спецификаций сделок и Массовая загрузка каталога номенклатуры через `pandas` в фоне)
- **Real-time:** `daphne`, Django Channels (WebSockets) + Redis Channel Layer для мгновенных чатов; Поллинг для Центра уведомлений (Admin Panel).
- **Генерация документов:** `WeasyPrint` для рендеринга PDF из HTML-шаблонов.
- **Архитектурный паттерн:** **Service Layer** (слой `services.py`) для изоляции бизнес-логики от контроллеров (Views).

### 1.2. Frontend (SPA)
- **Библиотеки:** React 18+, TypeScript
- **Стилизация:** Tailwind CSS
- **State Management:** Zustand
    - `authStore.ts`: Управление сессией и правами доступа.
    - `themeStore.ts`: Управление темой оформления.
    - `domainStore.ts`: Управление активным контекстом каталога (Домены).
    - `taskStore.ts`: Мониторинг фоновых задач (Excel импорт/экспорт).
- **Компоненты:** Lucide React, нативные WebSockets для чата.

---

## 2. Архитектура БД (Domain-Driven Taxonomy)

### 2.1. Глобальные Домены
Товары (`Product`) строго делятся по полю `domain_type` (TextChoices):
1.  **RAILWAY_MACHINERY:** Требует привязки к иерархическим справочникам техники.
2.  **GENERAL_GOODS:** Общие промышленные товары (плоский каталог, гибкие `specifications`).
3.  **SERVICES:** Услуги (транспортные, ремонтные). Использует нестандартные единицы измерения (`uom`).

### 2.2. Иерархия техники (для домена RAILWAY)
Реализована через `EquipmentGroup` со связью на саму себя (рекурсивная иерархия Тип $\rightarrow$ Серия):
- Поля `equipment_type`, `series`, и `parent` (`ForeignKey('self')`).

### 2.3. Ключевые ER-модели и Финансы
1. **`Company`**: `inn` (Unique Index), `verification_status` (L1/L2/L3).
2. **`Product`**: `sku`, `domain_type`, `base_price`, `currency` (FK), `uom` (FK единица измерения).
3. **`Deal`**: `client`, `manager`, `status`. Изоляция доступа на уровне `get_queryset`.
4. **`DealItem`**: 
    - `product` (Nullable для нераспознанных из Excel).
    - Базовые поля: `quantity`, `fca_base_price`, `logistics_dap`, `customs_duty`, `margin_percent`.
    - **Physical Computed fields (DecimalField):** `landed_cost`, `final_price_excl_vat`, `total_price_incl_vat`. Вычисляются через Service Layer перед сохранением.
5. **`Message`**: `deal`, `sender`, `text`, `timestamp`. Маршрутизация через Channels.
6. **`Notification`**: `user`, `title`, `message`, `type`, `is_read`. Системные и пользовательские алерты.
7. **`User` (Custom)**: `role`, `workspace_role`, `company` (FK), `company_id` (Write-only field in Serializer for invitation logic).

---

## 3. Ролевая модель, Workspaces и Безопасность
Авторизация: JWT. Глобальная политика: `IsAuthenticated`.

### 3.1. Workspace Roles (Внутри одной Company)
| Роль | Права |
| :--- | :--- |
| **OWNER** | Полный контроль над Workspace, приглашение сотрудников, управление счетами. |
| **ACCOUNTANT** | Просмотр и выгрузка финансовых документов, работа со статусами оплаты. |
| **MANAGER** | Создание сделок, импорт Excel-спецификаций, чат с менеджерами RailTech. |

### 3.2. Системные роли (RBAC)
Автоматическая изоляция QuerySet на уровне `get_queryset`.

| Роль | Права доступа (Изоляция QuerySet) |
| :--- | :--- |
| **GUEST** | Доступ к публичному каталогу, `Deal` (лимит: 1, статус Draft). Цены скрыты. |
| **CLIENT** | Управление строго своими сделками (`filter(client=user)`). Просмотр цен, принятие КП (`QUOTE_SENT`), чаты (WS). |
| **SALES_MANAGER / ACCOUNT_MANAGER** | Доступ к назначенным им сделкам или нераспределенным. Парсинг Excel, маппинг в Sourcing Hub, Калькулятор КП. |
| **ADMIN** | Полный доступ ко всем данным. Глобальная аналитика (Conversion, Target Margin, Sourcing Speed). |

---

## 4. Алгоритмы и Интеграции

### 4.1. Domain-Aware Smart Match (Celery + pg_trgm)
**Endpoint:** `POST /api/v1/crm/deals/{id}/import_excel/`
1. **Парсинг:** Celery-воркер `process_excel_import` читает Excel через `pandas` в фоновом режиме.
2. **Авто-сопоставление:** Функция `smart_match_product` использует `TrigramSimilarity` (порог `> 0.3`) по полю `name`.
3. **Ручной Sourcing:** Несопоставленные позиции остаются с `product=null`. Менеджер мапит их вручную через эндпоинт `PUT /api/v1/crm/deal-items/{id}/` в интерфейсе Sourcing Hub.

### 4.2. Экспорт PDF
**Endpoint:** `GET /api/v1/crm/deals/{id}/export_pdf/`
Использует `WeasyPrint` для генерации коммерческих предложений.

### 4.3. Коммерческая Аналитика
**Endpoint:** `GET /api/v1/crm/analytics/`
Возвращает агрегированные метрики:
- `pipeline_by_status`: Распределение сделок по воронке.
- `sourcing_backlog`: Количество позиций с `product=null`.
- `conversion_rate`: % успешно закрытых сделок.
- `total_pipeline_value`: Суммарная стоимость активного пайплайна.


---

## 5. Инфраструктура и Развертывание

### 5.1. Контейнеризация (Docker)
Система разворачивается в виде набора микросервисов:
- **`backend`**: Django/Daphne (Runtime: python:3.11-slim).
- **`frontend`**: React SPA (Served by nginx:alpine с поддержкой SPA-маршрутизации через `try_files`).
- **`celery_worker / beat`**: Фоновые задачи и расписание (запускается от имени non-root пользователя `appuser`).
- **`redis`**: Брокер задач и Channel Layer.
- **`db`**: PostgreSQL 15.
- **`nginx`**: Глобальный шлюз (SSL, Gzip, WebSocket Proxy, проксирование на React-контейнер).

### 5.2. CI/CD Pipeline
Автоматизация через GitHub Actions:
1.  **Stage 1 (Quality):** Flake8 (Backend), ESLint & TSC (Frontend).
2.  **Stage 2 (Verify):** Django tests с изолированными БД и Redis.
3.  **Stage 3 (Build):** Сборка Docker образов с передачей build-args (`VITE_API_URL`).
4.  **Stage 4 (Deploy):** Ротация контейнеров на production-сервере через SSH.

### 5.3. Безопасность окружения
Все чувствительные данные вынесены в секреты GitHub и подставляются в `.env` файл во время деплоя. Прямой доступ к базе данных Neon ограничен сетевыми правилами.
