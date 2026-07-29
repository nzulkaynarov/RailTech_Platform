"""Race-safe, per-company sequential document numbering — now scheme-driven (N1).

Replaces `Model.objects.filter(created_at__year=...).count() + 1`, which races:
two concurrent issuers read the same count and mint the same number, hitting the
`number` unique constraint → 500. Here a per-(company, doc_type, period)
DocumentSequence row is locked with select_for_update, so concurrent callers
serialize and each gets a distinct, gap-free number.

FORMAT is no longer hardcoded. Each company can carry a `DocumentNumberingScheme`
(token mask + padding + reset period + start value); the number is assembled from that
mask. A company without its own scheme falls back to the platform default scheme
(company=NULL, seeded by migration to reproduce the historical format) and finally to
the code-level DEFAULT_SCHEME below — so numbering works with NO scheme row at all
(hot path never writes a scheme on read; Rule 1).

Per-company branding: a selling company that sets a `doc_number_prefix` mints under
its OWN scoped counter and prefix — `ACME-CT-2026-00001`. A company WITHOUT a prefix
(and the actor=None automation path) uses the SHARED platform counter (company=NULL)
and the platform scheme `CT-2026-00001`.

GLOBAL-UNIQUE SAFETY (unchanged): Contract/Invoice/Act.number is globally `unique=True`.
A per-company counter is used ONLY when the company carries a (non-empty) prefix — the
prefix is the brand discriminator that makes the number globally distinct. Prefix-less
companies fall back to the single platform counter AND the platform scheme, so they
share ONE monotonic sequence under ONE format and can never mint the same number twice.
"""

from dataclasses import dataclass, field

from django.utils import timezone

# Reset-period codes (mirrors DocumentNumberingScheme.RESET_* to avoid importing the
# model at module import time / in hot-path branches).
RESET_NEVER = "never"
RESET_YEARLY = "yearly"
RESET_MONTHLY = "monthly"

# Code-level default scheme = the historical hardcoded format, so a company with NO
# scheme row (and no platform row) still mints `{prefix}-{label}-{year}-{NNNNN}`.
DEFAULT_PATTERN = "{prefix}{type}-{YYYY}-{seq}"
DEFAULT_PADDING = 5
DEFAULT_RESET_PERIOD = RESET_YEARLY
DEFAULT_START_VALUE = 0
# Shipped {type}-token labels per doc kind (mirrors DocumentNumberingScheme.DEFAULT_TYPE_LABELS).
# Used as the fallback when a company's scheme leaves a code unset — nothing is hardcoded at
# the call sites: each caller passes the doc's default label, but the scheme's editable
# type_labels override it.
DEFAULT_TYPE_LABELS = {"KP": "КП", "CT": "CT", "INV": "INV", "ACT": "ACT", "DOC": "DOC"}


@dataclass(frozen=True)
class SchemeSpec:
    """Immutable snapshot of the numbering scheme actually used to mint a number."""

    pattern: str = DEFAULT_PATTERN
    padding: int = DEFAULT_PADDING
    reset_period: str = DEFAULT_RESET_PERIOD
    start_value: int = DEFAULT_START_VALUE
    type_labels: dict = field(default_factory=lambda: dict(DEFAULT_TYPE_LABELS))

    @classmethod
    def from_row(cls, row) -> "SchemeSpec":
        return cls(
            pattern=row.pattern,
            padding=row.padding,
            reset_period=row.reset_period,
            start_value=row.start_value,
            type_labels=dict(row.type_labels or {}),
        )

    def label_for(self, doc_type: str, fallback: str) -> str:
        """The editable {type} label for a doc kind — company override → shipped default → the
        caller's fallback. Never hardcoded downstream."""
        value = self.type_labels.get(doc_type)
        if isinstance(value, str) and value.strip():
            return value
        return DEFAULT_TYPE_LABELS.get(doc_type, fallback)


DEFAULT_SCHEME = SchemeSpec()


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


def _scheme_company_id(company, prefix: str):
    """The company id whose scheme/counter applies — the SAME discriminator for both.

    Only a prefixed company is routed to its OWN counter and OWN scheme; without a prefix
    we route to the platform counter AND platform scheme. Tying scheme resolution to the
    exact prefix discriminator that routes the counter keeps the global `number` unique
    safe: all prefix-less callers share one counter under one format.
    """
    return getattr(company, "pk", company) if prefix else None


def _resolve_scheme(scheme_company_id) -> SchemeSpec:
    """Company row → platform (company=NULL) row → code-level DEFAULT_SCHEME."""
    from ..models import DocumentNumberingScheme

    row = None
    if scheme_company_id is not None:
        row = DocumentNumberingScheme.objects.filter(company_id=scheme_company_id).first()
    if row is None:
        row = DocumentNumberingScheme.objects.filter(company__isnull=True).first()
    if row is None:
        return DEFAULT_SCHEME
    return SchemeSpec.from_row(row)


def _period_key(reset_period: str, now) -> str:
    """Counter period key: never → "ALL", monthly → "YYYY-MM", yearly (default) → "YYYY"."""
    if reset_period == RESET_MONTHLY:
        return f"{now.year}-{now.month:02d}"
    if reset_period == RESET_NEVER:
        return "ALL"
    return str(now.year)


def _render_number(scheme: SchemeSpec, *, prefix: str, label: str, now, displayed: int) -> str:
    """Assemble the final number from the scheme's token mask."""
    prefix_segment = f"{prefix}-" if prefix else ""
    seq_str = f"{displayed:0{scheme.padding}d}"
    result = scheme.pattern
    result = result.replace("{prefix}", prefix_segment)
    result = result.replace("{type}", label)
    result = result.replace("{YYYY}", f"{now.year:04d}")  # before {YY} so it isn't clobbered
    result = result.replace("{YY}", f"{now.year % 100:02d}")
    result = result.replace("{MM}", f"{now.month:02d}")
    result = result.replace("{seq}", seq_str)
    return result


def next_document_number(doc_type: str, label: str, company=None) -> str:
    """Return the next gap-free document number from a locked counter.

    The FORMAT comes from the effective DocumentNumberingScheme (company → platform →
    code default); `doc_type` is the short storage code of the counter (e.g. "CT"/"INV"),
    `label` is the human doc kind substituted for the `{type}` token (kept separate: КП
    docs use doc_type "KP" but label "КП").

    Counter scope: a prefixed company gets its OWN (company, doc_type, period) row; a
    prefix-less company (or company=None) shares the platform (company=NULL) row — see
    the module docstring for why this keeps the global `number` unique safe. `period` is
    derived from the scheme's reset_period (never/yearly/monthly).

    MUST be called inside the caller's `transaction.atomic()` block — the row lock is
    held until that transaction commits, which is exactly the window in which the
    document row is created with this number.
    """
    from ..models import DocumentSequence

    prefix = _company_prefix(company)
    scheme_company_id = _scheme_company_id(company, prefix)
    scheme = _resolve_scheme(scheme_company_id)

    now = timezone.now()
    period = _period_key(scheme.reset_period, now)

    # select_for_update locks the row; get_or_create's internal IntegrityError retry
    # handles the first-ever concurrent insert for a (company, doc_type, period).
    seq = DocumentSequence.objects.select_for_update().get_or_create(
        company_id=scheme_company_id,
        doc_type=doc_type,
        period=period,
        defaults={"year": now.year},
    )[0]
    seq.last_value += 1
    seq.save(update_fields=["last_value"])

    displayed = scheme.start_value + seq.last_value
    # The {type} label is resolved from the company's EDITABLE type_labels (falling back to
    # the caller-supplied default), so the printed kind is never hardcoded downstream.
    effective_label = scheme.label_for(doc_type, label)
    return _render_number(scheme, prefix=prefix, label=effective_label, now=now, displayed=displayed)


# ── Editability API (thin, for the N2 Settings editor) ─────────────────────────────

# The doc kinds shown in the live preview, in order — the editable {type} codes. The label
# for each is resolved from the scheme's type_labels (single source of truth: the SAME token
# renderer + label resolution as `next_document_number`, so the editor can never drift).
PREVIEW_TYPE_CODES = ("KP", "CT", "INV", "ACT", "DOC")


@dataclass(frozen=True)
class SchemeView:
    """What the N2 editor reads: the EFFECTIVE scheme + the prefix that would brand it.

    `is_effective` mirrors the global-unique invariant — a company mints under its OWN
    scheme ONLY while it carries a non-empty prefix; prefix-less it uses the platform
    default. The editor surfaces this so the user understands why their custom mask is
    not yet applied (banner), without any blocking.
    """

    scheme: SchemeSpec
    prefix: str
    is_effective: bool


def get_company_scheme_view(company) -> SchemeView:
    """The effective scheme + prefix + effectiveness flag for the N2 Settings editor.

    The scheme carries the editable `type_labels` map so the editor can render one input
    per doc kind (with the shipped default filled in for any code the company hasn't set).
    """
    prefix = _company_prefix(company)
    scheme = _resolve_scheme(_scheme_company_id(company, prefix))
    # Present every editable code, defaulting unset ones — so the editor shows a full form.
    merged_labels = {code: scheme.label_for(code, code) for code in DEFAULT_TYPE_LABELS}
    scheme = SchemeSpec(
        pattern=scheme.pattern,
        padding=scheme.padding,
        reset_period=scheme.reset_period,
        start_value=scheme.start_value,
        type_labels=merged_labels,
    )
    return SchemeView(scheme=scheme, prefix=prefix, is_effective=bool(prefix))


def preview_scheme_numbers(
    company, *, pattern, padding, reset_period, start_value, prefix=None, type_labels=None
) -> list:
    """Dry-run: render example КП/CT/INV numbers for a DRAFT scheme, WITHOUT touching any
    counter (`DocumentSequence` is never read or incremented).

    Validates the draft the same way a save would (model `full_clean` → raises
    django ValidationError on a missing {seq} / empty mask / bad padding) so the preview
    endpoint and the PATCH endpoint reject identical input. Uses the same `_render_number`
    token parser as real minting, so the preview is the single source of truth for format.

    `prefix` is the DRAFT brand prefix from the editor field: when provided (not None) the
    preview renders `{prefix}` from it, so typing a prefix updates the example live (WYSIWYG)
    BEFORE saving. When None, falls back to the company's persisted prefix. `type_labels` is
    the DRAFT editable {type}-label map (same live-reflection role). `seq` is fixed at
    `start_value + 1` (the first number the counter would ever mint).
    """
    from ..models import DocumentNumberingScheme

    candidate = DocumentNumberingScheme(
        pattern=pattern,
        padding=padding,
        reset_period=reset_period,
        start_value=start_value,
    )
    if type_labels is not None:
        candidate.type_labels = type_labels
    # Validate the mask + type_labels fields — company (OneToOne) is irrelevant to a dry-run
    # and its uniqueness check would spuriously fail on the unsaved draft.
    candidate.full_clean(exclude=["company", "created_at", "updated_at"], validate_unique=False)

    spec = SchemeSpec.from_row(candidate)
    effective_prefix = prefix.strip() if prefix is not None else _company_prefix(company)
    now = timezone.now()
    displayed = spec.start_value + 1
    return [
        {
            "type_code": type_code,
            "label": spec.label_for(type_code, type_code),
            "number": _render_number(
                spec, prefix=effective_prefix, label=spec.label_for(type_code, type_code), now=now, displayed=displayed
            ),
        }
        for type_code in PREVIEW_TYPE_CODES
    ]


def get_company_scheme(company) -> SchemeSpec:
    """The EFFECTIVE scheme a company mints under (for live preview / display).

    Honours the same prefix discriminator as minting: a prefix-less company sees the
    platform/default scheme (its own row, if any, is not effective until it sets a
    prefix — that's the global-unique invariant). Returns a plain SchemeSpec so callers
    read `pattern`/`padding`/`reset_period`/`start_value` without touching the ORM.
    """
    prefix = _company_prefix(company)
    return _resolve_scheme(_scheme_company_id(company, prefix))


def set_company_scheme(company, *, pattern=None, padding=None, reset_period=None, start_value=None, type_labels=None):
    """Upsert a company's own DocumentNumberingScheme row (validated). Returns the row.

    Business logic lives here (Rule 8); the N2 DRF view is a thin wrapper. Runs
    `full_clean()` so an invalid pattern (missing {seq}, empty) or empty type label raises
    ValidationError before save. Effectiveness for minting still requires the company to carry
    a prefix (global-unique invariant) — the caller/UX surfaces that.
    """
    from ..models import DocumentNumberingScheme

    if company is None:
        raise ValueError("set_company_scheme requires a company")
    company_id = getattr(company, "pk", company)

    row = DocumentNumberingScheme.objects.filter(company_id=company_id).first()
    if row is None:
        row = DocumentNumberingScheme(company_id=company_id)
    if pattern is not None:
        row.pattern = pattern
    if padding is not None:
        row.padding = padding
    if reset_period is not None:
        row.reset_period = reset_period
    if start_value is not None:
        row.start_value = start_value
    if type_labels is not None:
        # Merge onto the shipped defaults so a partial map never blanks an unset code.
        merged = dict(DEFAULT_TYPE_LABELS)
        merged.update({code: value for code, value in type_labels.items() if code in DEFAULT_TYPE_LABELS})
        row.type_labels = merged
    row.full_clean()
    row.save()
    return row
