"""КП charge / status / charge-type / charge-template ViewSets.

Split out of the monolithic ``crm/views/quotes.py`` (ARCH refactor) — behaviour
unchanged. Charge writes are seller-gated (mirroring QuoteItemViewSet); charge
templates are scoped to the requester's own seller company.
"""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsCompanyMemberOrPlatformAdmin, RoleGatedViewMixin
from crm.models import ChargeTemplate, ChargeType, QuoteCharge, QuoteStatus
from crm.serializers import ChargeTemplateSerializer, ChargeTypeSerializer, QuoteChargeSerializer
from crm.services.quotes.editable import assert_quote_items_editable

from .items import _assert_staff_may_write_quote


@extend_schema_view(
    list=extend_schema(summary="List КП-level expense items / discounts", tags=["CRM"]),
    create=extend_schema(summary="Add КП-level expense item / discount", tags=["CRM"]),
    destroy=extend_schema(summary="Remove КП-level expense item / discount", tags=["CRM"]),
)
class QuoteChargeViewSet(RoleGatedViewMixin, viewsets.ModelViewSet):
    """CRUD for КП-level expense items / discounts (UBL document AllowanceCharge).

    Building the cost breakdown is a SELLER action (mirrors QuoteItemViewSet):
    only the seller team / superuser may write; the client never sees these rows.
    """

    required_permissions = {
        "create": "quote.edit_pricing",
        "update": "quote.edit_pricing",
        "partial_update": "quote.edit_pricing",
        "destroy": "quote.edit_pricing",
    }

    serializer_class = QuoteChargeSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    filterset_fields = {"quote": ["exact"], "quote__deal_id": ["exact"]}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return QuoteCharge.objects.none()
        from accounts.services.permissions import sees_all_deals

        queryset = QuoteCharge.objects.select_related("charge_type", "quote").all()
        # Administrator and own-company staff (the single seller) see every КП's charges;
        # buyers must never see the internal cost breakdown.
        if sees_all_deals(self.request.user):
            return queryset
        return queryset.none()

    def _assert_seller(self):
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import can_edit_quote_pricing

        user = self.request.user
        if not (getattr(user, "is_superuser", False) or can_edit_quote_pricing(user)):
            raise PermissionDenied("ONLY_SELLER_CAN_BUILD_QUOTE")

    def perform_create(self, serializer):
        self._assert_seller()
        quote = serializer.validated_data.get("quote")
        _assert_staff_may_write_quote(self.request, quote)
        assert_quote_items_editable(quote)
        # Append a manually-added charge at the BOTTOM of the cascade (after existing rows), so
        # e.g. a partner commission added last is based on the full running total above it.
        from django.db.models import Max

        next_order = (quote.charges.aggregate(m=Max("sort_order"))["m"] or 0) + 1 if quote else 0
        serializer.save(created_by=self.request.user, sort_order=next_order)

    def perform_update(self, serializer):
        self._assert_seller()
        # Расходы несут сумму КП: правка только в DRAFT и до заморозки (FIX-55, D-04).
        assert_quote_items_editable(serializer.instance.quote)
        target_quote = serializer.validated_data.get("quote")
        if target_quote is not None:
            assert_quote_items_editable(target_quote)
        # Editing a charge makes it the seller's deliberate value → mark it manual so a later
        # Incoterm switch (KP-05) won't wipe it with the rest of the old basis's template rows.
        serializer.save(from_template=False)

    def perform_destroy(self, instance):
        self._assert_seller()
        quote = instance.quote
        assert_quote_items_editable(quote)
        instance.delete()
        # save()-on-delete doesn't fire; recalc the КП so charges_total drops.
        quote.recalculate_totals()


class QuoteStatusLookupSerializer(serializers.Serializer):
    """Response shape for the QuoteStatus lookup feed ({code, name})."""

    code = serializers.CharField()
    name = serializers.CharField()


@extend_schema_view(
    list=extend_schema(summary="List quote statuses", tags=["CRM"]),
)
class QuoteStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = QuoteStatus.objects.all().order_by("sort_order", "name")
    serializer_class = QuoteStatusLookupSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        # Lightweight {code,name} feed (no serializer_class needed) — the frontend
        # status dropdowns consume codes, not full objects.
        data = [{"code": status.code, "name": status.name} for status in self.get_queryset()]
        return Response(data)


@extend_schema_view(
    list=extend_schema(summary="List КП expense-item types (ChargeType lookup)", tags=["CRM"]),
)
class ChargeTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ChargeType.objects.filter(is_active=True).order_by("sort_order", "name")
    serializer_class = ChargeTypeSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None


@extend_schema_view(
    list=extend_schema(summary="List the company's charge templates", tags=["CRM"]),
    create=extend_schema(summary="Add a charge template", tags=["CRM"]),
    destroy=extend_schema(summary="Remove a charge template", tags=["CRM"]),
)
class ChargeTemplateViewSet(RoleGatedViewMixin, viewsets.ModelViewSet):
    """Company-Admin manages their own per-Incoterm charge templates (org-admin zone).

    Scoped to the requester's seller company — they never see or touch another
    tenant's templates, nor the platform's global defaults (those are the fallback
    applied automatically when a company has no template for a basis).
    """

    required_permissions = {
        "create": "settings.charge_templates",
        "update": "settings.charge_templates",
        "partial_update": "settings.charge_templates",
        "destroy": "settings.charge_templates",
    }

    serializer_class = ChargeTemplateSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def _seller_company_id(self):
        from accounts.services.permissions import primary_seller_company_id

        return primary_seller_company_id(self.request.user)

    def _assert_company_admin(self, company_id):
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import member_has_permission

        user = self.request.user
        if getattr(user, "is_superuser", False):
            return
        # Keep the explicit NO_SELLER_COMPANY signal: member_has_permission(user, None, …) is False
        # and would otherwise collapse into the generic denial below.
        if not company_id:
            raise PermissionDenied("NO_SELLER_COMPANY")
        # Право роли `settings.charge_templates` (M1-ERP-05: только роли, без вывода из должности).
        if not member_has_permission(user, company_id, "settings.charge_templates"):
            raise PermissionDenied("ONLY_COMPANY_ADMIN_CAN_MANAGE_TEMPLATES")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ChargeTemplate.objects.none()
        company_id = self._seller_company_id()
        if not company_id:
            return ChargeTemplate.objects.none()
        return ChargeTemplate.objects.filter(company_id=company_id).select_related("delivery_basis", "charge_type")

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError

        company_id = self._seller_company_id()
        self._assert_company_admin(company_id)
        basis = serializer.validated_data["delivery_basis"]
        charge_type = serializer.validated_data["charge_type"]
        if ChargeTemplate.objects.filter(company_id=company_id, delivery_basis=basis, charge_type=charge_type).exists():
            raise ValidationError({"charge_type": "TEMPLATE_ALREADY_EXISTS"})
        serializer.save(company_id=company_id)

    def perform_update(self, serializer):
        self._assert_company_admin(self._seller_company_id())
        serializer.save()

    def perform_destroy(self, instance):
        self._assert_company_admin(self._seller_company_id())
        instance.delete()
