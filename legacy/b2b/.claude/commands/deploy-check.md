# Pre-Deployment Checklist

Проверь, что всё готово к deploy в production.

## Инструкции

### 1. Тесты должны пройти

```bash
# Backend tests
cd backend && python -m pytest --tb=short

# Frontend tests
cd frontend && npm run test

# ✓ Должны быть зелёные (all passed)
# ✗ Если есть failures — не деплоиь! Сначала исправь.
```

### 2. Build должен успешно завершиться

```bash
# Frontend build
cd frontend && npm run build

# Проверь артефакты
ls -lh dist/

# Backend не требует build, но проверь collectstatic
cd backend && python manage.py collectstatic --noinput --check

# Размер (должен быть <500MB для быстрого деплоя)
du -sh dist/ static/
```

### 3. DEBUG Mode ОТКЛЮЧЕН

```bash
# core/settings.py должен быть:
DEBUG = False  # НИКОГДА не True в production!

# Проверка:
grep "DEBUG\s*=" backend/core/settings.py

# Должно быть:
# DEBUG = False
# или
# DEBUG = os.environ.get('DEBUG') == 'True'  # но default False
```

### 4. SECRET_KEY установлен

```bash
# НИКОГДА не используй default value!

# Хорошо:
SECRET_KEY = os.environ['SECRET_KEY']
assert SECRET_KEY, "SECRET_KEY must be set in environment"

# Плохо:
SECRET_KEY = 'django-insecure-xxx...'  # никогда!

# Проверка:
grep "SECRET_KEY" backend/core/settings.py
```

### 5. ALLOWED_HOSTS правильно сконфигурирован

```python
# core/settings.py
ALLOWED_HOSTS = ['app.railtech.com', 'www.railtech.com']

# Или из environment:
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost').split(',')

# Для производства должно быть:
# ALLOWED_HOSTS = ['app.railtech.com', 'www.railtech.com']
# НЕ ['*'] !!!
```

### 6. Миграции БД применены

```bash
# Убедись, что нет pending миграций
cd backend
python manage.py showmigrations --plan

# Должны быть все [X]:
# [X] 0001_initial
# [X] 0002_user_role
# [X] 0003_...

# Если есть [ ]:
# Примени: python manage.py migrate
# НЕ коммитьте без примененных миграций!
```

### 7. Статические файлы собраны

```bash
# Собери все статические файлы
cd backend
python manage.py collectstatic --noinput

# Проверь сборку
ls -lh staticfiles/

# Должны быть:
# - admin/ (Django admin CSS/JS)
# - rest_framework/ (DRF UI)
# - custom assets если есть

# Если используешь S3/CloudFront:
# python manage.py collectstatic --noinput --s3
```

### 8. Docker образы собираются

```bash
# Сборка backend
docker build -t railtech-backend:latest ./backend

# Сборка frontend
docker build -t railtech-frontend:latest ./frontend

# Проверка
docker images | grep railtech

# Должны быть оба образа с tag latest
```

### 9. Environment Variables проверены

```bash
# Создай .env.production с ВСЕМИ необходимыми переменными
# НИКОГДА не коммитьте .env в production значениями!

# Обязательные переменные:
SECRET_KEY=<generate-new-random>
DEBUG=False
ALLOWED_HOSTS=app.railtech.com,www.railtech.com

# Database
DATABASE_URL=postgresql://user:pass@host:5432/railtech_prod

# Email (для notifications)
EMAIL_HOST=smtp.sendgrid.com
EMAIL_PORT=587
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=<sendgrid-api-key>

# Redis (Celery, cache)
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=$REDIS_URL

# AWS (если используешь S3, SES)
AWS_ACCESS_KEY_ID=<production-key>
AWS_SECRET_ACCESS_KEY=<production-secret>
AWS_STORAGE_BUCKET_NAME=railtech-prod

# JWT
JWT_SECRET=<generate-new>
JWT_ALGORITHM=HS256

# Third-party services
STRIPE_API_KEY=sk_live_xxx
SENDGRID_API_KEY=xxx
SENTRY_DSN=https://xxx@sentry.io/xxx

# Проверка: все ли ключи установлены?
source .env.production
echo $SECRET_KEY  # Должна быть непустая
echo $DATABASE_URL
echo $REDIS_URL
```

### 10. Health Checks включены

```bash
# Добавь health check endpoint
# core/urls.py

urlpatterns = [
    path('api/health/', HealthCheckView.as_view(), name='health'),
    # ... остальные URLs
]

# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

class HealthCheckView(APIView):
    permission_classes = []

    def get(self, request):
        try:
            # Проверь БД
            from django.db import connection
            connection.ensure_connection()

            # Проверь Redis
            import redis
            redis.from_url(settings.REDIS_URL).ping()

            return Response({'status': 'healthy'}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'status': 'unhealthy', 'error': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
```

### 11. Логирование сконфигурировано

```python
# core/settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/django.log',
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'sentry': {
            'level': 'ERROR',
            'class': 'sentry_sdk.integrations.logging.EventHandler',
        },
    },
    'root': {
        'handlers': ['file', 'sentry'],
        'level': 'INFO',
    },
}
```

### 12. Security Headers установлены

```python
# core/settings.py
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_SECURITY_POLICY = {
    'DEFAULT_SRC': ("'self'",),
    'SCRIPT_SRC': ("'self'", "'unsafe-inline'"),  # убрать unsafe-inline если можешь
    'STYLE_SRC': ("'self'", "'unsafe-inline'"),
}
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

### 13. Backup стратегия определена

```bash
# Ежедневный бэкап БД
# В production setup добавь:

# cron job или managed service
# 0 2 * * * /usr/local/bin/backup-db.sh  # 2 AM daily

# Скрипт:
#!/bin/bash
pg_dump $DATABASE_URL | gzip > /backups/railtech_$(date +%Y%m%d).sql.gz

# Проверь, что бэкапы хранятся не менее 30 дней
```

## Pre-Deployment Checklist

```
Code Quality:
  [ ] Все тесты проходят (frontend + backend)
  [ ] npm run build успешна (frontend)
  [ ] python manage.py check --deploy passes (backend)
  [ ] Нет TODO или FIXME комментов перед deadline
  [ ] Code review одобрен

Configuration:
  [ ] DEBUG = False
  [ ] SECRET_KEY set in environment
  [ ] ALLOWED_HOSTS правильно настроены
  [ ] CORS_ALLOWED_ORIGINS ограничены
  [ ] CSRF_COOKIE_SECURE = True
  [ ] SESSION_COOKIE_SECURE = True
  [ ] Security headers установлены

Database:
  [ ] Миграции применены (showmigrations все [X])
  [ ] Backup создан перед deploy
  [ ] Rollback план документирован

Static Files:
  [ ] collectstatic завершён успешно
  [ ] S3/CDN сконфигурирован если используется
  [ ] .gitignore содержит /static и /staticfiles

Docker:
  [ ] Backend image собирается
  [ ] Frontend image собирается
  [ ] docker-compose up успешно запускается
  [ ] Health check endpoint работает

Monitoring:
  [ ] Sentry сконфигурирован для error tracking
  [ ] Логирование включено (файлы, Sentry)
  [ ] Alert rules установлены
  [ ] Графики мониторинга настроены

Secrets:
  [ ] .env файл не в репозитории
  [ ] Все environment variables установлены
  [ ] API keys по-разному в dev vs production
  [ ] SSH ключи для deploy скрыты

Final:
  [ ] Release notes подготовлены
  [ ] Rollback план документирован
  [ ] Stakeholders уведомлены о времени deploy
  [ ] On-call engineer доступен во время deploy
```

## Команды для проверки перед deploy

```bash
# Backend checks
cd backend
python manage.py check --deploy
python manage.py showmigrations --plan
python -m pytest --tb=short -q

# Frontend checks
cd frontend
npm run build
npm run test

# Docker check
docker compose build
docker compose up -d
curl http://localhost:8000/api/health/
curl http://localhost:3000/

# Cleanup
docker compose down
```

## Если найдены проблемы

| Проблема | Решение |
|----------|---------|
| Tests fail | Не деплой! Исправь в dev, запусти тесты заново |
| Build fail | Проверь dependencies, webpack config, tsconfig |
| Migration pending | Примени: `python manage.py migrate` |
| SECRET_KEY missing | Добавь в environment, не в code |
| ALLOWED_HOSTS wrong | Обнови для production domain |
| Старая версия library | Обнови requirements.txt, переделай build |

## Сообщи результаты

```
✓ Tests passed: X/X
✓ Build successful
✓ Migrations applied
✓ DEBUG = False
✓ All environment variables set
✓ Docker images ready
✓ Health check working

Ready for deployment!
```

## После успешного deploy

```bash
# Мониторь логи
docker logs -f railtech-backend

# Проверь health
curl https://app.railtech.com/api/health/

# Запусти smoke tests
python -m pytest tests/smoke/ -v

# Уведоми stakeholders
# "✓ Deployment successful at 15:30 UTC"
```
