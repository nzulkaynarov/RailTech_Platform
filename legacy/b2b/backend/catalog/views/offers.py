from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets

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
class SupplierOfferViewSet(viewsets.ModelViewSet):
    """
    CRUD for supplier offers (pricing, stock, delivery terms).

    Public read access (active only); write operations require Manager/Admin role.
    """

    serializer_class = SupplierOfferSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["product", "supplier", "stock_status"]

    def get_queryset(self):
        qs = SupplierOffer.objects.select_related("supplier", "product", "currency", "delivery_basis", "stock_status")
        # Non-admin users only see active offers
        user = self.request.user
        if not (user.is_authenticated and (user.is_platform_admin)):
            qs = qs.filter(is_active=True)
        return qs

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.AllowAny()]
        # Write: manager/admin OR supplier with operational subscription
        from core.permissions import IsPlatformAdmin, IsSupplierWithActiveSubscription

        class _ManagerOrOperationalSupplier(permissions.BasePermission):
            def has_permission(self, request, view):
                return IsPlatformAdmin().has_permission(
                    request, view
                ) or IsSupplierWithActiveSubscription().has_permission(request, view)

        return [permissions.IsAuthenticated(), _ManagerOrOperationalSupplier()]
