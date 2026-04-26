from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets
from rest_framework.response import Response

from accounts.models import SystemRole, WorkspaceRole
from core.permissions import IsPlatformAdmin


@extend_schema_view(
    list=extend_schema(summary="List company types", tags=["Accounts"]),
)
class CompanyTypeViewSet(viewsets.ReadOnlyModelViewSet):
    """Lightweight public lookup for CompanyType (CLIENT / SUPPLIER / MANUFACTURER / ...)."""

    from accounts.models import CompanyType

    queryset = CompanyType.objects.filter(is_active=True).order_by("sort_order", "name")
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        data = [{"id": c.id, "code": c.code, "name": c.name} for c in self.get_queryset()]
        return Response(data)


@extend_schema_view(
    list=extend_schema(summary="List system roles", tags=["Accounts"]),
    retrieve=extend_schema(summary="Get system role", tags=["Accounts"]),
)
class SystemRoleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SystemRole.objects.all().order_by("sort_order", "name")
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        data = [{"code": r.code, "name": r.name} for r in self.get_queryset()]
        return Response(data)


@extend_schema_view(
    list=extend_schema(summary="List workspace roles", tags=["Accounts"]),
    retrieve=extend_schema(summary="Get workspace role", tags=["Accounts"]),
)
class WorkspaceRoleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Workspace roles with company type binding.

    Query:
      ?company_type=CLIENT -- return only roles applicable to CLIENT companies
                             (plus universal roles without type restriction).
    """

    queryset = (
        WorkspaceRole.objects.filter(is_active=True)
        .prefetch_related("applicable_to_types")
        .order_by("sort_order", "name")
    )
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        company_type = request.query_params.get("company_type")
        data = []
        for r in qs:
            applicable = list(r.applicable_to_types.values_list("code", flat=True))
            if company_type and applicable and company_type not in applicable:
                continue
            data.append(
                {
                    "code": r.code,
                    "name": r.name,
                    "applicable_to_types": applicable,
                }
            )
        return Response(data)
