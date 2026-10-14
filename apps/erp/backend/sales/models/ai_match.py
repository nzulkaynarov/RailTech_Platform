"""AI catalog-match telemetry."""

from django.db import models


class AIMatchOutcome(models.Model):
    """One row per AI fuzzy top-candidate proposed for a draft-КП line."""

    RESOLUTION_PENDING = "PENDING"
    RESOLUTION_SENT = "SENT"
    RESOLUTION_REASSIGNED = "REASSIGNED"
    RESOLUTION_CLEARED = "CLEARED"
    RESOLUTION_MANUAL_BOUND = "MANUAL_BOUND"

    RESOLUTION_CHOICES = [
        (RESOLUTION_PENDING, "Pending"),
        (RESOLUTION_SENT, "Sent unchanged"),
        (RESOLUTION_REASSIGNED, "Reassigned"),
        (RESOLUTION_CLEARED, "Cleared"),
        (RESOLUTION_MANUAL_BOUND, "Manually bound"),
    ]

    quote = models.ForeignKey(
        "sales.Quote",
        on_delete=models.CASCADE,
        related_name="ai_match_outcomes",
        help_text="The draft КП the candidate was proposed for (deleted draft → telemetry row goes too)",
    )
    quote_item = models.ForeignKey(
        "sales.QuoteItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_match_outcomes",
        help_text="The draft line; NULL after the seller deletes the line from the draft",
    )
    seller_company = models.ForeignKey(
        "parties.Company",
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
