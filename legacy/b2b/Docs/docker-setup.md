# RailTech B2B SaaS — Docker Infrastructure Guide

Complete production-ready Docker setup for the RailTech B2B monorepo.

## Quick Start

### Development (with hot reload)

```bash
# Copy environment file
cp .env.example .env

# Start all services
docker-compose up

# Access:
# - Frontend: http://localhost:5173
# - Backend API: http://localhost:8000
# - MinIO UI: http://localhost:9001 (access/railtech, secret key from .env)
# - PostgreSQL: localhost:5432
```

### Production (with nginx reverse proxy)

```bash
# Copy and configure production environment
cp .env.example .env
# Edit .env with production values

# Build and start
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Access:
# - HTTP/HTTPS: http(s)://your-domain.com
```

## Architecture Overview

### Services

```
┌─────────────────────────────────────────────────────┐
│ Nginx Reverse Proxy (Production only)               │
│ :80/:443 → Routes to backend, frontend, minio       │
└──────────────────┬──────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┬────────────────┐
    │              │              │                │
    ▼              ▼              ▼                ▼
 Backend       Frontend       MinIO           Redis-Celery
 Daphne        Nginx          S3-compat       (Broker)
 :8000         :5173/:80      :9000/9001
    │              │              │
    │              │              │
    └──────────────┼──────────────┘
                   │
        ┌──────────┴──────────┬──────────────┐
        │                     │              │
        ▼                     ▼              ▼
   PostgreSQL            Redis            Celery Workers
   :5432              (Channels)          + Beat Scheduler
                      :6379

```

### Components

| Service | Image | Purpose | Dev Port | Prod Port |
|---------|-------|---------|----------|-----------|
| **db** | postgres:15-alpine | Primary database | 5432 | internal |
| **redis** | redis:7-alpine | Django Channels (WebSocket) | 6379 | internal |
| **redis-celery** | redis:7-alpine | Celery broker & result backend | 6380 | internal |
| **minio** | minio/minio | S3-compatible object storage | 9000/9001 | internal |
| **minio-init** | minio/mc | Bucket initialization | - | - |
| **backend** | python:3.11-slim | Django + Daphne ASGI | 8000 | 8000 |
| **celery-worker** | python:3.11-slim | Async tasks (PDF, imports) | - | - |
| **celery-beat** | python:3.11-slim | Scheduled tasks | - | - |
| **frontend** | node:22-alpine + nginx | React SPA | 5173 | 80/443 |
| **nginx** | nginx:stable-alpine | Reverse proxy (prod only) | - | 80/443 |

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

**Critical for development:**
```env
POSTGRES_PASSWORD=postgres
REDIS_PASSWORD=
MINIO_SECRET_KEY=your-secret-key
DJANGO_SECRET_KEY=your-secret-key
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws
```

**Critical for production:**
```env
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=generate-secure-key
DATABASE_URL=postgresql://user:pass@db:5432/railtech
REDIS_PASSWORD=strong-random-password
MINIO_SECRET_KEY=strong-random-password
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
CORS_ALLOWED_ORIGINS=https://your-domain.com
VITE_API_URL=/api
VITE_WS_URL=/ws
```

### Building Images

**Frontend with custom Vite variables:**
```bash
docker-compose build \
  --build-arg VITE_API_URL=https://api.example.com \
  --build-arg VITE_WS_URL=wss://example.com/ws \
  frontend
```

**Backend:**
```bash
docker-compose build backend
```

## Development Workflow

### Hot Reload

- **Backend**: Code changes auto-reload via volume mount (`./backend:/app`)
- **Frontend**: Vite dev server with HMR enabled (served from container)
- **Database**: Schema changes require `docker-compose exec backend python manage.py migrate`

### Common Commands

**Database migrations:**
```bash
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py makemigrations
```

**Create superuser:**
```bash
docker-compose exec backend python manage.py createsuperuser
```

**Load seed data:**
```bash
docker-compose exec backend python manage.py loaddata core/data/seed_data.json
```

**Celery tasks:**
```bash
# Monitor worker
docker-compose logs -f celery-worker

# Purge pending tasks
docker-compose exec celery-worker celery -A core purge
```

**MinIO:**
```bash
# Access console: http://localhost:9001
# Default credentials: railtech / (from MINIO_SECRET_KEY)
```

**Redis:**
```bash
docker-compose exec redis redis-cli
docker-compose exec redis-celery redis-cli
```

## Production Deployment

### SSL/TLS Configuration

1. **Obtain certificates** (Let's Encrypt recommended):
   ```bash
   # Create ssl directory
   mkdir -p nginx/ssl

   # Place certificates:
   # - nginx/ssl/railtech.crt (full certificate chain)
   # - nginx/ssl/railtech.key (private key)
   ```

2. **Enable SSL in nginx.conf**:
   Uncomment the `ssl_certificate` and `ssl_certificate_key` directives in the HTTPS server block.

3. **Restart nginx**:
   ```bash
   docker-compose restart nginx
   ```

### Production Checklist

- [ ] Configure `.env` with production values
- [ ] Set `DJANGO_DEBUG=False`
- [ ] Generate strong `DJANGO_SECRET_KEY`
- [ ] Configure database (PostgreSQL, Neon, or RDS)
- [ ] Configure Redis (ElastiCache, Redis Cloud, or self-hosted)
- [ ] Configure MinIO (S3, MinIO Cloud, or self-hosted)
- [ ] Set up SSL certificates
- [ ] Configure `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS`
- [ ] Set up email (SMTP configuration)
- [ ] Run database migrations
- [ ] Collect static files: `docker-compose exec backend python manage.py collectstatic`
- [ ] Test health checks: curl http://localhost/health
- [ ] Set up monitoring and logging
- [ ] Configure backups for PostgreSQL and MinIO

### Health Checks

All services include health checks for orchestration (Kubernetes, Docker Swarm):

```bash
# Check service health
docker-compose ps

# Check individual service
docker-compose exec backend curl -f http://localhost:8000/health/
```

### Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f celery-worker
docker-compose logs -f frontend

# Follow last 100 lines
docker-compose logs --tail=100 -f
```

### Scaling

**Celery workers (production):**
```bash
docker-compose up -d --scale celery-worker=3
```

**Backend instances (with load balancer):**
- Configure Kubernetes or orchestration platform
- Update nginx upstream with multiple backend servers

## Networking

### Internal Communication

Services communicate via the `railtech` bridge network:

```
backend:8000     → Database at db:5432
backend:8000     → Redis at redis:6379 (Channels)
backend:8000     → Redis at redis-celery:6379 (Celery)
backend:8000     → MinIO at minio:9000
celery-worker    → Redis at redis-celery:6379
frontend:80      → (Reverse proxy, not direct)
```

### External Access (Production)

Nginx reverse proxy handles all external access:

```
Client :443      →  Nginx :443 (HTTPS)
Nginx /api/      →  Backend :8000
Nginx /ws/       →  Backend :8000 (WebSocket upgrade)
Nginx /storage/  →  MinIO :9000
Nginx /          →  Frontend :80 (SPA)
```

## Monitoring & Troubleshooting

### Common Issues

**Backend won't start:**
```bash
# Check logs
docker-compose logs backend

# Run migrations
docker-compose exec backend python manage.py migrate

# Check dependencies
docker-compose ps
```

**Frontend build fails:**
```bash
# Check Node version
docker run node:22-alpine node --version

# Clear node_modules and rebuild
docker-compose build --no-cache frontend
```

**Database connection refused:**
```bash
# Check PostgreSQL is healthy
docker-compose ps db

# Check connection string in .env
docker-compose exec backend python -c "import os; print(os.environ.get('DATABASE_URL'))"
```

**WebSocket connection fails:**
```bash
# Check Redis is running
docker-compose exec redis redis-cli ping

# Check Daphne logs
docker-compose logs backend | grep -i websocket
```

**MinIO bucket creation fails:**
```bash
# Manually create buckets
docker-compose exec minio-init mc mb railtech/railtech-public
docker-compose exec minio-init mc anonymous set public railtech/railtech-public
```

### Performance Tuning

**PostgreSQL:**
- Increase `max_connections` in docker-compose.yml
- Adjust `shared_buffers` based on RAM
- Use connection pooling (PgBouncer)

**Redis:**
- Monitor memory: `docker-compose exec redis redis-cli info memory`
- Set `maxmemory-policy` for eviction policy

**Celery:**
- Increase `CELERY_WORKER_CONCURRENCY` for CPU-bound tasks
- Scale workers: `docker-compose up -d --scale celery-worker=N`

**Nginx:**
- Increase `worker_connections` for high traffic
- Tune `upstream` balancing method

## Backup & Recovery

### PostgreSQL Backup

```bash
# Full backup
docker-compose exec db pg_dump -U ${POSTGRES_USER} ${POSTGRES_DB} > backup.sql

# Restore
docker-compose exec -T db psql -U ${POSTGRES_USER} ${POSTGRES_DB} < backup.sql
```

### MinIO Backup

```bash
# Sync to local directory
docker-compose exec minio-init mc mirror railtech/ ./backups/minio
```

### Volume Backup

```bash
# Backup Docker volume
docker run --rm -v railtech_postgres_data:/volume \
  -v $(pwd):/backup alpine tar czf /backup/db.tar.gz -C /volume .

# Restore
docker run --rm -v railtech_postgres_data:/volume \
  -v $(pwd):/backup alpine tar xzf /backup/db.tar.gz -C /volume
```

## File Structure

```
RailTech_SaaS_B2B/
├── backend/
│   ├── Dockerfile          # Multi-stage Python build
│   ├── entrypoint.sh       # Non-root user setup
│   ├── requirements.txt
│   ├── manage.py
│   ├── core/
│   │   ├── settings.py
│   │   ├── asgi.py        # Daphne entry point
│   │   └── wsgi.py
│   └── ...
├── frontend/
│   ├── Dockerfile          # Multi-stage Node + Nginx build
│   ├── nginx.conf         # SPA configuration
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   └── ...
├── nginx/
│   ├── nginx.conf         # Production reverse proxy
│   ├── ssl/               # SSL certificates (production)
│   │   ├── railtech.crt
│   │   ├── railtech.key
│   │   └── railtech_chain.crt
│   └── conf.d/            # Additional configurations
├── docker-compose.yml     # Development stack
├── docker-compose.prod.yml # Production overrides
├── .env.example           # Environment template
└── DOCKER_SETUP.md        # This file
```

## Resources & References

- [Docker Compose](https://docs.docker.com/compose/)
- [Django Daphne](https://github.com/django/daphne)
- [React Vite](https://vitejs.dev/)
- [Nginx Proxy](https://nginx.org/)
- [PostgreSQL](https://www.postgresql.org/)
- [Redis](https://redis.io/)
- [Celery](https://docs.celeryproject.io/)
- [MinIO S3](https://min.io/)

## Support

For issues or questions:

1. Check logs: `docker-compose logs -f`
2. Verify environment: `.env` file configuration
3. Ensure all services are healthy: `docker-compose ps`
4. Check Docker resources: `docker system df`
5. Review this guide's troubleshooting section
