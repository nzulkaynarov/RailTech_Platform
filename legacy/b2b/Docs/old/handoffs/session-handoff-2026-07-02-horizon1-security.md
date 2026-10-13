# Session handoff — 2026-07-02 (PM) — Security Horizon-1 + Phase C Slice C — ALL SHIPPED

> **READ FIRST on the other machine.** `git pull origin main`. Memory is machine-local; this git
> doc is the cross-machine source of truth. Supersedes `session-handoff-2026-07-02-e2e-audit.md`.

## State: everything merged, deployed, and PROD-VERIFIED. No open PRs.
`main` HEAD = `4283367` (Merge #206). Three PRs shipped this session (#204, #205, #206), all CI-green,
all deployed to **b2b.railtech.uz** (self-hosted runner). Final prod check: SPA 200, `db: up`, CSP
**enforcing** + clean, `NUM_PROXIES=1`, Sentry telemetry unblocked.

## What shipped

### PR #204 — Security Horizon-1 (from `Docs/audit-2026-07-02-security-arch-ux.md`)
- **SEC-04** — DRF `NUM_PROXIES` env-driven (`DRF_NUM_PROXIES`, dev=0 / prod=1) with a blank-env
  guard (`int((os.environ.get("DRF_NUM_PROXIES") or "0").strip() or "0")`). 6 tests in
  `backend/core/test_throttle_ident.py`. Caddy already OVERWRITES XFF (`header_up X-Forwarded-For
  {remote_host}`), added `header_up -X-Real-IP`.
- **INF-06** — all 30 `uses:` in `.github/workflows/*` pinned to full commit SHAs + `# vX.Y.Z`.
- **INF-02** — CI `security` job now gates: `pip-audit` hard-fails (clean today); `npm audit
  --audit-level=high` runs step-level `continue-on-error` + a TODO to flip hard.
- **INF-03** — SPA CSP flipped Report-Only → **enforcing** on the host Caddy. Django's own CSP
  (`core/csp.py`, /api + /admin) stays Report-Only (Unfold pages not yet eyes-on'd — see NEXT).
- **Self-hosted Inter** via `@fontsource/inter` (family stays `'Inter'`, 84 woff2 incl. Cyrillic) —
  dropped the `fonts.googleapis.com` `<link>` so the enforcing CSP stays strictly self-only.
- **npm audit fix** (lockfile only) — 6 runtime high/critical closed (axios, react-router(-dom),
  form-data, lodash, picomatch, ws). 5 residual are the **dev-only** vite/vitest/esbuild dev-server
  chain (needs a breaking vitest 4.x major → own PR); they never ship in the static prod build.

### PR #205 — Phase C Slice C (ADR-0005 unified nav) — eyes-on pure-buyer/seller/T0
- KYC verified set `L3_VERIFIED` → **`L3_CONTRACTED`** (phantom code was hiding nav for L3 companies).
- Store default `activeStatus` `SELLER` → **`BUYER`**; `loadFromAuth` now `invalidateQueries()` when
  the resolved context flips (a dual company no longer renders one frame of seller data on the buyer
  dashboard).
- **T0 tier** — `products`/`product_detail` added to `KYC_ALLOWED_PAGES`; `requires:{kyc:true}` added
  to the KYC-gated nav items, so nav-shown == guard-allowed. A pre-KYC user now sees exactly
  Dashboard + Catalog and Catalog opens without a bounce.

### PR #206 — prod follow-ups (two live issues #204 introduced on the box)
1. **Throttle collapse** — `NUM_PROXIES` defaulted to 0 and the deploy `.env` heredoc never set
   `DRF_NUM_PROXIES` → prod keyed throttles on the fixed Docker-bridge REMOTE_ADDR → all clients in
   one bucket (login 10/min GLOBAL). Fixed: `DRF_NUM_PROXIES=1` in `deploy-b2b.yml`'s heredoc.
   Verified: prod `api_settings.NUM_PROXIES == 1`.
2. **Sentry CSP-blocked** — prod sets `VITE_SENTRY_DSN` (bundle → `o4511501294108672.ingest.de.sentry.io`);
   the enforcing `connect-src` omitted it → telemetry silently dropped. Fixed: added
   `https://*.ingest.de.sentry.io` to connect-src.

## ⚠️ Operational facts to KNOW before touching prod
- **Prod Caddy is applied MANUALLY** — deploys never touch it. Master `/etc/caddy/Caddyfile`
  (`{ email }` + `import conf.d/*.caddy`) + per-project `conf.d/{b2b,grades}.caddy`. Apply recipe
  (from the repo fragment, over SSH — `ssh root@176.101.56.141`):
  backup → `cat > /etc/caddy/conf.d/b2b.caddy` → `caddy validate --config /etc/caddy/Caddyfile` →
  `systemctl reload caddy` → auto-restore the backup on validate failure. Backups at
  `/etc/caddy/b2b.caddy.bak-<ts>`.
- **Prod `.env` is rendered from GitHub secrets** via a heredoc in `deploy-b2b.yml` (the `.env` file
  itself is rsync-excluded on deploy). **New prod env vars go in that heredoc**, not a manual `.env`
  edit (a manual edit is overwritten on the next deploy).
- **CSP rollout order matters** — deploy the self-hosted-Inter SPA to `/var/www` BEFORE flipping
  Caddy to enforcing, or the old Google-Fonts build breaks live. (Learned the hard way; the
  adversarial-review agent caught it pre-user-impact.)
- **Deploy races** — two merges seconds apart made the self-hosted runner cancel the newer deploy;
  always confirm a deploy of `main` HEAD actually landed — check `/var/www/railtech-b2b/index.html`
  on the box (grep for `Inter is self-hosted` and the bundle hash).

## ⭐ Eyes-on harness (reused this session — keep using it)
- Local prod build → drive the authenticated Claude-in-Chrome tab. Mint `RefreshToken.for_user(u)`
  → write JSON to `railtech_frontend:/usr/share/nginx/html/__e2e/<name>.json` → in-page
  `document.cookie = 'refresh_token=<t>; path=/api/v1/auth/; max-age=604800; SameSite=Lax'` → reload.
  **UI-logout before switching users** (server sets an httpOnly refresh cookie `document.cookie` can't
  overwrite).
- **CSP verification gotcha:** Chrome's `read_console_messages` starts tracking only AFTER the first
  call → it MISSES load-time CSP violations. To verify a CSP is clean: either install a
  `securitypolicyviolation` listener via `javascript_tool`, OR read console AFTER a reload with
  tracking already active (navigate → read/clear → navigate again → read). "Zero messages on first
  read" is NOT proof.
- Local test users (this machine's DB only, all `SliceC2026*`): `pure.seller@slicec.uz` (SUPPLIER-only,
  L2, ACTIVE sub), `pure.buyer@slicec.uz` (CLIENT-only, L2), `t0.prekyc@slicec.uz` (CLIENT, L1). To
  make a genuine pure seller: `co.types.add(SUPPLIER)` (signal auto-adds CLIENT) then
  `co.types.remove(CLIENT)` (the "never-empty" guard only re-adds CLIENT when types would be empty).
  `username=email` is mandatory (legacy unique field); membership must be `is_primary=True`.

## NEXT (recommended order — nothing is blocking)
1. **Make CI `security` a required status check** in branch protection → INF-02 finally gates merges
   (owner-only GitHub setting; the job passes today).
2. **Django CSP enforcing** — eyes-on the Unfold `/admin/` inner pages under the Report-Only policy
   (`CSP_REPORT_ONLY=false` env flip + `core/csp.py`), then enforce. Today only the SPA is enforcing.
3. **Backend audit backlog** (from `Docs/audit-2026-07-02-security-arch-ux.md`, still OPEN): SEC-06
   django-axes per-account lockout (pairs with SEC-04 as the anti-brute-force layer), SEC-08 upload
   magic-byte check, ARCH-01 async LLM calls (8 sync `client.messages.create` sites block ASGI
   workers 5-30s), ARCH-03 sync WeasyPrint PDF in request path, ARCH-04 N+1 `.count()` in analytics.
4. **vitest 4.x** — `npm audit fix --force` closes the 5 dev-only advisories but is a breaking major;
   own PR, confirm the vitest suite still passes.

## Verify recipe on the new machine
`git pull origin main` (HEAD `4283367`). `make up && make migrate` (DB through `crm/0053` +
`accounts/0033`), restart celery after model changes. `docker compose ps` all healthy. SSH to prod
allowed: `ssh root@176.101.56.141`.
