"""КП charge / status / charge-type / charge-template ViewSets.

Split out of the monolithic ``crm/views/quotes.py`` (ARCH refactor) — behaviour
unchanged. Charge writes are seller-gated (mirroring QuoteItemViewSet); charge
templates are scoped to the requester's own seller company.
"""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsCompanyMemberOrPlatformAdmin
from crm.models import ChargeTemplate, ChargeType, QuoteCharge, QuoteStatus
from crm.serializers import ChargeTemplateSerializer, ChargeTypeSerializer, QuoteChargeSerializer

from .items import _assert_seller_owns_quote_deal


@extend_schema_view(
    list=extend_schema(summary="List КП-level expense items / discounts", tags=["CRM"]),
    create=extend_schema(summary="Add КП-level expense item / discount", tags=["CRM"]),
    destroy=extend_schema(summary="Remove КП-level expense item / discount", tags=["CRM"]),
)
class QuoteChargeViewSet(viewsets.ModelViewSet):
    """CRUD for КП-level expense items / discounts (UBL document AllowanceCharge).

    Building the cost breakdown is a SELLER action (mirrors QuoteItemViewSet):
    only the seller team / superuser may write; the buyer never sees these rows.
    """

    serializer_class = QuoteChargeSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    filterset_fields = {"quote": ["exact"], "quote__deal_id": ["exact"]}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return QuoteCharge.objects.none()
        user = self.request.user
        from accounts.services.permissions import seller_visible_deal_ids

        queryset = QuoteCharge.objects.select_related("charge_type", "quote").all()
        if getattr(user, "is_superuser", False):
            return queryset
        visible_deal_ids = seller_visible_deal_ids(user, self.request)
        if visible_deal_ids is not None:
            from accounts.models import CompanyMember
            from accounts.services.permissions import seller_acting_company_ids

            # The seller sees items/charges on deals routed to them. Audit H1 (no cross-seller
            # leak): hide a quote ONLY when it was prepared by a COMPETING seller company. The
            # buyer's request lines and the seller's КП are the SAME quote in this model, and
            # that quote is created by the BUYER (or left unassigned) — so scoping by
            # prepared_by's *seller* company alone wrongly hid the seller's own КП and made
            # pricing un-saveable (404 on item PATCH → subtotal stuck at 0). Exclude only
            # quotes whose prepared_by belongs to another seller company.
            seller_ids = seller_acting_company_ids(user, self.request) or set()
            # Dual-membership edge: a user who belongs to BOTH the viewer's own seller
            # company AND a competing one would otherwise land in competing_preparer_ids
            # and hide their OWN company's legitimately-prepared КП from their own viewers.
            # Subtract members of the viewer's OWN seller companies so only PURELY-competing
            # preparers are excluded.
            own_member_ids = CompanyMember.objects.filter(is_active=True, company_id__in=seller_ids).values_list(
                "user_id", flat=True
            )
            competing_preparer_ids = (
                CompanyMember.objects.filter(is_active=True)
                .in_seller_company()
                .exclude(company_id__in=seller_ids)
                .exclude(user_id__in=own_member_ids)
                .values_list("user_id", flat=True)
            )
            return (
                queryset.filter(quote__deal_id__in=visible_deal_ids)
                .exclude(quote__prepared_by_id__in=competing_preparer_ids)
                .distinct()
            )
        # Buyers must never see the internal cost breakdown.
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
        _assert_seller_owns_quote_deal(self.request, quote)
        # Append a manually-added charge at the BOTTOM of the cascade (after existing rows), so
        # e.g. a partner commission added last is based on the full running total above it.
        from django.db.models import Max

        next_order = (quote.charges.aggregate(m=Max("sort_order"))["m"] or 0) + 1 if quote else 0
        serializer.save(created_by=self.request.user, sort_order=next_order)

    def perform_update(self, serializer):
        self._assert_seller()
        # Editing a charge makes it the seller's deliberate value → mark it manual so a later
        # Incoterm switch (KP-05) won't wipe it with the rest of the old basis's template rows.
        serializer.save(from_template=False)

    def perform_destroy(self, instance):
        self._assert_seller()
        quote = instance.quote
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
class ChargeTemplateViewSet(viewsets.ModelViewSet):
    """Company-Admin manages their own per-Incoterm charge templates (org-admin zone).

    Scoped to the requester's seller company — they never see or touch another
    tenant's templates, nor the platform's global defaults (those are the fallback
    applied automatically when a company has no template for a basis).
    """

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
        # ADR-0005 Phase E U3: gate on the charge_templates.manage CompanyRole permission instead of
        # the legacy OWNER WorkspaceRole. A company_role-less OWNER still passes (OWNER-role fallback
        # branch); a company_role-less non-OWNER stays denied (charge_templates.manage ∈ _ADMIN_PERMS
        # → fallback False, so can_sell does not leak template management). An OWNER on a restricted
        # CompanyRole is governed by that role — intended U3 supersession.
        if not member_has_permission(user, company_id, "charge_templates.manage"):
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
