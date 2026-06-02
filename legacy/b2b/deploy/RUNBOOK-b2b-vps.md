# Deployment Runbook — b2b.railtech.uz

Target: `root@176.101.56.141` (vps00249.eskiz.uz) — Ubuntu 24.04, 2 vCPU / 3.8 GB RAM.

> **This is a SHARED multi-tenant server.** It already runs **GradeSentinel**
> (`grades.railtech.uz`, native Flask under systemd) and **Caddy** owning ports
> 80/443. Do **not** stop Caddy, the `gradesentinel-*` services, or the
> `actions.runner.*` service. RailTech runs in Docker on loopback only and is
> published through the existing Caddy.

Architecture:
```
Internet → Caddy (80/443, auto-TLS)
  ├─ grades.railtech.uz → GradeSentinel        (untouched)
  └─ b2b.railtech.uz
       ├─ /api,/ws,/admin,/static,/media,/health → 127.0.0.1:8000 (Docker backend)
       └─ /*                                      → /var/www/railtech-b2b (React SPA static)
Docker (loopback-only): backend · celery-worker · celery-beat · redis · redis-celery · minio
DB: Neon Cloud (external, sslmode=require)
```

Prereqs: DNS `b2b.railtech.uz → 176.101.56.141` (already ✅), a Neon DATABASE_URL,
an SMTP account for transactional email.

---

## 0. Connect & sanity-check (don't break neighbors)
```bash
ssh root@176.101.56.141
systemctl is-active caddy gradesentinel-webapp gradesentinel-bot   # all "active"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8443/health   # 200 (GradeSentinel)
free -h && df -h /
```

## 1. (Recommended) grow swap to 2 GB — headroom for Excel-import spikes
```bash
swapoff /swapfile && fallocate -l 2G /swapfile && chmod 600 /swapfile \
  && mkswap /swapfile && swapon /swapfile && free -h
# persists via existing /etc/fstab entry for /swapfile
```

## 2. Install Docker Engine + compose plugin
```bash
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker --version && docker compose version
```
> Note: the published ports in this project are bound to `127.0.0.1` (so Docker's
> iptables rules can't bypass ufw). Keep it that way — never publish a service to
> `0.0.0.0`. Verify after first boot with: `ss -tlnp | grep -E '6379|6380|9000|8000'`
> — every line must show `127.0.0.1:`.

## 3. Clone the repo
```bash
mkdir -p /opt/railtech-b2b && cd /opt/railtech-b2b
git clone git@github.com:nzulkaynarov/RailTech_SaaS_B2B.git .   # or https
# deploy a specific release: git checkout <tag/commit>
```

## 4. Configure environment
```bash
cp deploy/.env.b2b.example .env
# generate secrets:
python3 -c "import secrets;print('DJANGO_SECRET_KEY='+secrets.token_urlsafe(64))"
openssl rand -base64 32   # MINIO_SECRET_KEY
openssl rand -base64 24   # SUPERADMIN_PASSWORD
nano .env                 # fill DATABASE_URL (Neon), secrets, SMTP. Keep DJANGO_DEBUG=False, PRODUCTION=true
chmod 600 .env
```

## 5. Build the SPA and publish it for Caddy
```bash
cd /opt/railtech-b2b
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile frontend-build build frontend
mkdir -p /var/www/railtech-b2b
IMG=$(docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile frontend-build images -q frontend)
CID=$(docker create "$IMG")
docker cp "$CID":/usr/share/nginx/html/. /var/www/railtech-b2b/
docker rm "$CID"
chown -R caddy:caddy /var/www/railtech-b2b 2>/dev/null || chown -R www-data:www-data /var/www/railtech-b2b
ls /var/www/railtech-b2b   # expect index.html, assets/
```
> VITE_API_URL=/api and VITE_WS_URL=/ws are baked in (same-origin via Caddy).

## 6. Start the backend stack (migrations run automatically)
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# entrypoint runs `migrate` + `collectstatic` for the web (gunicorn) container only.
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend   # watch boot, Ctrl-C when healthy
curl -s http://127.0.0.1:8000/health/   # backend health
```
Seed business lookups + create the superadmin:
```bash
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$DC exec backend python manage.py seed 2>/dev/null || true   # data-migrations already seed on migrate; this is a no-op safety net
$DC exec backend python manage.py init_superadmin            # uses SUPERADMIN_* from .env
```

## 7. Wire up Caddy (publish b2b.railtech.uz)
```bash
mkdir -p /var/log/caddy
# append the project's Caddy block to the shared config:
cat /opt/railtech-b2b/deploy/caddy/b2b.railtech.uz.caddy >> /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile      # MUST pass before reload
systemctl reload caddy                             # zero-downtime; grades.railtech.uz unaffected
```
Caddy fetches the Let's Encrypt cert for b2b.railtech.uz on first request (a few seconds).

## 8. Verify end-to-end
```bash
curl -sI https://b2b.railtech.uz/            | head -1   # 200, SPA index
curl -s  https://b2b.railtech.uz/health/                 # backend health JSON
curl -sI https://b2b.railtech.uz/api/v1/master-data/currencies/ | head -1   # 200/401 (reachable)
# admin: open https://b2b.railtech.uz/admin/  and log in with SUPERADMIN_*
# confirm neighbor still healthy:
curl -sI https://grades.railtech.uz/ | head -1
```

---

## Updating / redeploying a new version
```bash
cd /opt/railtech-b2b && git fetch && git checkout <new-tag>
# rebuild + republish SPA (repeat step 5)
# rebuild backend (migrations auto-apply on the web container):
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker image prune -f
```

## Rollback
```bash
cd /opt/railtech-b2b && git checkout <previous-tag>
# rebuild SPA (step 5) + backend (up -d --build)
# DB: migrations are forward-only — only reverse if the release added a migration:
#   docker compose ... exec backend python manage.py migrate <app> <prev_number>
```

## Monitoring & resource checks (shared box!)
```bash
docker stats --no-stream    # watch RailTech mem vs the ~2.5 GB budget
free -h                     # whole-box memory
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 backend celery-worker
journalctl -u caddy -n 50
```
Hard limits (per docker-compose.prod.yml): backend ≤1.2 G, celery-worker ≤768 M,
beat ≤192 M, redis×2 ≤160 M each, minio ≤320 M. Total ceiling ~2.6 G — fits the
~2.7 G free alongside GradeSentinel, but watch during Excel-import bursts.

## Post-deploy TODO (not blocking, schedule soon)
- **Public file URLs:** MinIO is internal-only. Public assets (logos/images) currently
  flow through the backend `/media` route. If volume grows, expose a `files.b2b.railtech.uz`
  Caddy block → MinIO, or switch the public bucket to local storage served by Caddy.
- **Neon backups:** enable Neon's PITR/branching; document RTO/RPO. The app keeps no
  local DB, so Neon is the single source of truth.
- **Error tracking:** add Sentry (sentry-sdk) — currently no error aggregation.
- **CI/CD:** a self-hosted GitHub Actions runner already exists on this box (for
  GradeSentinel). A separate runner/workflow could automate steps 5–6 on tag push.
- **TLS/HSTS:** owned by Caddy (HSTS header + auto-renew). Django redirect stays OFF.
```
