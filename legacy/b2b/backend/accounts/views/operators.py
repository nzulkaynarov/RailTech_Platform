"""Platform Operator sub-role API (ADR-0004 G1) — thin wrappers over accounts.services.operators."""

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import services
from accounts.constants import OPERATOR_PERMISSION_GROUPS, OperatorPermission
from accounts.serializers import OperatorRoleSerializer
from core.permissions import OperatorScoped

# Service error code → HTTP status.
_ERROR_STATUS = {
    "ONLY_SUPER_OPERATOR_CAN_MANAGE_OPERATORS": status.HTTP_403_FORBIDDEN,
    "SYSTEM_OPERATOR_ROLE_IMMUTABLE": status.HTTP_403_FORBIDDEN,
    "ROLE_HAS_OPERATORS_REASSIGN_FIRST": status.HTTP_409_CONFLICT,
    "CANNOT_DEMOTE_LAST_OPERATOR": status.HTTP_409_CONFLICT,
    "NOT_A_PLATFORM_OPERATOR": status.HTTP_400_BAD_REQUEST,
    "USER_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "ROLE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
}


def _err(code):
    return Response({"detail": code}, status=_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST))


_GROUP_LABELS = {
    "users": {"ru": "Пользователи", "en": "Users"},
    "companies": {"ru": "Компании", "en": "Companies"},
    "kyc": {"ru": "KYC", "en": "KYC"},
    "billing": {"ru": "Биллинг", "en": "Billing"},
    "moderation": {"ru": "Модерация", "en": "Moderation"},
    "platform": {"ru": "Платформа", "en": "Platform"},
}
# English labels for the operator capability checkboxes (.label is RU). The SPA localizes
# via i18n keys; the catalog ships both so non-i18n clients render correctly.
_PERM_LABELS_EN = {
    "users.view": "View users",
    "users.manage": "Manage users (block / role)",
    "companies.view": "View companies",
    "companies.manage": "Manage companies",
    "kyc.view": "View KYC & documents",
    "kyc.verify": "Verify KYC (L1→L3)",
    "billing.view": "View subscriptions & invoices",
    "billing.manage": "Manage subscriptions & payments",
    "moderation.role_applications": "Moderate role applications",
    "moderation.force_override": "Force-override (deals / quotes / contracts)",
    "platform.settings": "System settings & master data",
    "operators.manage": "Manage operator roles",
}


class OperatorRoleViewSet(viewsets.ModelViewSet):
    """CRUD for platform-operator sub-roles. Any platform operator may read; mutating
    needs the `operators.manage` capability (SUPER_OPERATOR). Platform-scoped."""

    serializer_class = OperatorRoleSerializer
    permission_classes = [IsAuthenticated, OperatorScoped]
    operator_permissions = {
        "create": OperatorPermission.OPERATORS_MANAGE,
        "update": OperatorPermission.OPERATORS_MANAGE,
        "partial_update": OperatorPermission.OPERATORS_MANAGE,
        "destroy": OperatorPermission.OPERATORS_MANAGE,
        "assign": OperatorPermission.OPERATORS_MANAGE,
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            from accounts.models import OperatorRole

            return OperatorRole.objects.none()
        return services.list_operator_roles()

    def create(self, request, *args, **kwargs):
        role, err = services.create_operator_role(
            request.user,
            request.data.get("name"),
            request.data.get("permissions", []),
            request.data.get("description", ""),
        )
        if err:
            return _err(err)
        return Response(OperatorRoleSerializer(role).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        role, err = services.update_operator_role(
            request.user,
            self.get_object(),
            request.data.get("name"),
            request.data.get("permissions", []),
            request.data.get("description"),
        )
        if err:
            return _err(err)
        return Response(OperatorRoleSerializer(role).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        err = services.delete_operator_role(request.user, self.get_object())
        if err:
            return _err(err)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(summary="Assign an operator role to a platform operator", tags=["Accounts"])
    @action(detail=False, methods=["post"], url_path="assign")
    def assign(self, request):
        target, err = services.assign_operator_role(
            request.user, request.data.get("user_id"), request.data.get("role_id")
        )
        if err:
            return _err(err)
        return Response({"user_id": target.id, "operator_role_id": target.operator_role_id})


class OperatorPermissionCatalogView(APIView):
    """The operator capability catalog for the role editor (grouped, bilingual labels)."""

    permission_classes = [IsAuthenticated, OperatorScoped]

    @extend_schema(summary="Operator permission catalog", tags=["Accounts"])
    def get(self, request):
        groups = []
        for key, perms in OPERATOR_PERMISSION_GROUPS.items():
            groups.append(
                {
                    "key": key,
                    "label": _GROUP_LABELS.get(key, {}).get("ru", key),
                    "label_en": _GROUP_LABELS.get(key, {}).get("en", key),
                    "permissions": [
                        {"code": p.value, "label": p.label, "label_en": _PERM_LABELS_EN.get(p.value, p.label)}
                        for p in perms
                    ],
                }
            )
        return Response({"groups": groups})
