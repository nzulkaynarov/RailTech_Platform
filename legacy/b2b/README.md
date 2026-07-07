# RailTech B2B SaaS Platform

B2B маркетплейс и CRM для ж/д оборудования (Узбекистан).
Django 6.0 + React 18 + TypeScript, полностью в Docker.

**Актуальность документации:** 2026-07-06

---

## Требования

- **Docker Desktop** (или Docker Engine + Docker Compose v2)
- **Git**
- **Make** (предустановлен на macOS/Linux, на Windows — через WSL2)
- Ничего внешнего для БД не нужно — локальная PostgreSQL поднимается в Docker

> **Локальная разработка:** контейнер `db` (postgres:17) описан в `docker-compose.override.yml` — файл **gitignored**, на свежем клоне его нет, создаётся из шаблона (шаг 3 ниже). Backend ходит в него как `db:5432`.
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
| `DATABASE_URL` | Локально — `postgresql://railtech:railtech@db:5432/railtech?sslmode=disable` | Уже стоит в `.env.example` |
| `DJANGO_SECRET_KEY` | Секретный ключ Django | Сгенерировать командой ниже |
| `SUPERADMIN_EMAIL` | Email суперадмина | По умолчанию `admin@railtech.uz` |
| `SUPERADMIN_PASSWORD` | Пароль суперадмина | Задать надёжный пароль |

Генерация секретного ключа Django:

```bash
python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters + string.digits + '!%^*(-_=+)') for _ in range(50)))"
```

Для локальной разработки также рекомендуется `DJANGO_DEBUG=True` (письма печатаются в логи backend) и `CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000`.

MinIO **не нужен**: по умолчанию хранилище — FileSystemStorage (как на проде). S3 включается отдельно: `docker compose --profile with-minio up -d` + раскомментировать блок `MINIO_*` в `.env`.

Остальные переменные имеют рабочие значения по умолчанию. Полный список с описанием: [.env.example](.env.example).

### 3. Создать docker-compose.override.yml (локальная БД)

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
```

Файл добавляет контейнер `db` (postgres:17) и автоматически подхватывается `docker compose` / `make up`. Он в `.gitignore` — прод и staging его никогда не загружают (там явные `-f docker-compose.yml -f docker-compose.prod.yml`).

### 4. Поднять все сервисы

```bash
make up
```

Дождись завершения сборки (~1-3 мин; первый билд дольше). Поднимутся 7 контейнеров (без MinIO).

> **Мало памяти у Docker?** Если сборка падает с `cannot allocate memory` — собери образы последовательно: `docker compose build backend && docker compose build frontend && docker compose up -d`.

### 5. Применить миграции

```bash
make migrate
```

> `entrypoint.sh` бэкенда сам выполняет `migrate --noinput` при каждом старте контейнера, так что на свежей БД этот шаг обычно уже выполнен — команда идемпотентна. Миграции создают и все бизнес-коды справочников (стадии сделок, статусы KYC, роли) — см. IRON RULE 1 в [CLAUDE.md](CLAUDE.md).

### 6. Загрузить демо-данные (dev/demo-only)

```bash
make seed
```

Запускает `manage.py core_seed`: валюты, страны, единицы измерения, типы компаний и **тестовые пользователи** (пароль — `SEED_USER_PASSWORD` из `.env`, по умолчанию `Demo1234!`; логины — см. `backend/core/data/seed_data.json` → `test_users`).

### 7. Создать суперадмина

```bash
docker compose exec backend python manage.py init_superadmin
```

Команда создаст суперпользователя с email/паролем из `.env` (`SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD`); аккаунт будет `is_active=True`, `is_staff=True`, `is_superuser=True`. Существующий аккаунт команда **не трогает** (SEC-10) — для ротации пароля/флагов добавь `--reset-password`.

### 8. Проверить, что всё работает

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

### 9. Открыть в браузере

| Сервис | URL | Описание |
|---|---|---|
| Frontend (SPA) | http://localhost:5173 | Основное приложение |
| Backend API | http://localhost:8000/api/v1/ | REST API |
| Swagger UI | http://localhost:8000/api/docs/ | Интерактивная документация API |
| ReDoc | http://localhost:8000/api/redoc/ | API-документация (read-only) |
| Django Admin (Unfold) | http://localhost:8000/admin/ | Админка инженера платформы |
| Health Check | http://localhost:8000/health/ | Статус бэкенда и БД |
| MinIO Console | http://localhost:9001 | Только с профилем `with-minio` |

Логин в Django Admin и Frontend: email/пароль из `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` в `.env`.

---

## Сервисы в Docker

| Контейнер | Образ | Порт | Назначение |
|---|---|---|---|
| `railtech_backend` | python:3.12-slim | 8000 | Django + Daphne (ASGI), REST API, WebSocket |
| `railtech_frontend` | node:22 → nginx | 5173 | React SPA (production-сборка через nginx внутри контейнера) |
| `railtech_db` | postgres:17-alpine | 5432 | PostgreSQL — **только локально** (из override-файла) |
| `railtech_redis_channels` | redis:7-alpine | 6379 | Django Channels (WebSocket) |
| `railtech_redis_celery` | redis:7-alpine | 6380 | Celery broker + результаты задач |
| `railtech_celery_worker` | python:3.12-slim | — | Асинхронные задачи: импорт Excel, PDF, архивирование |
| `railtech_celery_beat` | python:3.12-slim | — | Планировщик периодических задач (DatabaseScheduler) |
| `railtech_minio` / `_init` | minio/minio, minio/mc | 9000, 9001 | **Опционально** — профиль `with-minio` |

Все порты проброшены только на loopback (`127.0.0.1:`). На проде БД внешняя (DB-VPS), edge — **host Caddy** (не контейнер): TLS, CSP-заголовки, X-Forwarded-For.

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
make seed                # core_seed: справочники + демо-пользователи (dev/demo-only)
make createsuperuser     # Создать суперпользователя (интерактивный ввод)
```

Создание суперадмина из `.env` (неинтерактивно):

```bash
docker compose exec backend python manage.py init_superadmin
```

### Тестирование

```bash
make test                # Backend-тесты (pytest, в контейнере)
make test-backend        # Backend-тесты с coverage
make test-frontend       # Frontend-тесты (vitest) — на машине разработчика, НЕ в контейнере
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
| **Frontend** | Требует пересборку: `docker compose up -d --build frontend` (production build, не dev-сервер) |
| **Celery** | Требует рестарт: `docker compose restart celery-worker celery-beat` — worker держит старый код в памяти. Обязательно после любых изменений моделей/миграций |

---

## Регистрация нового пользователя

1. Зарегистрироваться через http://localhost:5173/register
2. Ссылка для установки пароля придёт **в логи backend-контейнера** (при `DJANGO_DEBUG=True` email не отправляется, а печатается; каждое письмо также сохраняется в `EmailLog` — Unfold → Журнал email):

   ```bash
   docker compose logs backend | grep setup-password
   ```

3. Перейти по ссылке `/setup-password?uid=...&token=...`, задать пароль
4. Подтвердить KYC компании: войти Platform-оператором (суперадмин подходит) → SPA `#admin-kyc` (React Admin) → верифицировать L2. KYC без документов допускается (политика владельца) — потребуется предупреждение + обоснование
5. Войти в систему. Ниже KYC L2 доступны только просмотр каталога и черновики заявок (KYC-floor, ADR-0006)

---

## Продакшн-деплой

Прод разворачивается **только через GitHub Actions** — ручной деплой с ноутбука не используется.

- **Workflow:** `.github/workflows/deploy-b2b.yml`, выполняется self-hosted runner'ом на app-VPS
- **Прод-`.env` рендерится из GitHub production secrets** (heredoc в workflow) — ручные правки `.env` на сервере затираются каждым деплоем
- **Compose:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` (override-файл не участвует)
- **Edge:** host **Caddy** (TLS, CSP, rate-независимый XFF). Конфиг применяется вручную: фрагмент `deploy/caddy/b2b.railtech.uz.caddy` → `/etc/caddy/conf.d/b2b.caddy` → `caddy validate` → `systemctl reload caddy`
- **SPA** раздаётся Caddy из `/var/www/railtech-b2b`
- **БД** — DB-VPS через WireGuard; ежедневный `pg_dump` на DB-VPS (cron, 14 дней)
- **Мониторинг** — Sentry (backend `SENTRY_DSN` + SPA `VITE_SENTRY_DSN`)
- **Staging пока нет** — ветка → зелёный CI → merge в main → прод

Каталог `nginx/` — legacy-конфиг, не используется ни одним compose-файлом.

Операционные руководства: `Docs/dev/ops/` (RUNBOOK, smoke-checklist, deploy-lessons, observability, staging). Полная структура документации — `Docs/README.md`.

---

## Устранение неполадок

### Backend не стартует / unhealthy

```bash
docker compose logs backend --tail 50
```

Частые причины:
- **Connection refused (локально)** — контейнер `db` ещё не готов (`docker compose ps db`) или нет `docker-compose.override.yml` (шаг 3 первого запуска)
- **Connection refused / no pg_hba entry (прод)** — DB-VPS недоступен: проверить WireGuard, Postgres на DB-VPS, `pg_hba.conf`. После — `docker compose restart backend celery-worker celery-beat`
- **OperationalError: connection pool** — пул закэшировал мёртвые соединения: `docker compose restart backend`

### Сборка падает с `cannot allocate memory`

Docker VM не хватает памяти на параллельную сборку. Собрать последовательно:

```bash
docker compose build backend && docker compose build frontend && docker compose up -d
```

### Суперадмин не может войти

```bash
docker compose exec backend python manage.py shell -c "
from accounts.models import CustomUser
u = CustomUser.objects.filter(email='admin@railtech.uz').first()
print(f'Found: {u}, active: {u.is_active}, staff: {u.is_staff}' if u else 'NOT FOUND')
"
docker compose exec backend python manage.py init_superadmin --reset-password   # сбросить пароль/флаги (SEC-10: без флага существующий аккаунт не трогается)
```

Учти: после ≥10 неудачных попыток с разных IP аккаунт блокируется на 15 минут (login lockout, SEC-06).

### Frontend не собирается (TypeScript ошибки)

```bash
docker compose logs frontend --tail 30
docker compose up -d --build frontend
```

### Celery задачи не выполняются / падают на «несуществующей» колонке

```bash
docker compose exec celery-worker celery -A core inspect ping   # worker жив?
docker compose exec redis-celery redis-cli ping                 # брокер доступен?
make celery-logs
docker compose restart celery-worker celery-beat                # worker держит старый код
```

---

## Структура проекта

```
backend/                    # Django REST API
  accounts/                 # Пользователи, компании, KYC, подписки, entitlements, роли (Operator/Company)
  catalog/                  # Товары (PIM), категории, группы оборудования, AI-обогащение
  crm/                      # Сделки, routing по продавцам, КП, договоры, счета/акты/платежи, чат
  sourcing/                 # Импорт заявок (Excel + AI-разбор), асинхронные задачи
  master_data/              # Справочники: страны, валюты, единицы измерения
  notifications/            # Уведомления, журнал email (EmailLog)
  core/                     # Настройки, URL, ASGI, Celery, CSP, idempotency, optimistic locking
  */services/ | services.py # Бизнес-логика (пакеты в accounts и crm — см. CLAUDE.md)

frontend/                   # React SPA
  src/api/                  # Axios-клиенты с JWT interceptor + refresh mutex; schema.d.ts (генерируется)
  src/layouts/              # AppShell + PlatformAdminShell (оба — hash-навигация, без React Router)
  src/config/navigation.tsx # Единая capability-навигация (ADR-0005)
  src/components/           # ui (shadcn), Admin, Auth, Billing, CRM, Cabinet, Dashboard, Shared, Layout
  src/hooks/                # React Query хуки (useCRM, useCatalog, useCapabilities, useAdmin, ...)
  src/i18n/locales/         # Переводы: ru.json, en.json
  src/pages/                # ~40 страниц, включая 16 Admin*-страниц операторской плоскости
  src/store/                # 8 Zustand сторов (auth, user, cart, currency, domain, loading, task, theme)

deploy/caddy/               # Фрагмент прод-конфига Caddy (применяется вручную на VPS)
nginx/                      # LEGACY — не используется compose-файлами
Docs/                       # Документация: adr/, ops/, аудиты, спеки (канонический каталог в git)
```

---

## Документация

Подробная документация в папке [Docs/](Docs/):

| Файл | Содержание |
|---|---|
| `adr/0001…0006` | Действующие архитектурные решения: админ-разделение, роли, три админ-плоскости, единая навигация, wedge-loop + entitlements |
| `ROADMAP.md` | Хроника релизов + открытые треки (актуализирован 2026-07-06) |
| `ops/` | Session handoffs, оперативные роадмапы, smoke-чеклисты, deploy-lessons, observability |
| `audit-2026-07-02-security-arch-ux.md` | Последний большой аудит (security/arch/infra) со статусами находок |
| `audit-2026-07-03-ux-ui-eyes-on.md` | Eyes-on UX/UI аудит (закрыт PR #219–#229) |
| `architecture-diagrams.md` | Mermaid-диаграммы: FSM, KYC, Auth, Sourcing, Multi-tenancy |
| `websocket-messages.md` | Спецификация WebSocket-сообщений |
| `docker-setup.md` / `docker-quick-reference.md` | Docker-инфраструктура и шпаргалка |
| `master-system-document.md`, `technical-specification.md`, `business-logic.md`, `role-model.md`, `interface-architecture.md` | Системные документы ранних этапов — **частично устарели**, сверяйтесь с ADR и CLAUDE.md |

Контекст для AI-ассистентов и свод правил кодовой базы: [CLAUDE.md](CLAUDE.md).

---

## Лицензия

Проприетарное ПО. Все права защищены.
