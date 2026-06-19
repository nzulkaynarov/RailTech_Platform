# RailTech B2B SaaS Platform

B2B маркетплейс и CRM для ж/д оборудования (Узбекистан).
Django 5.2 + React 18 + TypeScript, полностью в Docker.

**Актуальность документации:** 2026-04-17

---

## Требования

- **Docker Desktop** (или Docker Engine + Docker Compose v2)
- **Git**
- **Make** (предустановлен на macOS/Linux, на Windows — через WSL2)
- Ничего внешнего для БД не нужно — локальная PostgreSQL поднимается в Docker автоматически

> **Локальная разработка:** `docker-compose.override.yml` (gitignored, подхватывается `make up`) поднимает контейнер `db` (postgres:17), backend ходит в него как `db:5432`. `DATABASE_URL` для локалки уже стоит в `.env.example`/`.env`.
> **Продакшн:** PostgreSQL 17 на отдельном DB-VPS (приватная сеть WireGuard, `sslmode=require`); прод-`DATABASE_URL` хранится только в GitHub Actions secret. Neon Cloud выведен из эксплуатации (2026-06-19).

---

## Первый запуск (с нуля)

### 1. Клонировать репозиторий

```bash
git clone git@github.com:nzulkaynarov/RailTech_SaaS_B2B.git
cd RailTech_SaaS_B2B
```

### 2. Создать файл окружения

```bash
cp .env.example .env
```

Открыть `.env` и заполнить **обязательные** переменные:

| Переменная | Что указать | Где взять |
|---|---|---|
| `DATABASE_URL` | Локально — `postgresql://railtech:railtech@db:5432/railtech?sslmode=disable` (локальный Docker-контейнер `db`). Прод — в GitHub secret | Локальное значение уже в `.env.example` |
| `DJANGO_SECRET_KEY` | Секретный ключ Django | Сгенерировать командой ниже |
| `SUPERADMIN_EMAIL` | Email суперадмина | По умолчанию `admin@railtech.uz` |
| `SUPERADMIN_PASSWORD` | Пароль суперадмина | Задать надёжный пароль |
| `MINIO_SECRET_KEY` | Пароль MinIO | Любой пароль (только для локального хранилища) |

Генерация секретного ключа Django:

```bash
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Остальные переменные имеют рабочие значения по умолчанию. Полный список с описанием: [.env.example](.env.example).

### 3. Поднять все сервисы

```bash
make up
```

Дождись завершения сборки (~1-3 мин при первом запуске). Это соберёт и запустит 8 контейнеров.

### 4. Применить миграции

```bash
make migrate
```

### 5. Загрузить справочные данные

```bash
make seed
```

Загружает в БД: валюты, страны, единицы измерения, стадии сделок, статусы, роли, типы компаний и другие справочники из `seed_data.json`.

### 6. Создать суперадмина

```bash
docker compose exec backend python manage.py init_superadmin
```

Команда создаст (или обновит) суперпользователя с email/паролем из `.env` (`SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD`). Аккаунт будет `is_active=True`, `is_staff=True`, `is_superuser=True`.

### 7. Проверить, что всё работает

```bash
# Статус всех контейнеров
docker compose ps

# Здоровье бэкенда (должно вернуть {"status": "healthy", "database": "up"})
curl http://localhost:8000/health/

# Redis Channels
docker compose exec redis redis-cli ping

# Redis Celery
docker compose exec redis-celery redis-cli ping

# Celery Worker
docker compose exec celery-worker celery -A core inspect ping
```

### 8. Открыть в браузере

| Сервис | URL | Описание |
|---|---|---|
| Frontend (SPA) | http://localhost:5173 | Основное приложение |
| Backend API | http://localhost:8000/api/v1/ | REST API |
| Swagger UI | http://localhost:8000/api/docs/ | Интерактивная документация API |
| ReDoc | http://localhost:8000/api/redoc/ | API-документация (read-only) |
| Django Admin | http://localhost:8000/admin/ | Админка (Unfold UI) |
| MinIO Console | http://localhost:9001 | Управление файлами |
| Health Check | http://localhost:8000/health/ | Статус бэкенда и БД |

Логин в Django Admin и Frontend: email/пароль из `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` в `.env`.

Логин в MinIO Console: `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` из `.env`.

---

## Сервисы в Docker

| Контейнер | Образ | Порт | Назначение |
|---|---|---|---|
| `railtech_backend` | python:3.13-slim | 8000 | Django + Daphne (ASGI), REST API, WebSocket |
| `railtech_frontend` | node:22 → nginx | 5173 | React SPA (production-сборка через nginx) |
| `railtech_redis_channels` | redis:7-alpine | 6379 | Django Channels (WebSocket) |
| `railtech_redis_celery` | redis:7-alpine | 6380 | Celery broker + результаты задач |
| `railtech_minio` | minio/minio | 9000, 9001 | S3-совместимое хранилище файлов |
| `railtech_minio_init` | minio/mc | — | Автосоздание бакетов (разовый, Exited) |
| `railtech_celery_worker` | python:3.13-slim | — | Асинхронные задачи: импорт Excel, генерация PDF, архивирование чата |
| `railtech_celery_beat` | python:3.13-slim | — | Планировщик периодических задач (DatabaseScheduler) |

> Локально PostgreSQL поднимается контейнером `railtech_db` (postgres:17) через `docker-compose.override.yml`. На продакшне БД внешняя — PostgreSQL 17 на отдельном DB-VPS (приватная сеть), `docker-compose.override.yml` там не загружается.
> На продакшне через `docker-compose.prod.yml` добавляется контейнер `railtech_nginx` (nginx:stable-alpine, порты 80/443).

---

## Повседневные команды

### Docker

```bash
make up                  # Собрать и запустить все контейнеры
make down                # Остановить все контейнеры
make logs                # Логи всех сервисов (follow)
make shell               # bash внутри backend-контейнера
make frontend-shell      # bash внутри frontend-контейнера
make clean               # Удалить всё: контейнеры, volumes, кэш (ОСТОРОЖНО)
```

### База данных

```bash
make migrate             # Применить миграции
make makemigrations      # Создать новые миграции
make seed                # Загрузить справочные данные
make createsuperuser     # Создать суперпользователя (интерактивный ввод)
```

Создание суперадмина из `.env` (неинтерактивно):

```bash
docker compose exec backend python manage.py init_superadmin
```

### Тестирование

```bash
make test                # Запустить все тесты (pytest)
make test-backend        # Тесты бэкенда с coverage
make test-frontend       # Тесты фронтенда (vitest)
```

### Линтинг и форматирование

```bash
make lint                # Все линтеры (flake8 + black + isort + eslint)
make format              # Автоформатирование (black + isort)
make security            # Аудит зависимостей (pip audit + npm audit)
```

### Celery и статика

```bash
make celery-logs         # Логи Celery worker
make collectstatic       # Собрать статику Django
```

---

## Горячая перезагрузка (hot reload)

| Компонент | Поведение |
|---|---|
| **Backend** | Автоматически. Volume mount `./backend:/app` — Daphne перезагружает при изменениях |
| **Frontend** | Требует пересборку. Фронтенд — production build (Vite → nginx), НЕ dev-сервер |
| **Celery Worker** | Требует рестарт. `docker compose restart celery-worker` |

Пересборка фронтенда:

```bash
docker compose up -d --build frontend
```

---

## Регистрация нового пользователя

1. Зарегистрироваться через http://localhost:5173/register
2. Ссылка для установки пароля придёт **в логи backend-контейнера** (в dev-режиме email не отправляется):

   ```bash
   docker compose logs backend | grep setup-password
   ```

3. Перейти по ссылке `/setup-password?uid=...&token=...`, задать пароль
4. Подтвердить KYC компании: Django Admin → Компании → выбрать → действие "Подтвердить KYC (L2)"
5. Войти в систему

---

## Продакшн-деплой

### Отличия от локальной разработки

| Параметр | Локально | Продакшн |
|---|---|---|
| `DJANGO_DEBUG` | `True` | `False` (обязательно) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | `https://railtech.uz,...` |
| `VITE_API_URL` | `http://localhost:8000` | `https://api.railtech.uz` или пустая строка |
| `VITE_WS_URL` | `ws://localhost:8000/ws` | `wss://crm.railtech.uz/ws` |
| `FRONTEND_URL` | `http://localhost:5173` | `https://railtech.uz` |
| `EMAIL_HOST_PASSWORD` | Заглушка | Реальный App Password |
| SSL | Нет | Через nginx (см. `nginx/nginx.conf`) |
| Nginx | Не используется | Reverse proxy перед всеми сервисами |

### Архитектура на продакшне

```
Клиент → Nginx (SSL, rate limiting, кэш)
             ├── /           → Frontend (SPA)
             ├── /api/       → Backend (Django/Daphne)
             ├── /admin/     → Backend (Django Admin)
             ├── /ws/        → Backend (WebSocket)
             └── /storage/   → MinIO (файлы)
```

Конфигурация Nginx: [`nginx/nginx.conf`](nginx/nginx.conf).

### Шаги деплоя

1. Настроить `.env` с продакшн-значениями (см. таблицу выше)
2. Раскомментировать SSL-секцию в `nginx/nginx.conf` и указать пути к сертификатам
3. Добавить nginx-контейнер в `docker-compose.prod.yml`:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

4. Применить миграции и создать суперадмина:

```bash
make migrate
docker compose exec backend python manage.py init_superadmin
make collectstatic
```

---

## Устранение неполадок

### Backend не стартует / unhealthy

```bash
docker compose logs backend --tail 50
```

Частые причины:
- **Connection refused (локально)** — контейнер `db` ещё не готов. Проверить `docker compose ps db` / `docker compose logs db`; дождаться healthcheck.
- **Connection refused / no pg_hba entry (прод)** — DB-VPS недоступен. Проверить WireGuard и Postgres на DB-VPS, что `pg_hba.conf` пускает IP app-VPS. После — `docker compose restart backend celery-worker celery-beat`
- **OperationalError: connection pool** — пул соединений закэшировал мёртвые соединения. Решение: `docker compose restart backend`

### Суперадмин не может войти

```bash
# Проверить, существует ли аккаунт
docker compose exec backend python manage.py shell -c "
from accounts.models import CustomUser
u = CustomUser.objects.filter(email='admin@railtech.uz').first()
print(f'Found: {u}, active: {u.is_active}, staff: {u.is_staff}' if u else 'NOT FOUND')
"

# Пересоздать суперадмина
docker compose exec backend python manage.py init_superadmin
```

### Frontend не собирается (TypeScript ошибки)

```bash
# Посмотреть ошибки
docker compose logs frontend --tail 30

# Пересобрать с нуля
docker compose up -d --build frontend
```

### Celery задачи не выполняются

```bash
# Проверить, что worker жив
docker compose exec celery-worker celery -A core inspect ping

# Проверить, что Redis-брокер доступен
docker compose exec redis-celery redis-cli ping

# Посмотреть логи
make celery-logs
```

---

## Структура проекта

```
backend/                    # Django REST API
  accounts/                 # Пользователи, компании, KYC, подписки, роли
  catalog/                  # Товары (PIM), категории, группы оборудования
  crm/                      # Сделки, котировки, чат, аналитика, лиды
  sourcing/                 # Импорт Excel, асинхронные задачи
  master_data/              # Справочники: страны, валюты, единицы измерения
  notifications/            # Уведомления
  core/                     # Настройки, URL, ASGI, Celery, middleware
  */services.py             # Бизнес-логика (все приложения)

frontend/                   # React SPA
  src/api/                  # Axios клиенты (10 файлов) с JWT interceptor + refresh mutex
  src/components/           # shadcn/ui (64 компонента), Admin, Auth, Cabinet, Catalog, Dashboard, Shared, Sourcing
  src/components/Layout/    # ChatDrawer, ErrorBoundary, NotificationCenter
  src/hooks/                # React Query хуки (useAccounts, useCatalog, useCRM, useMasterData, useSystemSettings, usePageStats, use-mobile)
  src/i18n/locales/         # Переводы: ru.json, en.json
  src/layouts/              # AppShell (единственный SPA-лейаут с hash-based навигацией)
  src/pages/                # 20 страниц: Dashboard, Deals, Products, KYC, Settings, Sourcing, Analytics и др.
  src/store/                # 9 Zustand сторов (auth, user, cart, currency, domain, flow, loading, task, theme)

nginx/                      # Nginx конфиг для продакшна (SSL, rate limiting, кэш, WebSocket)
Docs/                       # Архитектура, спеки, роадмап, ADR, аудиты
```

---

## Документация

Подробная документация в папке [Docs/](Docs/):

| Файл | Содержание |
|---|---|
| `master-system-document.md` | Полный системный чертёж (топология, домены, бизнес-логика) |
| `technical-specification.md` | Технический стек, модели БД, API, CI/CD |
| `business-logic.md` | Пользовательские сценарии, KYC, Landed Cost, FSM сделок |
| `role-model.md` | Ролевая модель (5 системных + 3 workspace ролей) |
| `ROADMAP.md` | План спринтов, статус выполнения |
| `interface-architecture.md` | UI/UX архитектура, единый AppShell, дизайн-система |
| `ux-ui-brief.md` | Дизайн-концепция и требования к UI/UX |
| `architecture-diagrams.md` | Mermaid-диаграммы: FSM, KYC, Auth, Sourcing, Multi-tenancy и др. |
| `docker-setup.md` | Полное руководство по Docker-инфраструктуре |
| `docker-quick-reference.md` | Шпаргалка по командам docker compose |
| `websocket-messages.md` | Спецификация WebSocket-сообщений (ChatConsumer) |
| `audit-checklist.md` | Чеклист аудита (апрель 2026) |
| `ui-audit-2026-04-07.md` | UI/UX аудит с планом исправлений |
| `security-audit-2026-03-20.md` | Аудит безопасности Sprint 0 |
| `adr/0001-admin-separation.md` | ADR: разделение Django Unfold и React Admin |

---

## Лицензия

Проприетарное ПО. Все права защищены.
