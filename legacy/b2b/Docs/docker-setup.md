# RailTech B2B SaaS — Docker Infrastructure Guide

**Актуальность:** 2026-04-17.

Полное руководство по Docker-инфраструктуре. База данных — **внешняя** (Neon Cloud PostgreSQL); локально в контейнере postgres не поднимается. Для быстрого ознакомления см. [docker-quick-reference.md](docker-quick-reference.md).

---

## Quick Start

### Development

```bash
cp .env.example .env
# заполнить минимум: DATABASE_URL, DJANGO_SECRET_KEY, SUPERADMIN_PASSWORD, MINIO_SECRET_KEY

make up                  # docker compose up -d --build
make migrate             # применить миграции к Neon Cloud
make seed                # справочники
docker compose exec backend python manage.py init_superadmin
```

Сервисы будут доступны на:

- `http://localhost:5173` — Frontend (SPA)
- `http://localhost:8000` — Backend API (+ `/admin/`, `/health/`, `/api/docs/` в DEBUG)
- `http://localhost:9001` — MinIO Console (логин — из `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`)

### Production

```bash
cp .env.example .env
# установить DJANGO_DEBUG=False, продакшн CORS_ALLOWED_ORIGINS, VITE_API_URL и т. д.

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Production-стек добавляет `nginx:stable-alpine` reverse proxy (порты 80/443) и заменяет Daphne на Gunicorn + Uvicorn-workers (4 воркера, 1000 connections/worker).

---

## Архитектура

```text
                 ┌───────────────────────────────┐
                 │  nginx (только prod)          │
                 │  80/443 → reverse proxy       │
                 └──────────────┬────────────────┘
                                │
       ┌────────────┬───────────┼───────────────┬─────────────────┐
       ▼            ▼           ▼               ▼                 ▼
  frontend      backend     minio          redis (Channels)   redis-celery
  nginx:alpine  daphne/     S3 API :9000   :6379              :6379 (maps 6380)
  :80 (prod)    gunicorn    Console :9001
  :5173 (dev)   :8000
                               │
                               ▼
                       Neon Cloud PostgreSQL
                       (внешняя БД, не в compose)
                               ▲
                               │
       ┌───────────────────────┴──────────────┐
       ▼                                      ▼
 celery-worker                           celery-beat
 queues: default, pdf, imports           DatabaseScheduler
```

### Сервисы (docker-compose.yml)

| Сервис | Контейнер | Образ | Dev-порт | Назначение |
| --- | --- | --- | --- | --- |
| `backend` | railtech_backend | python:3.13-slim | 8000 | Django 5.2 + DRF + Daphne ASGI |
| `frontend` | railtech_frontend | node:22-alpine → nginx:alpine | 5173 | Vite prod-build, отданный nginx'ом |
| `redis` | railtech_redis_channels | redis:7-alpine | 6379 | WebSocket channel layer |
| `redis-celery` | railtech_redis_celery | redis:7-alpine | 6380 (host) → 6379 (container) | Celery broker + result backend |
| `minio` | railtech_minio | minio/minio | 9000/9001 | S3-совместимое хранилище |
| `minio-init` | railtech_minio_init | minio/mc | — | Создание бакетов (exit 0 после успеха) |
| `celery-worker` | railtech_celery_worker | python:3.13-slim | — | `celery -A core worker -Q default,pdf,imports` |
| `celery-beat` | railtech_celery_beat | python:3.13-slim | — | `celery -A core beat --scheduler django_celery_beat.schedulers:DatabaseScheduler` |

### Prod-overrides (docker-compose.prod.yml)

- **Добавляется:** `nginx` (nginx:stable-alpine, порты 80/443, SSL-ready).
- **backend:** `gunicorn --worker-class=uvicorn.workers.UvicornWorker --workers=4 --worker-connections=1000 --max-requests=1000 --max-requests-jitter=100 --timeout=120`.
- **frontend:** immutable build без volume-mount.
- **Все сервисы:** `restart: always`, отдельные volumes `minio_data_prod`, `backend_static_prod`, `backend_media_prod`, `nginx_cache`.
- **celery-worker:** resource limits `2 CPU / 2 GB`, reservations `1 CPU / 1 GB`.

### MinIO-бакеты

| Бакет | Доступ | Содержимое |
| --- | --- | --- |
| `railtech-public` | anonymous get enabled | Product images, company logos, avatars |
| `railtech-private` | presigned URLs (15 мин по умолчанию) | KYC-документы, PDF КП, attachments |
| `railtech-temp` | presigned URLs | Временные файлы, Excel uploads |

Создаются одноразово контейнером `minio-init` при первом `docker compose up`.

---

## Hot reload

| Компонент | Поведение |
| --- | --- |
| **backend** | Автоматический reload. Volume `./backend:/app`, Daphne перечитывает код при изменениях. |
| **celery-worker / celery-beat** | Требуют `docker compose restart celery-worker celery-beat` после изменений кода. |
| **frontend** | Prod-build через nginx — не hot. Пересобрать: `docker compose up -d --build frontend`. Если нужен Vite dev-server с HMR — запускать `npm run dev` локально (вне контейнера). |

---

## Окружение

Полный список переменных — [.env.example](../.env.example). Ключевые:

```text
# База (один из двух вариантов)
DATABASE_URL=postgresql://user:pass@endpoint.neon.tech/neondb?sslmode=require
# или fallback
POSTGRES_DB/USER/PASSWORD/HOST/PORT

# Django
DJANGO_SECRET_KEY, DJANGO_DEBUG, ALLOWED_HOSTS
CORS_ALLOWED_ORIGINS, CSRF_TRUSTED_ORIGINS

# JWT
JWT_ACCESS_TOKEN_LIFETIME_MINUTES=30
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7
JWT_ROTATE_REFRESH_TOKENS=True

# Redis / Celery
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis-celery:6379/0
CELERY_RESULT_BACKEND=redis://:${REDIS_PASSWORD}@redis-celery:6379/0

# Channels
CHANNEL_LAYERS_HOST=redis, CHANNEL_LAYERS_PORT=6379, CHANNEL_LAYERS_DB=0

# MinIO
MINIO_ENDPOINT=http://minio:9000
MINIO_ACCESS_KEY=railtech
MINIO_SECRET_KEY=...
MINIO_PUBLIC_BUCKET=railtech-public
MINIO_PRIVATE_BUCKET=railtech-private
MINIO_TEMP_BUCKET=railtech-temp

# Frontend (build-time)
VITE_API_URL=http://localhost:8000   # prod: https://api.railtech.uz или /api
VITE_WS_URL=ws://localhost:8000/ws   # prod: wss://crm.railtech.uz/ws или /ws

# Email
EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_USE_TLS
DEFAULT_FROM_EMAIL

# Init
SUPERADMIN_EMAIL=admin@railtech.uz
SUPERADMIN_PASSWORD=...
SEED_DATA_PATH=core/data/seed_data.json

# PDF
PDF_BASE_URL=http://backend:8000
```

---

## Сборка образов

### Frontend с кастомными Vite-переменными

```bash
docker compose build \
  --build-arg VITE_API_URL=https://api.railtech.uz \
  --build-arg VITE_WS_URL=wss://crm.railtech.uz/ws \
  frontend
```

Переменные `VITE_*` **бейкаются в бандл** на этапе build — `import.meta.env.*` всегда возвращает значение из build-time, поэтому менять их в рантайме нельзя.

### Backend

```bash
docker compose build backend
```

### Всё с нуля

```bash
docker compose build --no-cache
```

---

## Общие команды

### Database / Django

```bash
make migrate
make makemigrations
make createsuperuser
make seed
make collectstatic
docker compose exec backend python manage.py init_superadmin   # неинтерактивно из .env
docker compose exec backend python manage.py shell
```

### Celery

```bash
make celery-logs
docker compose exec celery-worker celery -A core inspect ping
docker compose exec celery-worker celery -A core inspect active
docker compose exec celery-worker celery -A core purge
```

### Redis

```bash
docker compose exec redis redis-cli           # Channels (6379)
docker compose exec redis-celery redis-cli    # Celery broker
```

### MinIO

```bash
open http://localhost:9001
docker compose exec minio-init mc ls railtech
docker compose exec minio-init mc mb railtech/new-bucket
```

### Health checks

```bash
docker compose ps
curl http://localhost:8000/health/
docker compose exec redis redis-cli ping
docker compose exec redis-celery redis-cli ping
docker compose exec celery-worker celery -A core inspect ping
```

---

## Production deployment

### SSL

1. Получить сертификаты (Let's Encrypt рекомендуется).
2. Положить в `nginx/ssl/`:
   - `railtech.crt` (full chain)
   - `railtech.key` (private key)
3. Раскомментировать `ssl_certificate*` директивы в `nginx/nginx.conf`.
4. Раскомментировать HSTS в `backend/core/settings.py`.
5. Перезапустить: `docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx`.

### Production checklist

- [ ] `DJANGO_DEBUG=False` в `.env`.
- [ ] Сгенерирован сильный `DJANGO_SECRET_KEY`.
- [ ] `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` заполнены.
- [ ] `DATABASE_URL` указывает на продакшн Neon branch.
- [ ] `REDIS_PASSWORD` установлен (prod).
- [ ] SMTP-credentials для email уведомлений.
- [ ] SSL-сертификаты в `nginx/ssl/`.
- [ ] `init_superadmin` выполнен на проде.
- [ ] `make collectstatic`.
- [ ] `curl https://domain.com/health` отдаёт 200.
- [ ] Backup-стратегия для Neon (автоснапшоты) и MinIO (`mc mirror`).

### Масштабирование

```bash
# Celery workers
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale celery-worker=3

# Backend (для использования с внешним балансировщиком)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale backend=2
```

---

## Networking

Внутри compose-сети `railtech` (bridge) сервисы общаются по service-name:

```text
backend:8000            → Neon Cloud (внешний интернет)
backend:8000            → redis:6379 (Channels)
backend:8000            → redis-celery:6379 (Celery)
backend:8000            → minio:9000
celery-worker           → redis-celery:6379
celery-beat             → redis-celery:6379
frontend:80             → (только через nginx в prod)
```

Prod-роутинг через nginx:

```text
Client :443   → nginx :443 (TLS termination)
              ├─ /api/    → backend :8000
              ├─ /ws/     → backend :8000 (WebSocket upgrade)
              ├─ /admin/  → backend :8000 (Django admin)
              ├─ /storage/→ minio :9000
              └─ /        → frontend :80 (SPA fallback)
```

---

## Troubleshooting

### Backend unhealthy / Connection refused к Neon

Neon free-tier засыпает. Зайти в [Neon Console](https://console.neon.tech), разбудить проект, затем:

```bash
docker compose restart backend celery-worker celery-beat
```

Пул соединений `django-db-connection-pool` кэширует мёртвые сокеты — только рестарт контейнера сбрасывает пул.

### Frontend ошибки TypeScript

```bash
docker compose logs frontend --tail 50
docker compose up -d --build --force-recreate frontend
```

### Celery не обрабатывает задачи

```bash
docker compose exec celery-worker celery -A core inspect ping
docker compose exec redis-celery redis-cli ping
make celery-logs
```

### MinIO bucket creation fails

```bash
docker compose exec minio-init mc mb railtech/railtech-public --ignore-existing
docker compose exec minio-init mc anonymous set public railtech/railtech-public
```

### WebSocket не подключается

```bash
docker compose exec redis redis-cli ping
docker compose logs backend | grep -i "websocket\|channels"
```

---

## Backup

### Neon Cloud backups

Используйте встроенные branch snapshots в Neon Console. Для ручного дампа:

```bash
docker compose exec backend bash -c "pg_dump \$DATABASE_URL --format=custom --file=/app/backup-$(date +%F).dump"
docker compose cp backend:/app/backup-*.dump ./backups/
```

### MinIO backup

```bash
docker compose exec minio-init mc mirror railtech/ /tmp/minio-backup/
```

Для автоматизации можно добавить периодический Celery-таск (Sprint 6).

---

## См. также

- [docker-quick-reference.md](docker-quick-reference.md) — краткая шпаргалка.
- [technical-specification.md](technical-specification.md) — версии библиотек.
- [master-system-document.md](master-system-document.md) — общая архитектура.
