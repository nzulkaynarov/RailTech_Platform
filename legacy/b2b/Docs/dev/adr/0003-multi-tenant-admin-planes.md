# ADR-0003 — Multi-tenant admin planes, terminology, and the never-orphan invariant

- **Status:** Accepted (2026-06-24)
- **Supersedes/extends:** [0001-admin-separation](0001-admin-separation.md), [0002-role-responsibilities](0002-role-responsibilities.md)
- **Context:** Moving from single-seller RailTech toward a true many-sellers / many-buyers
  marketplace, while keeping tenant confidentiality. This ADR records the model converged on.

## Decision 1 — Three distinct admin planes (never merge them)

A marketplace has three separate administration planes. Collapsing any two is a confidentiality
or accountability hole.

| Plane | Who | Tool | Owns | MUST NOT |
|---|---|---|---|---|
| **Platform Engineer** | `is_superuser=True` | Django **Unfold** + terminal | Migrations, master-data CRUD (lookups), Celery Beat, emergency fixes. **Single source of truth, full access.** | Business operations on behalf of companies |
| **Platform Operator** | `SystemRole.ADMIN`, no memberships | **PlatformAdminShell** (`/admin/*` React) | Company registration, users, KYC, subscriptions, moderation. | Buy/sell/act for any company → backend returns `ADMIN_VIEWER_CANNOT_ACT`. See private trade data only under audit |
| **Company Admin** (tenant/org-admin) | `SystemRole.USER` + `CompanyMember(role=OWNER)` | **Org-admin zone** in the SPA seller/buyer context | Their OWN company only: team & access matrix, charge templates, catalog, settings. | See or touch any other tenant |

The Company Admin is **tenant-scoped by construction** — that scoping (row-level by
`CompanyMember`) is what gives confidentiality and lets us onboard many sellers.

## Decision 2 — Terminology: a person is a USER with rights, not a "type"

- On the platform there are only **Users** (`SystemRole.USER`, attached to companies via
  `CompanyMember`) and the **Platform Operator** (`SystemRole.ADMIN`). "In React: users + admin."
- "Owner" is **not** a user type — it is the **full-rights workspace role inside one company**.
  Internal code stays `WorkspaceRole.OWNER` (stable identifier, referenced across the codebase);
  the **display label is «Администратор компании»** (RU) / «Company Admin» (EN).
- The first user who registers a company and completes onboarding receives the Company-Admin role
  (all rights). They may delegate it to others and re-delegate / downgrade via the access matrix.
- Access model = a **permission matrix** engine (role/member → allowed actions/field-groups) with
  **named role presets** (Company Admin, Sales Manager, Logist, …) layered on top for usability —
  not raw checkboxes per person.

## Decision 3 — Never-orphan invariant (one irreducible admin anchor)

Multiple Company Admins are allowed. But a company must **always keep ≥1 active Company Admin**
(the party accountable for KYC/billing). Enforced in `accounts/services/members.py`:
`remove_company_member` refuses to delete the last active `OWNER` (`CANNOT_REMOVE_LAST_COMPANY_ADMIN`);
the role must be **transferred** first. This prevents orphaned companies (nobody can administer,
no KYC/billing responsible). A distinct single "primary/billing-responsible" designation is a
planned refinement layered on top of this invariant.

## Decision 4 — Where features live (refines ADR-0001's two surfaces into three)

- Engineer / master-data / lookups → **Unfold**.
- Platform-operator features (onboarding, moderation) → **PlatformAdminShell**.
- **Company business config** (team & access matrix, **charge templates**, catalog) → **Company-Admin
  org-admin zone**, NOT Unfold and NOT PlatformAdminShell.
  - Consequence: the КП charge-templates config (currently in Unfold as an interim) **moves to the
    org-admin zone** once the КП cost-engine branch merges.

## Decision 5 — Multi-seller routing is the confidentiality keystone (planned)

Today every seller sees every buyer's заявка (`seller_sees_all_deals` is see-all — by design for
single-seller RailTech). For many sellers this is a **cross-seller confidentiality leak**. The
keystone work: route each заявка to its **target seller(s)** (FK/M2M) and **scope the seller
queryset** so a seller sees only заявки directed at them. This MUST land before enabling multiple
sellers in production.

## Consequences

- The existing Platform Operator (`PlatformAdminShell`, `ADMIN_VIEWER_CANNOT_ACT`) and Platform
  Engineer (Unfold/superuser) planes already match this model — no rework, only the org-admin zone
  needs building out from the current `CompanyTeamSettings` seed.
- Foundation delivered with this ADR: never-orphan invariant + the OWNER→«Администратор компании»
  relabel (code stable).
