from rest_framework import serializers

from master_data.models import Currency, DeliveryBasis
from master_data.serializers import DeliveryBasisSerializer

from .models import (
    Act,
    ActivityLog,
    ChargeTemplate,
    ChargeType,
    Contract,
    Deal,
    Fulfillment,
    Invoice,
    InvoiceItem,
    Lead,
    Message,
    Payment,
    Quote,
    QuoteCharge,
    QuoteItem,
)


class QuoteItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_domain = serializers.CharField(source="product.domain_type.code", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_gost = serializers.CharField(source="product.gost_drawing", read_only=True)
    offer_supplier_name = serializers.CharField(source="offer.supplier.name", read_only=True)
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
    )

    class Meta:
        model = QuoteItem
        fields = [
            "id",
            "quote",
            "product",
            "product_name",
            "product_domain",
            "product_sku",
            "product_gost",
            "offer",
            "offer_supplier_name",
            "imported_raw_name",
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
            "landed_cost",
            "final_price_excl_vat",
        ]
        read_only_fields = ["landed_cost", "final_price_excl_vat"]

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
            "is_deduction",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["created_by", "created_at"]


class QuoteSerializer(serializers.ModelSerializer):
    items = QuoteItemSerializer(many=True, read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    status_code = serializers.CharField(source="status.code", read_only=True)
    # Currency as code ("UZS") in both directions, like frozen_currency on items.
    quote_currency = serializers.SlugRelatedField(
        slug_field="code", queryset=Currency.objects.all(), required=False, allow_null=True
    )
    # Incoterm responsibility flags drive cost-row visibility in the КП builder.
    delivery_basis_data = DeliveryBasisSerializer(source="delivery_basis", read_only=True)
    # Internal cost breakdown — gated to seller/admin in to_representation().
    charges = QuoteChargeSerializer(many=True, read_only=True)

    class Meta:
        model = Quote
        fields = [
            "id",
            "deal",
            "version",
            "status",
            "status_code",
            "status_name",
            "prepared_by",
            "delivery_basis",
            "delivery_basis_data",
            "quote_currency",
            "tax_country",
            "vat_rate",
            "subtotal_excl_vat",
            "charges_total",
            "vat_amount",
            "total_incl_vat",
            "valid_until",
            "notes",
            "pdf_file",
            "frozen_at",
            "approved_by",
            "approved_at",
            "items",
            "charges",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "subtotal_excl_vat",
            "charges_total",
            "vat_amount",
            "total_incl_vat",
            "approved_by",
            "approved_at",
            "created_at",
            # prepared_by anchors the КП-owning (seller) company and the whole
            # approval chain — the server sets it to the seller building the КП,
            # never the client request body.
            "prepared_by",
        ]

    # The КП-level cost breakdown (charges list + its total) reveals internal
    # overhead/margin structure — seller/admin/superuser only. The buyer sees the
    # final total_incl_vat, never WHY (the two-projection rule).
    _SELLER_ONLY_FIELDS = ("charges", "charges_total")

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


class DealListSerializer(serializers.ModelSerializer):
    """MED-3: Optimized list serializer with human-readable names."""

    stage_name = serializers.CharField(source="stage.name", read_only=True)
    stage_code = serializers.CharField(source="stage.code", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    active_quote = QuoteSerializer(read_only=True)
    target_sellers_data = serializers.SerializerMethodField()

    def get_target_sellers_data(self, obj) -> list:
        """Seller companies this RFQ is routed to (multi-seller routing)."""
        return [{"id": seller.id, "name": seller.name} for seller in obj.target_sellers.all()]

    class Meta:
        model = Deal
        fields = [
            "id",
            "title",
            "company",
            "company_name",
            "stage",
            "stage_code",
            "stage_name",
            "total_value",
            "manager",
            "active_quote",
            "target_sellers_data",
            "created_at",
        ]


class DealDetailSerializer(serializers.ModelSerializer):
    """MED-3: Full detail serializer with quotes."""

    quotes = QuoteSerializer(many=True, read_only=True)
    active_quote = QuoteSerializer(read_only=True)
    stage_name = serializers.CharField(source="stage.name", read_only=True)
    stage_code = serializers.CharField(source="stage.code", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    client_name = serializers.CharField(source="client.get_full_name", read_only=True)
    manager_name = serializers.CharField(source="manager.get_full_name", read_only=True)
    can_edit_request = serializers.SerializerMethodField()
    target_sellers_data = serializers.SerializerMethodField()

    def get_target_sellers_data(self, obj) -> list:
        """Seller companies this RFQ is routed to (multi-seller routing)."""
        return [{"id": seller.id, "name": seller.name} for seller in obj.target_sellers.all()]

    def get_can_edit_request(self, obj) -> bool:
        """Whether the current user may add/edit/remove this deal's request rows."""
        from crm.services import buyer_can_edit_request

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        return buyer_can_edit_request(obj, user)

    class Meta:
        model = Deal
        fields = [
            "id",
            "company",
            "company_name",
            "client",
            "client_name",
            "manager",
            "manager_name",
            "stage",
            "stage_code",
            "stage_name",
            "title",
            "notes",
            "active_quote",
            "quotes",
            "can_edit_request",
            "target_sellers_data",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "company": {"required": False},
            "client": {"required": False},
        }


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    is_me = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "deal",
            "sender",
            "sender_name",
            "text",
            "message_type",
            "timestamp",
            "is_me",
        ]
        read_only_fields = ["sender", "timestamp", "message_type"]

    def get_sender_name(self, obj):
        sender = obj.sender
        if not sender:
            return ""
        full = sender.get_full_name()
        return full or sender.email

    def get_is_me(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.sender_id == request.user.id
        return False


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = ["id", "name", "company", "phone", "email", "message", "is_processed", "created_at"]
        read_only_fields = ["created_at", "is_processed"]


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.get_full_name", read_only=True)

    class Meta:
        model = ActivityLog
        fields = ["id", "action", "detail", "user_name", "level", "timestamp"]


# ──────────────────────────────────────────────────────────────────────────
# Contracts / Invoices / Payments / Acts / Fulfillment
# ──────────────────────────────────────────────────────────────────────────


class ContractSerializer(serializers.ModelSerializer):
    client_signer_name = serializers.CharField(source="client_signer.get_full_name", read_only=True, default=None)
    manager_signer_name = serializers.CharField(source="manager_signer.get_full_name", read_only=True, default=None)
    # status is a FK lookup now (F5.4); keep emitting the code string under `status`
    # so the frontend contract is unchanged, plus the display name under status_name.
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    signed_file_url = serializers.SerializerMethodField()

    class Meta:
        model = Contract
        fields = [
            "id",
            "deal",
            "quote",
            "number",
            "status",
            "status_name",
            "total_amount",
            "currency",
            "pdf_file",
            "pdf_url",
            "signed_file",
            "signed_file_url",
            "client_signer",
            "client_signer_name",
            "client_signed_at",
            "manager_signer",
            "manager_signer_name",
            "manager_signed_at",
            "valid_from",
            "valid_until",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "number",
            "total_amount",
            "pdf_file",
            "client_signer",
            "client_signed_at",
            "manager_signer",
            "manager_signed_at",
            "created_at",
            "updated_at",
        ]

    def get_pdf_url(self, obj):
        return obj.pdf_file.url if obj.pdf_file else None

    def get_signed_file_url(self, obj):
        return obj.signed_file.url if obj.signed_file else None


class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields = ["id", "description", "quantity", "unit_price_excl_vat", "line_total_excl_vat", "source_quote_item"]


class PaymentSerializer(serializers.ModelSerializer):
    proof_url = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "invoice",
            "amount",
            "method",
            "paid_at",
            "reference",
            "proof_file",
            "proof_url",
            "recorded_by",
            "created_at",
        ]
        read_only_fields = ["recorded_by", "created_at"]

    def get_proof_url(self, obj):
        return obj.proof_file.url if obj.proof_file else None


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    balance_due = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=2)
    # status is a FK lookup now (F5.4); keep the code string under `status` (+ name).
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "deal",
            "contract",
            "number",
            "status",
            "status_name",
            "issued_at",
            "due_date",
            "subtotal_excl_vat",
            "vat_amount",
            "total_incl_vat",
            "amount_paid",
            "balance_due",
            "currency",
            "pdf_file",
            "pdf_url",
            "notes",
            "items",
            "payments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["number", "amount_paid", "pdf_file", "created_at", "updated_at"]

    def get_pdf_url(self, obj):
        return obj.pdf_file.url if obj.pdf_file else None


class ActSerializer(serializers.ModelSerializer):
    # status is a FK lookup now (F5.4); keep the code string under `status` (+ name).
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    signed_file_url = serializers.SerializerMethodField()

    class Meta:
        model = Act
        fields = [
            "id",
            "deal",
            "contract",
            "invoice",
            "number",
            "status",
            "status_name",
            "issued_at",
            "signed_at",
            "total_amount",
            "pdf_file",
            "pdf_url",
            "signed_file",
            "signed_file_url",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["number", "pdf_file", "signed_at"]

    def get_pdf_url(self, obj):
        return obj.pdf_file.url if obj.pdf_file else None

    def get_signed_file_url(self, obj):
        return obj.signed_file.url if obj.signed_file else None


class FulfillmentSerializer(serializers.ModelSerializer):
    # status is a FK lookup now (F5.4); keep emitting the code string under `status`
    # so the frontend contract is unchanged, plus the display name under status_name.
    status = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)

    class Meta:
        model = Fulfillment
        fields = [
            "id",
            "deal",
            "contract",
            "status",
            "status_name",
            "shipped_at",
            "delivered_at",
            "accepted_at",
            "expected_delivery_date",
            "tracking_number",
            "carrier",
            "notes",
            "created_at",
            "updated_at",
        ]
