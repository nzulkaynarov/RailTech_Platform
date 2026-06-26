"""Race-safe, per-company sequential document numbering.

Replaces `Model.objects.filter(created_at__year=...).count() + 1`, which races:
two concurrent issuers read the same count and mint the same number, hitting the
`number` unique constraint → 500. Here a per-(company, doc_type, year)
DocumentSequence row is locked with select_for_update, so concurrent callers
serialize and each gets a distinct, gap-free number.

Per-company branding: a selling company that sets a `doc_number_prefix` mints under
its OWN scoped counter and prefix — `ACME-CT-2026-00001`. A company WITHOUT a prefix
(and the actor=None automation path) uses the SHARED platform counter (company=NULL)
and the platform format `CT-2026-00001`.

GLOBAL-UNIQUE SAFETY: Contract/Invoice/Act.number is globally `unique=True`. To keep
two companies from colliding on that constraint, a per-company counter is used ONLY
when the company carries a (non-empty) prefix — the prefix is the brand discriminator
that makes `{prefix}-{label}-{year}-{NNNNN}` globally distinct. Prefix-less companies
fall back to the single platform counter, so they share ONE monotonic sequence and
can never mint the same `{label}-{year}-{NNNNN}` twice.
"""

from typing import Optional

from django.utils import timezone


def _company_prefix(company) -> str:
    """The company's configured numbering prefix, or "" when none/not a company.

    Reads CompanySettings.doc_number_prefix WITHOUT creating a settings row (a plain
    filter) — numbering is a hot path and must not write on read.
    """
    if company is None:
        return ""
    from accounts.models import CompanySettings

    company_id = getattr(company, "pk", company)
    row = CompanySettings.objects.filter(company_id=company_id).only("doc_number_prefix").first()
    return (row.doc_number_prefix or "").strip() if row else ""


def next_document_number(doc_type: str, label: str, company=None) -> str:
    """Return the next gap-free document number from a locked counter.

    Formats `{prefix}-{label}-{year}-{NNNNN}` when `company` has a doc_number_prefix,
    otherwise the platform default `{label}-{year}-{NNNNN}`. `doc_type` is the short
    storage code of the counter (e.g. "CT"/"INV"/"ACT"); `label` is the human doc kind
    printed in the number (kept equal to doc_type for the existing CT/INV/ACT docs).

    Counter scope: a prefixed company gets its OWN (company, doc_type, year) row; a
    prefix-less company (or company=None) shares the platform (company=NULL) row — see
    the module docstring for why this keeps the global `number` unique safe.

    MUST be called inside the caller's `transaction.atomic()` block — the row lock is
    held until that transaction commits, which is exactly the window in which the
    document row is created with this number.
    """
    from ..models import DocumentSequence

    prefix = _company_prefix(company)
    # Only a prefixed company is routed to its own counter; without a prefix we share
    # the platform counter so the global number can't collide across companies.
    sequence_company_id = (getattr(company, "pk", company) if prefix else None)

    year = timezone.now().year
    # select_for_update locks the row; get_or_create's internal IntegrityError retry
    # handles the first-ever concurrent insert for a (company, doc_type, year).
    seq = DocumentSequence.objects.select_for_update().get_or_create(
        company_id=sequence_company_id, doc_type=doc_type, year=year
    )[0]
    seq.last_value += 1
    seq.save(update_fields=["last_value"])

    if prefix:
        return f"{prefix}-{label}-{year}-{seq.last_value:05d}"
    return f"{label}-{year}-{seq.last_value:05d}"
