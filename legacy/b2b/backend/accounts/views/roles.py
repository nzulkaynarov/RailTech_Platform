"""Company roles API (Role+Permission-set) — thin wrappers over accounts.services.roles."""

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import services
from accounts.constants import PERMISSION_GROUPS
from accounts.serializers import CompanyRoleSerializer

# Service error code → HTTP status.
_ERROR_STATUS = {
    "ONLY_TEAM_MANAGER_CAN_MANAGE_ROLES": status.HTTP_403_FORBIDDEN,
    "SYSTEM_ROLE_IMMUTABLE": status.HTTP_403_FORBIDDEN,
    "ROLE_HAS_MEMBERS_REASSIGN_FIRST": status.HTTP_409_CONFLICT,
    "CANNOT_DEMOTE_LAST_COMPANY_ADMIN": status.HTTP_409_CONFLICT,
    "MEMBER_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "ROLE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
}


def _err(code):
    return Response({"error": code}, status=_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST))


_GROUP_LABELS = {
    "sales": {"ru": "Продажи / КП", "en": "Sales / Quotes"},
    "procurement": {"ru": "Закупки", "en": "Procurement"},
    "catalog": {"ru": "Каталог", "en": "Catalog"},
    "company": {"ru": "Компания", "en": "Company admin"},
    "data": {"ru": "Данные", "en": "Data"},
}
# English labels for the permission checkboxes (the .label on Permission is RU). The SPA
# localizes via i18n keys, but the catalog ships both so non-i18n clients render correctly.
_PERM_LABELS_EN = {
    "quote.build": "Build quotes",
    "quote.send": "Send quotes to client",
    "quote.view_cost_margin": "See cost & margin",
    "quote.edit_pricing": "Edit prices & discounts",
    "request.create": "Create requests",
    "quote.approve": "Approve / reject quotes",
    "contract.sign": "Sign contracts",
    "payment.record": "Record payments",
    "catalog.manage": "Manage catalog & offers",
    "catalog.publish": "Publish products",
    "team.manage": "Manage team & roles",
    "settings.edit": "Edit company settings",
    "charge_templates.manage": "Manage charge templates",
    "data.export": "Export data",
}


class CompanyRoleViewSet(viewsets.ModelViewSet):
    """CRUD for a company's own roles. Scoped to the requester's company; writes need
    the `team.manage` permission. Platform admins manage roles via Django Unfold."""

    serializer_class = CompanyRoleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            from accounts.models import CompanyRole

            return CompanyRole.objects.none()
        return services.list_roles_for_user(self.request.user)

    def create(self, request, *args, **kwargs):
        company_id = request.data.get("company") or (
            request.user.memberships.filter(is_active=True).values_list("company_id", flat=True).first()
        )
        role, err = services.create_company_role(
            request.user, company_id, request.data.get("name"), request.data.get("permissions", [])
        )
        if err:
            return _err(err)
        return Response(CompanyRoleSerializer(role).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        role, err = services.update_company_role(
            request.user, self.get_object(), request.data.get("name"), request.data.get("permissions", [])
        )
        if err:
            return _err(err)
        return Response(CompanyRoleSerializer(role).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        err = services.delete_company_role(request.user, self.get_object())
        if err:
            return _err(err)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(summary="Assign a company role to a member", tags=["Accounts"])
    @action(detail=False, methods=["post"], url_path="assign")
    def assign(self, request):
        member, err = services.assign_role_to_member(
            request.user, request.data.get("member_id"), request.data.get("role_id")
        )
        if err:
            return _err(err)
        return Response({"member_id": member.id, "role_id": member.company_role_id})


class PermissionCatalogView(APIView):
    """The permission checkbox catalog for the role editor (grouped, bilingual labels)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Company permission catalog", tags=["Accounts"])
    def get(self, request):
        groups = []
        for key, perms in PERMISSION_GROUPS.items():
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
