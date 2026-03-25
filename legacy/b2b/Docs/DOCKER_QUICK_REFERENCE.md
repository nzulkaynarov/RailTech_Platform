# Docker Quick Reference — RailTech B2B

## Startup

```bash
# Development (with hot reload)
docker-compose up

# Production (with reverse proxy)
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Rebuild images
docker-compose up --build

# Stop services
docker-compose down
docker-compose down -v          # Also remove volumes
```

## Common Commands

### Database

```bash
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py makemigrations
docker-compose exec backend python manage.py createsuperuser
docker-compose exec backend python manage.py loaddata core/data/seed_data.json
docker-compose exec backend python manage.py collectstatic --noinput
```

### Logs

```bash
docker-compose logs -f                    # All services
docker-compose logs -f backend            # Specific service
docker-compose logs -f --tail=50 celery-worker    # Last 50 lines
docker-compose logs --timestamps          # With timestamps
```

### Shell Access

```bash
docker-compose exec backend bash
docker-compose exec backend python manage.py shell
docker-compose exec db psql -U postgres railtech
docker-compose exec redis redis-cli
```

### Tasks & Workers

```bash
docker-compose logs -f celery-worker      # Monitor worker
docker-compose exec celery-worker celery -A core purge    # Clear queue
docker-compose exec backend celery -A core inspect active   # Active tasks
docker-compose exec backend celery -A core inspect stats    # Worker stats
```

### MinIO

```bash
# Web interface
open http://localhost:9001
# Default: railtech / (MINIO_SECRET_KEY from .env)

# Command line
docker-compose exec minio-init mc ls railtech
docker-compose exec minio-init mc mb railtech/new-bucket
```

### Redis

```bash
docker-compose exec redis redis-cli
docker-compose exec redis-celery redis-cli
# Inside redis-cli: ping, info, keys *, flushdb, etc.
```

## Rebuilding

```bash
# Frontend with custom Vite vars
docker-compose build \
  --build-arg VITE_API_URL=https://api.example.com \
  --build-arg VITE_WS_URL=wss://example.com/ws \
  frontend

# Backend only
docker-compose build backend

# All images (no cache)
docker-compose build --no-cache
```

## Health Checks

```bash
docker-compose ps                         # Status of all services

curl http://localhost:8000/health/        # Backend
curl http://localhost:5173/health         # Frontend (dev)
curl http://localhost/health              # Frontend (prod)
curl http://localhost:9000/minio/health/live  # MinIO

docker-compose exec db pg_isready -U postgres
docker-compose exec redis redis-cli ping
```

## Ports

| Service | Dev | Prod |
|---------|-----|------|
| Frontend | 5173 | 80/443 |
| Backend API | 8000 | 8000 |
| MinIO S3 | 9000 | internal |
| MinIO Console | 9001 | internal |
| PostgreSQL | 5432 | internal |
| Redis (Channels) | 6379 | internal |
| Redis (Celery) | 6380 | internal |

## Configuration

```bash
# Copy template
cp .env.example .env

# Edit environment
nano .env

# Required minimum:
DJANGO_SECRET_KEY=...
POSTGRES_PASSWORD=...
REDIS_PASSWORD=...
MINIO_SECRET_KEY=...
```

## Troubleshooting

```bash
# View all service status
docker-compose ps

# Check resource usage
docker stats

# Remove stopped containers
docker-compose down
docker system prune

# Full cleanup (WARNING: removes all data)
docker-compose down -v
docker system prune -a

# Rebuild specific service
docker-compose up -d --build backend

# View disk usage
docker system df
```

## Production Deployment

```bash
# Enable SSL in nginx/nginx.conf
# Place certificates in nginx/ssl/

# Start production stack
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Follow logs
docker-compose logs -f nginx
docker-compose logs -f backend

# Backup database
docker-compose exec db pg_dump -U postgres railtech > backup.sql

# Restore database
docker-compose exec -T db psql -U postgres railtech < backup.sql

# Scale celery workers
docker-compose up -d --scale celery-worker=3
```

## Environment Variables

**Development minimal:**
```
POSTGRES_PASSWORD=postgres
DJANGO_SECRET_KEY=dev-key
REDIS_PASSWORD=
MINIO_SECRET_KEY=minio
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws
```

**Production essential:**
```
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<strong-random>
DATABASE_URL=postgresql://...
REDIS_PASSWORD=<strong-random>
MINIO_SECRET_KEY=<strong-random>
ALLOWED_HOSTS=domain.com,www.domain.com
CORS_ALLOWED_ORIGINS=https://domain.com
VITE_API_URL=/api
VITE_WS_URL=/ws
```

## File Locations

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Development stack definition |
| `docker-compose.prod.yml` | Production overrides |
| `frontend/Dockerfile` | React SPA build |
| `frontend/nginx.conf` | Frontend web server config |
| `backend/Dockerfile` | Django ASGI server build |
| `nginx/nginx.conf` | Production reverse proxy |
| `.env` | Environment variables (create from .env.example) |
| `DOCKER_SETUP.md` | Complete documentation |

## Performance Tips

- **Backend**: Increase `WORKERS` in production docker-compose.prod.yml
- **Celery**: Scale workers: `docker-compose up -d --scale celery-worker=N`
- **Database**: Tune PostgreSQL settings in docker-compose env
- **Redis**: Monitor with `redis-cli info memory`
- **Nginx**: Adjust `worker_connections` for high traffic

## Security Checklist

- [ ] Change all default passwords in `.env`
- [ ] Set `DJANGO_DEBUG=False` in production
- [ ] Configure SSL certificates
- [ ] Set strong `DJANGO_SECRET_KEY`
- [ ] Restrict `ALLOWED_HOSTS`
- [ ] Configure `CORS_ALLOWED_ORIGINS`
- [ ] Enable Redis password
- [ ] Set MinIO credentials
- [ ] Configure email authentication
- [ ] Review nginx rate limiting zones

## Need Help?

1. Check logs: `docker-compose logs -f`
2. Verify environment: `docker-compose config | grep VARIABLE`
3. Check services: `docker-compose ps`
4. Read: `DOCKER_SETUP.md`
5. Inspect Docker: `docker inspect <container-name>`
