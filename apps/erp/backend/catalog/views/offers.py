from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets
from rest_framework.exceptions import PermissionDenied

from core.permissions import RoleGatedViewMixin

from ..models import SupplierOffer
from ..serializers import SupplierOfferSerializer


@extend_schema_view(
    list=extend_schema(
        summary="List supplier offers",
        description="Returns all supplier offers. Filterable by product, supplier, stock_status.",
        tags=["Catalog"],
    ),
    create=extend_schema(
        summary="Create supplier offer",
        description="Create a new supplier offer. Manager/Admin only.",
        tags=["Catalog"],
    ),
    retrieve=extend_schema(summary="Get supplier offer", tags=["Catalog"]),
    update=extend_schema(summary="Update supplier offer", tags=["Catalog"]),
    partial_update=extend_schema(summary="Partially update supplier offer", tags=["Catalog"]),
    destroy=extend_schema(summary="Delete supplier offer", tags=["Catalog"]),
)
class SupplierOfferViewSet(RoleGatedViewMixin, viewsets.ModelViewSet):
    """
    CRUD for supplier offers (pricing, stock, delivery terms).

    Public read access (active only); write operations require Manager/Admin role.
    """

    required_permissions = {
        "create": "supply.manage",
        "update": "supply.manage",
        "partial_update": "supply.manage",
        "destroy": "supply.manage",
    }

    serializer_class = SupplierOfferSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["product", "supplier", "stock_status"]

    def _seller_company_ids(self):
        """Active SUPPLIER/MANUFACTURER companies the user belongs to."""
        user = self.request.user
        if not user.is_authenticated:
            return []
        return list(user.memberships.filter(is_active=True).in_seller_company().values_list("company_id", flat=True))

    def get_queryset(self):
        # An offer carries the seller's cost + supplier identity — confidential (C1/C2).
        # Only the platform admin and the offer's OWNING seller may read it; buyers and
        # anonymous callers see nothing here (they get prices via КП quotes, not offers).
        qs = SupplierOffer.objects.select_related("supplier", "product", "currency", "delivery_basis", "stock_status")
        user = self.request.user
        if user.is_authenticated and user.is_superuser:
            return qs
        company_ids = self._seller_company_ids()
        if not company_ids:
            return qs.none()
        return qs.filter(supplier_id__in=company_ids)

    def perform_create(self, serializer):
        # A seller can only create offers for their OWN company. The supplier in the
        # body MUST be one of the seller's companies — a competitor's id is rejected
        # (C2 spoofing). Platform admin may create an offer for any supplier.
        user = self.request.user
        if user.is_superuser:
            serializer.save()
            return
        company_ids = self._seller_company_ids()
        if not company_ids:
            raise PermissionDenied("NO_SELLER_MEMBERSHIP")
        supplier = serializer.validated_data.get("supplier")
        if getattr(supplier, "id", None) not in company_ids:
            raise PermissionDenied("CANNOT_CREATE_OFFER_FOR_OTHER_SUPPLIER")
        # The product must be PUBLISHED (any seller may quote a live catalog card) or owned by
        # the seller — not a competitor's DRAFT/ARCHIVED card (audit L2: pricing-data pollution).
        product = serializer.validated_data.get("product")
        prod_published = getattr(getattr(product, "status", None), "code", None) == "PUBLISHED"
        prod_owned = getattr(product, "owner_company_id", None) in company_ids
        if product is not None and not (prod_published or prod_owned):
            raise PermissionDenied("CANNOT_ATTACH_OFFER_TO_FOREIGN_PRODUCT")
        serializer.save()

    def perform_update(self, serializer):
        # Non-admins cannot reassign an offer to another supplier OR another product (audit L2).
        user = self.request.user
        if user.is_superuser:
            serializer.save()
            return
        serializer.save(supplier=serializer.instance.supplier, product=serializer.instance.product)

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.AllowAny()]
        # Запись: право роли `supply.manage` (гейт RoleGatedViewMixin выше) И, для конкретного
        # предложения, членство в компании-поставщике этого предложения (уровень объекта).
        from core.permissions import IsOfferSupplierOrAdmin

        return [permissions.IsAuthenticated(), IsOfferSupplierOrAdmin()]
