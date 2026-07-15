from decimal import Decimal, InvalidOperation

from django.conf import settings
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
    QuoteApprovalStep,
    QuoteCharge,
    QuoteItem,
)


class QuoteApprovalStepSerializer(serializers.ModelSerializer):
    """One node of the КП approval chain — assigned vs actual approver, status, and whether
    the requesting user may act on it right now (current stage + has the permission)."""

    approver_name = serializers.SerializerMethodField()
    acted_by_name = serializers.SerializerMethodField()
    can_act = serializers.SerializerMethodField()

    class Meta:
        model = QuoteApprovalStep
        fields = [
            "id",
            "order",
            "participation",
            "status",
            "approver",
            "approver_name",
            "approver_role",
            "acted_by",
            "acted_by_name",
            "is_mandatory",
            "is_auto",
            "trigger_reason",
            "comment",
            "decided_at",
            "created_at",
            "can_act",
        ]

    @staticmethod
    def _member_name(member):
        user = getattr(member, "user", None)
        if not user:
            return ""
        return f"{user.first_name} {user.last_name}".strip() or user.email

    def get_approver_name(self, obj) -> str:
        return self._member_name(obj.approver)

    def get_acted_by_name(self, obj) -> str:
        user = obj.acted_by
        return (f"{user.first_name} {user.last_name}".strip() or user.email) if user else ""

    def get_can_act(self, obj) -> bool:
        from accounts.services.permissions import member_has_permission
        from crm.services.approvals import _active_order, _step_permission
        from crm.services.quotes import _quote_owner_company_id

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if obj.status != "PENDING" or obj.participation == "INFORMED":
            return False
        quote = obj.quote
        if not getattr(quote, "status", None) or quote.status.code != "PENDING_APPROVAL":
            return False
        if obj.order != _active_order(quote):
            return False
        company_id = _quote_owner_company_id(quote)
        return bool(
            company_id
            and (getattr(user, "is_superuser", False) or member_has_permission(user, company_id, _step_permission(obj)))
        )


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


class QuoteSerializer(serializers.ModelSerializer):
    items = QuoteItemSerializer(many=True, read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    status_code = serializers.CharField(source="status.code", read_only=True)
    # Presentation currency as code ("UZS") in both directions, like frozen_currency on items.
    quote_currency = serializers.SlugRelatedField(
        slug_field="code",
        queryset=Currency.objects.all(),
        required=False,
        allow_null=True,
    )
    # Default COST currency new lines inherit (UI convenience) — code in both directions.
    cost_currency_default = serializers.SlugRelatedField(
        slug_field="code",
        queryset=Currency.objects.all(),
        required=False,
        allow_null=True,
    )
    # Incoterm responsibility flags drive cost-row visibility in the КП builder.
    delivery_basis_data = DeliveryBasisSerializer(source="delivery_basis", read_only=True)
    # Internal cost breakdown — gated to seller/admin in to_representation().
    charges = QuoteChargeSerializer(many=True, read_only=True)
    # Effective КП delivery term = override (delivery_lead_time_days) or max(line lead times).
    effective_delivery_lead_time_days = serializers.SerializerMethodField()
    # Seller unit economics (landed cost / gross profit / margin / operating profit / loss flags).
    # Cost-gated AND only computed when the view asks (include_economics) — keeps it off list
    # endpoints (no N+1) and hidden from a viewer without quote.view_cost_margin.
    economics = serializers.SerializerMethodField()
    # Internal approval chain (only on the single-quote/deal detail, same gate as economics).
    approval_steps = serializers.SerializerMethodField()
    # Current market FX rates ({code: "rate"}) for the frontend pricing mirror — a preview of the
    # rate a line's cost currency WOULD get before it is frozen into fx_snapshot / fx_manual.
    fx_market = serializers.SerializerMethodField()

    def get_fx_market(self, obj) -> dict:
        """Current market rate_to_uzs for every ACTIVE currency, as a {code: "rate"} map (UZS = 1).

        Lets `usePricingMirror` recompute a line whose cost currency is NOT yet in the КП's
        fx_snapshot/fx_manual — instead of showing «пересчёт после сохранения». This is the PUBLIC
        reference rate, NOT the seller's chosen/frozen rate (those stay in fx_snapshot/fx_manual). A
        currency with no known rate is OMITTED so the mirror keeps its honest «no rate» marker.

        Rates come from get_rate_to_uzs, which reads the LOCAL ExchangeRate table only (the CBU
        fetch is a Celery job) — no network call runs in the request path. Currencies are a small
        lookup, so the per-currency read is bounded (Performance Conventions)."""
        from master_data.fx import get_rate_to_uzs

        rates: dict = {}
        for code in Currency.objects.filter(is_active=True).values_list("code", flat=True):
            normalized = (code or "").upper()
            if not normalized:
                continue
            rate = get_rate_to_uzs(normalized)
            if rate is not None:
                rates[normalized] = str(rate)
        return rates

    def get_effective_delivery_lead_time_days(self, obj) -> int:
        from crm.services import effective_quote_lead_time

        return effective_quote_lead_time(obj)

    def get_approval_steps(self, obj):
        if not self.context.get("include_economics"):
            return []
        steps = obj.approval_steps.select_related("approver__user", "approver_role", "acted_by").all()
        return QuoteApprovalStepSerializer(steps, many=True, context=self.context).data

    def validate_fx_manual(self, value):
        """Client-writable manual FX override (договорной курс). Harden it (adversarial HOLE 1):
        a rate of "0"/negative/non-numeric would otherwise sail past the fx_missing guard yet
        zero or flip a line's landed cost → a free/loss КП shown as profit. Accept only POSITIVE
        numerics; normalise keys to upper-case; drop blank entries."""
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("FX_MANUAL_INVALID")
        cleaned = {}
        for code, rate in value.items():
            if rate in (None, ""):
                continue  # blank = not set; falls through to snapshot/market
            try:
                parsed = Decimal(str(rate))
            except (InvalidOperation, ValueError, TypeError):
                raise serializers.ValidationError({code: "FX_RATE_INVALID"})
            if parsed <= 0:
                raise serializers.ValidationError({code: "FX_RATE_MUST_BE_POSITIVE"})
            cleaned[str(code).upper()] = str(parsed)
        return cleaned

    def get_economics(self, obj):
        if not self.context.get("include_economics"):
            return None
        if not self._can_see_costs(obj):
            return None
        from crm.services.quotes import compute_quote_economics

        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in compute_quote_economics(obj).items()}

    class Meta:
        model = Quote
        fields = [
            "id",
            "deal",
            "version",
            "number",
            "status",
            "status_code",
            "status_name",
            "prepared_by",
            "delivery_basis",
            "delivery_basis_data",
            "quote_currency",
            "cost_currency_default",
            "fx_snapshot",
            "fx_manual",
            "fx_market",
            "tax_country",
            "vat_rate",
            "margin_percent",
            "subtotal_excl_vat",
            "charges_total",
            "vat_amount",
            "total_incl_vat",
            "delivery_lead_time_days",
            "effective_delivery_lead_time_days",
            "delivery_note",
            "valid_until",
            "notes",
            "pdf_file",
            "frozen_at",
            "approved_by",
            "approved_at",
            "items",
            "charges",
            "economics",
            "approval_steps",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "number",
            "subtotal_excl_vat",
            "charges_total",
            "vat_amount",
            "total_incl_vat",
            # fx_snapshot is frozen by the engine, never set by the client; fx_manual is
            # the client-writable override.
            "fx_snapshot",
            "effective_delivery_lead_time_days",
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
    # SEC (audit #3): margin_percent (whole-КП markup) and the fx_snapshot/fx_manual
    # cost-conversion rates must be popped for the buyer too — with the visible per-line
    # final_price + discount the buyer could otherwise back out the seller's landed cost
    # (the exact datum item-level redaction + the FX-stripped PDF, PR #269, hide). The
    # item serializer already redacts item margin_percent; the quote level lagged behind.
    _SELLER_ONLY_FIELDS = (
        "charges",
        "charges_total",
        "margin_percent",
        "fx_snapshot",
        "fx_manual",
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


def _viewer_routing(obj, request):
    """The DealSellerRouting for the VIEWER's OWN seller company on this deal (per-seller ownership,
    ADR-0006 Move 2). Each seller sees only THEIR company's claim — a competitor's routing is never
    surfaced, so cross-seller identity leakage is structurally impossible. Buyer / platform admin
    have no own-routing here → None (they don't claim)."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    company_ids = set(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    if not company_ids:
        return None
    return next(
        (r for r in obj.seller_routings.all() if r.seller_company_id in company_ids),
        None,
    )


def _assigned_to_id(obj, request):
    routing = _viewer_routing(obj, request)
    return routing.assigned_to_id if routing else None


def _assigned_to_display(obj, request):
    """Owner display name for the viewer's OWN company routing (their colleague), falling back to
    email since invited members often have a blank full name. None if unclaimed / not the viewer's.
    """
    routing = _viewer_routing(obj, request)
    if routing is None or not routing.assigned_to_id:
        return None
    assignee = routing.assigned_to
    return assignee.get_full_name() or assignee.email


def _assigned_at(obj, request):
    routing = _viewer_routing(obj, request)
    return routing.assigned_at if routing else None


def _target_sellers_for_viewer(obj, request):
    """Seller companies this RFQ is routed to — VIEWER-SCOPED (audit #5). The buyer (RFQ owner)
    and platform admin see the full routed set; a routed SELLER viewer sees only its OWN company,
    so a competitor never learns who else is bidding on the same заявка (hidden competition,
    ADR-0003 §5). Previously the full roster leaked to every routed seller."""
    sellers = list(obj.target_sellers.all())
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    as_dicts = [{"id": s.id, "name": s.name} for s in sellers]
    if getattr(user, "is_platform_admin", False):
        return as_dicts
    company_ids = set(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    # Buyer owns the RFQ → sees everyone it fanned out to; a seller sees only itself.
    if obj.company_id in company_ids:
        return as_dicts
    return [d for d in as_dicts if d["id"] in company_ids]


class DealListSerializer(serializers.ModelSerializer):
    """MED-3: Optimized list serializer with human-readable names."""

    stage_name = serializers.CharField(source="stage.name", read_only=True)
    stage_code = serializers.CharField(source="stage.code", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    active_quote = QuoteSerializer(read_only=True)
    target_sellers_data = serializers.SerializerMethodField()
    # Per-seller ownership (ADR-0006 Move 2): these reflect the VIEWER's own company routing.
    assigned_to = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_at = serializers.SerializerMethodField()

    def get_assigned_to(self, obj):
        return _assigned_to_id(obj, self.context.get("request"))

    def get_assigned_to_name(self, obj):
        return _assigned_to_display(obj, self.context.get("request"))

    def get_assigned_at(self, obj):
        return _assigned_at(obj, self.context.get("request"))

    def get_target_sellers_data(self, obj) -> list:
        """Seller companies this RFQ is routed to (multi-seller routing)."""
        return _target_sellers_for_viewer(obj, self.context.get("request"))

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
            "assigned_to",
            "assigned_to_name",
            "assigned_at",
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
    # Per-seller ownership (ADR-0006 Move 2): these reflect the VIEWER's own company routing.
    assigned_to = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_at = serializers.SerializerMethodField()
    can_edit_request = serializers.SerializerMethodField()
    target_sellers_data = serializers.SerializerMethodField()

    def get_assigned_to(self, obj):
        return _assigned_to_id(obj, self.context.get("request"))

    def get_assigned_to_name(self, obj):
        return _assigned_to_display(obj, self.context.get("request"))

    def get_assigned_at(self, obj):
        return _assigned_at(obj, self.context.get("request"))

    def get_target_sellers_data(self, obj) -> list:
        """Seller companies this RFQ is routed to (multi-seller routing)."""
        return _target_sellers_for_viewer(obj, self.context.get("request"))

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
            "assigned_to",
            "assigned_to_name",
            "assigned_at",
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
            "seller_company",
            "sender",
            "sender_name",
            "text",
            "message_type",
            "timestamp",
            "is_me",
        ]
        # seller_company (the private lane) is resolved server-side from the sender's routing
        # / the buyer's selected counterparty — read-only here, never client-forgeable (audit #4).
        read_only_fields = ["sender", "timestamp", "message_type", "seller_company"]

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
        fields = [
            "id",
            "name",
            "company",
            "phone",
            "email",
            "message",
            "is_processed",
            "created_at",
        ]
        read_only_fields = ["created_at", "is_processed"]


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.get_full_name", read_only=True)

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "action",
            "detail",
            "event_code",
            "event_params",
            "user_name",
            "level",
            "timestamp",
        ]


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
    # Which side the VIEWER may sign, derived from their relationship to this contract's deal
    # (not the SPA page context) — a dual buy+sell company gets the correct button regardless of
    # the context it landed in. Mirrors the sign_contract_by_* authorization (review fix).
    viewer_can_sign_client = serializers.SerializerMethodField()
    viewer_can_sign_manager = serializers.SerializerMethodField()

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
            "viewer_can_sign_client",
            "viewer_can_sign_manager",
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

    def get_viewer_can_sign_client(self, obj):
        from crm.services.contracts import viewer_can_sign_client

        request = self.context.get("request")
        return bool(request and viewer_can_sign_client(request.user, obj))

    def get_viewer_can_sign_manager(self, obj):
        from crm.services.contracts import viewer_can_sign_manager

        request = self.context.get("request")
        return bool(request and viewer_can_sign_manager(request.user, obj))


class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields = [
            "id",
            "description",
            "quantity",
            "unit_price_excl_vat",
            "line_total_excl_vat",
            "source_quote_item",
        ]


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
        read_only_fields = [
            "number",
            "amount_paid",
            "pdf_file",
            "created_at",
            "updated_at",
        ]

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
