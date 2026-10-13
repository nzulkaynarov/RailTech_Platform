# Docker Compose Up

Запусти полный development стек с миграциями и seed-данными.

## Инструкции

### 1. Убедись, что Docker установлен

```bash
docker --version
docker compose --version

# Если не установлен:
# Mac: brew install docker docker-compose
# Linux: apt-get install docker.io docker-compose
# Windows: Download Docker Desktop
```

### 2. Проверь docker-compose.yml

```bash
# Убедись, что файл существует в root
ls -la docker-compose.yml

# Основные сервисы должны быть:
# - postgres (БД)
# - redis (cache, Celery broker)
# - backend (Django API)
# - frontend (React dev server или nginx)
# - celery (background tasks)
```

### 3. Запусти контейнеры

```bash
# Стартуй всё в фоне
docker compose up -d --build

# Или с логами в консоль (для дебага)
docker compose up --build
```

### 4. Дождись healthchecks

```bash
# Проверь статус сервисов
docker compose ps

# Пример:
# NAME              STATUS
# railtech-postgres HEALTHY
# railtech-redis    HEALTHY
# railtech-backend  HEALTHY (или STARTING)
# railtech-frontend HEALTHY (или STARTING)

# Жди, пока все будут HEALTHY
# Обычно это 30-60 секунд
```

### 5. Запусти миграции

```bash
# Если контейнер ещё работает
docker compose exec backend python manage.py migrate

# Или через docker run если контейнер не запущен
docker run --rm \
  --network railtech_default \
  -e DATABASE_URL=postgresql://user:password@postgres:5432/railtech \
  railtech-backend \
  python manage.py migrate
```

### 6. Создай superuser (admin)

```bash
docker compose exec backend python manage.py createsuperuser

# Интерактивно:
# Email: admin@railtech.com
# Password: (вводи)
# Password (again): (вводи)
```

### 7. Загрузи seed-данные (опционально)

```bash
# Если есть seed data
docker compose exec backend python manage.py loaddata core/data/seed_data.json

# Или создай через admin
# http://localhost:8000/admin/
```

### 8. Создай тестовых пользователей

```bash
docker compose exec backend python manage.py shell

# В shell:
from accounts.models import User, Company
from django.utils.timezone import now

# Создай тестовую компанию
company = Company.objects.create(
    name='Test Company',
    code='TEST',
    email='company@railtech.com'
)

# Создай пользователей для каждой роли
roles = ['GUEST', 'CLIENT', 'SALES_MANAGER', 'ACCOUNT_MANAGER', 'ADMIN']
for role in roles:
    User.objects.create_user(
        email=f'{role.lower()}@railtech.com',
        password='password123',
        first_name=role,
        company=company,
        role=role,
    )

exit()
```

## Service URLs

После запуска доступны:

| Сервис | URL | Логин |
|--------|-----|-------|
| **Backend API** | http://localhost:8000 | - |
| **API Docs** | http://localhost:8000/api/ | - |
| **Swagger UI** | http://localhost:8000/api/schema/swagger/ | - |
| **Admin Panel** | http://localhost:8000/admin/ | admin / password |
| **Frontend** | http://localhost:3000 | - |
| **Adminer (DB UI)** | http://localhost:8080 | postgres / password |
| **Flower (Celery)** | http://localhost:5555 | - |

## Проверка сервисов

```bash
# Backend API
curl http://localhost:8000/api/health/

# Frontend
curl http://localhost:3000/

# Database
docker compose exec postgres psql -U postgres -c "SELECT version();"

# Redis
docker compose exec redis redis-cli ping
# Response: PONG

# Celery
docker compose logs celery | head -20
```

## Частые проблемы

### Port уже занят

```bash
# Если порт 8000 занят:
# Либо убей процесс:
lsof -i :8000
kill -9 <PID>

# Либо измени port в docker-compose.yml:
# ports: ["8001:8000"]  # local:container
```

### Database ошибка "database does not exist"

```bash
# Создай DB вручную:
docker compose exec postgres createdb -U postgres railtech

# Или в docker-compose.yml должно быть:
# environment:
#   - POSTGRES_DB=railtech
#   - POSTGRES_USER=postgres
#   - POSTGRES_PASSWORD=password
```

### Миграции падают

```bash
# 1. Проверь логи
docker compose logs backend

# 2. Если DB в плохом состоянии, удали и пересоздай:
docker compose down -v  # удалить volumes
docker compose up -d --build
docker compose exec backend python manage.py migrate
```

### Redis connection refused

```bash
# Если backend не видит Redis:
docker compose exec backend python -c "import redis; redis.from_url('redis://redis:6379').ping()"

# Если падает:
# 1. Проверь, что redis запущен: docker compose ps redis
# 2. Проверь логи: docker compose logs redis
# 3. Перезапусти: docker compose restart redis
```

### Frontend не загружается

```bash
# Если npm ошибки:
docker compose logs frontend

# Пересоздай node_modules:
docker compose exec frontend npm install

# Пересоздай контейнер:
docker compose down frontend
docker compose up -d --build frontend
```

## Управление контейнерами

```bash
# Останови все
docker compose down

# Останови без удаления volumes (БД сохранится)
docker compose stop

# Удали всё включая БД
docker compose down -v

# Перезапусти отдельный сервис
docker compose restart backend

# Пересоздай один контейнер
docker compose up -d --build backend

# Смотри логи
docker compose logs backend -f
docker compose logs -f  # все логи

# Войди в контейнер
docker compose exec backend bash
docker compose exec postgres psql -U postgres
```

## Полезные комманды

```bash
# Создай новую миграцию
docker compose exec backend python manage.py makemigrations

# Примени миграции
docker compose exec backend python manage.py migrate

# Запусти тесты
docker compose exec backend python -m pytest

# Shell Django
docker compose exec backend python manage.py shell

# Cоздай суперюзера
docker compose exec backend python manage.py createsuperuser

# Загрузи данные
docker compose exec backend python manage.py loaddata core/data/seed_data.json

# Dump БД в бэкап
docker compose exec postgres pg_dump -U postgres railtech > backup.sql

# Restore из бэкапа
docker compose exec -T postgres psql -U postgres railtech < backup.sql
```

## Production vs Development

```yaml
# development (docker-compose.yml)
services:
  backend:
    environment:
      - DEBUG=True
      - ALLOWED_HOSTS=localhost,127.0.0.1
    ports: ["8000:8000"]
    volumes: [".:/app"]  # code reloading

# production (docker-compose.prod.yml)
services:
  backend:
    environment:
      - DEBUG=False
      - ALLOWED_HOSTS=app.railtech.com
    # NO volumes (immutable)
    # healthcheck added
    # resource limits added
```

## После запуска

1. Проверь, что все сервисы HEALTHY:
   ```bash
   docker compose ps
   ```

2. Протестируй API:
   ```bash
   curl http://localhost:8000/api/health/
   ```

3. Протестируй фронтенд:
   ```bash
   curl http://localhost:3000/
   ```

4. Создай тестовых пользователей через admin:
   ```bash
   http://localhost:8000/admin/
   ```

5. Проверь Swagger:
   ```bash
   http://localhost:8000/api/schema/swagger/
   ```

## Сообщи результаты

```
✓ Docker compose up -d --build completed
✓ All services healthy (docker compose ps)
✓ Migrations applied
✓ Backend API responding at http://localhost:8000
✓ Frontend running at http://localhost:3000
✓ Admin panel at http://localhost:8000/admin/

Development environment ready!
```

## Clean Up

```bash
# Перед окончанием работы (опционально)
docker compose down  # остановка контейнеров

# Полная очистка (осторожно!)
docker compose down -v  # удалить volume (БД)
```
