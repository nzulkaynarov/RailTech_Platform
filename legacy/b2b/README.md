# RailTech B2B SaaS Platform

B2B маркетплейс и CRM для ж/д оборудования (Узбекистан).
Django 5.1 + React 18 + TypeScript, полностью в Docker.

## Требования

- **Docker Desktop** (или Docker Engine + Docker Compose v2)
- **Git**
- Доступ к удалённой БД (Neon Cloud PostgreSQL) — `DATABASE_URL` от администратора

> Локальной БД нет. База всегда удалённая — и при разработке, и на продакшне.

## Запуск проекта

### 1. Клонировать и настроить окружение

```bash
git clone git@github.com:nzulkaynarov/RailTech_SaaS_B2B.git
cd RailTech_SaaS_B2B
cp .env.example .env
```

Открыть `.env` и заполнить **обязательные** переменные:

| Переменная | Что указать |
| --- | --- |
| `DATABASE_URL` | Строка подключения к Neon Cloud (получить у админа) |
| `DJANGO_SECRET_KEY` | Сгенерировать: `python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `SUPERADMIN_PASSWORD` | Пароль суперадмина (будет создан автоматически при миграции) |
| `MINIO_SECRET_KEY` | Любой пароль для локального хранилища файлов |

Остальные переменные имеют рабочие значения по умолчанию для локальной разработки.

### 2. Поднять все сервисы

```bash
make up
```

Это соберёт и запустит 7 контейнеров: backend, frontend, 2× Redis, MinIO, Celery worker, Celery beat.

### 3. Применить миграции и загрузить справочники

```bash
make migrate
make seed
```

### 4. Открыть

| Сервис | URL |
| --- | --- |
| Фронтенд | `http://localhost:5173` |
| API | `http://localhost:8000` |
| Django Admin | `http://localhost:8000/admin/` |
| MinIO Console | `http://localhost:9001` |

### Тестовые аккаунты (после seed)

| Email | Пароль | Роль |
| --- | --- | --- |
| `admin@railtech.uz` | `admin123` | Админ (суперпользователь) |
| `manager@railtech.uz` | `manager123` | Менеджер по продажам |
| `client@test.uz` | `client123` | Клиент |

## Повседневные команды

```bash
make up                  # Поднять все контейнеры (с пересборкой)
make down                # Остановить всё
make logs                # Логи всех сервисов (follow)
make shell               # bash внутри backend-контейнера
make migrate             # Применить миграции
make makemigrations      # Создать новые миграции
make seed                # Загрузить справочные данные
make test                # Запустить тесты (pytest)
make test-backend        # Тесты бэкенда с coverage
make test-frontend       # Тесты фронтенда (vitest)
make lint                # Линтеры (flake8 + black + isort + eslint)
make format              # Автоформатирование (black + isort)
make celery-logs         # Логи Celery worker
make collectstatic       # Собрать статику Django
make clean               # Снести всё: контейнеры, volumes, кэш
```

## Горячая перезагрузка (hot reload)

- **Backend:** бэкенд монтируется как volume (`./backend:/app`) — изменения применяются автоматически через Daphne
- **Frontend:** после изменений нужна пересборка контейнера.
  Причина: фронтенд — это production-сборка (Vite build), а не dev-сервер.

  ```bash
  docker compose up -d --build frontend
  ```

## Регистрация нового пользователя

1. Зарегистрироваться через `/register`
2. Ссылка для установки пароля придёт **в логи backend-контейнера** (в dev-режиме):

   ```bash
   make logs | grep setup-password
   ```

3. Перейти по ссылке `/setup-password?uid=...&token=...`, задать пароль
4. Подтвердить KYC компании: Django Admin → Компании → действие "Подтвердить KYC (L2)"
5. Войти в систему

## Структура проекта

```
backend/                 # Django REST API
  accounts/              # Пользователи, компании, KYC, роли
  catalog/               # Товары (PIM), категории, оборудование
  crm/                   # Сделки, котировки, чат, аналитика
  sourcing/              # Импорт Excel, асинхронные задачи
  master_data/           # Страны, валюты, единицы измерения
  notifications/         # Центр уведомлений
  core/                  # Настройки, URL, ASGI, Celery, middleware

frontend/                # React SPA
  src/api/               # Axios клиенты с JWT interceptor
  src/components/        # shadcn/ui компоненты
  src/hooks/             # React Query хуки (accounts, catalog, crm)
  src/i18n/locales/      # Переводы: ru.json, en.json
  src/pages/             # Страницы приложения
  src/store/             # Zustand сторы (auth, cart, theme и др.)

nginx/                   # Конфиг Nginx для продакшна
docs/                    # Архитектура, спеки, роадмап, мокапы
```

## Сервисы в Docker

| Контейнер | Порт | Назначение |
| --- | --- | --- |
| `backend` | 8000 | Django + Daphne (ASGI) |
| `frontend` | 5173 | React (nginx, prod-сборка) |
| `redis` | 6379 | Django Channels (WebSocket) |
| `redis-celery` | 6380 | Celery broker + результаты |
| `minio` | 9000, 9001 | S3-совместимое хранилище файлов |
| `celery-worker` | — | Импорт Excel, генерация PDF |
| `celery-beat` | — | Запланированные задачи |

> PostgreSQL — внешняя БД (Neon Cloud), в Docker не поднимается.

## Переменные окружения

Полный список с описанием: [.env.example](.env.example)

## Документация

Подробная документация в папке [docs/](docs/):
архитектура, бизнес-логика, ролевая модель, спринт-план, мокапы, аудит безопасности.

## Лицензия

Проприетарное ПО. Все права защищены.
