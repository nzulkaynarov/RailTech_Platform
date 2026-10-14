"""E4 — CRUD согласованных вариантов формулировок (библиотека компании).

Thin wrappers (Rule 8): авторизация → валидация → один вызов сервиса. Право — то же,
что у формулировок D1 и шаблонов документов: `settings.edit` компании-владельца.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import RoleGatedViewMixin
from crm import services as crm_services
from crm.models import CompanyWordingVariant
from crm.serializers.documents import CompanyWordingVariantSerializer
from crm.services import wording_variants as wording_service


@extend_schema(tags=["CRM"])
class WordingVariantViewSet(RoleGatedViewMixin, viewsets.ModelViewSet):
    """Библиотека согласованных формулировок компании (E4, playbook-канон)."""

    required_permissions = {
        "create": "settings.edit",
        "update": "settings.edit",
        "partial_update": "settings.edit",
        "destroy": "settings.edit",
    }

    serializer_class = CompanyWordingVariantSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    # Список короткий и правится целиком в настройках — без пагинации (как шаблоны).
    pagination_class = None
    filterset_fields = ["field"]

    def _owner_company(self):
        from accounts.models import Company
        from accounts.services.permissions import member_has_permission

        user = self.request.user
        company_id = crm_services.resolve_owner_company_id(user)
        if not company_id:
            raise PermissionDenied("NO_COMPANY")
        if not (getattr(user, "is_superuser", False) or member_has_permission(user, company_id, "settings.edit")):
            raise PermissionDenied("SETTINGS_EDIT_REQUIRED")
        return Company.objects.get(pk=company_id)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CompanyWordingVariant.objects.none()
        company_id = crm_services.resolve_owner_company_id(self.request.user)
        return (
            CompanyWordingVariant.objects.filter(company_id=company_id)
            if company_id
            else (CompanyWordingVariant.objects.none())
        )

    def create(self, request, *args, **kwargs):
        company = self._owner_company()
        try:
            variant = wording_service.create_variant(
                company,
                request.user,
                field=str(request.data.get("field", "")),
                title=str(request.data.get("title", "")),
                text=str(request.data.get("text", "")),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=400)
        return Response(self.get_serializer(variant).data, status=201)

    def update(self, request, *args, **kwargs):
        self._owner_company()
        variant = self.get_object()
        try:
            variant = wording_service.update_variant(
                variant,
                title=request.data.get("title"),
                text=request.data.get("text"),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=400)
        return Response(self.get_serializer(variant).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._owner_company()
        self.get_object().delete()
        return Response(status=204)
