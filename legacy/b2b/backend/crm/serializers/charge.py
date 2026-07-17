"""КП charge serializers: charge-type lookup, per-Incoterm templates, and the
document-level expense/discount line (`QuoteCharge`).

Split out of the monolithic ``crm/serializers.py`` (ARCH refactor) — behaviour
unchanged, including the seller-cost redaction on the standalone charges endpoint.
"""

from rest_framework import serializers

from crm.models import ChargeTemplate, ChargeType, QuoteCharge
from master_data.models import DeliveryBasis


class ChargeTypeSerializer(serializers.ModelSerializer):
    """Read-only lookup feed for the КП charge-type dropdown."""

    class Meta:
        model = ChargeType
        fields = ["id", "code", "name"]


class ChargeTemplateSerializer(serializers.ModelSerializer):
    """Company-Admin CRUD for per-Incoterm charge templates (org-admin zone).

    `company` is set by the viewset from the requester's seller company — never
    from the request body — so a Company Admin can only manage their own templates.
    """

    delivery_basis = serializers.SlugRelatedField(slug_field="code", queryset=DeliveryBasis.objects.all())
    delivery_basis_name = serializers.CharField(source="delivery_basis.name", read_only=True)
    charge_type = serializers.SlugRelatedField(slug_field="code", queryset=ChargeType.objects.all())
    charge_type_name = serializers.CharField(source="charge_type.name", read_only=True)

    class Meta:
        model = ChargeTemplate
        fields = [
            "id",
            "delivery_basis",
            "delivery_basis_name",
            "charge_type",
            "charge_type_name",
            "default_amount",
            "default_rate_percent",
            "is_deduction",
            "sort_order",
            "is_active",
        ]


class QuoteChargeSerializer(serializers.ModelSerializer):
    """КП-level expense item / discount (UBL document AllowanceCharge)."""

    charge_type = serializers.SlugRelatedField(slug_field="code", queryset=ChargeType.objects.all())
    charge_type_name = serializers.CharField(source="charge_type.name", read_only=True)

    class Meta:
        model = QuoteCharge
        fields = [
            "id",
            "quote",
            "charge_type",
            "charge_type_name",
            "description",
            "amount",
            "rate_percent",
            "cost_amount",
            "is_deduction",
            "sort_order",
            "resolved_base",
            "resolved_amount",
            "from_template",
            "created_by",
            "created_at",
        ]
        # sort_order is set server-side (append on create / dedicated reorder endpoint); the
        # resolved_* snapshots are computed by recalc — all read-only on the charge serializer.
        read_only_fields = [
            "created_by",
            "created_at",
            "sort_order",
            "resolved_base",
            "resolved_amount",
            "from_template",
        ]

    # Seller-cost / per-charge breakdown — same redaction invariant as QuoteItem/QuoteSerializer.
    # The standalone quote-charges endpoint must NOT serve these to a teammate who lacks
    # quote.view_cost_margin on the КП (a restricted Наблюдатель/logist could otherwise back out
    # the margin). cost_amount is the seller's REAL cost; resolved_* + the per-charge amount/% are
    # the breakdown the client PDF deliberately collapses into one aggregated line.
    _COST_FIELDS = (
        "cost_amount",
        "resolved_base",
        "resolved_amount",
        "amount",
        "rate_percent",
    )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        from accounts.services.permissions import can_view_quote_costs_for

        if not (user and can_view_quote_costs_for(user, instance.quote)):
            for field_name in self._COST_FIELDS:
                data.pop(field_name, None)
        return data
