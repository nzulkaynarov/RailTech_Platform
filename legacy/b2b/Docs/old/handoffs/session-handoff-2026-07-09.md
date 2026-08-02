# Session handoff — 2026-07-09 (PDF docs + review findings)

_Cross-machine handoff. Continue tomorrow on another computer: `git fetch --all`, read this, pick up the open PRs._

## State: main is clean; all work is in OPEN PRs (nothing uncommitted)

Hosted GitHub Actions CI is **down (billing)** — every PR's checks fail at runner-provision (steps=0), NOT because of the code. All work is validated LOCALLY (backend pytest, frontend build+vitest, schema regenerated). Self-hosted **deploy runner works**; #270 (doc refactor) already deployed successfully.

## Open PRs (merge order recommendation)

| PR | Branch | What | Priority |
|---|---|---|---|
| **#275** | `fix/billing-multiseller-leak` | 🔴 HIGH — losing co-routed seller saw the WINNER's contract/invoice/act/payment on a shared multi-seller deal. Scoped seller billing visibility to owned docs (`contract.quote.seller_company`) + null-owner routing fallback (WP-1 kept). | **merge first (security)** |
| **#274** | `fix/roles-never-orphan-gap` | 🔴 HIGH — sole legacy-OWNER (company_role NULL) could self-reassign to a permission-less role → company orphaned (0 admins). Unified `assign_role_to_member` on `company_active_admins` floor. | **merge (security)** |
| **#273** | `fix/review-docs-findings` | CTA dead-end (honest wording), money_words wrong currency (CNY→ISO code), money_words IndexError ≥10^15 (→ quadrillion + degrade). | normal |
| **#276** | `fix/contract-sign-side` | 🟡 MED — contract sign buttons/badge from page context, not real side → dual buy+sell saw wrong button. Server `viewer_can_sign_client/manager` hints (single source of truth w/ sign auth); schema regenerated. | normal |
| **#272** | `feat/invalidate-document-pdfs` | `manage.py invalidate_document_pdfs` — clears cached `pdf_file` so EXISTING docs re-render with the new template (why the refactor wasn't visible on old КП). | normal |

All 5 are MERGEABLE, base=main, independent (no stacking). Each has tests.

## After merging: roll out the document redesign to existing docs (prod, owner-run)

The doc refactor (#270/#271, already on main+prod) only affects NEWLY rendered PDFs — existing КП/contracts serve cached `pdf_file`. Once #272 is merged+deployed:
```
docker compose exec backend printenv DATABASE_URL          # confirm PROD db
docker compose exec backend python manage.py invalidate_document_pdfs --dry-run
docker compose exec backend python manage.py invalidate_document_pdfs   # or --sent-only / --since
```

## What was done today (context)

1. **CRM document PDF refactor** — phases 0/1/3/4 (money formatting + self-written RU amount-in-words, base design system, 10 legal contract articles, invoice payment block, act line-item table). Phase 2 (manager block + text CTA) done RU-only; QR deferred (needs PyPI dep). **Documents stay RU-only — owner decided Phase 5 EN is out of scope.** All merged (#270/#271) + deployed. Eyes-on via sips PDF→PNG.
2. **Phase E U3 (WorkspaceRole→permission)** — discovered it was ALREADY merged (commit 268384e, steps 3-5). Ran the only open acceptance item: **eyes-on the full заявка→КП→контракт chain on a migrated tenant — PASSED** (every gate works; also fails correctly on KYC/subscription/FSM). U3 fully closed.
3. **Multi-agent review of recent changes** (HEAD~20..HEAD) → 6 confirmed findings, all fixed (PRs above).

## Known issues / notes

- `smoke_full_cycle` management command is **stale/broken** — drives all business ops as a platform ADMIN, which the admin-viewer guard correctly blocks (`ADMIN_VIEWER_CANNOT_ACT`). Needs rewrite to use company-member actors. Not a product regression.
- Deferred (not started): **QR code on КП** (needs `segno`/`qrcode` PyPI dep + hashed-lock regen — risk to `deps-lock` CI gate); **ВЭД-reviewer restoration** (new seed role «Менеджер ВЭД» = «Менеджер по продажам» + quote.review — product decision, pre-existing since migration 0030, additive).
- Gotcha: don't run two pytest on the same test DB concurrently (schema-create deadlock). Line-length: check with Python (awk counts Cyrillic as 2 bytes). No black/flake8/pdftoppm/pip-tools in the backend container.
