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

## Deployment model: CI/CD (push-to-deploy)

Deploys run through **`.github/workflows/deploy-b2b.yml`** on a **self-hosted runner
registered to this repo** (label `railtech-b2b`) living on the VPS. On push to `main`
(or manual *Run workflow*) it: syncs code → `/opt/railtech-b2b`, builds the SPA →
`/var/www/railtech-b2b`, `docker compose up -d --build` (migrations auto-apply on the
web container), health-checks the backend.

**Secrets live in GitHub** (repo → Settings → Secrets and variables → Actions,
Environment `production`). The workflow renders them into `/opt/railtech-b2b/.env`
on the runner at deploy time. Add these secrets:

| Secret | Value |
|---|---|
| `DATABASE_URL` | Neon prod connection string (`...?sslmode=require&channel_binding=require`) |
| `DJANGO_SECRET_KEY` | `python3 -c "import secrets;print(secrets.token_urlsafe(64))"` |
| `MINIO_SECRET_KEY` | `openssl rand -base64 32` |
| `SUPERADMIN_PASSWORD` | `openssl rand -base64 24` |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP (optional; email is skipped if unset) |

> Recommended: use a **separate Neon branch/project for production**, not the dev DB.

The GradeSentinel runner is repo-scoped and **cannot** run this repo's jobs, so a
dedicated runner is registered below. Steps **B-1 … B-7 are one-time bootstrap**;
after that, every `git push` to `main` deploys automatically.

### B-1 … B-3: server prep
Do sections **1–2** below once (swap, Docker). The repo, `.env` and SPA are handled
by the pipeline (the workflow rsyncs code, renders `.env` from secrets, builds the SPA).

### B-5: register a self-hosted runner for THIS repo
On GitHub: repo → Settings → Actions → Runners → **New self-hosted runner** (Linux/x64)
to get a registration token. Then on the VPS, as a dedicated `deploy` user that is in
the `docker` group and owns the deploy paths:
```bash
# as root: ensure a deploy user with docker access + path ownership
id deploy &>/dev/null || useradd -m -s /bin/bash deploy
usermod -aG docker deploy
mkdir -p /opt/railtech-b2b /var/www/railtech-b2b
chown -R deploy:deploy /opt/railtech-b2b /var/www/railtech-b2b
# install the runner under the deploy user
sudo -iu deploy bash -c '
  mkdir -p ~/actions-runner-railtech && cd ~/actions-runner-railtech
  curl -o r.tar.gz -L https://github.com/actions/runner/releases/download/v2.319.1/actions-runner-linux-x64-2.319.1.tar.gz
  tar xzf r.tar.gz
  ./config.sh --url https://github.com/nzulkaynarov/RailTech_SaaS_B2B \
    --token <RUNNER_REGISTRATION_TOKEN> --labels railtech-b2b --name vps-b2b --unattended
'
# install as a service (run from the runner dir as root)
cd /home/deploy/actions-runner-railtech && ./svc.sh install deploy && ./svc.sh start
```

### B-6: add the Caddy block (one-time) — see section 7
### B-7: trigger the first deploy & create the superadmin
```bash
# from GitHub: Actions → "Deploy b2b.railtech.uz" → Run workflow (branch main)
# after it goes green, once:
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
cd /opt/railtech-b2b && $DC exec backend python manage.py init_superadmin
```

> The sections below double as **the manual fallback** and as the reference for what
> the pipeline automates. After bootstrap you normally only `git push`.

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
>
> **Firewall must allow UDP 443 for Caddy HTTP/3 (QUIC).** Caddy advertises
> `alt-svc: h3=":443"` and listens on UDP 443 by default; if ufw allows only
> `443/tcp`, browsers cache the alt-svc, retry over QUIC, get their UDP packets
> silently dropped, stall on the QUIC timeout, then fall back to TCP — the site
> "opens on the tenth attempt". Open it: `ufw allow 443/udp` (and `443/tcp`).
> If a region/ISP blocks UDP 443 outbound and flakiness persists, disable HTTP/3
> instead via a Caddy global block: `{ servers { protocols h1 h2 } }`.

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
**Normal path: just `git push` to `main`** — the deploy-b2b workflow rebuilds the SPA,
restarts the backend (migrations auto-apply), and health-checks. Or trigger it manually
from the Actions tab. Manual fallback (if the runner is down):
```bash
cd /opt/railtech-b2b && git fetch && git checkout <new-tag>   # (manual git needs repo creds)
# rebuild + republish SPA (repeat step 5), then:
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
