"""AI catalog-match telemetry (spec-remaining-2026-07-07, AI-калибровка).

`AI_DRAFT_MATCH_CONFIDENCE` (the fuzzy auto-bind threshold in draft-КП generation) is a guess —
this model records every AI top-candidate proposed for a draft line together with what the seller
eventually did about it (kept it in the sent КП / reassigned / cleared / bound a below-threshold
suggestion manually). `manage.py ai_match_report` sweeps thresholds over the resolved rows to
compute precision/coverage, so the env value can be tuned on real traffic without a deploy.
"""

from django.db import models


class AIMatchOutcome(models.Model):
    """One row per AI fuzzy top-candidate proposed for a draft-КП line.

    Written inside `generate_draft_quote` (crm/services/draft_quote.py) for BOTH bound and
    below-threshold candidates — the below-threshold rows are what lets the report answer
    "what would a lower threshold have bound, and would it have been right?". Resolved by the
    seller's later actions (reassign / clear / send) via crm/services/ai_telemetry.py.
    """

    RESOLUTION_PENDING = "PENDING"
    RESOLUTION_SENT = "SENT"  # КП sent with no explicit re-match action on the line
    RESOLUTION_REASSIGNED = "REASSIGNED"  # seller picked a different product for an auto-bound line
    RESOLUTION_CLEARED = "CLEARED"  # seller removed the binding
    RESOLUTION_MANUAL_BOUND = "MANUAL_BOUND"  # seller manually bound a line the AI left unbound

    RESOLUTION_CHOICES = [
        (RESOLUTION_PENDING, "Pending"),
        (RESOLUTION_SENT, "Sent unchanged"),
        (RESOLUTION_REASSIGNED, "Reassigned"),
        (RESOLUTION_CLEARED, "Cleared"),
        (RESOLUTION_MANUAL_BOUND, "Manually bound"),
    ]

    quote = models.ForeignKey(
        "crm.Quote",
        on_delete=models.CASCADE,
        related_name="ai_match_outcomes",
        help_text="The draft КП the candidate was proposed for (deleted draft → telemetry row goes too)",
    )
    quote_item = models.ForeignKey(
        "crm.QuoteItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_match_outcomes",
        help_text="The draft line; NULL after the seller deletes the line from the draft",
    )
    seller_company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Issuing seller at draft time (report dimension)",
    )
    line_raw = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="The raw request line the candidate was matched against",
    )
    candidate_product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="AI top candidate (top-1 is the only candidate auto-bind ever considers)",
    )
    confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        help_text="AI confidence of the top candidate (0..1)",
    )
    threshold_used = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        help_text="AI_DRAFT_MATCH_CONFIDENCE in effect at draft time",
    )
    auto_bound = models.BooleanField(
        help_text="confidence >= threshold at draft time → the candidate was bound into the draft"
    )
    resolution = models.CharField(
        max_length=16,
        choices=RESOLUTION_CHOICES,
        default=RESOLUTION_PENDING,
        db_index=True,
    )
    final_product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="What the line actually carried after resolution (ground truth for the report)",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "AI match outcome"
        verbose_name_plural = "AI match outcomes"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"AIMatchOutcome #{self.pk} conf={self.confidence} {self.resolution}"
