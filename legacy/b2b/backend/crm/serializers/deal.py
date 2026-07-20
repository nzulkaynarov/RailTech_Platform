"""Deal list/detail serializers + the viewer-scoped routing helpers.

Split out of the monolithic ``crm/serializers.py`` (ARCH refactor) — behaviour
unchanged. The routing helpers enforce per-seller ownership visibility (a seller sees
only its own claim / itself among the routed sellers — hidden competition).
"""

from datetime import datetime

from rest_framework import serializers

from crm.models import Deal

from .quote import QuoteSerializer


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
    company_name = serializers.CharField(source="company.name", read_only=True, allow_null=True)
    active_quote = QuoteSerializer(read_only=True)
    target_sellers_data = serializers.SerializerMethodField()
    # Per-seller ownership (ADR-0006 Move 2): these reflect the VIEWER's own company routing.
    assigned_to = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_at = serializers.SerializerMethodField()

    def get_assigned_to(self, obj) -> int | None:
        return _assigned_to_id(obj, self.context.get("request"))

    def get_assigned_to_name(self, obj) -> str | None:
        return _assigned_to_display(obj, self.context.get("request"))

    def get_assigned_at(self, obj) -> datetime | None:
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
    company_name = serializers.CharField(source="company.name", read_only=True, allow_null=True)
    client_name = serializers.CharField(source="client.get_full_name", read_only=True)
    manager_name = serializers.CharField(source="manager.get_full_name", read_only=True)
    # Per-seller ownership (ADR-0006 Move 2): these reflect the VIEWER's own company routing.
    assigned_to = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_at = serializers.SerializerMethodField()
    can_edit_request = serializers.SerializerMethodField()
    target_sellers_data = serializers.SerializerMethodField()

    def get_assigned_to(self, obj) -> int | None:
        return _assigned_to_id(obj, self.context.get("request"))

    def get_assigned_to_name(self, obj) -> str | None:
        return _assigned_to_display(obj, self.context.get("request"))

    def get_assigned_at(self, obj) -> datetime | None:
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
