"""КП line-item serializer (`QuoteItem`).

Split out of the monolithic ``crm/serializers.py`` (ARCH refactor) — behaviour
unchanged. Enforces the seller-only cost-field redaction and the machine-code input
caps the bulk endpoints echo verbatim.
"""

from django.conf import settings
from rest_framework import serializers

from crm.models import QuoteItem
from master_data.models import Currency


class QuoteItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_domain = serializers.CharField(source="product.domain_type.code", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_gost = serializers.CharField(source="product.gost_drawing", read_only=True)
    # Fallbacks so the buyer's review grid can show a catalog line's identity from the linked
    # Product when the denormalised copy is blank (audit M12) — single source of truth.
    product_mpn = serializers.SerializerMethodField()
    product_uom = serializers.SerializerMethodField()
    offer_supplier_name = serializers.CharField(source="offer.supplier.name", read_only=True)

    def get_product_mpn(self, obj) -> str:
        return obj.product.manufacturer_part_number if obj.product_id else ""

    def get_product_uom(self, obj) -> str:
        return obj.product.uom.name if (obj.product_id and obj.product.uom_id) else ""

    # UBL data-quality gate: a line must be identified by a name OR an item code
    # (mpn / ГОСТ-чертёж) OR a matched product. Incomplete lines are highlighted in
    # the buyer's review grid and block submission until completed.
    is_incomplete = serializers.SerializerMethodField()

    def get_is_incomplete(self, obj) -> bool:
        return not (
            (obj.imported_raw_name or "").strip()
            or (obj.mpn or "").strip()
            or (obj.gost_drawing or "").strip()
            or obj.product_id
        )

    # Currency travels as its code ("USD") in both directions — the frontend grid
    # (formatMoney) and the manual "Add item" path use the code, never the PK.
    frozen_currency = serializers.SlugRelatedField(
        slug_field="code",
        queryset=Currency.objects.all(),
        required=False,
        allow_null=True,
        error_messages={
            "does_not_exist": "CURRENCY_NOT_FOUND",
            "invalid": "CURRENCY_NOT_FOUND",
        },
    )

    # E2 + bulk-update: EVERY bounds violation must surface as a machine code — the
    # bulk endpoint returns rows[].errors verbatim and the frontend matches codes by
    # value (Rule 2/7). Explicit field declarations bypass the auto-mapped model
    # validators (whose messages are DRF prose); validate_<field> re-enforces the
    # same model bounds (KP-04 MinValue / MaxValue) with codes. Caps: settings.QUOTE_ITEM_MAX_*.
    quantity = serializers.IntegerField(required=False)
    frozen_base_price = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    logistics_cost = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    customs_duty = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    margin_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    lead_time_days = serializers.IntegerField(required=False)

    def validate_quantity(self, value):
        if value is not None and value < 1:
            raise serializers.ValidationError("QUOTE_ITEM_QTY_INVALID")
        if value is not None and value > settings.QUOTE_ITEM_MAX_QUANTITY:
            raise serializers.ValidationError("QUOTE_ITEM_QTY_TOO_LARGE")
        return value

    def _validate_price_cap(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("QUOTE_ITEM_PRICE_INVALID")
        if value is not None and value > settings.QUOTE_ITEM_MAX_UNIT_PRICE:
            raise serializers.ValidationError("QUOTE_ITEM_PRICE_TOO_LARGE")
        return value

    def validate_frozen_base_price(self, value):
        return self._validate_price_cap(value)

    def validate_logistics_cost(self, value):
        return self._validate_price_cap(value)

    def validate_customs_duty(self, value):
        return self._validate_price_cap(value)

    def validate_margin_percent(self, value):
        # Mirrors the model bound MaxValueValidator(500) / MinValueValidator(0).
        if value is not None and not (0 <= value <= 500):
            raise serializers.ValidationError("QUOTE_ITEM_MARGIN_INVALID")
        return value

    def validate_discount_percent(self, value):
        # Mirrors the model bound MaxValueValidator(100) / MinValueValidator(0).
        if value is not None and not (0 <= value <= 100):
            raise serializers.ValidationError("QUOTE_ITEM_DISCOUNT_INVALID")
        return value

    def validate_lead_time_days(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("QUOTE_ITEM_LEAD_TIME_INVALID")
        return value

    # Odoo-style display_type: pricing/quantity fields that SECTION/NOTE rows must never carry —
    # a group header / free-text note has no price. If a client sends any of these non-zero on a
    # non-ITEM row we reject with SECTION_NOTE_NO_PRICING rather than silently zero it, so the grid
    # never ships a section with a stray price and the buyer projection can trust the type.
    _PRICING_FIELDS = (
        "frozen_base_price",
        "logistics_cost",
        "customs_duty",
        "margin_percent",
        "discount_percent",
    )

    def validate(self, attrs):
        from decimal import Decimal

        # Effective display_type: the payload's value on write, else the existing row's (partial
        # PATCH may omit it). Only ITEM rows may carry pricing / be marked optional.
        display_type = attrs.get("display_type")
        if display_type is None and self.instance is not None:
            display_type = self.instance.display_type
        if display_type and display_type != QuoteItem.DisplayType.ITEM:
            for field_name in self._PRICING_FIELDS:
                value = attrs.get(field_name)
                if value is not None and Decimal(str(value)) != Decimal("0"):
                    raise serializers.ValidationError({field_name: ["SECTION_NOTE_NO_PRICING"]})
            # A SECTION/NOTE is never an "optional priced line" — it is not a line at all.
            if attrs.get("is_optional"):
                raise serializers.ValidationError({"is_optional": ["SECTION_NOTE_NO_PRICING"]})
        return attrs

    class Meta:
        model = QuoteItem
        fields = [
            "id",
            "quote",
            "display_type",
            "is_optional",
            "position",
            "product",
            "product_name",
            "product_domain",
            "product_sku",
            "product_gost",
            "product_mpn",
            "product_uom",
            "offer",
            "offer_supplier_name",
            "imported_raw_name",
            "name_canonical",
            "quantity",
            "unit",
            "unit_code",
            "mpn",
            "gost_drawing",
            "hs_code",
            "note",
            "is_incomplete",
            "assigned_at",
            "frozen_base_price",
            "frozen_currency",
            "logistics_cost",
            "customs_duty",
            "margin_percent",
            "discount_percent",
            "lead_time_days",
            "landed_cost",
            "final_price_excl_vat",
            "version",
        ]
        # `version` is READ-ONLY on the serializer (it appears in every read so the client knows
        # the row's current revision) but is NEVER persisted from client input — the optimistic
        # concurrency check + increment live in the service (bulk) and viewset (single PATCH),
        # which read the client's known version straight off the request body. This mirrors how
        # the bulk endpoint already handles it and makes the counter impossible to spoof.
        read_only_fields = ["landed_cost", "final_price_excl_vat", "version"]

    # Cost-structure fields that reveal the seller's markup. Visible to the
    # seller team / platform admin / superuser only — NEVER to the buyer, who
    # could otherwise derive the margin. (PDF is gated separately in
    # crm/templates/crm/quote_pdf.html.)
    _SELLER_ONLY_FIELDS = (
        "frozen_base_price",
        "logistics_cost",
        "customs_duty",
        "margin_percent",
        "landed_cost",
    )

    def _can_see_costs(self, quote) -> bool:
        # Per-quote (C1): cost/margin only on a quote the viewer's own company prepared —
        # not a competitor's quote on the same multi-seller-routed deal. Cached by quote id
        # so a list of items on one quote doesn't re-query the preparer's memberships.
        cache = getattr(self, "_cost_cache", None)
        if cache is None:
            cache = self._cost_cache = {}
        qid = getattr(quote, "id", None)
        if qid not in cache:
            user = getattr(self.context.get("request"), "user", None)
            from accounts.services.permissions import can_view_quote_costs_for

            cache[qid] = bool(user and quote is not None and can_view_quote_costs_for(user, quote))
        return cache[qid]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # QuoteItem → its .quote; Quote → itself.
        if not self._can_see_costs(getattr(instance, "quote", instance)):
            for field_name in self._SELLER_ONLY_FIELDS:
                data.pop(field_name, None)
        return data
