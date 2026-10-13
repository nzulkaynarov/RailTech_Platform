# ADR-0004 — The three admin planes: the core model (values, world-standard, roadmap)

- **Status:** Accepted (2026-06-26)
- **Extends:** [0001-admin-separation](0001-admin-separation.md), [0002-role-responsibilities](0002-role-responsibilities.md), [0003-multi-tenant-admin-planes](0003-multi-tenant-admin-planes.md)
- **Deciders:** Product owner + Engineering
- **Context:** Before the next global, phased build-out (document/template management, org-admin
  hub, granular operator roles), the owner asked to crystallise the **core**: a precise, shared
  understanding of the *values* (responsibilities + boundaries) of each admin plane, benchmarked
  against world practice, with honest pros/cons. This ADR is that canon. Implementation phases are
  tracked separately and reference this document.

## Decision 1 — Three admin planes, never merged (the core)

A marketplace has **three** distinct administration planes. Collapsing any two is a
confidentiality, accountability, or compliance hole. Owner's terms map as follows.

| Owner's term | Plane | Identity | Tool | OWNS | MUST NOT | Boundary mechanism |
|---|---|---|---|---|---|---|
| «Админ системы (Джанго)» | **Platform Engineer** | `is_superuser=True` | Django **Unfold** + terminal | Deploy, DB migrations, master-data CRUD (lookups: currency/country/UoM/Incoterm), Celery Beat, seed, emergency data fixes, audit inspection (ActivityLog/pghistory/QuoteItemHistory). **Single source of truth — full access.** | Business operations on behalf of any company (no trading/КП/contract as a participant) | Tooling (Unfold) + `ReadOnlyInspectionMixin` |
| «Админ платформы (React)» | **Platform Operator** | `SystemRole.ADMIN`, **no `CompanyMember`** | **PlatformAdminShell** (`/admin/*` React) | Company registration, users, **KYC L1→L3**, supplier subscriptions, role-application moderation, force-overrides (deal stage / approve КП / cancel contract), system settings | Buy / sell / sign / pay / bid **for any company** → backend returns `ADMIN_VIEWER_CANNOT_ACT`. Be a company member. See private trade data except under audited access | No-membership invariant (`accounts/0010`) + `ADMIN_VIEWER_CANNOT_ACT` in `services.py` |
| «Админ компании» | **Company Admin** (tenant / org-admin) | `SystemRole.USER` + `CompanyMember(role=OWNER)`, label **«Администратор компании»** | **Org-admin zone** in the SPA (seller/buyer context) | Their **OWN company only**: team & access matrix, member `can_sell`/`can_buy`, charge templates, catalog, company settings (planned: document profile, defaults) | See or touch **any other tenant** | **Row-level scoping by `CompanyMember`** (isolation by construction) + **never-orphan** (≥1 active OWNER always) |

These are not interchangeable. The Operator is the marketplace's *staff*; the Company Admin is a
*customer's* admin; the Engineer is the *vendor's* ops. Different trust domains, different blast radius.

## Decision 2 — World-standard alignment (the principles we hold)

This three-plane split **is** the world standard for multi-tenant marketplace/SaaS governance
(Salesforce internal-admin vs org-admin, Shopify staff vs merchant, GitHub staff vs org owner,
Slack/Okta/Auth0/Google Workspace org admins, AWS control-plane vs tenant). The principles we
commit to, and our current standing:

| Principle (world) | Standing |
|---|---|
| **Segregation of duties** — moderator ≠ engineer ≠ tenant | ✅ held (three planes) |
| **Tenant isolation** — a tenant admin is locked to their org | ✅ held (row-level by `CompanyMember`) |
| **No standing staff access to tenant trade data; only audited, reasoned, time-boxed break-glass / impersonation** (SOC2 / GDPR) | ⚠️ partial — operator reads trade data for overrides, but break-glass is not yet formalised (gap G2) |
| **Self-service tenant admin** — tenants manage their own users/roles/settings | ✅ designed; the zone is thin (gap G3) |
| **Least privilege + granular staff roles** — support ≠ billing ≠ KYC ≠ moderation | ❌ operator is a single all-powerful `ADMIN` (gap G1) |
| **RBAC presets + a permission matrix** (action/field level) | 🟡 presets + `can_sell`/`can_buy` exist; a full action/field matrix does not (gap G4) |
| **Least-privilege & logged engineer access** (break-glass even for ops) | ⚠️ superuser has full DB access; partially mitigated by `ReadOnlyInspectionMixin` (gap G6) |

## Decision 3 — Pros / cons of our solution (honest)

**Strengths (keep):** clean 3-plane separation = world-standard, not a bespoke invention;
`ADMIN_VIEWER_CANNOT_ACT` makes "a support agent ran a trade" structurally impossible;
tenant isolation by construction scales to many sellers; never-orphan prevents un-administerable
companies; Unfold reserved for engineers keeps business users out of raw data.

**Weaknesses → the roadmap (gaps G1–G6):**
- **G1 — Operator is a monolith.** One `ADMIN` = KYC + billing + moderation + force-override. No
  segregation of duties *within* the operator plane.
- **G2 — No audited break-glass.** The operator can read private trade data for overrides, but it
  is not modelled as logged, reason-bound, time-boxed impersonation/access.
- **G3 — Org-admin (tenant) zone is under-built.** Charge templates still in Unfold (interim);
  document profile, defaults, and email/document templates not yet there.
- **G4 — Access matrix is coarse.** `can_sell`/`can_buy` + role codes, not a real
  role/member → action/field-group permission engine with presets + overrides.
- **G5 — No designated primary** (billing/legal-responsible) above the never-orphan floor.
- **G6 — Engineer = full DB access.** A SOC2/audit concern; wants logging + minimisation
  (break-glass for Unfold fixes).

## Decision 4 — Where features live (the hub split that flows from this)

Everything business-configurable leaves Django Unfold for **React admin zones**, grouped by the
plane that *owns* it:

- **Engineer / master-data / lookups → Unfold.**
- **Platform-Operator features** (onboarding, users, KYC, subscriptions, moderation, **platform
  email templates**, platform config) → **PlatformAdminShell** (React). *Transactional emails are
  one-per-platform → operator-owned.*
- **Company business config** (team & access matrix, charge templates, **company document
  profile** = requisites/logo/footer for КП/contract/invoice, defaults: Incoterm/cost currency/
  numbering) → **Company-Admin org-admin zone** (React, tenant-scoped). *Each seller's documents
  carry that seller's own requisites → tenant-owned.*

## Decision 5 — Resolutions to the three open questions (ADR's recommended decisions; adjustable)

1. **Operator granularity (G1):** introduce granular operator sub-roles under `SystemRole.ADMIN`
   as a planned refinement — target presets **SUPPORT, KYC_OFFICER, BILLING_OPERATOR, MODERATOR,
   SUPER_OPERATOR** (least privilege). Keep a single `ADMIN` until the granular layer is built; do
   not block current work on it.
2. **Break-glass (G2):** plan it as a **near-term compliance item**, layered on the existing
   `ActivityLog` — operator access to a tenant's private trade data records who/when/why/which
   entity (reason required, time-boxed). Not a blocker for the org-admin hub, but ordered before
   onboarding many real external sellers.
3. **Company defaults (Incoterm / cost currency / numbering):** live in the **tenant org-admin
   hub** (Company Admin), not Unfold, not PlatformAdminShell. **Decided.**

## Consequences

- The Engineer and Operator planes already match this model — no rework. The work is to **build out
  the tenant org-admin hub (G3/G4)**, then **harden the operator plane (G1/G2)**, then **G5/G6**.
- Phased global build-out references this ADR. Suggested order: (1) tenant org-admin hub
  (doc profile + charge templates + defaults + access matrix) & platform email templates →
  (2) operator sub-roles + break-glass → (3) designated primary + engineer access logging.
- Terminology stays per ADR-0003: users + Platform Operator + Company Admin («Администратор
  компании»); `WorkspaceRole.OWNER` remains the stable code.
