# Staging environment

**Why:** today every push to `main` deploys straight to production. A staging
buffer means a bad change is caught on `staging.b2b.railtech.uz` and the smoke
checklist, not by a client on prod.

**Model:** a second isolated stack on the SAME VPS (176.101.56.141), beside prod
and GradeSentinel. Separate compose project, separate web root, its own subdomain
and Caddy block, and **its own database** (a separate Neon branch/project — never
share prod data).

`.github/workflows/deploy-staging.yml` is committed but **manual-trigger only
(`workflow_dispatch`)** and inert until the 3 prerequisites below exist. Once they
do, flip it to also trigger on push to a `staging` branch.

## Prerequisites (need your infra access — I can't do these from here)

1. **DNS:** add an A record `staging.b2b.railtech.uz → 176.101.56.141`.
2. **GitHub environment `staging`** with its own secrets:
   - `DATABASE_URL` → a **separate** Neon branch/project (not prod!)
   - `DJANGO_SECRET_KEY` (a different key from prod)
   - `SUPERADMIN_PASSWORD`, and email secrets if you want mail on staging
3. **Caddy block** for the new host (TLS is automatic). Mirror the prod block but
   point the web root at `/var/www/railtech-staging` and proxy `/api` + `/ws` to
   the staging backend container port. Add to the same Caddyfile the prod block
   lives in.

The self-hosted runner (label `railtech-b2b`) is reused — staging just deploys to
a different directory/project on the same box.

## Isolation rules (do not violate)

- **Different DB.** Staging must never point at the prod Neon DATABASE_URL.
- **Different compose project name** (`-p railtech-staging`) so containers,
  networks and volumes don't collide with prod or GradeSentinel.
- **Different ports** for the backend container if both run on the host network;
  Caddy routes by host name to the right upstream.
- **CPU constraint still applies** — MinIO off, numpy<2 (see `vps-cpu-constraints.md`).

## Promotion flow once live

```
PR → CI green → merge to `staging` → auto-deploy staging → smoke checklist
   → merge `staging` → `main` → auto-deploy prod
```
