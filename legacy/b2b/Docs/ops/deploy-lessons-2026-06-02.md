# Deploy lessons — first b2b.railtech.uz cutover (2026-06-02)

The first production cutover failed six different ways before the site stayed up. Each fix is its own commit in `main`; these notes capture the *general lesson* so the same traps don't bite again.

Read this before touching `docker-compose.prod.yml`, `.github/workflows/deploy-b2b.yml`, the backend Dockerfile, the SPA's `VITE_API_URL` plumbing, or `ALLOWED_HOSTS`.

---

## 1. `docker compose images -q <service>` returns empty for profile-only services

**Commit:** `8063fb8`

Compose's `images` subcommand lists images of *created containers*, not all built images. If a service is gated behind a `profiles:` directive and never started, `compose images -q frontend` returns nothing, and any `docker create "$IMG"` downstream crashes with `invalid reference format`.

**Use instead:** the known image tag. Compose names built images `<project>-<service>:latest` where project defaults to the working-directory basename:

```bash
$COMPOSE --profile frontend-build build frontend
IMG="$(basename "$PWD")-frontend"
CID=$(docker create "$IMG")
```

---

## 2. `docker cp` preserves container UIDs verbatim

**Commit:** `f5c4543`

When the deploy step extracts SPA dist via `docker cp container:/usr/share/nginx/html/. /var/www/...`, the files land owned by whatever UID the nginx image used (101 → `systemd-network` on the host). On the *next* deploy, the unprivileged `deploy` user can't `find -delete` those files and the step aborts with EACCES.

**Fix:** clean the destination via a throwaway root container **before** extracting:

```bash
docker run --rm -v "$WEB_ROOT":/out alpine find /out -mindepth 1 -delete
docker cp "$CID":/usr/share/nginx/html/. "$WEB_ROOT"/
```

---

## 3. Modern MinIO requires x86_64_v2

**Commit:** `585ddfc`

`minio/minio:latest` (and the 2024+ release line) exits with `Fatal glibc error: CPU does not support x86-64-v2` on the production VPS. See `Docs/ops/vps-cpu-constraints.md` for the underlying CPU caveat.

Backend depended on `minio: service_healthy`, so the whole stack stayed in restart loop when MinIO failed.

**Fix:** gate MinIO behind a never-activated profile in `docker-compose.prod.yml`, `!reset` `backend.depends_on` to drop the minio dependency. Storage falls back to Django `FileSystemStorage` when `MINIO_ENDPOINT` is unset — see `backend/core/storage.py::_minio_is_configured`.

```yaml
# docker-compose.prod.yml
services:
  minio:
    profiles: ["with-minio"]   # never activated in prod
  minio-init:
    profiles: ["with-minio"]

  backend:
    depends_on: !reset
      redis:
        condition: service_healthy
      redis-celery:
        condition: service_healthy
```

---

## 4. NumPy 2.x wheels require x86_64_v2

**Commits:** `6ed58b2` + `4801399`

Daphne is in `INSTALLED_APPS`, daphne pulls autobahn, autobahn imports numpy via flatbuffers. On boot Django setup → autobahn → numpy → `RuntimeError: NumPy was built with baseline optimizations (X86_V2)`.

Pinning `numpy<2` is necessary; pinning alone is not sufficient because NumPy 1.26.x has no wheels for Python 3.13, and the slim image had no gfortran/BLAS to build from source.

**Fix:** in `backend/requirements.txt`:

```
numpy>=1.26,<2
pandas>=2.2,<2.3
```

…AND base image `python:3.12-slim` in `backend/Dockerfile`. Drop both when the VPS gets a modern CPU.

---

## 5. `ALLOWED_HOSTS=b2b.railtech.uz` rejects healthchecks

**Commit:** `c253515`

The container healthcheck (`curl http://localhost:8000/health/`) and the deploy workflow's loopback probe (`curl http://127.0.0.1:8000/...`) send a Host header that Django returns 400 `DisallowedHost` for. Deploy never reaches "healthy" even though the backend is otherwise up.

**Fix:** include loopback hostnames:

```
ALLOWED_HOSTS=b2b.railtech.uz,localhost,127.0.0.1
```

Caddy still forwards the real public Host (`b2b.railtech.uz`) for external traffic — no security regression.

---

## 6. SPA `VITE_API_URL` has two conflicting consumers

**Commits:** `8e9a63b` + `8636c28`

Two different code paths read `VITE_API_URL` (baked at build time):

- `frontend/src/api/client.ts` smart-joins:
  `BASE.endsWith('/api/v1') ? BASE : BASE + '/api/v1'`. Treats env as "either empty or already includes `/api/v1`".
- `frontend/src/store/authStore.ts` raw login fetch: hardcoded `${API_URL}/auth/token/`. After the fix expects env to already include `/api/v1`.

Originally the workflow rendered `VITE_API_URL=/api`, which client.ts turned into `/api/api/v1` AND authStore turned into `/api/api/v1/auth/token/`. A naive fix of `VITE_API_URL=/api/v1` cleaned client.ts but broke authStore (`/api/v1/api/v1/auth/token/`).

**Fix:** set `VITE_API_URL=/api/v1` in the workflow AND make authStore consistent (drop the hardcoded `/api/v1/` prefix). Both consumers now treat `VITE_API_URL` as "the full prefix including the version".

**General lesson:** baked-in env vars (Vite, CRA) are not runtime config; they ship inside the JS bundle. Test SPA → API calls in DevTools Network on a *real* prod build, not against `npm run dev` or curl-direct.

---

## Why none of this was caught earlier

- Test suite runs with `--nomigrations` (pyproject pytest addopts) against a clean Postgres, masking deploy-graph issues. (#3 mitigated by the `migration-check` CI job.)
- No staging environment — Compose + Caddy + Neon is unique to prod and only exercised at cutover.
- JWT smoke test went curl-direct, bypassing the SPA build, so #6 wasn't seen during early "login works" verification.
- Self-hosted runner uploads stdout to GitHub and wipes local artefacts; local diagnostics rely on `/home/deploy/actions-runner-railtech/_diag/Worker_*.log`, which only has metadata, not command stdout. Reproducing failures often requires re-running the failing step manually on the VPS.

## How to debug a failed deploy

1. SSH to the runner: `ssh vps-eskiz`.
2. Find the latest worker log: `ls -t /home/deploy/actions-runner-railtech/_diag/Worker_*.log | head -1`.
3. Grep for `Step result|exit code 1|::error` to locate the failing step.
4. Re-run that step's command sequence in `/opt/railtech-b2b/` manually to see real stdout/stderr.
5. Cross-check against the gotchas above before changing anything.
