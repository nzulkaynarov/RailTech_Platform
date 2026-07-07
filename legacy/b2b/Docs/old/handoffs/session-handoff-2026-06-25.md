# RailTech — Session handoff 2026-06-25 (RBAC matrix + AI features)

> Cross-machine source of truth (Claude Code memory is machine-local; this travels via
> `git pull`). Continues docs/ops/ai-features-roadmap-2026-06-18.md.

## TL;DR
Replaced the home-grown Buy/Sell capability toggles with a world-standard **Role+Permission-set**
access matrix (company-defined roles + permission checkboxes), and shipped the **first AI feature**
(semantic заявка→catalog matching). All verified eyes-on in the local browser. Several branches
are pushed and **waiting to be merged**.

## Branches (merge these — pushed, green, verified)
Merge order = creation order; each was cut from the previous `main`.
1. `fix/logout-and-ux-gaps` — **MERGED** (#124): async logout fix + i18n (workspace roles, deal stage).
2. `feat/company-roles-rbac` — **MERGED** (#125): RBAC phase-1 backend (CompanyRole model, Permission
   catalog, migration 0023 seeds 5 roles/company + maps members, `member_has_permission`).
3. `feat/rbac-phase2` — **MERGED** (#?, in main @970a24b): roles API + Team&Roles UI (removes Buy/Sell)
   + additive permission guards.
4. `feat/rbac-polish` — **PUSHED, NOT merged**: readable permission labels + КП cost/margin gated on
   `quote.view_cost_margin` (`can_view_quote_costs`).
5. `feat/ai-semantic-match` — **PUSHED, NOT merged**: AI #1 backend + КП-builder UI.

Verify what's in main: `git log --oneline -8`. If 4 & 5 are not in `main`, merge them before continuing.

## RBAC — what exists now (see Docs/ops/rbac-roles-design-2026-06-25.md + memory rbac_role_permission_set_2026_06_25)
- `accounts.constants.Permission` (14 codes) + `PERMISSION_GROUPS` + `ROLE_TEMPLATES` (5 presets).
- `accounts.CompanyRole(company, name, permissions[], is_system, has_perm())` + `CompanyMember.company_role`.
- `accounts.services.member_has_permission(user, company_id, perm)` (company_role → fallback to OWNER/
  can_sell/can_buy). `can_view_quote_costs(user)` gates КП cost/margin redaction (crm/serializers).
- API: `CompanyRoleViewSet` (/api/v1/accounts/company-roles/, team.manage guard, is_system immutable),
  `/accounts/permissions/` (catalog), `/company-roles/assign/`. Member serializer exposes company_role(+_name).
- UI: Settings → Team → "Company Roles" (create role + grouped permission checkboxes) + per-member role
  dropdown. `frontend/src/components/Cabinet/CompanyTeamSettings.tsx`. "OWNER" code stays, displays
  "Администратор компании" (ADR-0003).

### RBAC polish still TODO
- **Invite assigns a WorkspaceRole, not a CompanyRole** — invited members get no `company_role` (fall to
  legacy fallback). Switch the invite flow + `invite_member` service to assign a CompanyRole.
- **Purge legacy WorkspaceRoles** (Директор/Бухгалтер/Сотрудник — beyond the canonical set; same class as
  the retired SystemRoles). Reassign members' `role` FK to a kept code first (it's PROTECT), then delete.

## AI features — roadmap status (order = docs/ops/ai-features-roadmap-2026-06-18.md)
| # | Feature | Size | Status |
|---|---|---|---|
| 1 | Semantic match заявка→catalog | M | ✅ DONE (backend+UI, verified) |
| 5 | Bilingual normalisation (ru/uz/en) | S | NEXT — strengthens #1 (trigram preselect misses Latin↔Cyrillic) |
| 3 | КП-vs-заявка diff | M | queued |
| 7 | Pre-flight заявка check | S | queued |
| 4 | Chat reply-assist | S | queued |
| 6 | PDF contract/invoice extraction | M | queued |
| 2 | PIM catalog enrichment (seller) | M | queued |
| 8 | Conversational заявка builder | L | last (builds on #1) |

### AI #1 — the established pattern to reuse for the rest
- **Backend service:** `backend/sourcing/services_ai.py` → `match_lines_to_catalog(lines, domain_code, top_k)`
  + `_shortlist_products` (pg_trgm `TrigramSimilarity` + exact ГОСТ). Reuses `_client()` + `output_config`
  json_schema. **Rule 1:** Claude only RANKS a DB shortlist — product_id validated against the shortlist,
  hallucinated ids dropped. Logs token usage. Returns [] when `settings.AI_IMPORT_ENABLED` is False.
- **Endpoint:** `POST /api/v1/sourcing/match-catalog/` (`MatchCatalogView`, IsAuthenticated, throttle
  scope `ai_match` 20/min, 50-line cap, 503 AI_DISABLED / 400 LINES_REQUIRED).
- **Frontend:** `crmApi.matchCatalog` + `useMatchCatalog` + `AICatalogMatchDialog.tsx`; button in
  `QuoteBuilderGrid.tsx` shown when any item has `!product`; binds via `useUpdateQuoteItem({id,{product}})`.
  **Gotcha:** the list endpoint is paginated — frontend api MUST unwrap `.results` (and `{groups}` for the
  permission catalog); forgetting this crashed the page with "x.map is not a function".
- **Tests:** stub `_client` (no paid calls) — see `backend/sourcing/tests/test_ai_match.py`.

### #5 next-step notes
Extend `ITEM_SCHEMA` in services_ai with `name_canonical` (canonical Russian search name; keep original
`name`). To pay off, persist it (add a QuoteItem field) and search BOTH name + name_canonical in
`_shortlist_products`, and pass it from the match dialog. That fixes the transliteration gap observed
("tormoznaya koloda" didn't preselect against Cyrillic catalog).

## Hard-won lessons (don't relearn)
- **Verify agents — they can report success falsely.** A workflow build-agent claimed "15 tests pass" but
  its files were never in the tree (`git status` + import check caught it; I rebuilt that slice by hand).
- **Always eyes-on in the local browser after frontend changes.** Caught 2 real crashes (paginated
  `.results` / `{groups}` not unwrapped) that the agent's tsc + the test scripts missed.
- Parallel workflow agents must own DISJOINT files; pass the API contract explicitly so they align.

## Local verify recipe (this machine; replicate keys/data on the other)
- Backend tests: `docker compose exec -T backend python -m pytest <path> -p no:cacheprovider --create-db -q`
  (use `--create-db` after branch switches; addopts default to `--reuse-db --nomigrations`).
- tsc: `docker run --rm -v "$PWD/frontend":/app -w /app node:22 sh -c "npx tsc --noEmit"`.
- i18n symmetry: `python3 scripts/check_i18n_symmetry.py` (run from repo root).
- Frontend after edits: `docker compose up -d --build frontend`; browser at `localhost:5173`.
- AI needs `ANTHROPIC_API_KEY` in `.env` (local + prod both set; model `claude-opus-4-8`,
  `AI_IMPORT_ENABLED` auto-derives from the key).
- Test seller: `seller.local@railtech.uz` / `Test1234!` (defaults to BUYER context — switch the sidebar
  context to Seller). Deal 2 (D-2026-002, quote 5) has 2 unmatched КП items seeded for the AI-match demo.

## Other open context (unchanged)
- **Prod is barren** (0 products, 5 deals) — the "3/10" felt experience is mostly empty data, not broken
  code. After merging, deploy + populate the catalog. Never seed prod without owner OK.
- AI parsing (заявка import) works + is wired (ImportRequestDialog, AI default-on, key set on prod).
