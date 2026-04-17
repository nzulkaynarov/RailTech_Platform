# Docker Quick Reference — RailTech B2B

**Актуальность:** 2026-04-17. Полный гайд — [docker-setup.md](docker-setup.md).

> База данных — внешняя **Neon Cloud PostgreSQL**. Локального postgres в `docker-compose.yml` нет.

## Старт и стоп

```bash
# Dev (hot reload backend, prod-build frontend)
make up                                    # docker compose up -d --build
make down                                  # docker compose down
make logs                                  # follow all logs

# Prod (с nginx, gunicorn, без volume-mount)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Полная чистка (с volumes) — ОСТОРОЖНО
make clean                                 # down -v + system prune
```

## База / миграции

```bash
make migrate
make makemigrations
make seed                                  # loaddata seed_data
make createsuperuser                       # интерактивно
docker compose exec backend python manage.py init_superadmin   # из .env
docker compose exec backend python manage.py shell
```

## Логи

```bash
docker compose logs -f                     # все
docker compose logs -f backend
docker compose logs -f --tail=50 celery-worker
make celery-logs
```

## Shell / exec

```bash
make shell                                 # backend bash
make frontend-shell                        # frontend bash
docker compose exec backend python manage.py shell
docker compose exec redis redis-cli        # Channels (port 6379 inside)
docker compose exec redis-celery redis-cli # Celery broker
```

## Celery

```bash
docker compose exec celery-worker celery -A core inspect ping
docker compose exec celery-worker celery -A core inspect active
docker compose exec celery-worker celery -A core inspect stats
docker compose exec celery-worker celery -A core purge
```

## MinIO

```bash
open http://localhost:9001                 # Web Console
# Логин — значения MINIO_ACCESS_KEY / MINIO_SECRET_KEY из .env

docker compose exec minio-init mc ls railtech
docker compose exec minio-init mc mb railtech/new-bucket --ignore-existing
docker compose exec minio-init mc mirror railtech/ /tmp/minio-backup/
```

## Health checks

```bash
docker compose ps
curl http://localhost:8000/health/
docker compose exec redis redis-cli ping
docker compose exec redis-celery redis-cli ping
docker compose exec celery-worker celery -A core inspect ping
```

## Пересборка отдельного сервиса

```bash
# Frontend с кастомными Vite env (бейкается в бандл!)
docker compose build \
  --build-arg VITE_API_URL=https://api.railtech.uz \
  --build-arg VITE_WS_URL=wss://crm.railtech.uz/ws \
  frontend

docker compose build backend
docker compose up -d --build frontend       # пересобрать и перезапустить
docker compose build --no-cache             # всё с нуля
```

## Ports

| Сервис | Dev (host:container) | Prod |
| --- | --- | --- |
| Frontend | 5173 : 80 | 80/443 (через nginx) |
| Backend API | 8000 : 8000 | internal (через nginx) |
| MinIO API | 9000 : 9000 | internal |
| MinIO Console | 9001 : 9001 | internal |
| Redis (Channels) | 6379 : 6379 | internal |
| Redis (Celery) | 6380 : 6379 | internal |
| Nginx | — | 80 : 80, 443 : 443 |
| PostgreSQL | — (внешняя Neon) | — |

## Минимальный .env (для dev)

```text
DATABASE_URL=postgresql://user:pass@endpoint.neon.tech/neondb?sslmode=require
DJANGO_SECRET_KEY=<generate>
DJANGO_DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
MINIO_ACCESS_KEY=railtech
MINIO_SECRET_KEY=<strong-random>
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws
FRONTEND_URL=http://localhost:5173
SUPERADMIN_EMAIL=admin@railtech.uz
SUPERADMIN_PASSWORD=<strong-random>
```

Генерация `DJANGO_SECRET_KEY`:

```bash
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## Prod обязательные переменные

```text
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<strong-random-50chars>
DATABASE_URL=postgresql://...                     # prod Neon branch
REDIS_PASSWORD=<strong-random>
MINIO_SECRET_KEY=<strong-random>
ALLOWED_HOSTS=railtech.uz,www.railtech.uz
CORS_ALLOWED_ORIGINS=https://railtech.uz
CSRF_TRUSTED_ORIGINS=https://railtech.uz
VITE_API_URL=/api                                 # либо https://api.railtech.uz
VITE_WS_URL=/ws                                   # либо wss://crm.railtech.uz/ws
FRONTEND_URL=https://railtech.uz
EMAIL_HOST_PASSWORD=<real-app-password>
```

## Neon "Connection refused"

Neon free-tier засыпает. Разбудите проект в [Neon Console](https://console.neon.tech), затем:

```bash
docker compose restart backend celery-worker celery-beat
```

Пул `django-db-connection-pool` кэширует мёртвые соединения — рестарт необходим.

## Масштабирование

```bash
# Больше Celery worker'ов
docker compose up -d --scale celery-worker=3

# Больше backend'ов (нужен внешний балансировщик)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale backend=2
```

## Безопасность перед продом

- [ ] Все секреты в `.env` сгенерированы заново (не из `.env.example`).
- [ ] `DJANGO_DEBUG=False`.
- [ ] `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` заданы строго.
- [ ] `REDIS_PASSWORD` установлен.
- [ ] SSL-сертификаты в `nginx/ssl/`, SSL-блок в `nginx/nginx.conf` раскомментирован.
- [ ] Rate limiting zones в nginx не отключены.
- [ ] SMTP настроен для реальных email.
- [ ] `init_superadmin` выполнен.
