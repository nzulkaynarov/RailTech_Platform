"""Race-safe sequential document numbering.

Replaces `Model.objects.filter(created_at__year=...).count() + 1`, which races:
two concurrent issuers read the same count and mint the same number, hitting the
`number` unique constraint → 500. Here a per-(doc_type, year) DocumentSequence
row is locked with select_for_update, so concurrent callers serialize and each
gets a distinct, gap-free number.
"""

from django.utils import timezone


def next_document_number(doc_type: str, prefix: str) -> str:
    """Return `{prefix}-{year}-{NNNNN}` from a locked counter.

    MUST be called inside the caller's `transaction.atomic()` block — the row
    lock is held until that transaction commits, which is exactly the window in
    which the document row is created with this number.
    """
    from ..models import DocumentSequence

    year = timezone.now().year
    # select_for_update locks the row; get_or_create's internal IntegrityError
    # retry handles the first-ever concurrent insert for a (doc_type, year).
    seq = DocumentSequence.objects.select_for_update().get_or_create(doc_type=doc_type, year=year)[0]
    seq.last_value += 1
    seq.save(update_fields=["last_value"])
    return f"{prefix}-{year}-{seq.last_value:05d}"
