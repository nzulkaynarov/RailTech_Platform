"""КП document serializers: the approval-chain step and the full `Quote`.

Split out of the monolithic ``crm/serializers.py`` (ARCH refactor) — behaviour
unchanged. ``QuoteSerializer`` nests the item / charge serializers and applies the
seller-only redaction of the КП-level cost breakdown (charges, margin, FX).
"""

from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from crm.models import Quote, QuoteApprovalStep
from master_data.models import Currency
from master_data.serializers import DeliveryBasisSerializer

from .charge import QuoteChargeSerializer
from .item import QuoteItemSerializer


class QuoteEconomicsSerializer(serializers.Serializer):
    """Documentation-only shape of ``compute_quote_economics()`` as it lands in the API.

    NOT used for (de)serialization — ``QuoteSerializer.get_economics`` builds the dict by hand
    and stringifies every ``Decimal``. This class exists so drf-spectacular emits a real object
    schema (and therefore a real TypeScript type) instead of an opaque ``{[key]: unknown}``,
    which let the backend and the SPA drift silently — the below-floor gate reads
    ``below_floor`` / ``below_cost`` / ``min_margin_percent`` off a hand-written local type.

    The service has exactly ONE unconditional ``return`` with these 11 keys, so every field is
    always present — none is ``required=False``. The OBJECT itself is nullable: the serializer
    returns ``None`` when the view did not ask for economics (``include_economics``) or when the
    viewer lacks ``quote.view_cost_margin`` (``_can_see_costs``). Keep this in sync with
    ``crm/services/quotes/pricing.py::compute_quote_economics`` —
    ``crm/tests/test_quote_economics_schema.py`` fails if they diverge.
    """

    # Decimals are stringified by get_economics() → strings on the wire, not numbers.
    total_landed_cost = serializers.CharField(help_text="Себестоимость (landed cost × qty) по billable-строкам.")
    gross_profit = serializers.CharField(help_text="Валовая прибыль = subtotal − total_landed_cost.")
    gross_margin_percent = serializers.CharField(help_text="Валовая маржа НА ЦЕНЕ (прибыль/цена), 1 знак.")
    markup_percent = serializers.CharField(help_text="Наценка на себестоимость (справочно), 1 знак.")
    charge_cost_total = serializers.CharField(help_text="Реальная себестоимость статей затрат для продавца.")
    operating_profit = serializers.CharField(
        help_text="tax_exclusive − total_landed_cost − charge_cost_total (реальный операционный результат)."
    )
    below_cost = serializers.BooleanField(help_text="Жёсткий стоп: цена не покрывает себестоимость + статьи.")
    below_floor = serializers.BooleanField(help_text="Маржа ниже порога компании → путь предупреждение+согласование.")
    min_margin_percent = serializers.CharField(help_text="Порог маржи компании (CompanySettings), %.")
    target_margin_percent = serializers.CharField(help_text="Целевая маржа компании (CompanySettings), %.")
    fx_missing = serializers.ListField(
        child=serializers.CharField(),
        help_text="Коды валют без разрешимого курса — блокируют submit/send (KP-01).",
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
        # Same include_economics gate as economics/approval_steps: the mirror lives only on the
        # КП builder (detail view). Without this, every deal row in a LIST endpoint would pay
        # ~(1 + N_currencies) ExchangeRate queries — the exact N+1 the gate exists to prevent.
        if not self.context.get("include_economics"):
            return {}
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

    def get_approval_steps(self, obj) -> list:
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

    @extend_schema_field(QuoteEconomicsSerializer(allow_null=True))
    def get_economics(self, obj) -> dict | None:
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
            # Wave A/B post-send tracking: when the client first opened the public КП page,
            # whether the public link is revoked, and the token itself (seller-only — see
            # _SELLER_ONLY_FIELDS: it grants client-projection access and must not reach the buyer).
            "first_viewed_at",
            "public_token_revoked",
            "public_access_token",
            "approved_by",
            "approved_at",
            "items",
            "charges",
            "economics",
            "approval_steps",
            "created_at",
            "updated_at",
        ]
        # Версию КП назначает СЕРВЕР (perform_create: max(version)+1). Без явного отключения
        # DRF генерирует UniqueTogetherValidator по unique_together=(deal, version) и проверяет
        # его ДО perform_create с дефолтом version=1 → второй POST на ту же сделку падал 400
        # «должны производить массив с уникальными значениями»: кнопка «Create new version»
        # не работала НИКОГДА (v1 у сделки есть всегда). Найдено прогоном глазами 2026-08-17.
        validators = []
        read_only_fields = [
            "version",
            "number",
            "subtotal_excl_vat",
            "charges_total",
            "vat_amount",
            "total_incl_vat",
            # fx_snapshot is frozen by the engine, never set by the client; fx_manual is
            # the client-writable override.
            "fx_snapshot",
            "effective_delivery_lead_time_days",
            "first_viewed_at",
            "public_token_revoked",
            "public_access_token",
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
        # The public no-login link grants client-projection access; only the КП-owning seller
        # needs it (to copy/revoke the link on the post-send panel). Never hand it to the buyer.
        "public_access_token",
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
