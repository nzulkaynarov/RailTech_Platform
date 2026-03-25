# RailTech B2B Ecosystem — Аудит двух проектов и стратегия слияния

**Дата:** 24 марта 2026
**Автор:** Claude (technical audit)
**Проекты:** RailTech_B2B_Ecosystem (Backend) + RailTech_B2B_SaaS_Frontend (Frontend)

---

## 1. Общая картина

Два репозитория формируют единую B2B SaaS-платформу для поставок железнодорожного и промышленного оборудования. Backend (Django 5 + DRF + Celery + Channels) содержит ~5 450 строк Python-кода в 8 приложениях. Frontend (React 18 + TypeScript + Vite 7 + Zustand) — ~29 500 строк в 150+ файлах. Оба проекта Docker-ready с CI/CD через GitHub Actions.

---

## 2. Слабые звенья: Backend (RailTech_B2B_Ecosystem)

### 2.1 Тесты — формальные заглушки

Backend содержит тестовые файлы общим объёмом 104 строки на 6 приложений. При CI-пороге покрытия ≥30% это означает, что критическая бизнес-логика (финансовый конвейер, Smart Match, RBAC) фактически не тестируется. Файлы `master_data/tests.py` и `notifications/tests.py` содержат по 3 строки — это пустые заглушки.

**Риск:** регрессии в финансовых расчётах (Landed Cost, VAT, маржа) останутся незамеченными до продакшена.

### 2.2 Дублирование сериализаторов в catalog и master_data

В `catalog/serializers.py` определены `CurrencySerializer`, `UnitOfMeasureSerializer`, `DeliveryBasisSerializer` — и точно такие же классы есть в `master_data/serializers.py`. Это нарушает DRY и создаёт расхождение при изменении полей в одном месте без обновления другого.

### 2.3 Миграции — всего 11 на 30+ моделей

Для проекта на стадии активной разработки 11 миграций говорит о том, что схема менялась путём пересоздания базы, а не эволюционных миграций. При работе команды из нескольких человек это приведёт к конфликтам миграций.

### 2.4 Отсутствие .env.example

Хотя CLAUDE.md требует поддерживать `.env.example`, файл отсутствует. Новый разработчик не знает, какие переменные нужны для запуска (DATABASE_URL, REDIS_URL, SECRET_KEY, CORS origins и т.д.).

### 2.5 Sourcing — минимальная реализация

Приложение `sourcing` содержит всего 86 строк моделей. Smart Match — ключевая бизнес-фича по спецификации GEMINI.md — реализована минимально. Нет видимой логики fuzzy matching, нет обработки синонимов, нет весовых коэффициентов для сопоставления.

### 2.6 Нет API-версионирования на уровне приложения

URL-пространство использует `/api/v1/`, но нет механизма для поддержки v2 при изменении контрактов. При наличии внешних клиентов API это станет проблемой.

### 2.7 WebSocket consumers — нет reconnection и heartbeat

`crm/consumers.py` реализует WebSocket-чат для сделок, но отсутствует серверный heartbeat/ping для обнаружения «мёртвых» подключений.

---

## 3. Слабые звенья: Frontend (RailTech_B2B_SaaS_Frontend)

### 3.1 Полное отсутствие тестов

Нет ни одного тестового файла. Нет Vitest, нет React Testing Library, нет Playwright/Cypress. Качество кода держится исключительно на TypeScript strict mode и ESLint.

**Риск:** любой рефакторинг компонентов (особенно QuoteBuilderGrid, DealSplitView) может сломать UX без обнаружения.

### 3.2 Нарушение правила «финансы — только на сервере»

Файл `src/utils/decimal.ts` содержит функции `calculateLineTotal()` и `calculateVAT()`. Это прямое нарушение CLAUDE.md: *«Keep ALL financial calculations server-side (Django backend only)»*. Даже если эти функции используются только для preview, они создают риск рассогласования с серверными расчётами.

### 3.3 State-based routing вместо React Router

`react-router-dom@7.13.1` установлен, но не используется. Навигация реализована через `useState<Page>` с дискриминированным объединением 22+ типов страниц. Это делает невозможными: deep linking, browser back/forward, URL sharing, code splitting по маршрутам, SSR/SSG в будущем.

### 3.4 PlaceholderPages.tsx — 1 434 строки заглушек

Файл содержит 22+ компонентов-заглушек (SourcingRequestsPage, DealsPage, QuotesPage, AnalyticsPage и др.). Это говорит о том, что значительная часть функционала ещё не реализована, хотя структура API и хуков уже готова.

### 3.5 flowStore.ts — 508 строк хардкод-данных

Демо-данные для B2B procurement flow вшиты прямо в Zustand store. Это затрудняет тестирование, увеличивает бандл и смешивает mock-данные с production-кодом.

### 3.6 Два toast-библиотеки одновременно

Установлены и `sonner@2.0.7`, и `react-hot-toast@2.6.0`. Использование двух библиотек для одной задачи ведёт к несогласованному UX уведомлений.

### 3.7 WebSocket — нет reconnection

`ContextualChat.tsx` использует WebSocket напрямую без retry/reconnection логики. При потере сети чат «умирает» без уведомления пользователя.

### 3.8 Отсутствие .env.example

Аналогично бэкенду — нет документации переменных `VITE_API_URL`, `VITE_WS_URL` для локальной разработки.

---

## 4. Проблемы на стыке двух проектов

### 4.1 Несогласованность типов (Serializer ↔ Interface)

GEMINI.md требует: *«All Frontend interfaces must strictly match DRF serializers»*. Текущее состояние:

| Backend Serializer | Frontend Interface | Статус |
|---|---|---|
| ProductSerializer (15+ полей) | Product (catalogApi.ts) | Частичное совпадение — нет верификации |
| QuoteItemSerializer | QuoteItem (crmApi.ts) | Поля frozen_* не видны во frontend |
| CompanySerializer | Company (accountsApi.ts) | Поля KYC статусов могут расходиться |
| SupplierOfferSerializer | Нет интерфейса | Отсутствует на фронте |
| ActivityLogSerializer | ActivityLog (crmApi.ts) | Не верифицировано |
| LeadSerializer | Lead (crmApi.ts) | Не верифицировано |

Нет автоматической генерации TypeScript-типов из DRF serializers (drf-spectacular → openapi → openapi-typescript).

### 4.2 Два раздельных Docker-стека без общего docker-compose

Backend имеет `docker-compose.yml` с 5 сервисами (postgres, redis, web, celery, beat), Frontend — отдельный Dockerfile с nginx. Нет единого `docker-compose.yml` для поднятия full-stack в один `docker-compose up`.

### 4.3 Разные Git-истории, разные CI-пайплайны

CI backend проверяет flake8 + pytest. CI frontend проверяет tsc + eslint + vite build. Но нет интеграционных тестов, которые проверяют API-контракт между двумя проектами.

### 4.4 RBAC: дублирование логики

Backend определяет роли через `SystemRole` (ADMIN, MANAGER, CLIENT, GUEST). Frontend хранит свой маппинг в `authStore.ts` (MANAGER → SALES_MANAGER). Нет единого источника правды для RBAC-правил.

---

## 5. Стратегия слияния: Monorepo

### 5.1 Почему monorepo

Два отдельных репозитория для одного продукта с одной командой создают трение: нет атомарных коммитов (изменил API на бэке → должен обновить фронт), нет общих типов, нет общего CI. Monorepo решает все три проблемы.

### 5.2 Целевая структура

```
railtech/
├── .github/
│   └── workflows/
│       ├── ci-backend.yml          # Триггер: changes in backend/**
│       ├── ci-frontend.yml         # Триггер: changes in frontend/**
│       ├── ci-integration.yml      # Триггер: changes in either
│       └── deploy.yml
├── backend/
│   ├── accounts/
│   ├── catalog/
│   ├── crm/
│   ├── sourcing/
│   ├── notifications/
│   ├── master_data/
│   ├── core/
│   ├── manage.py
│   ├── requirements/
│   │   ├── base.txt
│   │   ├── dev.txt
│   │   └── prod.txt
│   ├── Dockerfile
│   └── pytest.ini
├── frontend/
│   ├── src/
│   ├── package.json
│   ├── vite.config.ts
│   ├── Dockerfile
│   └── tsconfig.json
├── shared/
│   └── api-schema/               # OpenAPI spec (auto-generated)
│       ├── schema.yaml
│       └── generated-types.ts     # Auto-generated TS types
├── docker-compose.yml             # Full-stack: postgres + redis + backend + celery + frontend
├── docker-compose.dev.yml         # Development overrides
├── .env.example                   # Все переменные для обоих проектов
├── Makefile                       # make dev, make test, make lint, make types
├── CLAUDE.md                      # Единый для monorepo
└── GEMINI.md                      # Спецификация продукта
```

### 5.3 Дорожная карта слияния

**Фаза 0 — Подготовка (1–2 дня)**

Создать monorepo и перенести оба проекта с сохранением git-истории (`git subtree add` или `git filter-repo`). Создать единый `.env.example`. Написать `docker-compose.yml` для full-stack.

**Фаза 1 — Контракт типов (3–5 дней)**

Установить `drf-spectacular` на бэке для генерации OpenAPI 3.1 спецификации. Настроить `openapi-typescript` для автогенерации TypeScript-интерфейсов из `schema.yaml`. Заменить все ручные интерфейсы в `src/api/*.ts` на сгенерированные. Добавить CI-шаг: `make check-types` — сравнение сгенерированных типов с текущими.

**Фаза 2 — Устранение слабых звеньев (1–2 недели)**

На бэке: написать тесты для `QuoteCalculationService` (финансовый конвейер), Smart Match, RBAC-фильтрации. Устранить дублирование сериализаторов catalog/master_data. Добавить WebSocket heartbeat.

На фронте: удалить `calculateVAT()` и `calculateLineTotal()` из `decimal.ts`. Внедрить React Router v7 вместо state-based routing. Удалить `react-hot-toast` (оставить `sonner`). Вынести демо-данные из `flowStore.ts` в `src/data/`. Настроить Vitest + React Testing Library.

**Фаза 3 — Интеграционное тестирование (1 неделя)**

Написать contract tests: бэкенд-ответы проверяются против OpenAPI-схемы. Добавить Playwright E2E тесты для критических путей: авторизация → каталог → создание сделки → квотирование → согласование.

**Фаза 4 — Production-readiness (1 неделя)**

Настроить Sentry (backend + frontend). Добавить WebSocket reconnection с exponential backoff на фронте. Добавить health check endpoints. Настроить мониторинг (Web Vitals, Celery task latency).

---

## 6. Матрица приоритетов

| Задача | Критичность | Усилие | ROI |
|---|---|---|---|
| Тесты финансового конвейера | Критическая | Среднее | Очень высокий |
| Убрать фронтенд-расчёты (decimal.ts) | Критическая | Низкое | Высокий |
| Автогенерация типов (OpenAPI → TS) | Высокая | Среднее | Очень высокий |
| React Router миграция | Высокая | Высокое | Высокий |
| Единый docker-compose | Высокая | Низкое | Высокий |
| Удаление дублей сериализаторов | Средняя | Низкое | Средний |
| WebSocket reconnection | Средняя | Низкое | Средний |
| E2E тесты (Playwright) | Средняя | Высокое | Высокий |
| Smart Match улучшения | Средняя | Высокое | Высокий |
| Vitest на фронте | Средняя | Среднее | Средний |
| Удаление react-hot-toast | Низкая | Низкое | Низкий |

---

## 7. Заключение

Оба проекта архитектурно зрелые: domain-driven design, строгая типизация, Decimal для финансов, JWT + RBAC, production-ready Docker. Главные системные риски — отсутствие тестов (обе стороны), нарушение контракта «финансы только на сервере», и отсутствие механизма синхронизации типов между Django serializers и TypeScript interfaces. Слияние в monorepo с автогенерацией типов и интеграционными тестами устранит все три корневые проблемы.
